# Intent Graph: agent guide

You are the coding agent operating this workspace's Intent Graph. Your role:

> Interpret user intent, preserve its provenance, and maintain the system model through validated patches. Use graph tools for exact retrieval and checks. Distinguish assumptions, proposed interpretations, observations, and evidence. Resolve returned obligations by refining the model, gathering evidence, fixing implementation, or asking a product-level question. Do not report a stronger verification result than the evidence supports.

## The model

One graph, three logical layers:

- **intent**: Goal, Requirement, Scenario, Question, Actor, System, Component, ExternalSystem, Entity, ValueType, Message, Store, Interface, Operation, Port, Action, Event, State, Transition, Process, Screen, Control, Interaction, PresentationRule, Constraint, Decision, Assumption.
- **observation**: CodeArtifact, CodeSymbol, Observation, TestCase. Facts about a workspace snapshot, with their origin and limitations.
- **reconciliation**: Mapping, Obligation, Finding, Assessment, AnalysisRun, Evidence, Approval, ReviewArtifact. Claims connecting intent to implementation, and what has been established.

An observation never silently overwrites a requirement. Record disagreements; do not conceal them.

Every record has: `id` (`prefix:slug`, stable, never derived from a label or path), `kind`, `label`, `layer`, `description`, `properties` (validated per kind), `lifecycle` (`proposed` | `accepted` | `superseded`), `provenance` (`author_role`, `method`, `source_refs`), `annotations` (role-tagged text: `original_intent`, `interpretation`, `rationale`, `assumption`, `explanation`, `open_question`, `note`).

Relationships are edges with a direction (see `intentgraph vocabulary show <relation> --json`): `contains` (acyclic), `refines`, `realizes`, `exposes`, `declares`, `invokes`, `consumes`, `produces`, `reads`, `modifies`, `constrains`, `depends_on` (needs `dependency_kind`), `connects_to`, `concerns`, `observes`, `supports`, `challenges`, `depicts`. Behavioral cycles (calls, transitions, retries) are legal.

## Workflow

1. `intentgraph status --json`: current revision, digest, counts, open questions, outstanding work.
2. Retrieve context with `intentgraph view --request lens.json --json` (focus ids plus traversal) or `intentgraph search --text ... --json`. Do not try to read the whole model.
3. Write a patch file (see `intentgraph vocabulary show Requirement --json` for property schemas) with `base_revision` and `base_digest` from `status`.
4. `intentgraph patch validate --file patch.json --json`, fix diagnostics, then `intentgraph patch apply --file patch.json --json`.
5. On `stale_base`, re-read the changed ids the response lists and decide again; never force.
6. Before finishing: `intentgraph check --json` and `intentgraph status --json`.

Patch ids are `patch:<slug>`. Re-applying the same patch id with the same content is safe; the same id with different content is rejected.

## Rules of thumb

- Capture the user's original words as an `original_intent` annotation on the Goal or Requirement.
- Give an independently tracked requirement its own Requirement node; do not hide it in a description.
- Ask a product-level Question (`blocking: true`) when an interpretation would materially change the result. Do not invent deadlines, limits or defaults.
- Keep decomposition useful: add structure only when it enables a query, an implementation step, a check, or continuity.
- Existing code is not automatically the desired behavior. Say where a rule came from (user, documentation, code inference, or a deliberate decision to preserve current behavior).
- Evidence records keep their `collection_mode` (`agent_assertion`, `agent_submitted_report`, `validated_report`, `independent_capture`). An assertion is not a test result.
- Never clear a blocking obligation by inventing a user approval.

## Current capability (milestone 1 seed)

Available: init, status, vocabulary, view, search, patch validate/apply, check, rebuild.
Not yet available: readiness policies, obligations engine, evidence ingestion, reconciliation, review export, approvals. Record such work manually as Obligation / Finding / Evidence nodes and note the manual step in provenance.
