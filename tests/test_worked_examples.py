"""The steps shown in docs/worked-examples.md, executed."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from intentgraph.patches import Patch
from intentgraph.repository import Repository
from intentgraph.services import Context, approval_record, capabilities, evidence_submit, impact, patch_apply, readiness, reconcile, review_export, status

U = {"author_role": "user", "method": "conversation"}
A = {"author_role": "agent", "method": "interpretation"}
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def _apply(repo, pid, ops):
    snap = repo.load_snapshot()
    return patch_apply(repo, Patch.model_validate({"patch_id": pid, "base_revision": snap.revision, "base_digest": snap.content_digest, "operations": ops}))


def n(id, kind, layer, props=None, lifecycle="accepted", prov=A, label=None, annotations=None, description=""):
    return {"op": "add_node", "record": {"id": id, "kind": kind, "label": label or id, "layer": layer, "description": description, "properties": props or {}, "lifecycle": lifecycle, "provenance": prov, "annotations": annotations or []}}


def e(id, kind, s, t, layer="intent", props=None):
    return {"op": "add_edge", "record": {"id": id, "kind": kind, "source": s, "target": t, "layer": layer, "properties": props or {}, "lifecycle": "accepted", "provenance": A}}


def _obl(res):
    return {o["id"]: o for o in res["obligations"]}


@pytest.fixture
def ws(tmp_path):
    repo, _ = Repository.init(tmp_path / "app", name="examples")
    return repo


def test_example_1_successful_refinement(ws):
    _apply(ws, "patch:goal", [n("goal:interrupt", "Goal", "intent", prov=U, label="Learner can interrupt the coach",
                                annotations=[{"role": "original_intent", "text": "The learner must be able to interrupt the coach."}])])
    _apply(ws, "patch:refine", [
        n("req:stop", "Requirement", "intent", {"priority": "must", "formalization": "descriptive"}, label="Learner can stop an active response"),
        n("scenario:stop-mid-answer", "Scenario", "intent", {"steps": ["coach is speaking", "learner taps stop"], "expected_outcome": "speech stops"}),
        n("decision:stable-response-id", "Decision", "intent", {"decided_by": "user", "decision_kind": "choice", "rationale": "late content must be attributable"}, prov=U),
        n("component:player", "Component", "intent", {"role": "frontend"}), n("interface:control", "Interface", "intent"),
        n("operation:stop", "Operation", "intent", {}),
        e("e:req-refines-goal", "refines", "req:stop", "goal:interrupt"), e("e:scn-refines-req", "refines", "scenario:stop-mid-answer", "req:stop"),
        e("e:dec-concerns-req", "concerns", "decision:stable-response-id", "req:stop"),
        e("e:player-exposes", "exposes", "component:player", "interface:control"), e("e:ctl-declares-stop", "declares", "interface:control", "operation:stop"),
        e("e:stop-realizes", "realizes", "operation:stop", "req:stop"),
        n("scope:interrupt", "Scope", "reconciliation", {"member_refs": ["component:player", "req:stop"], "status": "active"}),
    ])
    r = readiness(Context(ws), "scope:interrupt")
    assert r["status"] == "needs_work" and {"obligation:interrupt/operations/operation.stop", "obligation:interrupt/packet/scope"} <= set(_obl(r))
    _apply(ws, "patch:contract", [{"op": "update_properties", "id": "operation:stop", "changes": {"inputs": {"response_id": "id"}, "outputs": {"acknowledged": "bool"}, "failures": ["unknown_response"]}}])
    out = review_export(ws, "scope:interrupt", record=True)
    assert "req:stop" in out["coverage"]["ids"] and out["recorded"]["revision"] > 0
    packet = json.loads(Path(out["json"]).read_text())
    assert packet["diagram"]["format"] == "mermaid" and "n0" in packet["diagram"]["text"] and "exposes" in packet["diagram"]["text"]
    r = readiness(Context(ws), "scope:interrupt")
    assert r["status"] == "ready"
    a = approval_record(ws, {"scope_ref": "scope:interrupt", "recorded_by": "agent", "source_statement": "Yes, build the interrupt feature."})
    assert a["approval_status_after"]["status"] == "current"


def test_example_2_ambiguous_requirement(ws):
    _apply(ws, "patch:ambiguous", [
        n("req:stop", "Requirement", "intent", {"priority": "must", "formalization": "descriptive"}, lifecycle="proposed"),
        n("question:stop-scope", "Question", "intent", {"status": "open", "blocking": True}, lifecycle="proposed", label="Does stop also cancel pending generation?"),
        e("e:q-concerns-req", "concerns", "question:stop-scope", "req:stop"),
        n("scope:stop", "Scope", "reconciliation", {"member_refs": ["req:stop"], "status": "active"}),
    ])
    r = readiness(Context(ws), "scope:stop")
    assert r["status"] == "blocked" and _obl(r)["obligation:stop/questions/question.stop-scope"]["acceptable_resolution"] == ["user_clarification"]
    # An agent-written waiver does not clear it.
    _apply(ws, "patch:bad-waiver", [n("obligation:stop/questions/question.stop-scope", "Obligation", "reconciliation", {"obligation_kind": "intent_question", "blocking": True, "state": "waived", "waiver": {"authorized_by": "agent", "reason": "probably playback only"}})])
    r = readiness(Context(ws), "scope:stop")
    assert r["status"] == "blocked" and any(f["code"] == "invalid_waiver" for f in r["findings"])
    _apply(ws, "patch:answer", [
        {"op": "update_properties", "id": "question:stop-scope", "changes": {"status": "answered", "answer": "Both: playback stops and pending generation is cancelled."}},
        n("decision:stop-cancels-generation", "Decision", "intent", {"decided_by": "user", "decision_kind": "choice", "rationale": "user said so"}, prov=U),
        e("e:dec-concerns", "concerns", "decision:stop-cancels-generation", "req:stop"),
        {"op": "update_fields", "id": "req:stop", "lifecycle": "accepted"},
        {"op": "remove", "id": "obligation:stop/questions/question.stop-scope"},
    ])
    r = readiness(Context(ws), "scope:stop")
    assert r["status"] == "needs_work" and "obligation:stop/questions/question.stop-scope" not in _obl(r)
    assert "obligation:stop/realized/req.stop" in _obl(r)  # the real next obligation


def test_example_3_stale_evidence_after_code_change(ws):
    root = ws.paths.root
    (root / "src").mkdir()
    (root / "src" / "player.py").write_text("def stop(rid):\n    return True\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_player.py").write_text("def test_stop():\n    assert True\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base"], cwd=root, check=True, capture_output=True, env=GIT_ENV)
    _apply(ws, "patch:model", [
        n("req:stop", "Requirement", "intent", {"priority": "must", "formalization": "descriptive"}),
        n("operation:stop", "Operation", "intent", {"inputs": {}, "outputs": {}, "failures": []}), e("e:realizes", "realizes", "operation:stop", "req:stop"),
        n("symbol:stop", "CodeSymbol", "observation", {"repository": ".", "path": "src/player.py", "symbol": "stop", "resolution_status": "resolved"}),
        n("test:stop", "TestCase", "observation", {"repository": ".", "path": "tests/test_player.py", "test_id": "test_stop"}),
        n("mapping:stop", "Mapping", "reconciliation", {"model_refs": ["req:stop"], "implementation_refs": ["symbol:stop", "test:stop"], "mapping_kind": "implements"}),
        n("scope:interrupt", "Scope", "reconciliation", {"member_refs": ["operation:stop", "req:stop"], "status": "active"}),
    ])
    review_export(ws, "scope:interrupt", record=True)
    approval_record(ws, {"scope_ref": "scope:interrupt", "recorded_by": "user", "source_statement": "go"})
    evidence_submit(ws, {"id": "evidence:run-1", "method": "unit_test", "result": "passed", "collection_mode": "agent_submitted_report", "supports": ["req:stop"], "test_refs": ["test:stop"],
                         "inputs": {"repository": ".", "paths": ["src/player.py", "tests/test_player.py"]}})
    rec = reconcile(ws, "scope:interrupt")
    assert rec["conformance"]["status"] == "ready" and not rec["blocking"]
    (root / "src" / "player.py").write_text("def stop(rid):\n    return False  # regression\n")
    rec = reconcile(ws, "scope:interrupt")
    assert any(f["code"] == "source_changed" for f in rec["findings"]) and rec["conformance"]["status"] == "needs_work" and rec["blocking"]
    (root / "src" / "player.py").write_text("def stop(rid):\n    return True\n")
    assert reconcile(ws, "scope:interrupt")["conformance"]["status"] == "ready"  # content-based, not time-based


def test_example_4_counterexample(ws):
    _apply(ws, "patch:rule", [
        n("entity:response", "Entity", "intent", {"fields": {"cancelled": "bool", "playing": "bool"}}),
        n("assumption:monotonic", "Assumption", "intent", {"status": "unverified"}),
        n("operation:cancel", "Operation", "intent", {"inputs": {}, "outputs": {}, "failures": []}),
        n("constraint:silent", "Constraint", "intent", {"constraint_kind": "temporal_safety", "expression_language": "intent-expr/0.1", "assumption_refs": ["assumption:monotonic"],
            "expression": {"op": "always", "arg": {"op": "forall", "variable": "r", "domain_ref": "entity:response", "body": {"op": "implies", "left": {"op": "field_eq", "variable": "r", "field": "cancelled", "value": True}, "right": {"op": "field_eq", "variable": "r", "field": "playing", "value": False}}}}}),
        e("e:constrains", "constrains", "constraint:silent", "operation:cancel"),
        n("scope:cancel", "Scope", "reconciliation", {"member_refs": ["operation:cancel"], "status": "active"}),
    ])
    _apply(ws, "patch:counterexample", [
        n("analysis:tlc-1", "AnalysisRun", "reconciliation", {"tool": "tlc", "outcome": "counterexample", "config": {"states": 3, "trace": ["pending", "cancelled", "playing"]}}),
        n("finding:late-play", "Finding", "reconciliation", {"finding_kind": "counterexample", "severity": "blocker", "state": "open", "related_refs": ["constraint:silent", "operation:cancel"], "detail": "trace reaches playing after cancelled"}),
        e("e:f-challenges-c", "challenges", "finding:late-play", "constraint:silent", layer="reconciliation"),
        e("e:f-challenges-op", "challenges", "finding:late-play", "operation:cancel", layer="reconciliation"),
    ])
    st = status(Context(ws))
    assert st["outstanding"]["open_findings"] == ["finding:late-play"]
    imp = impact(Context(ws), {"changed": ["constraint:silent"], "max_depth": 1, "include_references": False})
    assert {c["id"] for c in imp["candidates"]} == {"operation:cancel", "finding:late-play"}  # what the rule governs, and the finding that challenges it
    # Resolution leaves a record: a design fix plus the finding resolved.
    _apply(ws, "patch:fix", [
        n("transition:reject-late", "Transition", "intent", {"from_state": "state:cancelled", "to_state": "state:cancelled", "guard": "late content for cancelled id"}) | {},
        n("state:cancelled", "State", "intent", {"entity_ref": "entity:response", "terminal": True}),
        {"op": "update_properties", "id": "finding:late-play", "changes": {"state": "resolved"}},
    ])
    assert status(Context(ws))["outstanding"]["open_findings"] == []


def test_example_5_unsupported_analysis(ws):
    _apply(ws, "patch:unsupported", [
        n("req:audio-latency", "Requirement", "intent", {"priority": "must", "formalization": "descriptive"}, label="No audible continuation 50 ms after cancel"),
        n("operation:cancel", "Operation", "intent", {"inputs": {}, "outputs": {}, "failures": []}), e("e:realizes", "realizes", "operation:cancel", "req:audio-latency"),
        n("analysis:device-timing", "AnalysisRun", "reconciliation", {"tool": "none-available", "outcome": "unsupported", "config": {"reason": "needs a physical device measurement"}}),
        n("obligation:measure-device", "Obligation", "reconciliation", {"obligation_kind": "measurement", "blocking": True, "state": "blocked", "scope_refs": ["req:audio-latency"], "request": "Measure on the target device."}),
        n("scope:latency", "Scope", "reconciliation", {"member_refs": ["operation:cancel", "req:audio-latency"], "status": "active"}),
    ])
    r = readiness(Context(ws), "scope:latency")
    assert r["status"] == "blocked" and _obl(r)["obligation:measure-device"]["state"] == "blocked"
    caps = capabilities()
    assert any(u["capability"].startswith("formal analysis") and u["status"] == "recording only" for u in caps["unsupported"])
    # A hand measurement recorded as evidence with its limitations, then the obligation closes.
    evidence_submit(ws, {"id": "evidence:device-measurement", "method": "manual_measurement", "result": "passed", "collection_mode": "agent_submitted_report", "supports": ["req:audio-latency", "obligation:measure-device"],
                         "limitations": ["measured once on one device"], "inputs": {"repository": ".", "paths": []}})
    _apply(ws, "patch:close", [{"op": "update_properties", "id": "obligation:measure-device", "changes": {"state": "satisfied"}}])
    assert readiness(Context(ws), "scope:latency")["status"] != "blocked"
