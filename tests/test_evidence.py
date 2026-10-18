"""Milestone 4 guarantees (architecture sections 16, 18, 21.7, 22)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from intentgraph.errors import InvalidInput
from intentgraph.patches import Patch
from intentgraph.repository import Repository
from intentgraph.services import Context, approval_record, ci, evidence_capture, evidence_submit, patch_apply, readiness, reconcile, review_export, workspace_snapshot

PROV = {"author_role": "agent", "method": "t"}
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def _apply(repo, pid, ops):
    snap = repo.load_snapshot()
    return patch_apply(repo, Patch.model_validate({"patch_id": pid, "base_revision": snap.revision, "base_digest": snap.content_digest, "operations": ops}))


def _node(id, kind, layer, props, lifecycle="accepted"):
    return {"op": "add_node", "record": {"id": id, "kind": kind, "label": id, "layer": layer, "properties": props, "lifecycle": lifecycle, "provenance": PROV}}


def _git(root, *args):
    subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=root, check=True, capture_output=True, env=GIT_ENV)


@pytest.fixture
def app(coaching_repo: Repository) -> Repository:
    """Coaching model plus a tiny real 'app' with files the fixture symbols point at, committed in Git."""
    root = coaching_repo.paths.root
    for rel, text in {
        "lib/coaching/playback_controller.dart": "class PlaybackController { void cancelResponse(String id) {} }\n",
        "backend/coaching/coordinator.py": "class ResponseCoordinator:\n    def cancel(self, rid):\n        return True\n",
        "test/coaching/cancel_test.dart": "void main() {}\n",
        "README.md": "app\n",
    }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    # Fixture symbols use repository "app"; map it to the workspace root.
    manifest = json.loads(coaching_repo.paths.project.read_text())
    manifest["roots"] = {".": ".", "app": "."}
    coaching_repo.paths.project.write_text(json.dumps(manifest))
    return coaching_repo


def _junit(path: Path, failures=0):
    path.write_text(f'<testsuite name="s" tests="3" failures="{failures}" errors="0"><testcase name="a"/><testcase name="b"/><testcase name="c"/></testsuite>')


def test_submit_validated_report_binds_inputs_and_model(app: Repository, tmp_path):
    report = tmp_path / "junit.xml"
    _junit(report)
    out = evidence_submit(app, {"id": "evidence:cancel-run-1", "label": "cancel tests", "method": "unit_test", "result": "passed", "collection_mode": "validated_report",
                                "supports": ["req:cancel-response"], "test_refs": ["test:cancel-then-late-response"], "tool": "flutter-test",
                                "inputs": {"repository": "app", "paths": ["lib/coaching/playback_controller.dart", "test/coaching/cancel_test.dart"]},
                                "artifact": {"path": str(report), "format": "junit-xml"}})
    assert out["collection_mode"] == "validated_report" and out["missing_paths"] == []
    snap = app.load_snapshot()
    ev = snap.get("evidence:cancel-run-1")
    wsnap = snap.get(out["workspace_snapshot_ref"])
    assert wsnap.kind == "WorkspaceSnapshot" and wsnap.properties["git_available"] and len(wsnap.properties["head"]) == 40
    assert set(wsnap.properties["files"]) == {"lib/coaching/playback_controller.dart", "test/coaching/cancel_test.dart"}
    assert ev.properties["model_scope_digest"].startswith("sha256:") and ev.properties["artifact_digest"].startswith("sha256:")
    assert (app.paths.root / ev.properties["artifact_ref"]).is_file()
    assert any(e.kind == "supports" and e.source == ev.id and e.target == "req:cancel-response" for e in snap.edges)
    rec = reconcile(app, "scope:cancel") if False else reconcile(app)
    fresh = {e["evidence_id"]: e for e in rec["evidence"]}
    assert fresh["evidence:cancel-run-1"]["fresh"] and fresh["evidence:cancel-run-1"]["effective_collection_mode"] == "validated_report"
    # The pre-existing fixture evidence has no snapshot and is conservatively stale.
    assert not fresh["evidence:late-response-test"]["fresh"]


def test_validated_report_must_match_claim_and_format(app: Repository, tmp_path):
    report = tmp_path / "junit.xml"
    _junit(report, failures=1)
    base = {"id": "evidence:x", "method": "unit_test", "supports": ["req:cancel-response"], "collection_mode": "validated_report", "inputs": {"repository": "app", "paths": []}}
    with pytest.raises(InvalidInput) as exc:
        evidence_submit(app, {**base, "result": "passed", "artifact": {"path": str(report), "format": "junit-xml"}})
    assert exc.value.code == "report_validation_failed" and "shows failed" in exc.value.message
    with pytest.raises(InvalidInput) as exc:
        evidence_submit(app, {**base, "result": "failed", "artifact": {"path": str(report), "format": "opaque"}})
    assert exc.value.code == "report_validation_failed"
    with pytest.raises(InvalidInput):
        evidence_submit(app, {**base, "result": "passed"})  # validated without artifact
    with pytest.raises(InvalidInput) as exc:
        evidence_submit(app, {**base, "result": "passed", "collection_mode": "independent_capture"})
    assert exc.value.code == "invalid_evidence"
    with pytest.raises(InvalidInput) as exc:
        evidence_submit(app, {**base, "result": "passed", "collection_mode": "agent_submitted_report", "supports": ["req:nope"]})
    assert exc.value.code == "unknown_record"
    assert app.load_snapshot().revision == 1  # nothing written


def test_capture_runs_argv_without_shell_and_records_outcome(app: Repository):
    spec = {"id": "evidence:captured", "method": "command", "supports": ["req:cancel-response"], "repository": "app",
            "command": [sys.executable, "-c", "import sys; print('ok'); sys.exit(0)"], "inputs": {"paths": ["backend/coaching/coordinator.py"]}}
    out = evidence_capture(app, spec)
    assert out["result"] == "passed" and out["exit_code"] == 0
    ev = app.load_snapshot().get("evidence:captured")
    assert ev.properties["collection_mode"] == "independent_capture" and ev.provenance.author_role == "tool"
    capture = json.loads((app.paths.root / ev.properties["artifact_ref"]).read_text())
    assert capture["stdout"].strip() == "ok" and capture["exit_code"] == 0
    bad = evidence_capture(app, {**spec, "id": "evidence:captured-fail", "command": [sys.executable, "-c", "raise SystemExit(3)"]})
    assert bad["result"] == "failed" and bad["exit_code"] == 3
    rec = reconcile(app)
    assert any(f["code"] == "test_failed" and f["related_ids"] == ["evidence:captured-fail"] for f in rec["findings"])
    with pytest.raises(InvalidInput) as exc:
        evidence_capture(app, {**spec, "id": "evidence:nocmd", "command": ["definitely-not-a-command-xyz"]})
    assert exc.value.code == "command_not_found"
    with pytest.raises(InvalidInput):
        evidence_capture(app, {**spec, "id": "evidence:shell", "command": "pytest -q"})  # string, not argv


def _submit_ok(app, ev_id="evidence:run", paths=("lib/coaching/playback_controller.dart",)):
    return evidence_submit(app, {"id": ev_id, "method": "unit_test", "result": "passed", "collection_mode": "agent_submitted_report", "supports": ["req:cancel-response"],
                                 "inputs": {"repository": "app", "paths": list(paths)}})


def test_source_change_without_model_change_is_detected_in_fresh_process(app: Repository):
    _submit_ok(app)
    assert reconcile(app)["summary"]["evidence_stale"] == 1  # only the fixture evidence (unbound)
    (app.paths.root / "lib/coaching/playback_controller.dart").write_text("class PlaybackController { void cancelResponse(String id) { /* retry */ } }\n")
    code = ("import json,sys\nfrom intentgraph.repository import Repository\nfrom intentgraph.services import reconcile\n"
            "r = reconcile(Repository.find(sys.argv[1]))\nprint(json.dumps({'findings': [f['code'] for f in r['findings']], 'evidence': {e['evidence_id']: e['fresh'] for e in r['evidence']}}))")
    out = json.loads(subprocess.run([sys.executable, "-c", code, str(app.paths.root)], capture_output=True, text=True, check=True).stdout)
    assert out["evidence"]["evidence:run"] is False and "source_changed" in out["findings"]


def test_rename_mapped_file_breaks_locator(app: Repository):
    (app.paths.root / "backend/coaching/coordinator.py").rename(app.paths.root / "backend/coaching/coord.py")
    rec = reconcile(app)
    broken = [f for f in rec["findings"] if f["code"] == "broken_locator"]
    assert [f["related_ids"] for f in broken] == [["symbol:python-cancel"]] and rec["blocking"]
    assert broken[0]["safe_conclusion"] == "The mapping locator is broken."


def test_removed_artifact_downgrades_evidence_grade(app: Repository, tmp_path):
    report = tmp_path / "junit.xml"
    _junit(report)
    out = evidence_submit(app, {"id": "evidence:val", "method": "unit_test", "result": "passed", "collection_mode": "validated_report", "supports": ["req:cancel-response"],
                                "inputs": {"repository": "app", "paths": ["lib/coaching/playback_controller.dart"]}, "artifact": {"path": str(report), "format": "junit-xml"}})
    (app.paths.root / out["artifact_ref"]).unlink()
    rec = reconcile(app)
    e = {x["evidence_id"]: x for x in rec["evidence"]}["evidence:val"]
    assert e["artifact_available"] is False and e["effective_collection_mode"] == "agent_assertion"
    assert any(f["code"] == "evidence_artifact_missing" for f in rec["findings"])


def test_model_change_marks_evidence_stale(app: Repository):
    _submit_ok(app)
    _apply(app, "patch:req-change", [{"op": "update_fields", "id": "req:cancel-response", "description": "Stricter: no audio within 50 ms of cancellation."}])
    rec = reconcile(app)
    e = {x["evidence_id"]: x for x in rec["evidence"]}["evidence:run"]
    assert e["model_scope_changed"] and not e["fresh"]
    assert any(f["code"] == "model_scope_changed" for f in rec["findings"])


def test_unmapped_change_detected_via_git_baseline(app: Repository):
    assert reconcile(app)["workspace"]["app"]["available"] is False  # no baseline yet
    workspace_snapshot(app, "app")
    (app.paths.root / "README.md").write_text("changed but unmapped\n")
    (app.paths.root / "lib/coaching/playback_controller.dart").write_text("// mapped change\n")
    (app.paths.root / "lib/new_feature.dart").write_text("new\n")
    rec = reconcile(app)
    w = rec["workspace"]["app"]
    assert w["available"] and sorted(w["unmapped_paths"]) == ["README.md", "lib/new_feature.dart"]
    assert w["mapped_paths"] == ["lib/coaching/playback_controller.dart"]
    assert any(f["code"] == "unmapped_change" and f["severity"] == "info" for f in rec["findings"])


def test_policy_change_invalidates_approval_and_conformance_uses_freshness(app: Repository):
    _apply(app, "patch:scope", [_node("scope:cancel", "Scope", "reconciliation", {"member_refs": ["component:response-coordinator", "req:cancel-response"], "status": "active", "policy_ref": "policy:default-readiness"}),
                                {"op": "update_properties", "id": "obligation:cancel-late-arrival", "changes": {"state": "satisfied"}}])
    review_export(app, "scope:cancel", record=True)
    approval_record(app, {"scope_ref": "scope:cancel", "recorded_by": "user", "source_statement": "ship it"})
    _submit_ok(app)
    rec = reconcile(app, "scope:cancel")
    assert rec["conformance"]["status"] == "ready" and not rec["blocking"]
    # Stale evidence no longer satisfies conformance; plain `conformance` without freshness says so in its note.
    (app.paths.root / "lib/coaching/playback_controller.dart").write_text("changed\n")
    rec = reconcile(app, "scope:cancel")
    assert rec["conformance"]["status"] == "needs_work" and "stale" in rec["conformance"]["obligations"][0]["request"]
    assert "freshness was not evaluated" in readiness(Context(app), "scope:cancel", kind="conformance")["note"]
    # Changing the applicable policy invalidates the approval (policy version is in the design digest).
    pol = next(p for p in app.load_snapshot().policies if p["id"] == "policy:default-readiness")
    _apply(app, "patch:policy", [{"op": "set_policy", "policy": {**pol, "version": "0.2"}}])
    rec = reconcile(app, "scope:cancel")
    assert any(f["code"] == "approval_invalidated" for f in rec["findings"]) and rec["blocking"]


def test_gate_property_keeps_implementation_obligations_out_of_readiness(app: Repository):
    _apply(app, "patch:scope", [_node("scope:cancel", "Scope", "reconciliation", {"member_refs": ["component:response-coordinator"], "status": "active"}),
                                {"op": "update_properties", "id": "obligation:cancel-late-arrival", "changes": {"state": "satisfied"}},
                                _node("obligation:impl", "Obligation", "reconciliation", {"obligation_kind": "implementation", "blocking": True, "state": "pending", "gate": "conformance", "scope_refs": ["scope:cancel"]}, lifecycle="proposed")])
    ready = readiness(Context(app), "scope:cancel")
    assert "obligation:impl" not in {o["id"] for o in ready["obligations"]}
    conf = readiness(Context(app), "scope:cancel", kind="conformance")
    assert "obligation:impl" in {o["id"] for o in conf["obligations"]}


def test_ci_reports_blockers_only_for_broken_or_authorized_scopes(app: Repository):
    _apply(app, "patch:scope", [_node("scope:cancel", "Scope", "reconciliation", {"member_refs": ["component:response-coordinator", "req:cancel-response"], "status": "active"}),
                                {"op": "update_properties", "id": "obligation:cancel-late-arrival", "changes": {"state": "satisfied"}}])
    out = ci(app)
    sc = out["scopes"][0]
    assert sc["readiness"] == "needs_work" and sc["approval"] == "none" and not out["blocking"]  # work in progress is reported, not failed
    review_export(app, "scope:cancel", record=True)
    approval_record(app, {"scope_ref": "scope:cancel", "recorded_by": "user", "source_statement": "go"})
    out = ci(app)
    assert out["scopes"][0]["approval"] == "current" and out["scopes"][0]["conformance"] == "needs_work" and out["blocking"]  # authorized but not conformant
    _submit_ok(app)
    out = ci(app)
    assert out["scopes"][0]["conformance"] == "ready" and not out["blocking"]
    (app.paths.root / "backend/coaching/coordinator.py").unlink()
    out = ci(app)
    assert out["blocking"] and out["scopes"][0]["reconcile_blockers"] == ["broken_locator:symbol:python-cancel"]


def test_roots_accept_list_and_dict(app: Repository):
    from intentgraph.repository.manifest import ProjectManifest
    base = {"project_id": "project:x", "name": "x", "format_version": "0.1", "vocabulary_version": "core/0.3", "created_at": "t", "created_by_tool_version": "0"}
    assert ProjectManifest.model_validate({**base, "roots": ["app", "web"]}).roots == {"app": "app", "web": "web"}
    assert ProjectManifest.model_validate({**base, "roots": {"app": "apps/mobile"}}).roots == {"app": "apps/mobile"}
    with pytest.raises(InvalidInput) as exc:
        workspace_snapshot(app, "nope")
    assert exc.value.code == "unknown_root"
    with pytest.raises(InvalidInput) as exc:
        workspace_snapshot(app, "app", ["../../etc/passwd"])
    assert exc.value.code == "invalid_path"


def test_directory_inputs_ignore_caches_and_untracked_ignored_files(app: Repository):
    root = app.paths.root
    (root / ".gitignore").write_text("__pycache__/\n*.log\n")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-q", "-m", "ignore")
    out = evidence_submit(app, {"id": "evidence:tree", "method": "unit_test", "result": "passed", "collection_mode": "agent_submitted_report", "supports": ["req:cancel-response"],
                                "inputs": {"repository": "app", "paths": ["backend"]}})
    (root / "backend/coaching/__pycache__").mkdir()
    (root / "backend/coaching/__pycache__/coordinator.cpython-313.pyc").write_bytes(b"\x00bytecode")
    (root / "backend/debug.log").write_text("noise")
    fresh = {e["evidence_id"]: e for e in reconcile(app)["evidence"]}["evidence:tree"]
    assert fresh["fresh"], fresh["reasons"]  # caches and ignored files do not count as source
    (root / "backend/coaching/new_module.py").write_text("x = 1\n")  # untracked but not ignored: counts
    fresh = {e["evidence_id"]: e for e in reconcile(app)["evidence"]}["evidence:tree"]
    assert not fresh["fresh"] and fresh["source_changed"] == ["backend"]
    # Without Git the default ignore list applies.
    from intentgraph.repository import workspace as wsmod
    files = wsmod.tree_files.__wrapped__ if hasattr(wsmod.tree_files, "__wrapped__") else None
    import shutil
    shutil.rmtree(root / ".git")
    names = {p.name for p in wsmod.tree_files(root, root / "backend")}
    assert "coordinator.cpython-313.pyc" not in names and "new_module.py" in names and "debug.log" in names  # *.log only ignored via .gitignore
