import json

import pytest

from intentgraph.errors import InvalidInput, StaleBase, ValidationFailed
from intentgraph.patches import Patch
from intentgraph.repository import Repository
from intentgraph.services import Context, patch_apply, patch_validate

from conftest import load_fixture_patch


def _patch(snap, pid, ops, **kw):
    return Patch.model_validate({"patch_id": pid, "base_revision": snap.revision, "base_digest": snap.content_digest, "reason": "t", "operations": ops, **kw})


def _goal(i):
    return {"op": "add_node", "record": {"id": i, "kind": "Goal", "label": i, "layer": "intent", "provenance": {"author_role": "user", "method": "t"}}}


def test_apply_increments_revision_and_records_transaction(coaching_repo: Repository):
    snap = coaching_repo.load_snapshot()
    assert snap.revision == 1 and len(snap.transactions) == 1
    t = snap.transactions[0]
    assert t.patch_id == "patch:coaching-fixture" and t.base_revision == 0 and t.result_revision == 1
    assert "req:cancel-response" in t.added_ids


def test_stale_base_rejected_with_changed_ids(coaching_repo: Repository):
    snap0 = coaching_repo.load_snapshot()
    p1 = _patch(snap0, "patch:one", [_goal("goal:one")])
    p2 = _patch(snap0, "patch:two", [_goal("goal:two")])  # same base as p1
    patch_apply(coaching_repo, p1)
    with pytest.raises(StaleBase) as exc:
        patch_apply(coaching_repo, p2)
    assert exc.value.details["changed_ids"] == ["goal:one"]
    assert exc.value.details["current_revision"] == 2
    # The concurrent accepted change was not overwritten.
    assert coaching_repo.load_snapshot().get("goal:one") is not None
    assert coaching_repo.load_snapshot().get("goal:two") is None


def test_repeated_patch_is_idempotent_and_conflict_is_error(coaching_repo: Repository):
    snap = coaching_repo.load_snapshot()
    p = _patch(snap, "patch:again", [_goal("goal:again")])
    r1 = patch_apply(coaching_repo, p)
    r2 = patch_apply(coaching_repo, p)  # same id, same content, stale base is fine
    assert r2["idempotent_replay"] and r2["revision"] == r1["revision"]
    assert coaching_repo.load_snapshot().revision == r1["revision"]
    different = _patch(coaching_repo.load_snapshot(), "patch:again", [_goal("goal:other")])
    with pytest.raises(InvalidInput) as exc:
        patch_apply(coaching_repo, different)
    assert exc.value.code == "patch_id_conflict"


def test_invalid_candidate_is_not_written(coaching_repo: Repository):
    before = coaching_repo.paths.model.read_text()
    snap = coaching_repo.load_snapshot()
    bad = _patch(snap, "patch:bad", [{"op": "add_edge", "record": {"id": "edge:bad", "kind": "depends_on", "source": "component:playback-controller", "target": "nope:missing", "layer": "intent", "properties": {"dependency_kind": "runtime"}, "provenance": {"author_role": "agent", "method": "t"}}}])
    with pytest.raises(ValidationFailed) as exc:
        patch_apply(coaching_repo, bad)
    assert any(d["code"] == "missing_endpoint" for d in exc.value.details["diagnostics"])
    assert coaching_repo.paths.model.read_text() == before


def test_validate_does_not_mutate(coaching_repo: Repository):
    ctx = Context(coaching_repo)
    p = _patch(ctx.snapshot, "patch:preview", [{"op": "update_properties", "id": "operation:cancel-response", "changes": {"idempotent": None, "mode": "async"}}])
    res = patch_validate(ctx, p)
    assert res["valid"] and res["effects"]["updated_ids"] == ["operation:cancel-response"]
    assert coaching_repo.load_snapshot().revision == 1
    assert coaching_repo.load_snapshot().get("operation:cancel-response").properties["idempotent"] is True


def test_update_fields_and_remove(coaching_repo: Repository):
    snap = coaching_repo.load_snapshot()
    p = _patch(snap, "patch:edit", [
        {"op": "update_fields", "id": "req:stop-active-response", "lifecycle": "accepted", "label": "Learner can stop a response"},
        {"op": "add_annotation", "id": "req:stop-active-response", "annotation": {"role": "rationale", "text": "Resolved in conversation."}},
        {"op": "update_properties", "id": "question:cancel-scope", "changes": {"status": "answered", "answer": "Both playback and pending generation."}},
    ])
    r = patch_apply(coaching_repo, p)
    assert sorted(r["effects"]["updated_ids"]) == ["question:cancel-scope", "req:stop-active-response"]
    rec = coaching_repo.load_snapshot().get("req:stop-active-response")
    assert rec.lifecycle == "accepted" and rec.annotations[-1].role == "rationale"
    # Removing a node still referenced by an edge fails; removing edge + node together succeeds (with a warning on accepted).
    snap = coaching_repo.load_snapshot()
    with pytest.raises(ValidationFailed):
        patch_apply(coaching_repo, _patch(snap, "patch:rm1", [{"op": "remove", "id": "decision:cancel-semantics"}]))
    r = patch_apply(coaching_repo, _patch(snap, "patch:rm2", [{"op": "remove", "id": "edge:decision-concerns-req"}, {"op": "remove", "id": "decision:cancel-semantics"}]))
    assert r["effects"]["removed_ids"] == ["decision:cancel-semantics", "edge:decision-concerns-req"]
    assert any(d["code"] == "removed_accepted_record" for d in r["diagnostics"])


def test_patch_shape_errors():
    with pytest.raises(Exception):
        Patch.model_validate({"patch_id": "bad id", "base_revision": 0, "base_digest": "x", "operations": [_goal("g:a")]})
    with pytest.raises(Exception):
        Patch.model_validate({"patch_id": "patch:x", "base_revision": 0, "base_digest": "x", "operations": []})
    with pytest.raises(Exception):
        Patch.model_validate({"patch_id": "patch:x", "base_revision": 0, "base_digest": "x", "operations": [{"op": "exec", "cmd": "rm -rf /"}]})


def test_fixture_patch_from_file_applies_to_empty_workspace(empty_repo: Repository):
    p = load_fixture_patch("coaching-patch.json", empty_repo.load_snapshot())
    r = patch_apply(empty_repo, p)
    assert r["applied"] and r["revision"] == 1 and len(r["effects"]["added_ids"]) == 51
