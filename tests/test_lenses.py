import pytest

from intentgraph.errors import InvalidInput
from intentgraph.services import Context, search, view


def test_lens_includes_global_rules_and_boundary(coaching_ctx: Context):
    res = view(coaching_ctx, {"focus": ["operation:cancel-response"], "include": ["parent_intent", "constraints"], "depth": 1})
    assert res["status"] == "ok" and res["source_revision"] == 1
    ids = set(res["selected_ids"])
    assert "operation:cancel-response" in ids
    assert "req:cancel-response" in ids  # parent intent via realizes
    assert "constraint:cancelled-response-silent" in ids  # global rule, also a direct constraint
    assert res["project_rule_ids"] == ["constraint:cancelled-response-silent"]
    assert "interface:response-events" not in ids  # declares is incoming and not requested
    boundary_outside = {b["outside_id"] for b in res["boundary"]}
    assert "interface:response-events" in boundary_outside
    assert all(e["source"] in ids and e["target"] in ids for e in res["edges"])


def test_lens_never_drops_mandatory_records(coaching_ctx: Context):
    res = view(coaching_ctx, {"focus": ["operation:cancel-response"], "include": ["neighbors"], "depth": 3, "max_records": 3})
    assert res["status"] == "ok" and res["truncated"] and res["omitted_count"] > 0
    assert set(res["selected_ids"]) >= {"operation:cancel-response", "constraint:cancelled-response-silent"}
    assert len(res["selected_ids"]) == 3
    over = view(coaching_ctx, {"focus": ["operation:cancel-response"], "max_records": 1})
    assert over["status"] == "overflow" and over["nodes"] == []


def test_lens_implementations_and_findings(coaching_ctx: Context):
    res = view(coaching_ctx, {"focus": ["req:cancel-response"], "include": ["implementations", "findings"], "include_project_rules": False})
    ids = set(res["selected_ids"])
    assert {"mapping:cancel-controller", "mapping:cancel-test", "obligation:cancel-late-arrival"} <= ids
    assert res["project_rule_ids"] == []


def test_lens_rejects_unknown_focus(coaching_ctx: Context):
    with pytest.raises(InvalidInput):
        view(coaching_ctx, {"focus": ["nope:x"]})


def test_search(coaching_ctx: Context):
    res = search(coaching_ctx, text="restart speech", kind="Requirement")
    assert [r["id"] for r in res["records"]] == ["req:cancel-response"]
    res = search(coaching_ctx, layer="observation")
    assert res["count"] == 3
    res = search(coaching_ctx, lifecycle="proposed")
    assert "question:cancel-scope" not in {r["id"] for r in res["records"]}
    assert "req:stop-active-response" in {r["id"] for r in res["records"]}
