"""CLI behaviour in fresh processes: each call reconstructs state from files."""
import json
import subprocess
import sys
from pathlib import Path

from conftest import FIXTURES

CLI = [sys.executable, "-m", "intentgraph.cli.main"]


def run(*args, cwd: Path, expect: int):
    proc = subprocess.run([*CLI, "--json", *args], cwd=cwd, capture_output=True, text=True)
    assert proc.returncode == expect, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def test_full_cli_round_trip(tmp_path: Path):
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text("# Existing instructions\nKeep me.\n")
    out = run("init", "--name", "cli-demo", cwd=ws, expect=0)
    assert out["status"] == "ok" and out["data"]["created"] and out["data"]["pointer"]["status"] == "appended"
    assert (ws / "CLAUDE.md").read_text().startswith("# Existing instructions\nKeep me.")
    out = run("init", cwd=ws, expect=0)
    assert not out["data"]["created"] and out["data"]["pointer"]["status"] == "present"

    status = run("status", cwd=ws, expect=0)["data"]
    assert status["revision"] == 0
    # The fixture's symbols name repository root "app"; configure it (a list form is also accepted).
    manifest = json.loads((ws / ".intentgraph" / "project.json").read_text())
    manifest["roots"] = {".": ".", "app": "."}
    (ws / ".intentgraph" / "project.json").write_text(json.dumps(manifest))
    for rel in ("lib/coaching/playback_controller.dart", "backend/coaching/coordinator.py", "test/coaching/cancel_test.dart"):
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text("stub\n")

    patch = json.loads((FIXTURES / "coaching-patch.json").read_text())
    patch["base_revision"] = status["revision"]
    patch["base_digest"] = status["content_digest"]
    pfile = tmp_path / "patch.json"
    pfile.write_text(json.dumps(patch))

    out = run("patch", "validate", "--file", str(pfile), cwd=ws, expect=0)
    assert out["data"]["valid"]
    out = run("patch", "apply", "--file", str(pfile), cwd=ws, expect=0)
    assert out["data"]["revision"] == 1

    # Fresh process, nested cwd: state comes only from files.
    nested = ws / "lib" / "x"
    nested.mkdir(parents=True)
    status = run("status", cwd=nested, expect=0)["data"]
    assert status["revision"] == 1 and status["counts"]["nodes"] == 31
    assert status["outstanding"]["blocking_questions"] == ["question:cancel-scope"]
    assert status["outstanding"]["pending_obligations"] == ["obligation:cancel-late-arrival"]
    assert status["gates"]["status"] == "no_active_scope"

    # Stale base -> exit 3 with changed ids.
    out = run("patch", "apply", "--file", str(pfile), cwd=ws, expect=0)  # idempotent replay
    assert out["data"]["idempotent_replay"]
    patch["patch_id"] = "patch:second"
    pfile.write_text(json.dumps(patch))
    out = run("patch", "apply", "--file", str(pfile), cwd=ws, expect=3)
    assert out["status"] == "invalid" and out["error"]["code"] == "stale_base"
    assert "req:cancel-response" in out["error"]["details"]["changed_ids"]

    # Invalid candidate -> validate exits 2 and apply exits 3; nothing written.
    status = run("status", cwd=ws, expect=0)["data"]
    bad = {"patch_id": "patch:bad", "base_revision": 1, "base_digest": status["content_digest"], "operations": [
        {"op": "add_node", "record": {"id": "req:x", "kind": "Requirement", "label": "x", "layer": "intent", "provenance": {"author_role": "agent", "method": "t"}}}]}
    pfile.write_text(json.dumps(bad))
    out = run("patch", "validate", "--file", str(pfile), cwd=ws, expect=2)
    assert not out["data"]["valid"] and out["data"]["diagnostics"][0]["code"] == "invalid_property"
    out = run("patch", "apply", "--file", str(pfile), cwd=ws, expect=3)
    assert out["error"]["code"] == "validation_failed"
    assert run("status", cwd=ws, expect=0)["data"]["revision"] == 1

    out = run("vocabulary", "show", "depends_on", cwd=ws, expect=0)["data"]
    assert out["type"] == "relation" and out["definition"]["required_properties"] == ["dependency_kind"]
    out = run("vocabulary", "show", "Requirement", cwd=ws, expect=0)["data"]
    assert out["definition"]["properties"]["priority"]["enum"] == ["must", "should", "could"]
    run("vocabulary", "show", "Nope", cwd=ws, expect=3)

    out = run("view", "--focus", "operation:cancel-response", "--include", "parent_intent", cwd=ws, expect=0)["data"]
    assert "req:cancel-response" in out["selected_ids"]
    out = run("search", "--text", "late", cwd=ws, expect=0)["data"]
    assert out["count"] >= 2
    out = run("show", "req:cancel-response", cwd=ws, expect=0)["data"]
    assert {r["id"] for r in out["referenced_by"]} >= {"mapping:cancel-controller", "evidence:late-response-test"}

    out = run("impact", "--changed", "interface:response-events", "--depth", "1", cwd=ws, expect=0)["data"]
    assert {c["id"] for c in out["candidates"]} >= {"component:playback-controller", "component:response-coordinator"}
    out = run("diff", "--since", "0", cwd=ws, expect=0)["data"]
    assert out["summary"]["added"] == 51
    out = run("diff", "--git", "HEAD", cwd=ws, expect=4)
    assert out["status"] == "error" and out["error"]["code"] == "git_failed"

    # Readiness loop through the CLI: scope -> needs_work -> resolve -> review export -> ready -> approval.
    status = run("status", cwd=ws, expect=0)["data"]
    scope_patch = {"patch_id": "patch:scope", "base_revision": status["revision"], "base_digest": status["content_digest"], "operations": [
        {"op": "add_node", "record": {"id": "scope:cancel", "kind": "Scope", "label": "Cancellation", "layer": "reconciliation", "lifecycle": "accepted",
                                      "properties": {"member_refs": ["component:response-coordinator"], "status": "active"}, "provenance": {"author_role": "agent", "method": "t"}}},
        {"op": "update_properties", "id": "obligation:cancel-late-arrival", "changes": {"state": "satisfied"}}]}
    pfile.write_text(json.dumps(scope_patch))
    run("patch", "apply", "--file", str(pfile), cwd=ws, expect=0)
    out = run("readiness", "--scope", "scope:cancel", cwd=ws, expect=2)["data"]
    assert out["status"] == "needs_work" and [o["id"] for o in out["obligations"]] == ["obligation:cancel/packet/scope"]
    assert run("status", cwd=ws, expect=0)["data"]["gates"]["scopes"][0]["readiness"] == "needs_work"
    out = run("review", "export", "--scope", "scope:cancel", "--record", cwd=ws, expect=0)["data"]
    assert out["recorded"]["revision"] == 3 and Path(out["markdown"]).is_file()
    out = run("readiness", "--scope", "scope:cancel", cwd=ws, expect=0)["data"]
    assert out["status"] == "ready"
    afile = tmp_path / "approval.json"
    afile.write_text(json.dumps({"scope_ref": "scope:cancel", "recorded_by": "agent", "source_statement": "Build it."}))
    out = run("approval", "record", "--file", str(afile), cwd=ws, expect=0)["data"]
    assert out["approval_status_after"]["status"] == "current"
    out = run("conformance", "--scope", "scope:cancel", cwd=ws, expect=0)["data"]
    assert out["status"] == "ready" and out["policy_kind"] == "conformance"
    assert {p["id"] for p in run("policy", "list", cwd=ws, expect=0)["data"]["policies"]} == {"policy:default-readiness", "policy:default-conformance"}
    assert run("migrate", cwd=ws, expect=0)["data"]["steps"] == []
    out = run("workspace", "snapshot", "--repository", ".", "--paths", "CLAUDE.md", cwd=ws, expect=0)["data"]
    assert "CLAUDE.md" in out["properties"]["files"] and out["recorded"]["revision"] == 5
    (ws / "lib" / "x" / "thing.txt").write_text("t")
    efile = tmp_path / "ev.json"
    efile.write_text(json.dumps({"id": "evidence:cli", "method": "unit_test", "result": "passed", "collection_mode": "agent_submitted_report", "supports": ["req:cancel-response"], "inputs": {"repository": ".", "paths": ["lib/x/thing.txt"]}}))
    assert run("evidence", "submit", "--file", str(efile), cwd=ws, expect=0)["data"]["evidence_id"] == "evidence:cli"
    out = run("reconcile", "--scope", "scope:cancel", cwd=ws, expect=0)["data"]
    assert out["conformance"]["status"] == "ready" and not out["blocking"]
    (ws / "lib" / "x" / "thing.txt").write_text("changed")
    out = run("reconcile", "--scope", "scope:cancel", cwd=ws, expect=2)["data"]
    assert out["conformance"]["status"] == "needs_work" and any(f["code"] == "source_changed" for f in out["findings"])
    out = run("ci", cwd=ws, expect=2)["data"]
    assert out["blocking"] and out["scopes"][0]["evidence"]["stale"] >= 1

    out = run("check", cwd=ws, expect=0)["data"]
    assert not out["blocking"]
    out = run("rebuild", cwd=ws, expect=0)["data"]
    assert out["graph"] == {"nodes": 37, "edges": 23} and out["unresolved_references"] == []


def test_no_workspace_is_invalid_input(tmp_path: Path):
    out = run("status", cwd=tmp_path, expect=3)
    assert out["error"]["code"] == "workspace_not_found"


def test_human_output(tmp_path: Path):
    ws = tmp_path / "h"
    ws.mkdir()
    subprocess.run([*CLI, "init", "--no-pointer"], cwd=ws, check=True, capture_output=True)
    proc = subprocess.run([*CLI, "status"], cwd=ws, capture_output=True, text=True)
    assert proc.returncode == 0 and "revision 0" in proc.stdout
    assert not (ws / "AGENTS.md").exists()
