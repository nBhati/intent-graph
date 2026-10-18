"""Milestone 3 guarantees (architecture sections 13, 21.6, 22)."""
import json

import pytest

from intentgraph.errors import InvalidInput, ValidationFailed
from intentgraph.patches import Patch
from intentgraph.repository import Repository
from intentgraph.services import Context, approval_record, patch_apply, readiness, review_export

PROV = {"author_role": "agent", "method": "t"}


def _apply(repo, pid, ops):
    snap = repo.load_snapshot()
    return patch_apply(repo, Patch.model_validate({"patch_id": pid, "base_revision": snap.revision, "base_digest": snap.content_digest, "operations": ops}))


def _node(id, kind, layer, props, lifecycle="accepted", label=None):
    return {"op": "add_node", "record": {"id": id, "kind": kind, "label": label or id, "layer": layer, "properties": props, "lifecycle": lifecycle, "provenance": PROV}}


def _edge(id, kind, s, t, layer="intent"):
    return {"op": "add_edge", "record": {"id": id, "kind": kind, "source": s, "target": t, "layer": layer, "lifecycle": "accepted", "provenance": PROV}}


SCOPE = _node("scope:cancel", "Scope", "reconciliation", {"member_refs": ["component:response-coordinator", "component:playback-controller"], "status": "active", "policy_ref": "policy:default-readiness"}, label="Cancellation scope")


@pytest.fixture
def scoped(coaching_repo: Repository) -> Repository:
    _apply(coaching_repo, "patch:scope", [SCOPE])
    return coaching_repo


def _r(repo, scope="scope:cancel", **kw):
    return readiness(Context(repo), scope, **kw)


def _oblig(res):
    return {o["id"]: o for o in res["obligations"]}


def test_missing_obligations_are_actionable_and_readiness_does_not_modify(scoped):
    before = scoped.paths.model.read_text()
    res = _r(scoped)
    assert res["status"] == "needs_work" and res["policy"] == "policy:default-readiness@0.1"
    o = _oblig(res)
    assert "obligation:cancel/packet/scope" in o and o["obligation:cancel/packet/scope"]["acceptable_resolution"] == ["review_export"]
    assert "obligation:cancel-late-arrival" in o and o["obligation:cancel-late-arrival"]["source"] == "model"
    assert all(x["request"] for x in res["obligations"])
    reasons = {m["id"]: m["reason"] for m in res["closure"]["members"]}
    assert reasons["req:cancel-response"] == "realized by member" and reasons["constraint:cancelled-response-silent"] in ("constraint on member", "global rule")
    assert reasons["operation:cancel-response"] == "structural child via declares"
    assert "question:cancel-scope" not in reasons
    assert any(w["kind"] == "unverified_assumption" for w in res["warnings"])
    assert scoped.paths.model.read_text() == before  # readiness never writes


def test_blocking_question_blocks(scoped):
    _apply(scoped, "patch:q", [{"op": "update_properties", "id": "scope:cancel", "changes": {"member_refs": ["component:response-coordinator", "component:playback-controller", "req:stop-active-response"]}},
                                {"op": "update_fields", "id": "req:stop-active-response", "lifecycle": "accepted"}])
    res = _r(scoped)
    assert res["status"] == "blocked"
    o = _oblig(res)
    assert o["obligation:cancel/questions/question.cancel-scope"]["state"] == "blocked"
    assert o["obligation:cancel/questions/question.cancel-scope"]["acceptable_resolution"] == ["user_clarification"]
    assert "obligation:cancel/realized/req.stop-active-response" in o  # accepted but unrealized


def test_deferral_decision_satisfies_realization(scoped):
    _apply(scoped, "patch:q", [{"op": "update_properties", "id": "scope:cancel", "changes": {"member_refs": ["component:response-coordinator", "req:stop-active-response"]}},
                                {"op": "update_fields", "id": "req:stop-active-response", "lifecycle": "accepted"},
                                {"op": "update_properties", "id": "question:cancel-scope", "changes": {"status": "deferred"}}])
    assert "obligation:cancel/realized/req.stop-active-response" in _oblig(_r(scoped))
    _apply(scoped, "patch:defer", [_node("decision:defer-stop", "Decision", "intent", {"decision_kind": "deferral", "decided_by": "user", "rationale": "later"}),
                                    _edge("edge:defer-concerns-stop", "concerns", "decision:defer-stop", "req:stop-active-response")])
    assert "obligation:cancel/realized/req.stop-active-response" not in _oblig(_r(scoped))


def _make_ready(repo):
    _apply(repo, "patch:resolve", [{"op": "update_properties", "id": "obligation:cancel-late-arrival", "changes": {"state": "satisfied"}}])
    review_export(repo, "scope:cancel", record=True)
    res = _r(repo)
    assert res["status"] == "ready", res["obligations"]
    return res


def test_review_packet_then_approval_digest_stability_and_invalidation(scoped, tmp_path):
    ready = _make_ready(scoped)
    digest = ready["design_digest"]
    packet = json.loads((scoped.paths.artifacts / "review-cancel.json").read_text())
    assert packet["design_digest"] == digest and "req:cancel-response" in packet["coverage"]["ids"]
    md = (scoped.paths.artifacts / "review-cancel.md").read_text()
    assert "Cancelled responses do not restart speech" in md and digest in md
    # Approval: recorded by the agent from the user's words; does not change the design digest.
    out = approval_record(scoped, {"scope_ref": "scope:cancel", "recorded_by": "agent", "source_statement": "Yes, build the cancellation scope.", "source_ref": "chat:2026-10-18#12"})
    assert out["design_digest"] == digest == out["design_digest_after"]
    assert out["approval_status_after"]["status"] == "current"
    rec = scoped.load_snapshot().get(out["approval_id"])
    assert rec.properties["design_digest"] == digest and rec.properties["source_statement"].startswith("Yes")
    # Unrelated evidence addition: approval stays current.
    _apply(scoped, "patch:evidence", [_node("evidence:extra", "Evidence", "reconciliation", {"method": "unit_test", "result": "passed", "collection_mode": "validated_report", "supports": ["req:cancel-response"]})])
    res = _r(scoped)
    assert res["status"] == "ready" and res["approval"]["status"] == "current" and res["design_digest"] == digest
    # Unrelated intent addition outside the closure: still current.
    _apply(scoped, "patch:outside", [_node("goal:unrelated", "Goal", "intent", {})])
    assert _r(scoped)["approval"]["status"] == "current"
    # Relevant design change inside the scope: approval invalidated, packet stale, affected approval named.
    _apply(scoped, "patch:change", [{"op": "update_properties", "id": "operation:cancel-response", "changes": {"idempotent": False}}])
    res = _r(scoped)
    assert res["status"] == "needs_work" and res["design_digest"] != digest
    assert res["approval"]["status"] == "invalidated" and res["approval"]["approval_id"] == out["approval_id"]
    assert res["approval"]["changed_in_scope_ids"] == ["operation:cancel-response"]
    assert "obligation:cancel/packet/scope" in _oblig(res)


def test_approval_refused_when_not_ready(scoped):
    with pytest.raises(InvalidInput) as exc:
        approval_record(scoped, {"scope_ref": "scope:cancel", "recorded_by": "user", "source_statement": "go"})
    assert exc.value.code == "scope_not_ready" and exc.value.details["obligations"]
    with pytest.raises(InvalidInput):
        approval_record(scoped, {"scope_ref": "scope:cancel", "recorded_by": "agent", "source_statement": ""})


def test_waiver_requires_user_authorization(scoped):
    oid = "obligation:cancel/packet/scope"
    _apply(scoped, "patch:bad-waiver", [_node(oid, "Obligation", "reconciliation", {"obligation_kind": "review_packet", "blocking": True, "state": "waived", "waiver": {"authorized_by": "agent", "reason": "seems fine"}})])
    res = _r(scoped)
    assert oid in _oblig(res) and any(f["code"] == "invalid_waiver" for f in res["findings"])
    _apply(scoped, "patch:good-waiver", [{"op": "update_properties", "id": oid, "changes": {"waiver": {"authorized_by": "user", "reason": "Prototype scope; packet not needed.", "source_statement": "skip the packet for this one"}}}])
    res = _r(scoped)
    assert oid not in _oblig(res) and [w["id"] for w in res["waived"]] == [oid]


def test_agent_assertion_cannot_satisfy_executable_evidence(scoped):
    _apply(scoped, "patch:assert", [{"op": "update_properties", "id": "evidence:late-response-test", "changes": {"collection_mode": "agent_assertion"}}])
    res = _r(scoped, kind="conformance")
    o = _oblig(res)
    assert "obligation:cancel/tested/req.cancel-response" in o
    assert "agent_assertion" in o["obligation:cancel/tested/req.cancel-response"]["request"]
    _apply(scoped, "patch:report", [{"op": "update_properties", "id": "evidence:late-response-test", "changes": {"collection_mode": "agent_submitted_report"}}])
    assert "obligation:cancel/tested/req.cancel-response" not in _oblig(_r(scoped, kind="conformance"))


def test_policy_change_is_explicit_and_validated(scoped):
    with pytest.raises(ValidationFailed):
        _apply(scoped, "patch:badpol", [{"op": "set_policy", "policy": {"id": "policy:x", "version": "1", "kind": "readiness", "rules": [{"id": "r", "rule": "run_shell", "params": {}}]}}])
    r = _apply(scoped, "patch:pol", [{"op": "set_policy", "policy": {"id": "policy:lenient", "version": "0.1", "kind": "readiness", "rules": [{"id": "s", "rule": "structural_checks_pass"}]}}])
    assert r["effects"]["added_ids"] == ["policy:lenient"]
    res = _r(scoped, policy_id="policy:lenient")
    assert res["policy"] == "policy:lenient@0.1" and [o["source"] for o in res["obligations"]] == ["model"]
    with pytest.raises(InvalidInput):
        _r(scoped, policy_id="policy:nope")
    # Policy version is part of the design digest.
    d1 = _r(scoped)["design_digest"]
    current = next(p for p in scoped.load_snapshot().policies if p["id"] == "policy:default-readiness")
    _apply(scoped, "patch:bump", [{"op": "set_policy", "policy": {**json.loads(json.dumps(current)), "version": "0.2"}}])
    assert _r(scoped)["design_digest"] != d1


def test_unknown_scope(scoped):
    with pytest.raises(InvalidInput) as exc:
        _r(scoped, scope="component:playback-controller")
    assert exc.value.code == "unknown_scope"
