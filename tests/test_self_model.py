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
    assert proc.returncode == expect, proc.stdout + proc.stderr
    return json.loads(proc.stdout)["data"]


def test_self_model_is_structurally_valid():
    data = run("rebuild")
    assert not data["blocking"] and data["unresolved_references"] == []


def test_fresh_process_can_resume_milestone_work():
    status = run("status")
    assert status["project_id"] == "project:intentgraph"
    pending = status["outstanding"]["pending_obligations"]
    assert "obligation:m3-readiness" in pending and "obligation:m2-self-model-and-lenses" not in pending
    # The next piece of work and what it concerns.
    rec = run("show", "obligation:m3-readiness")
    assert rec["record"]["properties"]["state"] == "pending" and rec["record"]["properties"]["request"]
    assert {e["target"] for e in rec["outgoing"]} == {"component:obligations"}
    # Its surrounding intent and the cross-cutting rules, without loading the whole model.
    lens = run("view", "--focus", "component:obligations", "--include", "parent_intent", "constraints", "findings")
    assert lens["status"] == "ok" and len(lens["selected_ids"]) < status["counts"]["nodes"]
    assert set(lens["project_rule_ids"]) == {"constraint:no-hidden-state-between-calls", "constraint:records-are-data"}
    assert "obligation:m3-readiness" in lens["selected_ids"]
    # The completed milestone 2 work is traceable: requirement -> mapping -> symbols and evidence.
    mapping = run("show", "mapping:impact-command")["record"]["properties"]
    assert mapping["model_refs"] == ["req:impact-slice"] and "symbol:lenses-impact" in mapping["implementation_refs"]
    evidence = run("show", "evidence:m2-test-suite")["record"]["properties"]
    assert evidence["collection_mode"] == "agent_submitted_report" and evidence["limitations"]
    # Impact of changing the checks module reaches the modules that build on it.
    imp = run("impact", "--changed", "component:checks", "--depth", "1", "--no-references")
    assert {"component:patches", "component:services", "component:obligations"} <= {c["id"] for c in imp["candidates"]}


def test_history_diff_against_git_when_available():
    probe = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"], capture_output=True)
    if probe.returncode != 0:
        pytest.skip("not a git checkout")
    data = run("diff", "--git", "HEAD")
    assert data["mode"] == "git" and data["to_revision"] >= data["from_revision"]
