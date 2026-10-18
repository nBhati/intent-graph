# Intent Graph

A local, agent-operated system that maintains an annotated model of software intent, design, implementation mappings, and evidence. It closes the loop from human intent to implementation and back through explicit refinement, computable checks, and scoped review.

The full vision and architecture is in [docs/vision-and-architecture.md](docs/vision-and-architecture.md). This repository is its implementation, built in the milestone order that document prescribes (section 21). Current state: **milestone 1 seed complete** (see [docs/milestones.md](docs/milestones.md)).

## What exists today

- A typed record envelope (Pydantic) for nodes and edges with stable IDs, layers, lifecycle, provenance and role-tagged annotations.
- A versioned core vocabulary (`core/0.1`): 39 node kinds and 18 relationship kinds with per-kind property schemas, endpoint rules, and explicit acyclicity only where it belongs (`contains`). Project extensions via namespaced kinds.
- Canonical serialization with a content digest; one JSON snapshot in `.intentgraph/model.json`.
- A repository layer with an exclusive write lock, atomic replacement, and digest verification on load. A hand-edited or half-written snapshot is detected, never silently accepted.
- Revision-bound patches: stale bases are rejected with the IDs changed since the base; a repeated patch ID with identical content replays idempotently; the same ID with different content is an error; invalid candidates are never written.
- Structural checks: identity, kind, layer, property schema, endpoint existence and kind, reference integrity across properties and expressions, containment cycles, `intent-expr/0.1` expression shape.
- A basic lens (focus plus explicit traversal, mandatory global rules, boundary reporting, honest truncation/overflow), search, and record inspection.
- A CLI with stable JSON responses and the exit-code convention from section 12 (0 ok, 2 blockers, 3 invalid input or stale base, 4 execution failure).
- An agent guide and an idempotent pointer installed into the workspace's existing `CLAUDE.md`/`AGENTS.md`.

Not yet built: readiness policies and obligations engine, evidence ingestion, workspace snapshots and drift reconciliation, review-packet export, approvals, migrations, bundled executable. `intentgraph status` reports gates as `unsupported` rather than pretending.

## Install (development)

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest -q
```

Requires Python 3.11+. Runtime dependencies: Pydantic, NetworkX.

## Quick start

```bash
cd your-project
intentgraph init                       # creates .intentgraph/ and an agent pointer
intentgraph status --json              # revision, digest, counts, outstanding work
intentgraph vocabulary show Requirement --json
intentgraph patch validate --file patch.json --json
intentgraph patch apply --file patch.json --json
intentgraph view --focus operation:cancel-response --include parent_intent constraints --json
intentgraph search --text cancellation --json
intentgraph check --json
intentgraph rebuild --json
```

A patch names its base:

```json
{
  "patch_id": "patch:cancel-refinement-01",
  "base_revision": 12,
  "base_digest": "sha256:...",
  "reason": "Capture late-response behavior agreed in the discussion.",
  "operations": [
    {"op": "update_properties", "id": "operation:cancel-response", "changes": {"idempotent": true}},
    {"op": "add_edge", "record": {
      "id": "edge:cancel-rule-target", "kind": "constrains", "layer": "intent",
      "source": "constraint:cancelled-response-silent", "target": "operation:cancel-response",
      "provenance": {"author_role": "agent", "method": "design"}}}
  ]
}
```

Operations: `add_node`, `add_edge`, `update_properties` (null removes a key), `update_fields` (label, description, lifecycle, provenance, annotations), `add_annotation`, `remove`. See [docs/data-contract.md](docs/data-contract.md).

A complete worked example lives in `tests/fixtures/coaching-patch.json` (the interruptible-coaching scenario from the architecture document): three layers, a component dependency with parallel edges, a behavioral cycle, an unresolved requirement with a blocking question, and a requirement-to-test mapping.

## Layout

```
src/intentgraph/
  model/        record envelope, canonical serialization, intent-expr validation
  vocabulary/   core kinds/relations (JSON) and the registry with extension loading
  repository/   workspace layout, manifest, lock, atomic store
  graph/        NetworkX MultiDiGraph construction and reverse-reference index
  checks/       structural validation -> diagnostics
  patches/      patch model, validation, application, idempotency
  lenses/       basic lens and search
  services.py   application services shared by CLI (and a later MCP server)
  cli/          argparse front end, JSON envelope, exit codes
  playbooks/    agent guide and workspace pointer
tests/          executable guarantees (section 22) and fixtures
docs/           vision, data contract, milestone log
```

This repository also models itself: `.intentgraph/` holds the project's own goals, decisions and obligations, maintained through the tool (section 21.1, progressive self-use).
