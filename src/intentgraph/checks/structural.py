"""Structural checks (architecture sections 5.3, 5.6, 7.2, 22).

Each check produces ``Diagnostic`` records with a stable code. ``error``
severity means the snapshot is not a valid model; ``warning`` means something
deserves attention but the model is usable.
"""
from __future__ import annotations

from collections import Counter
from typing import Literal

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field

from ..model import EdgeRecord, NodeRecord, Snapshot
from ..model.expressions import EXPRESSION_LANGUAGE, validate_expression
from ..vocabulary import Vocabulary, validate_properties
from ..graph import build_index

Severity = Literal["error", "warning"]


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    severity: Severity
    message: str
    record_ids: list[str] = Field(default_factory=list)


def has_blocking(diagnostics: list[Diagnostic]) -> bool:
    return any(d.severity == "error" for d in diagnostics)


def validate_snapshot(snapshot: Snapshot, vocabulary: Vocabulary, *, compat_unknown_kinds: bool = False) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    unknown_severity: Severity = "warning" if compat_unknown_kinds else "error"

    # --- identity -------------------------------------------------------
    counts = Counter([n.id for n in snapshot.nodes] + [e.id for e in snapshot.edges])
    for rid, c in counts.items():
        if c > 1:
            diags.append(Diagnostic(code="duplicate_id", severity="error", message=f"id {rid!r} appears {c} times", record_ids=[rid]))
    # Transactions: patch ids unique, revisions contiguous.
    seen_patches = Counter(t.patch_id for t in snapshot.transactions)
    for pid, c in seen_patches.items():
        if c > 1:
            diags.append(Diagnostic(code="duplicate_patch_id", severity="error", message=f"patch id {pid!r} recorded {c} times"))
    if snapshot.vocabulary_version != vocabulary.version:
        diags.append(Diagnostic(code="vocabulary_version_mismatch", severity="error", message=f"snapshot vocabulary {snapshot.vocabulary_version!r} but loaded vocabulary is {vocabulary.version!r}"))

    node_map = snapshot.node_map()
    all_ids = set(node_map) | {e.id for e in snapshot.edges}

    # --- nodes ----------------------------------------------------------
    for node in snapshot.nodes:
        kind = vocabulary.kind(node.kind)
        if kind is None:
            diags.append(Diagnostic(code="unknown_kind", severity=unknown_severity, message=f"node {node.id!r} has unknown kind {node.kind!r}", record_ids=[node.id]))
            continue
        if node.layer not in kind.layers:
            diags.append(Diagnostic(code="invalid_layer", severity="error", message=f"node {node.id!r} of kind {node.kind!r} must be in layer(s) {kind.layers}, found {node.layer!r}", record_ids=[node.id]))
        for err in validate_properties(kind.properties, node.properties):
            diags.append(Diagnostic(code="invalid_property", severity="error", message=f"node {node.id!r}: {err}", record_ids=[node.id]))
        _check_expression(node, diags)

    # --- edges ----------------------------------------------------------
    for edge in snapshot.edges:
        rel = vocabulary.relation(edge.kind)
        if rel is None:
            diags.append(Diagnostic(code="unknown_relation", severity=unknown_severity, message=f"edge {edge.id!r} has unknown relation kind {edge.kind!r}", record_ids=[edge.id]))
            continue
        if edge.layer not in rel.layers:
            diags.append(Diagnostic(code="invalid_layer", severity="error", message=f"edge {edge.id!r} of kind {edge.kind!r} must be in layer(s) {rel.layers}, found {edge.layer!r}", record_ids=[edge.id]))
        for err in validate_properties(rel.property_specs(), edge.properties):
            diags.append(Diagnostic(code="invalid_property", severity="error", message=f"edge {edge.id!r}: {err}", record_ids=[edge.id]))
        for role, endpoint in (("source", edge.source), ("target", edge.target)):
            node = node_map.get(endpoint)
            if node is None:
                diags.append(Diagnostic(code="missing_endpoint", severity="error", message=f"edge {edge.id!r} {role} {endpoint!r} does not exist", record_ids=[edge.id, endpoint]))
                continue
            allowed = rel.source_kinds if role == "source" else rel.target_kinds
            if vocabulary.kind(node.kind) is not None and not vocabulary.endpoint_allowed(allowed, node.kind):
                diags.append(Diagnostic(code="illegal_endpoint_kind", severity="error", message=f"edge {edge.id!r}: {role} kind {node.kind!r} is not allowed for {edge.kind!r} (allowed: {allowed})", record_ids=[edge.id, endpoint]))

    # --- property references --------------------------------------------
    index = build_index(snapshot, vocabulary)
    for ref, referrers in index.referenced_by.items():
        if ref not in all_ids:
            for rid, prop in referrers:
                diags.append(Diagnostic(code="dangling_reference", severity="error", message=f"record {rid!r} property {prop!r} references missing id {ref!r}", record_ids=[rid, ref]))

    # --- acyclic relations -------------------------------------------------
    for rel in vocabulary.relations.values():
        if not rel.acyclic:
            continue
        sub = nx.DiGraph()
        for edge in snapshot.edges:
            if edge.kind == rel.name and edge.source in node_map and edge.target in node_map:
                sub.add_edge(edge.source, edge.target)
        try:
            cycle = nx.find_cycle(sub)
        except nx.NetworkXNoCycle:
            continue
        ids = [u for u, _ in cycle]
        diags.append(Diagnostic(code="containment_cycle" if rel.name == "contains" else "acyclic_relation_cycle", severity="error", message=f"relation {rel.name!r} must be acyclic; cycle through {ids}", record_ids=ids))

    # --- lifecycle hints -----------------------------------------------------
    for edge in snapshot.edges:
        if edge.lifecycle == "accepted":
            for endpoint in (edge.source, edge.target):
                node = node_map.get(endpoint)
                if node is not None and node.lifecycle == "superseded":
                    diags.append(Diagnostic(code="accepted_edge_to_superseded", severity="warning", message=f"accepted edge {edge.id!r} touches superseded record {endpoint!r}", record_ids=[edge.id, endpoint]))
    return diags


def _check_expression(node: NodeRecord, diags: list[Diagnostic]) -> None:
    lang = node.properties.get("expression_language")
    expr = node.properties.get("expression")
    if expr is None and lang is None:
        return
    if expr is not None and lang is None:
        diags.append(Diagnostic(code="invalid_expression", severity="error", message=f"node {node.id!r}: expression without expression_language", record_ids=[node.id]))
        return
    if lang != EXPRESSION_LANGUAGE:
        diags.append(Diagnostic(code="unsupported_expression_language", severity="warning", message=f"node {node.id!r}: expression language {lang!r} is not interpreted by this tool (supported: {EXPRESSION_LANGUAGE}); it is stored, not checked", record_ids=[node.id]))
        return
    for err in validate_expression(expr):
        diags.append(Diagnostic(code="invalid_expression", severity="error", message=f"node {node.id!r}: {err}", record_ids=[node.id]))
