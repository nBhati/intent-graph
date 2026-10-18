"""Impact slice (architecture sections 10 and 16.2).

Starting from changed ids, traverse each relation in its declared impact
direction and follow property references back to their referrers. The result
is *recorded reachability*: it reports plausible affected elements with the
path that reached them. It cannot reveal dependencies that were never
recorded, and it says so in every response.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..errors import InvalidInput
from ..graph import GraphIndex
from ..vocabulary import Vocabulary

Category = Literal["design", "behavior", "evidence", "review", "implementation", "other"]

_CATEGORY: dict[str, Category] = {
    **{k: "design" for k in ("Goal", "Requirement", "Scenario", "System", "Component", "ExternalSystem", "Interface", "Operation", "Port", "Entity", "ValueType", "Message", "Store", "Screen", "Control", "Interaction", "PresentationRule", "Constraint", "Actor")},
    **{k: "behavior" for k in ("Action", "Event", "State", "Transition", "Process")},
    **{k: "evidence" for k in ("Evidence", "AnalysisRun", "Assessment", "Mapping", "ReviewArtifact", "TestCase")},
    **{k: "review" for k in ("Question", "Decision", "Assumption", "Obligation", "Finding", "Approval")},
    **{k: "implementation" for k in ("CodeArtifact", "CodeSymbol", "Observation")},
}


class ImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changed: list[str] = Field(min_length=1)
    max_depth: int = Field(default=3, ge=1, le=10)
    relations: list[str] | None = None  # restrict traversal to these relation kinds
    include_references: bool = True  # follow property references (Mapping.model_refs, Transition.from_state, ...)
    max_candidates: int = Field(default=200, ge=1)


class ImpactStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_id: str
    to_id: str
    via: str  # relation kind or "property:<name>"
    edge_id: str | None = None


class ImpactCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    label: str
    layer: str
    lifecycle: str
    category: Category
    distance: int
    path: list[ImpactStep]
    reasons: list[str]  # distinct "via" values that reach this record


class ImpactResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]
    source_revision: int
    source_digest: str
    changed: list[str]
    rules: dict[str, Any]
    candidates: list[ImpactCandidate]
    by_category: dict[str, int]
    truncated: bool
    omitted_count: int
    coverage_note: str


COVERAGE_NOTE = (
    "Recorded reachability only. Elements whose dependency on the change was never recorded are not listed; "
    "treat absence as unknown, not as unaffected."
)


def compute_impact(index: GraphIndex, vocabulary: Vocabulary, req: ImpactRequest) -> ImpactResult:
    for rid in req.changed:
        if rid not in index.nodes and rid not in index.edges:
            raise InvalidInput(f"changed id {rid!r} is not in the model", code="unknown_record", details={"id": rid})
    allowed = set(req.relations) if req.relations is not None else None

    # Seed: for a changed edge, both of its endpoints count as changed loci (distance 0) but are not candidates.
    seeds: list[str] = []
    for rid in req.changed:
        if rid in index.edges:
            e = index.edges[rid]
            seeds += [e.source, e.target]
        else:
            seeds.append(rid)
    seeds = list(dict.fromkeys(seeds))
    changed_set = set(seeds)

    best: dict[str, tuple[int, list[ImpactStep]]] = {}
    reasons: dict[str, set[str]] = {}
    queue: deque[tuple[str, int, list[ImpactStep]]] = deque((s, 0, []) for s in seeds)
    visited: set[str] = set(seeds)
    truncated = False
    omitted = 0

    while queue:
        rid, dist, path = queue.popleft()
        if dist >= req.max_depth:
            continue
        for nxt, step in _neighbours(index, vocabulary, rid, allowed, req.include_references):
            if nxt in changed_set:
                continue
            reasons.setdefault(nxt, set()).add(step.via)
            if nxt in visited:
                continue
            if len(best) >= req.max_candidates:
                truncated = True
                omitted += 1
                continue
            visited.add(nxt)
            new_path = path + [step]
            best[nxt] = (dist + 1, new_path)
            queue.append((nxt, dist + 1, new_path))

    candidates: list[ImpactCandidate] = []
    for nid, (dist, path) in best.items():
        node = index.nodes[nid]
        candidates.append(ImpactCandidate(
            id=nid, kind=node.kind, label=node.label, layer=node.layer, lifecycle=node.lifecycle,
            category=_CATEGORY.get(node.kind, "other"), distance=dist, path=path, reasons=sorted(reasons.get(nid, set())),
        ))
    candidates.sort(key=lambda c: (c.distance, c.id))
    by_cat: dict[str, int] = {}
    for c in candidates:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
    return ImpactResult(
        status="ok", source_revision=index.snapshot.revision, source_digest=index.snapshot.content_digest,
        changed=req.changed,
        rules={"max_depth": req.max_depth, "relations": sorted(allowed) if allowed is not None else "all with declared impact",
               "include_references": req.include_references, "max_candidates": req.max_candidates,
               "impact_directions": {r.name: r.impact for r in vocabulary.relations.values() if r.impact != "none"}},
        candidates=candidates, by_category=dict(sorted(by_cat.items())), truncated=truncated, omitted_count=omitted,
        coverage_note=COVERAGE_NOTE,
    )


def _neighbours(index: GraphIndex, vocabulary: Vocabulary, rid: str, allowed: set[str] | None, include_refs: bool) -> list[tuple[str, ImpactStep]]:
    out: list[tuple[str, ImpactStep]] = []
    for e in index.in_edges(rid):  # rid is the target; the source may be affected
        rel = vocabulary.relation(e.kind)
        if rel is None or (allowed is not None and e.kind not in allowed):
            continue
        if rel.impact in ("incoming", "both") and e.source in index.nodes:
            out.append((e.source, ImpactStep(from_id=rid, to_id=e.source, via=e.kind, edge_id=e.id)))
    for e in index.out_edges(rid):  # rid is the source; the target may be affected
        rel = vocabulary.relation(e.kind)
        if rel is None or (allowed is not None and e.kind not in allowed):
            continue
        if rel.impact in ("outgoing", "both") and e.target in index.nodes:
            out.append((e.target, ImpactStep(from_id=rid, to_id=e.target, via=e.kind, edge_id=e.id)))
    if include_refs:
        for referrer, prop in index.referenced_by.get(rid, []):
            if referrer in index.nodes:
                out.append((referrer, ImpactStep(from_id=rid, to_id=referrer, via=f"property:{prop}")))
            elif referrer in index.edges:
                e = index.edges[referrer]
                for endpoint in (e.source, e.target):
                    if endpoint != rid and endpoint in index.nodes:
                        out.append((endpoint, ImpactStep(from_id=rid, to_id=endpoint, via=f"edge-property:{prop}", edge_id=e.id)))
    # Deterministic order.
    out.sort(key=lambda t: (t[0], t[1].via))
    return out
