import pytest

from intentgraph.model import EdgeRecord, NodeRecord, Provenance, Snapshot
from intentgraph.checks import validate_snapshot
from intentgraph.vocabulary import load_core_vocabulary

V = load_core_vocabulary()
P = Provenance(author_role="agent", method="test")


def node(i, kind, layer="intent", **props):
    return NodeRecord(id=i, kind=kind, label=i, layer=layer, provenance=P, properties=props)


def edge(i, kind, s, t, layer="intent", **props):
    return EdgeRecord(id=i, kind=kind, source=s, target=t, layer=layer, provenance=P, properties=props)


def snap(nodes, edges=()):
    return Snapshot(vocabulary_version="core/0.1", project_id="project:t", revision=0, nodes=list(nodes), edges=list(edges))


def codes(s):
    return {d.code for d in validate_snapshot(s, V) if d.severity == "error"}


def test_missing_endpoint_rejected():
    s = snap([node("c:a", "Component")], [edge("e:1", "depends_on", "c:a", "c:missing", dependency_kind="runtime")])
    assert "missing_endpoint" in codes(s)


def test_illegal_endpoint_kind_rejected():
    s = snap([node("g:a", "Goal"), node("c:b", "Component")], [edge("e:1", "exposes", "g:a", "c:b")])
    assert "illegal_endpoint_kind" in codes(s)


def test_required_relation_property():
    s = snap([node("c:a", "Component"), node("c:b", "Component")], [edge("e:1", "depends_on", "c:a", "c:b")])
    assert "invalid_property" in codes(s)
    s2 = snap([node("c:a", "Component"), node("c:b", "Component")], [edge("e:1", "depends_on", "c:a", "c:b", dependency_kind="runtime")])
    assert codes(s2) == set()


def test_containment_cycle_rejected_but_invocation_cycle_allowed():
    cyc = snap([node("c:a", "Component"), node("c:b", "Component")],
               [edge("e:1", "contains", "c:a", "c:b"), edge("e:2", "contains", "c:b", "c:a")])
    assert "containment_cycle" in codes(cyc)
    calls = snap([node("o:a", "Operation"), node("o:b", "Operation")],
                 [edge("e:1", "invokes", "o:a", "o:b"), edge("e:2", "invokes", "o:b", "o:a")])
    assert codes(calls) == set()


def test_unknown_kind_and_compat_mode():
    s = snap([node("x:a", "piano:PracticeSection")])
    assert "unknown_kind" in codes(s)
    warnings = validate_snapshot(s, V, compat_unknown_kinds=True)
    assert [d.severity for d in warnings] == ["warning"]


def test_property_schema():
    assert "invalid_property" in codes(snap([node("r:a", "Requirement")]))  # missing required
    assert "invalid_property" in codes(snap([node("r:a", "Requirement", priority="urgent", formalization="descriptive")]))  # bad enum
    assert "invalid_property" in codes(snap([node("r:a", "Requirement", priority="must", formalization="descriptive", verified=True)]))  # unknown prop
    assert codes(snap([node("r:a", "Requirement", priority="must", formalization="descriptive")])) == set()


def test_layer_must_match_kind():
    assert "invalid_layer" in codes(snap([node("r:a", "Requirement", layer="observation", priority="must", formalization="descriptive")]))


def test_dangling_property_reference():
    s = snap([node("t:a", "Transition", from_state="s:x", to_state="s:y")])
    assert "dangling_reference" in codes(s)


def test_expression_checked_only_for_supported_language():
    bad = snap([node("k:a", "Constraint", constraint_kind="invariant", expression_language="intent-expr/0.1", expression={"op": "eval", "code": "x"})])
    assert "invalid_expression" in codes(bad)
    other = snap([node("k:a", "Constraint", constraint_kind="invariant", expression_language="tla+/1", expression={"spec": "..."})])
    diags = validate_snapshot(other, V)
    assert [d.code for d in diags] == ["unsupported_expression_language"] and diags[0].severity == "warning"


def test_duplicate_ids():
    s = snap([node("g:a", "Goal"), node("g:a", "Goal")])
    assert "duplicate_id" in codes(s)


def test_project_extension_kind(tmp_path):
    from intentgraph.vocabulary import load_core_vocabulary
    ext = tmp_path / "piano.json"
    ext.write_text('{"namespace": "piano", "kinds": [{"name": "piano:PracticeSection", "parent": "Component", "properties": {"tempo": {"type": "integer"}}}]}')
    v = load_core_vocabulary()
    v.load_extensions(tmp_path)
    s = snap([node("c:a", "piano:PracticeSection", role="module", tempo=120), node("c:b", "Component")],
             [edge("e:1", "depends_on", "c:a", "c:b", dependency_kind="runtime")])
    assert {d.code for d in validate_snapshot(s, v) if d.severity == "error"} == set()
    with pytest.raises(Exception):
        bad = tmp_path / "bad"; bad.mkdir()
        (bad / "x.json").write_text('{"namespace": "x", "kinds": [{"name": "Unprefixed"}]}')
        load_core_vocabulary().load_extensions(bad)
