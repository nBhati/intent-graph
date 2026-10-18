"""Basic lens (architecture section 10; milestone 1 scope).

A lens starts from focal elements and traverses explicitly selected
relationship kinds in specified directions. Mandatory content (the focal
records and applicable global rules) is never silently truncated: if it
alone exceeds ``max_records`` the lens reports overflow instead.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..errors import InvalidInput
from ..graph import GraphIndex
from ..model import Snapshot
from ..vocabulary import Vocabulary

Include = Literal["parent_intent", "constraints", "implementations", "findings", "neighbors"]

# Shortcut names expand to traversal rules (direction, relation kinds).
_INCLUDE_RULES: dict[str, dict[str, list[str]]] = {
    "parent_intent": {"outgoing": ["refines", "realizes"]},
    "constraints": {"incoming": ["constrains"]},
    "findings": {"incoming": ["concerns", "challenges"]},
    "neighbors": {"incoming": ["*"], "outgoing": ["*"]},
}


class Traversal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incoming: list[str] = Field(default_factory=list)
    outgoing: list[str] = Field(default_factory=list)


class LensRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: list[str] = Field(min_length=1)
    include: list[Include] = Field(default_factory=list)
    traversal: Traversal = Field(default_factory=Traversal)
    depth: int = Field(default=1, ge=0, le=6)
    include_project_rules: bool = True
    max_records: int = Field(default=80, ge=1)


class LensResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "overflow"]
    source_revision: int
    source_digest: str
    focus: list[str]
    selection_rules: dict[str, Any]
    selected_ids: list[str]
    project_rule_ids: list[str]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    boundary: list[dict[str, Any]]
    truncated: bool
    omitted_count: int
    message: str = ""


def _effective_traversal(req: LensRequest) -> tuple[set[str], set[str]]:
    incoming = set(req.traversal.incoming)
    outgoing = set(req.traversal.outgoing)
    for inc in req.include:
        rule = _INCLUDE_RULES.get(inc, {})
        incoming.update(rule.get("incoming", []))
        outgoing.update(rule.get("outgoing", []))
    return incoming, outgoing


def _matches(kinds: set[str], kind: str) -> bool:
    return "*" in kinds or kind in kinds


def compute_lens(index: GraphIndex, vocabulary: Vocabulary, req: LensRequest) -> LensResult:
    snapshot = index.snapshot
    for rid in req.focus:
        if rid not in index.nodes:
            raise InvalidInput(f"focus id {rid!r} is not a node in the model", code="unknown_record", details={"id": rid})
    incoming, outgoing = _effective_traversal(req)

    # Mandatory: focus + global rules.
    rule_ids: list[str] = []
    if req.include_project_rules:
        rule_ids = sorted(
            n.id for n in snapshot.nodes
            if n.kind == "Constraint" and n.properties.get("scope") == "global" and n.lifecycle != "superseded"
        )
    mandatory = list(dict.fromkeys(req.focus + rule_ids))
    if len(mandatory) > req.max_records:
        return LensResult(
            status="overflow", source_revision=snapshot.revision, source_digest=snapshot.content_digest,
            focus=req.focus, selection_rules=_rules(req, incoming, outgoing), selected_ids=[], project_rule_ids=rule_ids,
            nodes=[], edges=[], boundary=[], truncated=True, omitted_count=len(mandatory) - req.max_records,
            message=f"focal elements and {len(rule_ids)} global rule(s) alone exceed max_records={req.max_records}; narrow the task or raise the limit",
        )

    # Breadth-first traversal in deterministic order (sorted neighbours).
    selected: list[str] = list(mandatory)
    selected_set = set(selected)
    queue: deque[tuple[str, int]] = deque((rid, 0) for rid in req.focus)
    truncated = False
    omitted = 0
    while queue:
        rid, d = queue.popleft()
        if d >= req.depth:
            continue
        neighbours: list[str] = []
        for e in index.out_edges(rid):
            if _matches(outgoing, e.kind):
                neighbours.append(e.target)
        for e in index.in_edges(rid):
            if _matches(incoming, e.kind):
                neighbours.append(e.source)
        if "implementations" in req.include:
            neighbours.extend(ref for ref, _ in _mapping_referrers(index, rid))
        if "findings" in req.include:
            neighbours.extend(ref for ref, _ in _referrers_of_kind(index, rid, {"Finding", "Obligation", "Question", "Assumption"}))
        for nid in sorted(set(neighbours)):
            if nid in selected_set or nid not in index.nodes:
                continue
            if len(selected) >= req.max_records:
                truncated = True
                omitted += 1
                continue
            selected.append(nid)
            selected_set.add(nid)
            queue.append((nid, d + 1))

    nodes = [index.nodes[i].model_dump(mode="json") for i in selected]
    edge_recs = [e for e in snapshot.edges if e.source in selected_set and e.target in selected_set]
    edges = [e.model_dump(mode="json") for e in edge_recs]
    boundary: list[dict[str, Any]] = []
    for e in snapshot.edges:
        if (e.source in selected_set) != (e.target in selected_set):
            outside = e.target if e.source in selected_set else e.source
            out_node = index.nodes.get(outside)
            boundary.append({
                "edge_id": e.id, "kind": e.kind, "source": e.source, "target": e.target,
                "outside_id": outside, "outside_kind": out_node.kind if out_node else None,
                "outside_label": out_node.label if out_node else None,
            })
    return LensResult(
        status="ok", source_revision=snapshot.revision, source_digest=snapshot.content_digest,
        focus=req.focus, selection_rules=_rules(req, incoming, outgoing), selected_ids=selected, project_rule_ids=rule_ids,
        nodes=nodes, edges=edges, boundary=boundary, truncated=truncated, omitted_count=omitted,
        message="truncated: some reachable records were omitted (mandatory records are complete)" if truncated else "",
    )


def _rules(req: LensRequest, incoming: set[str], outgoing: set[str]) -> dict[str, Any]:
    return {
        "include": list(req.include), "depth": req.depth,
        "traversal": {"incoming": sorted(incoming), "outgoing": sorted(outgoing)},
        "include_project_rules": req.include_project_rules, "max_records": req.max_records,
    }


def _mapping_referrers(index: GraphIndex, rid: str) -> list[tuple[str, str]]:
    out = []
    for referrer, prop in index.referenced_by.get(rid, []):
        node = index.nodes.get(referrer)
        if node is not None and node.kind == "Mapping":
            out.append((referrer, prop))
    return out


def _referrers_of_kind(index: GraphIndex, rid: str, kinds: set[str]) -> list[tuple[str, str]]:
    out = []
    for referrer, prop in index.referenced_by.get(rid, []):
        node = index.nodes.get(referrer)
        if node is not None and node.kind in kinds:
            out.append((referrer, prop))
    return out


def search_records(snapshot: Snapshot, *, text: str = "", kind: str | None = None, layer: str | None = None, lifecycle: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    needle = text.lower()
    hits: list[dict[str, Any]] = []
    for rec in list(snapshot.nodes) + list(snapshot.edges):
        if kind and rec.kind != kind:
            continue
        if layer and rec.layer != layer:
            continue
        if lifecycle and rec.lifecycle != lifecycle:
            continue
        if needle:
            hay = " ".join([rec.id, rec.label, rec.description] + [a.text for a in rec.annotations]).lower()
            if needle not in hay:
                continue
        entry = {"id": rec.id, "kind": rec.kind, "label": rec.label, "layer": rec.layer, "lifecycle": rec.lifecycle}
        if hasattr(rec, "source"):
            entry["source"] = rec.source  # type: ignore[attr-defined]
            entry["target"] = rec.target  # type: ignore[attr-defined]
        hits.append(entry)
    hits.sort(key=lambda h: h["id"])
    return hits[:limit]
