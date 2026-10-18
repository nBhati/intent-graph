import json

import pytest
from pydantic import ValidationError

from intentgraph.model import NodeRecord, Provenance, Snapshot, canonical_dumps, compute_digest, is_valid_id, serialize_snapshot
from intentgraph.model.expressions import validate_expression


def _node(i: str, **kw) -> NodeRecord:
    base = dict(id=i, kind="Goal", label=i, layer="intent", provenance=Provenance(author_role="user", method="test"))
    base.update(kw)
    return NodeRecord(**base)


def test_id_format():
    assert is_valid_id("req:cancel-response")
    assert is_valid_id("piano:PracticeSection/1")
    assert not is_valid_id("Requirement")
    assert not is_valid_id("req:")
    assert not is_valid_id("req: space")
    with pytest.raises(ValidationError):
        _node("no-colon")


def test_envelope_forbids_extra_fields():
    with pytest.raises(ValidationError):
        NodeRecord(id="g:x", kind="Goal", label="x", layer="intent", provenance=Provenance(author_role="user", method="t"), verified=True)


def test_digest_independent_of_record_order_and_key_order():
    a = Snapshot(vocabulary_version="core/0.2", project_id="project:x", revision=0, nodes=[_node("g:a"), _node("g:b")])
    b = Snapshot(vocabulary_version="core/0.2", project_id="project:x", revision=0, nodes=[_node("g:b"), _node("g:a")])
    assert compute_digest(a) == compute_digest(b)
    # Digest excludes the stored digest field itself.
    a.content_digest = "sha256:garbage"
    assert compute_digest(a) == compute_digest(b)
    # Serialized form parses back to the same digest and carries a matching digest.
    text = serialize_snapshot(a)
    data = json.loads(text)
    assert data["content_digest"] == compute_digest(a)
    assert text.endswith("\n")
    assert compute_digest(Snapshot.model_validate(data)) == data["content_digest"]


def test_digest_changes_with_content():
    a = Snapshot(vocabulary_version="core/0.2", project_id="project:x", revision=0, nodes=[_node("g:a")])
    b = Snapshot(vocabulary_version="core/0.2", project_id="project:x", revision=0, nodes=[_node("g:a", label="other")])
    assert compute_digest(a) != compute_digest(b)


def test_non_finite_numbers_rejected():
    with pytest.raises(ValueError):
        canonical_dumps({"x": float("nan")})


def test_expression_validation():
    good = {"op": "always", "arg": {"op": "forall", "variable": "r", "domain_ref": "entity:response", "body": {"op": "implies", "left": {"op": "field_eq", "variable": "r", "field": "cancelled", "value": True}, "right": {"op": "field_eq", "variable": "r", "field": "playing", "value": False}}}}
    assert validate_expression(good) == []
    assert validate_expression({"op": "eval", "code": "1+1"})
    assert validate_expression({"op": "and", "args": [good]})
    assert validate_expression({"op": "always"})
    assert validate_expression({"op": "always", "arg": good, "extra": 1})
