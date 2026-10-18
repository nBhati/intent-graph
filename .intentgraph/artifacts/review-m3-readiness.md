# Review: Milestone 3: readiness, review packets and approvals

Scope `scope:m3-readiness` · policy `policy:default-readiness@0.1` · model revision 7 · readiness **needs_work**

Design digest: `sha256:e3e866981d7c9f0de5ef31448e53c91cb931c498f852c4ae9f15f4e2ed6c6138`

## What are we trying to achieve?

_Goals and the requirements in scope._

- **An agent assertion cannot satisfy a rule that requires executable evidence** `req:assertion-cannot-satisfy-executable-evidence` (Requirement)
  - priority: must
- **A semantic change inside the approved scope invalidates the prior approval and names the affected approval** `req:design-change-invalidates-readiness` (Requirement)
  - priority: must
- **Recording an approval or adding evidence does not change the approved design digest** `req:design-digest-stable-under-approval` (Requirement)
  - priority: must
- **A readiness check never modifies the model or its own policy** `req:readiness-does-not-modify` (Requirement)
  - priority: must
- **Readiness evaluates a versioned policy against a scope and returns actionable obligations** `req:readiness-evaluates-policy` (Requirement)
  Inputs: a Scope record (explicit members, closure rule, policy ref) and the current snapshot. Output: status, design digest, obligations, warnings, approval state.
  - priority: must
- **The review packet is selected deterministically from the scope and carries its scope digest and coverage** `req:review-packet-deterministic` (Requirement)
  - priority: must
- **A waiver is honoured only when it records a user authorization and a reason** `req:waiver-requires-user` (Requirement)
  - priority: must

## What will the user experience?

_Scenarios and experience elements._

(nothing in scope)


## How will the main parts cooperate?

_Structure, contracts and behavior._

- **obligations** `component:obligations` (Component)
- **reports** `component:reports` (Component)
- **Record a source-backed user approval for a ready scope** `operation:approval-record` (Operation)
  - failures: ['scope_not_ready', 'unknown_scope', 'stale_base']
  - inputs: {'recorded_by': 'user|agent', 'scope': 'Scope id', 'statement': 'exact user statement'}
  - outputs: {'approval_id': 'id', 'design_digest': 'sha256'}
- **Evaluate readiness of a scope** `operation:readiness` (Operation)
  - failures: ['unknown_scope', 'unknown_policy', 'invalid_policy']
  - inputs: {'policy': 'optional policy id', 'scope': 'Scope id'}
  - outputs: {'design_digest': 'sha256', 'obligations': 'list', 'status': 'ready|needs_work|blocked'}
- **Export a review packet for a scope** `operation:review-export` (Operation)
  - failures: ['unknown_scope']
  - inputs: {'record': 'boolean', 'scope': 'Scope id'}
  - outputs: {'packet': 'markdown + json', 'scope_digest': 'sha256'}
- **Internal check/refine/check loop before user confirmation** `process:readiness-loop` (Process)
  - concurrency_sensitive: False
  - steps: ['readiness', 'resolve obligations by patch or assessment', 'readiness', 'review export', 'readiness (packet current)', 'approval record']

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
- **Policies are declarative rule records in the snapshot, evaluated by built-in rule types** `decision:policy-rules-declarative` (Decision)
  - decision_kind: choice
  - rationale: Keeps policy as versioned data that cannot execute code; new rule types are tool changes, not policy edits.
- **Scope closure = explicit members, their structural children, realized requirements, applicable constraints, global constraints, and concerning questions, decisions and assumptions** `decision:scope-closure-rule` (Decision)
  - decision_kind: choice
  - rationale: Deterministic and explainable; every closure member records why it is included.

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

## Exclusions and deferrals

None recorded.

## Explanation

_No explanation written yet. The coding agent may add one; it is a judgment, not a computed check._

## Coverage

20 intent records of 20 closure members are listed above. Ids: `component:obligations`, `component:reports`, `constraint:no-hidden-state-between-calls`, `constraint:records-are-data`, `decision:agent-runs-language-tools`, `decision:policy-rules-declarative`, `decision:scope-closure-rule`, `operation:approval-record`, `operation:readiness`, `operation:review-export`, `process:readiness-loop`, `question:default-mandatory-rules`, `question:readiness-default-obligations`, `req:assertion-cannot-satisfy-executable-evidence`, `req:design-change-invalidates-readiness`, `req:design-digest-stable-under-approval`, `req:readiness-does-not-modify`, `req:readiness-evaluates-policy`, `req:review-packet-deterministic`, `req:waiver-requires-user`
