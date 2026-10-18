"""Scope closure and design digest (architecture sections 13 and 13.3).

Closure rule (decision:scope-closure-rule in the self-model): explicit
members; their structural children (contains, declares, exposes); the
requirements, goals and scenarios realized by *specific* design elements
(operations, actions, processes, screens, controls, interactions,
transitions, decisions, scenarios) but not by shared containers
(components, systems), which would drag every feature they serve into every
scope that names them; scenarios refining in-scope
requirements; constraints targeting any closure member; global constraints;
assumptions referenced by in-scope constraints; and the questions, decisions
and assumptions that concern closure members. Every member records why.

The design digest covers the *intent-layer* closure records (id, kind, label,
description, properties, lifecycle, edges among them) and the policy
reference. Reconciliation records (approvals, evidence, obligations, review
artifacts, mappings) and provenance/annotations are excluded, so recording an
approval or adding evidence does not change the digest, while a semantic
change inside the scope does.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..graph import GraphIndex
from ..model import NodeRecord, digest_of
from ..vocabulary import Vocabulary

STRUCTURAL_OUT = ("contains", "declares", "exposes")
# Kinds whose `realizes` edges pull their targets into the closure. Shared containers are excluded.
REALIZING_KINDS = {"Operation", "Action", "Process", "Screen", "Control", "Interaction", "Transition", "Decision", "Scenario", "Interface"}
LEAF_KINDS = {"Question", "Decision", "Assumption", "Constraint", "Scenario"}


@dataclass(frozen=True)
class ClosureMember:
    id: str
    kind: str
    reason: str
    via: str | None


def scope_closure(index: GraphIndex, vocabulary: Vocabulary, scope: NodeRecord) -> dict[str, ClosureMember]:
    members: dict[str, ClosureMember] = {}
    queue: deque[str] = deque()

    def add(nid: str, reason: str, via: str | None, expand: bool) -> None:
        node = index.nodes.get(nid)
        if node is None or nid in members:
            return
        members[nid] = ClosureMember(id=nid, kind=node.kind, reason=reason, via=via)
        if expand:
            queue.append(nid)

    for nid in scope.properties.get("member_refs", []):
        add(nid, "explicit member", None, True)

    while queue:
        nid = queue.popleft()
        for e in index.out_edges(nid, set(STRUCTURAL_OUT)):
            add(e.target, f"structural child via {e.kind}", nid, True)
        if index.nodes[nid].kind in REALIZING_KINDS:
            for e in index.out_edges(nid, {"realizes"}):
                add(e.target, "realized by member", nid, True)
        for e in index.in_edges(nid, {"refines"}):
            src = index.nodes.get(e.source)
            if src is not None and src.kind == "Scenario":
                add(e.source, "scenario refining member", nid, False)
        for e in index.in_edges(nid, {"constrains"}):
            add(e.source, "constraint on member", nid, False)
            for _, ref in index.property_refs(e.source, vocabulary):
                add(ref, "assumption of constraint", e.source, False)
        for e in index.in_edges(nid, {"concerns"}):
            src = index.nodes.get(e.source)
            if src is not None and src.kind in ("Question", "Decision", "Assumption"):
                add(e.source, f"{src.kind.lower()} concerning member", nid, False)

    for node in index.snapshot.nodes:
        if node.kind == "Constraint" and node.properties.get("scope") == "global" and node.lifecycle != "superseded":
            add(node.id, "global rule", None, False)
            for _, ref in index.property_refs(node.id, vocabulary):
                add(ref, "assumption of global rule", node.id, False)
    return members


def design_digest(index: GraphIndex, closure_ids: set[str], policy_ref: str) -> str:
    nodes = []
    for nid in sorted(closure_ids):
        n = index.nodes[nid]
        if n.layer != "intent":
            continue
        nodes.append({"id": n.id, "kind": n.kind, "label": n.label, "description": n.description, "properties": n.properties, "lifecycle": n.lifecycle})
    intent_ids = {n["id"] for n in nodes}
    edges = []
    for e in sorted(index.snapshot.edges, key=lambda e: e.id):
        if e.layer == "intent" and e.source in intent_ids and e.target in intent_ids:
            edges.append({"id": e.id, "kind": e.kind, "source": e.source, "target": e.target, "properties": e.properties, "lifecycle": e.lifecycle})
    return digest_of({"policy": policy_ref, "nodes": nodes, "edges": edges})
