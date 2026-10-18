"""Milestone 1 exit criterion: a fresh process reconstructs the model from files."""
import json
import subprocess
import sys

from intentgraph.graph import build_graph
from intentgraph.repository import Repository
from intentgraph.services import Context


def test_round_trip_preserves_ids_and_parallel_edges(coaching_repo: Repository):
    first = coaching_repo.load_snapshot()
    # Reload through a *new* Repository object (no shared state).
    second = Repository(coaching_repo.paths).load_snapshot()
    assert first == second
    assert first.content_digest == second.content_digest
    assert first.revision == 1
    ids = {n.id for n in second.nodes} | {e.id for e in second.edges}
    assert "req:cancel-response" in ids and "edge:controller-dependency" in ids
    # Parallel edges between the same endpoints survive with distinct keys.
    g = build_graph(second)
    keys = set(g["component:playback-controller"]["interface:response-events"].keys())
    assert keys == {"edge:controller-dependency", "edge:controller-build-dependency"}
    assert g.number_of_nodes() == len(second.nodes)
    assert g.number_of_edges() == len(second.edges)


def test_round_trip_in_fresh_process(coaching_repo: Repository):
    code = (
        "import json,sys\n"
        "from intentgraph.services import Context\n"
        "from intentgraph.model import compute_digest\n"
        "ctx = Context.open(sys.argv[1])\n"
        "assert ctx.snapshot.content_digest == compute_digest(ctx.snapshot)\n"
        "assert not [d for d in ctx.diagnostics() if d.severity == 'error']\n"
        "print(json.dumps({'revision': ctx.snapshot.revision, 'nodes': len(ctx.snapshot.nodes), 'edges': len(ctx.snapshot.edges)}))\n"
    )
    out = subprocess.run([sys.executable, "-c", code, str(coaching_repo.paths.root)], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    snap = coaching_repo.load_snapshot()
    assert data == {"revision": 1, "nodes": len(snap.nodes), "edges": len(snap.edges)}


def test_fixture_covers_three_layers_and_required_shapes(coaching_ctx: Context):
    snap = coaching_ctx.snapshot
    layers = {r.layer for r in snap.nodes}
    assert layers == {"intent", "observation", "reconciliation"}
    kinds = {n.kind for n in snap.nodes}
    # component dependency, behavioral cycle, unresolved requirement, requirement-to-test mapping
    assert any(e.kind == "depends_on" for e in snap.edges)
    assert {e.kind for e in snap.edges if e.source == "operation:generate-response"} >= {"invokes"}
    assert snap.get("req:stop-active-response").lifecycle == "proposed"
    assert snap.get("question:cancel-scope").properties["blocking"] is True
    mapping = snap.get("mapping:cancel-test")
    assert mapping.properties["mapping_kind"] == "tests" and "test:cancel-then-late-response" in mapping.properties["implementation_refs"]
    assert {"Mapping", "Evidence", "Obligation", "CodeSymbol", "Constraint"} <= kinds
    assert [d for d in coaching_ctx.diagnostics() if d.severity == "error"] == []
