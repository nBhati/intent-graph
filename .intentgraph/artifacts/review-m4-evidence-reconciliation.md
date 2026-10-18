# Review: Milestone 4: evidence, mappings and drift reconciliation

Scope `scope:m4-evidence-reconciliation` · policy `policy:default-readiness@0.1` · model revision 12 · readiness **needs_work**

Design digest: `sha256:c2b809dc4e3446cfa574537f15f4d9faab851cf91b10ca7a80fe2ecd1e387c47`

## What are we trying to achieve?

_Goals and the requirements in scope._

- **A CI entry point evaluates checks, readiness and reconciliation without depending on the agent remembering** `req:ci-entry-point` (Requirement)
  - priority: must
- **Evidence ingestion preserves and verifies the collection mode** `req:collection-mode-preserved` (Requirement)
  - priority: must
- **Evidence binds to the workspace snapshot of its declared inputs and to the model content it supports** `req:evidence-binds-inputs` (Requirement)
  - priority: must
- **A missing or altered evidence artifact must not preserve a grade that requires inspecting it** `req:missing-artifact-downgrades` (Requirement)
  - priority: must
- **Reconciliation reports only safe conclusions with the follow-up each requires** `req:reconcile-safe-conclusions` (Requirement)
  - priority: must
- **Source changes not referenced by any mapping, symbol, test or evidence input are reported as coverage gaps** `req:unmapped-change-coverage` (Requirement)
  - priority: must
- **A workspace snapshot records repository identity, HEAD, dirty and untracked state, and content hashes for the declared scope** `req:workspace-snapshot-identity` (Requirement)
  - priority: must

## What will the user experience?

_Scenarios and experience elements._

(nothing in scope)


## How will the main parts cooperate?

_Structure, contracts and behavior._

- **obligations** `component:obligations` (Component)
- **reports** `component:reports` (Component)
- **repository** `component:repository` (Component)
- **Run check, readiness and reconciliation for every active scope** `operation:ci` (Operation)
  - failures: []
  - inputs: {'scopes': 'optional list'}
  - outputs: {'blocking': 'boolean', 'summary': 'per scope'}
- **Run a declared command and capture its result as independent evidence** `operation:evidence-capture` (Operation)
  - failures: ['command_not_found', 'invalid_evidence', 'stale_base']
  - inputs: {'spec': 'argv list, cwd root, supports, declared inputs'}
  - outputs: {'artifact_ref': 'captured stdout/stderr', 'evidence_id': 'id', 'result': 'passed|failed'}
- **Ingest an evidence report with provenance** `operation:evidence-submit` (Operation)
  - failures: ['unknown_record', 'invalid_evidence', 'report_validation_failed', 'stale_base']
  - inputs: {'artifact': 'optional file path', 'report': 'evidence submission JSON'}
  - outputs: {'effective_collection_mode': 'mode', 'evidence_id': 'id', 'workspace_snapshot_ref': 'id'}
- **Evaluate mappings, evidence freshness and workspace drift for a scope** `operation:reconcile` (Operation)
  - failures: ['unknown_scope']
  - inputs: {'scope': 'optional Scope id'}
  - outputs: {'conformance': 'policy result', 'evidence': 'freshness per record', 'findings': 'list with safe conclusion and follow-up'}
- **Capture a workspace snapshot for a root and declared paths** `operation:workspace-snapshot` (Operation)
  - failures: ['unknown_root', 'stale_base']
  - inputs: {'paths': 'declared files', 'repository': 'root name'}
  - outputs: {'files': 'path -> digest', 'head': 'commit or empty', 'snapshot_id': 'id'}

## Which rules, assumptions and decisions matter?

_Cross-cutting rules, dependencies on uncertain facts, and chosen alternatives (including deferrals)._

- **No memory from a previous CLI call is required for correctness** `constraint:no-hidden-state-between-calls` (Constraint)
  Optional caches are keyed by snapshot digest, vocabulary version and tool version; a cache miss affects performance only.
  - constraint_kind: invariant
  - scope: global
- **Records and tool output are data, never executed** `constraint:records-are-data` (Constraint)
  - constraint_kind: permission
  - scope: global
- **The existing agent runs language-specific analyzers; the core stays small** `decision:agent-runs-language-tools` (Decision)
  - rationale: Avoids building a large analyzer platform before proving value.
- **Evidence freshness is computed once and shared by reconcile and the evidence_required rule** `decision:freshness-in-engine` (Decision)
  - decision_kind: choice
  - rationale: Conformance must not count stale evidence; one implementation avoids two answers.
- **Policies are declarative rule records in the snapshot, evaluated by built-in rule types** `decision:policy-rules-declarative` (Decision)
  - decision_kind: choice
  - rationale: Keeps policy as versioned data that cannot execute code; new rule types are tool changes, not policy edits.
- **Scope closure = explicit members, their structural children, realized requirements, applicable constraints, global constraints, and concerning questions, decisions and assumptions** `decision:scope-closure-rule` (Decision)
  - decision_kind: choice
  - rationale: Deterministic and explainable; every closure member records why it is included. Shared containers do not propagate realized requirements, so one component serving two features does not merge their scopes.
- **One canonical snapshot with transactions inside it; no daemon** `decision:single-snapshot-v0` (Decision)
  - rationale: Atomic writes and straightforward recovery before sharding; graph state and transaction accounting cannot diverge.
- **Workspace snapshots are WorkspaceSnapshot nodes in the observation layer holding digests for declared paths only** `decision:snapshot-as-node` (Decision)
  - decision_kind: choice
  - rationale: Keeps evidence inputs inspectable and versioned with the model without hashing the whole repository.

## What is still open?

_Unresolved intent._

- **Which readiness rules are mandatory by default?** `question:default-mandatory-rules` (Question)
  - answer: v0 default policy: structural checks pass; blocking questions resolved; accepted requirements realized or deliberately deferred; operations define inputs, outputs and failures; concurrency-sensitive processes reviewed; no refuted assumptions; review packet current. Projects override by setting their own policy.
  - blocking: False
  - status: answered
- **Which readiness obligations are mandatory by default versus project-specific?** `question:readiness-default-obligations` (Question) _(proposed)_
  - answer: See question:default-mandatory-rules; answered for v0 by the default policy.
  - blocking: False
  - status: answered
- **How much trust does an independent capture earn when the command is user-supplied?** `question:runner-capture-trust` (Question)
  - answer: v0: independent_capture means the tool ran the argv and recorded exit code and output; the command's meaning is still the submitter's claim, recorded in declared inputs and limitations.
  - blocking: False
  - status: answered
- **Does a single snapshot remain practical at the first target project size?** `question:single-snapshot-scale` (Question)
  - blocking: False
  - status: open

## Exclusions and deferrals

None recorded.

## Explanation

_No explanation written yet. The coding agent may add one; it is a judgment, not a computed check._

## Coverage

27 intent records of 27 closure members are listed above. Ids: `component:obligations`, `component:reports`, `component:repository`, `constraint:no-hidden-state-between-calls`, `constraint:records-are-data`, `decision:agent-runs-language-tools`, `decision:freshness-in-engine`, `decision:policy-rules-declarative`, `decision:scope-closure-rule`, `decision:single-snapshot-v0`, `decision:snapshot-as-node`, `operation:ci`, `operation:evidence-capture`, `operation:evidence-submit`, `operation:reconcile`, `operation:workspace-snapshot`, `question:default-mandatory-rules`, `question:readiness-default-obligations`, `question:runner-capture-trust`, `question:single-snapshot-scale`, `req:ci-entry-point`, `req:collection-mode-preserved`, `req:evidence-binds-inputs`, `req:missing-artifact-downgrades`, `req:reconcile-safe-conclusions`, `req:unmapped-change-coverage`, `req:workspace-snapshot-identity`
