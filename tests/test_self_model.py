"""Self-use product test (architecture section 21.1): the repository's own model
must validate, and a fresh process must be able to resume milestone work from
the persisted files alone. Not independent proof of correctness."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLI = [sys.executable, "-m", "intentgraph.cli.main", "--json"]

pytestmark = pytest.mark.skipif(not (ROOT / ".intentgraph" / "project.json").is_file(), reason="self-model not present")


def run(*args, expect=0):
    proc = subprocess.run([*CLI, *args], cwd=ROOT, capture_output=True, text=True)
    if expect is not None:
        assert proc.returncode == expect, proc.stdout + proc.stderr
    return json.loads(proc.stdout)["data"]


def test_self_model_is_structurally_valid():
    data = run("rebuild")
    assert not data["blocking"] and data["unresolved_references"] == []


def test_fresh_process_can_resume_milestone_work():
    status = run("status")
    assert status["project_id"] == "project:intentgraph"
    pending = status["outstanding"]["pending_obligations"]
    assert "obligation:m6-ab-evaluation" in pending
    assert not {"obligation:m2-self-model-and-lenses", "obligation:m3-readiness", "obligation:m4-evidence-reconciliation", "obligation:m5-installable"} & set(pending)
    # The next piece of work, its scope, and what it concerns.
    rec = run("show", "obligation:m6-ab-evaluation")
    assert rec["record"]["properties"]["state"] == "pending" and rec["record"]["properties"]["request"]
    assert rec["record"]["properties"]["scope_refs"] == ["scope:m6-ab-evaluation"] and rec["record"]["properties"]["gate"] == "conformance"
    # Delivered scopes: milestone 3 closed (its approval was invalidated by a tool semantic change, recorded on the scope),
    # milestone 4 ready and approved, and a standing conformance scope that is never approved.
    gates = {g["scope"]: g for g in status["gates"]["scopes"]}
    assert "scope:m3-readiness" not in gates
    assert gates["scope:m4-evidence-reconciliation"]["readiness"] == "ready" and gates["scope:m4-evidence-reconciliation"]["approval"] == "current"
    assert gates["scope:m5-installable"]["readiness"] == "ready" and gates["scope:m5-installable"]["approval"] == "current"
    assert gates["scope:package-guarantees"]["approval"] == "none"
    # The distribution revision is traceable: the superseded executable requirement, the user's decision, and the invalidated-then-renewed approval.
    assert run("show", "req:bundled-executable")["record"]["lifecycle"] == "superseded"
    assert run("show", "decision:uv-tool-install")["record"]["properties"]["decided_by"] == "user"
    assert run("show", "approval:m5-installable/r25")["record"]["properties"]["source_statement"].startswith("I'd make a Python package")
    m3 = run("show", "scope:m3-readiness")["record"]
    assert m3["properties"]["status"] == "closed" and any("invalidated" in a["text"] for a in m3["annotations"])
    ready = run("readiness", "--scope", "scope:m4-evidence-reconciliation")
    assert ready["design_digest"] == ready["approval"]["design_digest"]
    assert "obligation:m6-ab-evaluation" not in {o["id"] for o in ready["obligations"]}
    # Surrounding intent and cross-cutting rules for the next scope, without loading the whole model.
    lens = run("view", "--focus", "system:intentgraph", "--include", "parent_intent", "constraints", "findings")
    assert lens["status"] == "ok" and len(lens["selected_ids"]) < status["counts"]["nodes"]
    assert set(lens["project_rule_ids"]) == {"constraint:no-hidden-state-between-calls", "constraint:records-are-data"}
    assert "obligation:m5-installable" in lens["selected_ids"]  # delivered work concerning the system
    assert run("show", "scope:m6-ab-evaluation")["record"]["properties"]["status"] == "draft"  # next milestone's scope exists
    # Traceability of delivered work: requirement -> mapping -> symbols, and tool-captured evidence.
    mapping = run("show", "mapping:evidence-ingestion")["record"]["properties"]
    assert "req:collection-mode-preserved" in mapping["model_refs"] and "symbol:m4-evidence-capture" in mapping["implementation_refs"]
    evidence = run("show", "evidence:m5-pytest-capture")["record"]["properties"]
    assert evidence["collection_mode"] == "independent_capture" and evidence["result"] == "passed"
    assert evidence["workspace_snapshot_ref"].startswith("workspace:")
    # Impact of changing the checks module reaches the modules that build on it.
    imp = run("impact", "--changed", "component:checks", "--depth", "1", "--no-references")
    assert {"component:patches", "component:services", "component:obligations"} <= {c["id"] for c in imp["candidates"]}


def test_reconcile_runs_on_self_model_without_blockers():
    """Evidence may be stale in a working tree that edits the source (that is the point); only blockers fail this."""
    data = run("reconcile", "--scope", "scope:m5-installable", expect=None)
    assert data["summary"]["blockers"] == 0, data["findings"]
    codes = {f["code"] for f in data["findings"]}
    assert not codes & {"broken_locator", "unknown_root", "test_failed", "approval_invalidated"}


def test_history_diff_against_git_when_available():
    probe = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"], capture_output=True)
    if probe.returncode != 0:
        pytest.skip("not a git checkout")
    data = run("diff", "--git", "HEAD")
    assert data["mode"] == "git" and data["to_revision"] >= data["from_revision"]
