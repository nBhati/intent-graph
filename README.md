# Intent Graph

A local, agent-operated system that maintains an annotated model of software intent, design, implementation mappings, and evidence. It closes the loop from human intent to implementation and back through explicit refinement, computable checks, and scoped review.

The full vision and architecture is in [docs/vision-and-architecture.md](docs/vision-and-architecture.md). This repository is its implementation, built in the milestone order that document prescribes (section 21). Current state: **milestone 5 complete (v0.1.0 frozen for the external study)** (see [docs/milestones.md](docs/milestones.md)).

## What exists today

- A typed record envelope (Pydantic) for nodes and edges with stable IDs, layers, lifecycle, provenance and role-tagged annotations.
- A versioned core vocabulary (`core/0.1`): 39 node kinds and 18 relationship kinds with per-kind property schemas, endpoint rules, and explicit acyclicity only where it belongs (`contains`). Project extensions via namespaced kinds.
- Canonical serialization with a content digest; one JSON snapshot in `.intentgraph/model.json`.
- A repository layer with an exclusive write lock, atomic replacement, and digest verification on load. A hand-edited or half-written snapshot is detected, never silently accepted.
- Revision-bound patches: stale bases are rejected with the IDs changed since the base; a repeated patch ID with identical content replays idempotently; the same ID with different content is an error; invalid candidates are never written.
- Structural checks: identity, kind, layer, property schema, endpoint existence and kind, reference integrity across properties and expressions, containment cycles, `intent-expr/0.1` expression shape.
- A basic lens (focus plus explicit traversal, mandatory global rules, boundary reporting, honest truncation/overflow), search, and record inspection.
- An impact slice: from changed ids, traverse each relation in its declared impact direction plus property references, returning candidates with the path that reached them and an explicit "recorded reachability only" note.
- Graph diffs: exact ids changed since a revision (from transaction summaries), or record-level differences against another snapshot file or a Git revision.
- Scopes with a deterministic closure, versioned declarative policies (readiness and conformance), and an obligation engine that returns actionable obligations with deterministic ids. It never modifies the model or its policy.
- Design digests that bind approvals to the intent content of a scope: recording an approval or adding evidence leaves the digest unchanged; a design change inside the scope invalidates the approval and names it.
- Review-packet export (Markdown and JSON) selected deterministically from the scope, recorded as a ReviewArtifact; source-backed approval records; user-authorized waivers; explicit, previewable, backed-up migrations.
- Evidence ingestion that preserves and verifies the collection mode: submitted reports, validated reports the tool parses (JUnit XML, a small JSON format), and independent captures the tool runs itself. Every evidence record binds to a workspace snapshot of its declared inputs (Git HEAD, dirty and untracked state, content digests) and to the model content it supports.
- Freshness rules shared by reconciliation and conformance: changed inputs, changed model content, changed lockfiles, missing artifacts. Stale evidence never satisfies a policy; a missing artifact drops the evidence to an assertion.
- `reconcile`: broken locators, failed tests, stale or unbound evidence, unmapped source changes against a snapshot baseline, invalidated approvals, each with its safe conclusion and follow-up. `ci`: the independent trigger for all of the above.
- `recover`: diagnose a damaged snapshot and preview or apply recovery from a migration backup or a Git revision, keeping the damaged copy. `capabilities` and `version`: what this build supports and what it does not, with tool, format, vocabulary and response versions. Every JSON response carries `response_version`.
- Review packets include a Mermaid component diagram when the scope has structure to show. `docs/worked-examples.md` covers refinement, an ambiguous requirement, stale evidence, a counterexample and an unsupported analysis, and `tests/test_worked_examples.py` runs those steps.
- A CLI with stable JSON responses and the exit-code convention from section 12 (0 ok, 2 blockers, 3 invalid input or stale base, 4 execution failure).
- An agent guide and an idempotent pointer installed into the workspace's existing `CLAUDE.md`/`AGENTS.md`.

Not built: native symbol extraction (symbol claims carry their extractor), formal-analysis invocation (results are recorded, not produced), an MCP server, standalone executables (deferred). `intentgraph capabilities --json` lists these.

## Install

The Python package is the installation route. `uv` installs command-line tools in isolated environments and obtains a Python runtime automatically, so you do not manage a virtual environment or install NetworkX and Pydantic yourself. The tool is not a runtime dependency of the project you model; a Flutter or TypeScript project uses the same CLI.

```bash
uv tool install intentgraph        # recommended (package name illustrative until published)
pipx install intentgraph           # alternative
intentgraph init
intentgraph status
```

Until the package is on PyPI, install from a checkout: `uv tool install /path/to/intent-graph` (or `uv build` and install the wheel). Standalone executables are deferred; an npm wrapper may come later.

Development:

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest -q
```

Requires Python 3.11+. Runtime dependencies: Pydantic, NetworkX. `tests/test_install.py` installs the built wheel into an isolated uv tool environment and runs the whole loop with no source tree on the path, then checks that reinstalling and uninstalling preserve project files.

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
intentgraph impact --changed interface:response-events --json
intentgraph diff --since 12 --json
intentgraph diff --git HEAD~1 --json
intentgraph readiness --scope scope:cancel --json
intentgraph review export --scope scope:cancel --record
intentgraph approval record --file approval.json --json
intentgraph conformance --scope scope:cancel --json
intentgraph migrate --apply
intentgraph evidence capture --file capture.json --json     # tool runs the argv, records independent_capture
intentgraph evidence submit --file report.json --json       # submitted or validated report
intentgraph workspace snapshot --repository app
intentgraph reconcile --scope scope:cancel --json
intentgraph ci --json
intentgraph recover --from-git HEAD --apply
intentgraph capabilities --json
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
  model/        record envelope, canonical serialization, intent-expr validation, snapshot diff
  vocabulary/   core kinds/relations (JSON) and the registry with extension loading
  repository/   workspace layout, manifest, lock, atomic store, Git baselines, migrations,
                workspace snapshots
  graph/        NetworkX MultiDiGraph construction and reverse-reference index
  checks/       structural validation -> diagnostics
  patches/      patch model, validation, application, idempotency
  lenses/       basic lens, impact slice, search
  obligations/  policies, scope closure and design digest, readiness/conformance engine,
                evidence freshness, reconciliation findings, report validation
  reports/      review packet (Markdown + JSON)
  services.py   application services shared by CLI (and a later MCP server)
  cli/          argparse front end, JSON envelope, exit codes
  playbooks/    agent guide and workspace pointer
tests/          executable guarantees (section 22) and fixtures
docs/           vision, data contract, milestone log, worked examples
```

This repository also models itself: `.intentgraph/` holds the project's own goals, decisions and obligations, maintained through the tool (section 21.1, progressive self-use).
