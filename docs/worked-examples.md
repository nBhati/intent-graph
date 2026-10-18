# Worked examples

Five situations the agent playbook (architecture section 11.1) must cover. Each is a sequence of real commands; `tests/test_worked_examples.py` runs the same steps, so the document cannot drift from the tool. Commands assume a workspace initialized with `intentgraph init` and patches that carry the current `base_revision` and `base_digest` from `intentgraph status --json`.

## 1. A successful refinement

Original intent: "The learner must be able to interrupt the coach."

1. Record the goal with the user's exact words as an `original_intent` annotation.
2. Refine it into a requirement, a scenario and a decision (`refines`, `concerns`), then the operation and component that realize it (`realizes`, `declares`, `exposes`).
3. Create a `Scope` with the component and the requirement as members and run `intentgraph readiness --scope scope:interrupt`.
4. Resolve what it asks for: define the operation's inputs, outputs and failures; export the review packet with `intentgraph review export --scope scope:interrupt --record`.
5. `readiness` reports `ready`; after the user says so in their own words, `intentgraph approval record --file approval.json` binds that authorization to the design digest.

What the tool proves: the scope's structure is complete under the policy and the packet covers it. What it does not prove: that the interpretation is what the user meant. That is why the packet is shown to the user before approval.

## 2. An ambiguous requirement

"Stop the coach" could mean stopping playback only or also cancelling pending generation.

1. Do not pick silently. Record a `Question` with `blocking: true` and a `concerns` edge to the requirement, and keep the requirement `proposed`.
2. `readiness` returns status `blocked` with an obligation whose acceptable resolution is `user_clarification`; nothing else can clear it.
3. When the user answers, patch the question (`status: answered`, `answer`), record the choice as a `Decision` with `decided_by: user`, and accept the requirement.
4. `readiness` moves on to the remaining obligations.

An agent-written waiver cannot clear the blocked item: a waiver is honoured only with `authorized_by: "user"` and a reason.

## 3. Stale evidence after a code change

1. Implement, map the code (`CodeSymbol`, `TestCase`, `Mapping`) and submit evidence with declared inputs: `intentgraph evidence submit --file report.json` where `inputs.paths` lists the files the result depends on, or let the tool run the tests with `intentgraph evidence capture --file spec.json`.
2. `intentgraph reconcile --scope scope:interrupt` reports the evidence fresh and conformance `ready`.
3. Someone edits a mapped source file without touching the model.
4. A fresh `intentgraph reconcile --scope scope:interrupt` reports `source_changed` for the evidence, conformance `needs_work` with the stale evidence named, and `ci` exits 2 for the authorized scope.
5. Re-run the tests and resubmit; freshness returns.

Reverting the file also restores freshness, because freshness is content-based, not time-based.

## 4. A counterexample from an analysis

1. A behavioral rule is recorded as a `Constraint` with an `intent-expr/0.1` expression and an `Assumption` it depends on.
2. An analyzer run (operated by the agent, outside the tool) finds a trace that violates it. Record an `AnalysisRun` with `outcome: counterexample`, the configuration, and the trace as an artifact; record a `Finding` with `severity: blocker` that `challenges` the constraint and the operation it targets.
3. `readiness` on the scope reports the model obligation/finding; `status` lists the open finding; `impact --changed constraint:...` shows what the rule governs.
4. Resolution is one of: fix the design (patch the transition or operation), weaken the constraint deliberately (a `Decision` with rationale, superseding the old constraint), or refute the assumption. Each leaves a different record. Mark the finding `resolved` only after one of those is recorded.

## 5. An unsupported analysis

1. A requirement asks for a property no available tool can check (for example a timing bound on a physical audio device).
2. Record an `AnalysisRun` with `outcome: unsupported` and why, and an `Obligation` with `state: blocked` naming what would be needed (a device measurement).
3. `readiness` reports the scope `blocked` with that obligation; `capabilities` lists formal analysis as recording-only; nothing reports the property as verified.
4. The user decides: measure by hand (record the result as evidence with `collection_mode: agent_submitted_report` and its limitations), waive with a reason, or defer the requirement with a `Decision`.

The tool never upgrades an unsupported outcome to a pass. Absence of a check is reported as unknown, not as satisfied.
