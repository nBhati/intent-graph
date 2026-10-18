"""Milestone 2 verification: determine which elements depend on a changed interface."""
import pytest

from intentgraph.errors import InvalidInput
from intentgraph.services import Context, impact


def _ids(res):
    return {c["id"]: c for c in res["candidates"]}


def test_changed_interface_reaches_dependents_and_exposer(coaching_ctx: Context):
    res = impact(coaching_ctx, {"changed": ["interface:response-events"], "max_depth": 1})
    c = _ids(res)
    assert "component:playback-controller" in c and "depends_on" in c["component:playback-controller"]["reasons"]
    assert "component:response-coordinator" in c and c["component:response-coordinator"]["reasons"] == ["exposes"]
    assert "operation:cancel-response" in c and c["operation:cancel-response"]["reasons"] == ["declares"]  # declares is 'both'
    assert res["coverage_note"].startswith("Recorded reachability only")
    assert res["by_category"]["design"] == len(c)


def test_changed_operation_reaches_callers_mappings_and_evidence(coaching_ctx: Context):
    res = impact(coaching_ctx, {"changed": ["operation:cancel-response"], "max_depth": 2})
    c = _ids(res)
    assert c["interface:response-events"]["distance"] == 1  # declares (both)
    assert "property:model_refs" in c["mapping:cancel-controller"]["reasons"]
    assert "property:scope_refs" in c["obligation:cancel-late-arrival"]["reasons"]
    assert c["assessment:cancel-mapping-review"]["distance"] == 2  # reached through the mapping it assesses
    # Not reached, by design: realizes/constrains do not propagate from a changed design element back to the
    # requirement or constraint, and evidence is cited by the mapping rather than referring to the operation.
    assert "req:cancel-response" not in c
    assert "constraint:cancelled-response-silent" not in c
    assert "evidence:late-response-test" not in c


def test_changed_constraint_affects_its_targets(coaching_ctx: Context):
    res = impact(coaching_ctx, {"changed": ["constraint:cancelled-response-silent"], "max_depth": 1, "include_references": False})
    assert set(_ids(res)) == {"operation:cancel-response"}


def test_behavioral_cycle_terminates_and_relation_filter(coaching_ctx: Context):
    res = impact(coaching_ctx, {"changed": ["operation:generate-response"], "max_depth": 10, "relations": ["invokes"], "include_references": False})
    assert set(_ids(res)) == {"operation:retry-generation"}
    assert _ids(res)["operation:retry-generation"]["path"][0]["edge_id"] == "edge:retry-invokes-generate"


def test_changed_edge_seeds_both_endpoints(coaching_ctx: Context):
    res = impact(coaching_ctx, {"changed": ["edge:controller-dependency"], "max_depth": 1, "include_references": False})
    ids = set(_ids(res))
    assert "component:playback-controller" not in ids and "interface:response-events" not in ids
    assert "component:response-coordinator" in ids  # exposes the interface endpoint


def test_truncation_and_unknown_id(coaching_ctx: Context):
    res = impact(coaching_ctx, {"changed": ["req:cancel-response"], "max_depth": 4, "max_candidates": 2})
    assert res["truncated"] and len(res["candidates"]) == 2 and res["omitted_count"] > 0
    with pytest.raises(InvalidInput):
        impact(coaching_ctx, {"changed": ["nope:x"]})
