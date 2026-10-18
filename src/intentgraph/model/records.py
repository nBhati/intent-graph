"""Record envelope shared by nodes and edges (architecture section 5.2).

Per-kind *property* validation is deliberately not encoded here as Python
classes: the vocabulary registry (``intentgraph.vocabulary``) holds the kind
and relation definitions, and ``intentgraph.checks`` validates properties
against them after individual records load. Cross-record rules (endpoint
existence, legal relation kinds, containment acyclicity) also live there.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Layer = Literal["intent", "observation", "reconciliation"]
Lifecycle = Literal["proposed", "accepted", "superseded"]
AuthorRole = Literal["user", "agent", "tool", "import"]
AnnotationRole = Literal[
    "original_intent",
    "interpretation",
    "rationale",
    "assumption",
    "explanation",
    "open_question",
    "note",
]

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*:[A-Za-z0-9][A-Za-z0-9._/-]*$")


def is_valid_id(value: str) -> bool:
    """IDs are ``prefix:slug``. They are stable identities, never derived from labels or paths."""
    return bool(ID_PATTERN.match(value))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=False)


class Provenance(StrictModel):
    author_role: AuthorRole
    method: str
    source_refs: list[str] = Field(default_factory=list)
    notes: str = ""


class Annotation(StrictModel):
    role: AnnotationRole
    text: str
    refs: list[str] = Field(default_factory=list)


class Record(StrictModel):
    id: str
    kind: str
    label: str = ""
    layer: Layer
    description: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)
    lifecycle: Lifecycle = "proposed"
    provenance: Provenance
    annotations: list[Annotation] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not is_valid_id(value):
            raise ValueError(f"invalid record id {value!r}: expected 'prefix:slug'")
        return value

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, value: str) -> str:
        if not value or any(ch.isspace() for ch in value):
            raise ValueError(f"invalid kind {value!r}")
        return value


class NodeRecord(Record):
    pass


class EdgeRecord(Record):
    source: str
    target: str

    @field_validator("source", "target")
    @classmethod
    def _check_endpoint(cls, value: str) -> str:
        if not is_valid_id(value):
            raise ValueError(f"invalid endpoint id {value!r}")
        return value


class TransactionRecord(StrictModel):
    """Summary of an applied patch. Kept inside the snapshot in v0 so graph
    state and transaction accounting cannot diverge (section 9.4)."""

    patch_id: str
    base_revision: int
    result_revision: int
    applied_at: str
    reason: str = ""
    operations_digest: str
    added_ids: list[str] = Field(default_factory=list)
    updated_ids: list[str] = Field(default_factory=list)
    removed_ids: list[str] = Field(default_factory=list)


class Snapshot(StrictModel):
    format_version: Literal["0.1"] = "0.1"
    vocabulary_version: str
    project_id: str
    revision: int = Field(ge=0)
    content_digest: str = ""
    nodes: list[NodeRecord] = Field(default_factory=list)
    edges: list[EdgeRecord] = Field(default_factory=list)
    policies: list[dict[str, Any]] = Field(default_factory=list)
    transactions: list[TransactionRecord] = Field(default_factory=list)

    # Convenience accessors. The snapshot is the record store; NetworkX only indexes it.
    def node_map(self) -> dict[str, NodeRecord]:
        return {n.id: n for n in self.nodes}

    def edge_map(self) -> dict[str, EdgeRecord]:
        return {e.id: e for e in self.edges}

    def record_map(self) -> dict[str, Record]:
        out: dict[str, Record] = {}
        for n in self.nodes:
            out[n.id] = n
        for e in self.edges:
            out[e.id] = e
        return out

    def get(self, record_id: str) -> Record | None:
        for n in self.nodes:
            if n.id == record_id:
                return n
        for e in self.edges:
            if e.id == record_id:
                return e
        return None
