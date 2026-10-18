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
   - Before changing an element, run `intentgraph impact --changed <id> --json`: it lists the recorded elements the change may affect, with the path that reached each one. Absence means unknown, not unaffected.
   - To see what changed since a revision or a Git ref: `intentgraph diff --since N --json`, `intentgraph diff --git HEAD~1 --json`, or `intentgraph diff --file old-model.json --json`.
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

## Readiness loop (before asking the user to authorize a build)

1. Create a `Scope` node (`member_refs`: the components, operations and requirements of the change; `status: active`; `policy_ref`). The closure adds structural children, realized requirements, applicable and global constraints, and concerning questions, decisions and assumptions.
2. `intentgraph readiness --scope <id> --json`. Status `ready`, `needs_work` or `blocked`. Each obligation names the rule, the related ids, the request and the acceptable resolutions.
3. Resolve obligations by patching the model (realize a requirement, define an operation's inputs/outputs/failures, record a deferral Decision, answer a Question) or by recording an Assessment/Obligation record. Only the user can resolve a `blocked` item; ask a product-level question.
4. `intentgraph review export --scope <id> --record`: writes the packet (Markdown + JSON) and records a ReviewArtifact at the current design digest. Show the user the packet in product language; you may add an explanation, which is a judgment.
5. When `ready`, and only after the user has said so in their own words, run `intentgraph approval record --file approval.json` with `recorded_by`, the exact `source_statement` and a `source_ref`. The approval binds to the design digest; later evidence does not invalidate it, a design change inside the scope does.
6. After implementation, record mappings (CodeSymbol/CodeArtifact/TestCase records plus a Mapping) and submit evidence:
   - `intentgraph evidence capture --file spec.json`: the tool runs a declared argv (no shell) and records exit code and output as `independent_capture`.
   - `intentgraph evidence submit --file report.json`: a report you ran yourself. With `collection_mode: validated_report` and a `junit-xml` or `intentgraph-test-report/0.1` artifact the tool parses it and refuses a mismatched claim; otherwise it is `agent_submitted_report`.
   - Always declare `inputs.paths` (the files the result depends on). Evidence binds to a WorkspaceSnapshot of those paths and to the model content it supports; either changing makes it stale.
7. `intentgraph reconcile --scope <id> --json` before you report completion: broken locators, stale or unbound evidence, missing artifacts, failed tests, unmapped source changes, invalidated approvals, and freshness-aware conformance. Resolve each finding by the operation it names (fix code, correct a mapping, resubmit evidence, or propose a deliberate change); do not clear findings by editing records to match the code.
8. `intentgraph workspace snapshot --repository <root>` records a baseline so later unmapped changes can be detected. CI runs `intentgraph ci` independently.

A waiver is an Obligation node with the computed obligation id, `state: waived` and `waiver: {authorized_by: "user", reason, source_statement}`. Never write one without the user's authorization. Policies change only through `set_policy` patch operations with a reason.

## Resuming work in a fresh conversation

1. `intentgraph status --json`: read `outstanding` (open questions, pending obligations, open findings).
2. `intentgraph search --kind Obligation --lifecycle proposed --json`, then `intentgraph show <obligation id> --json` for its `request`, `scope_refs` and what it `concerns`.
3. `intentgraph view --focus <scope ids> --include parent_intent constraints findings --json` for the surrounding intent and rules.
4. `intentgraph diff --git <last known ref> --json` to see what the model gained since you last looked.
5. Continue from the obligation; when done, patch its `state` to `satisfied` and add Mapping/Evidence records that say how.

## Current capability (v0.1.0)

Run `intentgraph capabilities --json` for the authoritative list of commands, rule types, formats, and what is explicitly unsupported. If `intentgraph status` reports a corrupt snapshot, do not hand-edit it: `intentgraph recover` lists backups and previews a restore from a backup or Git revision. Worked examples with real command sequences are in the package documentation (`docs/worked-examples.md`).
