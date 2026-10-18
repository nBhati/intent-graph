"""In-memory graph (architecture section 8.3).

The snapshot's typed records are the record store. NetworkX indexes them for
traversal; it must not become a second independently mutable copy of domain
truth. Graph node/edge attributes therefore hold only ``kind`` and the record
id, never the mutable record object.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import networkx as nx

from ..model import EdgeRecord, NodeRecord, Snapshot
from ..model.expressions import expression_refs
from ..vocabulary import Vocabulary
from ..vocabulary.registry import reference_properties


def build_graph(snapshot: Snapshot) -> nx.MultiDiGraph:
    """Build a ``MultiDiGraph`` keyed by stable edge IDs. Edges with missing
    endpoints are skipped here; structural validation reports them."""
    graph = nx.MultiDiGraph()
    for node in snapshot.nodes:
        graph.add_node(node.id, kind=node.kind, layer=node.layer, record_id=node.id)
    node_ids = set(graph.nodes)
    for edge in snapshot.edges:
        if edge.source in node_ids and edge.target in node_ids:
            graph.add_edge(edge.source, edge.target, key=edge.id, kind=edge.kind, layer=edge.layer, record_id=edge.id)
    return graph


@dataclass
class GraphIndex:
    snapshot: Snapshot
    graph: nx.MultiDiGraph
    nodes: dict[str, NodeRecord]
    edges: dict[str, EdgeRecord]
    # record id -> list of (referrer id, property name) for property/expression references
    referenced_by: dict[str, list[tuple[str, str]]] = field(default_factory=lambda: defaultdict(list))
    # node id -> outgoing / incoming edge ids
    outgoing: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    incoming: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def out_edges(self, node_id: str, kinds: set[str] | None = None) -> list[EdgeRecord]:
        return [self.edges[e] for e in self.outgoing.get(node_id, []) if kinds is None or self.edges[e].kind in kinds]

    def in_edges(self, node_id: str, kinds: set[str] | None = None) -> list[EdgeRecord]:
        return [self.edges[e] for e in self.incoming.get(node_id, []) if kinds is None or self.edges[e].kind in kinds]

    def property_refs(self, record_id: str, vocabulary: Vocabulary) -> list[tuple[str, str]]:
        rec = self.nodes.get(record_id) or self.edges.get(record_id)
        if rec is None:
            return []
        return _record_refs(rec, vocabulary)


def _record_refs(rec: NodeRecord | EdgeRecord, vocabulary: Vocabulary) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    if isinstance(rec, EdgeRecord):
        rel = vocabulary.relation(rec.kind)
        specs = rel.property_specs() if rel else {}
    else:
        kind = vocabulary.kind(rec.kind)
        specs = kind.properties if kind else {}
    refs.extend(reference_properties(specs, rec.properties))
    expr = rec.properties.get("expression")
    if expr is not None:
        refs.extend(("expression", r) for r in expression_refs(expr))
    return refs


def build_index(snapshot: Snapshot, vocabulary: Vocabulary) -> GraphIndex:
    graph = build_graph(snapshot)
    index = GraphIndex(snapshot=snapshot, graph=graph, nodes=snapshot.node_map(), edges=snapshot.edge_map())
    for edge in snapshot.edges:
        index.outgoing[edge.source].append(edge.id)
        index.incoming[edge.target].append(edge.id)
    for rec in list(snapshot.nodes) + list(snapshot.edges):
        for prop, ref in _record_refs(rec, vocabulary):
            index.referenced_by[ref].append((rec.id, prop))
    return index
