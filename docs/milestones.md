# Milestone log

Development follows section 21 of the architecture document: seed, progressive self-use, external evaluation.

## Milestone 0: implementation contract (done, 2026-10-18)

Built: package scaffold with the module boundaries from section 8; initial vocabulary registry (39 kinds, 18 relations); the hand-authored coaching fixture (`tests/fixtures/coaching-patch.json`) containing a component dependency with parallel edges, a behavioral `invokes` cycle, an unresolved requirement with a blocking question, and a requirement-to-test mapping; the snapshot, patch, CLI-response and error conventions in `docs/data-contract.md`.

Verified: the fixture distinguishes intent, observation and reconciliation; relation directions are declared per relation; every envelope field has a defined meaning.

## Milestone 1: independently tested seed (done, 2026-10-18)

Built: typed records, vocabulary lookup, canonical serialization and digests, snapshot loading with digest verification, NetworkX construction, reference validation, atomic patch application under a file lock, revision checks, idempotent patch ids, and the CLI: `init`, `status`, `vocabulary show|list`, `view`, `search`, `show`, `patch validate|apply`, `check`, `rebuild`.

Verified by `tests/` (43 tests): serialization/reconstruction preserves ids and parallel edges; missing endpoints fail; legal behavioral cycles remain valid; containment cycles fail; stale patches are rejected with changed ids and cannot overwrite concurrent accepted changes; repeated patch ids are idempotent and conflicting reuse is an error; interrupted writes preserve the previous readable snapshot; hand edits and truncated files are detected; the write lock is exclusive; a fresh process reconstructs and queries the model from files alone; lenses never drop mandatory records and report overflow.

Exit criterion met: a fresh CLI process reconstructs and edits a small complete model from persisted files without hidden state.

Known limits: no caches yet (the cache directory exists and `rebuild` clears it); `status` reports gates as unsupported; evidence trust levels are recorded but not evaluated.

## Milestone 2: self-model and agent views (done, 2026-10-18)

Built: the self-model in `.intentgraph/` (goals, decisions, requirements, the twelve modules and their dependencies, global constraints, open questions, one obligation per remaining milestone, all with source references into the architecture document); the agent playbook with a resume procedure; `impact` (dependency slice driven by per-relation `impact` directions declared in the vocabulary, plus property references); `diff` (transaction-based ids since a revision; record-level diff against a snapshot file or a Git ref); explicit truncation, boundary and coverage reporting.

Self-use: the impact and diff commands were the "one real improvement" of section 21.5. The plan was recorded first (`patch:plan-m2-impact-diff`: two requirements, a design decision, a deferred question, a blocking obligation), the code was written against it, and the closing patch (`patch:close-m2-impact-diff`) added CodeSymbol records, a Mapping, an Evidence record from the test run, and marked the obligation satisfied. `tests/test_self_model.py` proves a fresh process can recover that context from the persisted files alone.

Verified: the agent can find the intent behind persistence behavior (`view --focus component:repository --include parent_intent`), determine which elements depend on a changed interface (`impact --changed interface:response-events`), and update the model through targeted patches without loading every record; global constraints appear in every lens regardless of focus.

Known limits: impact reports recorded reachability only; upward propagation from a refinement to its parent is deferred to readiness policy; diffs show which fields changed, not textual hunks.

## Milestone 3: readiness through self-use (done, 2026-10-18)

Defined first in the self-model (`patch:plan-m3-readiness`): seven requirements covering inputs, states, errors, policy behaviour and completion criteria of readiness; the three operations (`readiness`, `review export`, `approval record`) with inputs, outputs and failures; the readiness states; the check/refine/check process; two design decisions (declarative policies; the closure rule); the answered question about default mandatory rules; and `scope:m3-readiness`.

Built: vocabulary `core/0.2` (Scope kind, `decision_kind`, approval binding fields) with an explicit, previewable, backed-up migration; `set_policy`/`remove_policy` patch operations with schema validation; scope closure with per-member reasons; the design digest; the obligation engine with eleven rule types, model obligations, user-authorized waivers and approval state; review-packet export and recording; approval records; `conformance` as the post-build policy kind; `status` gates for every active scope.

Verified by tests (68 passing): missing obligations produce actionable responses; a blocking question yields `blocked`; a deferral decision satisfies realization; an agent assertion cannot satisfy an evidence rule while a submitted report can; recording an approval leaves the design digest unchanged; an unrelated evidence or out-of-scope addition keeps the approval current; a design change inside the scope invalidates the approval, names it and lists the changed ids; readiness never writes; waivers without user authorization are not honoured; invalid policies are rejected and policy versions are part of the digest; migrations preview, back up and record a transaction.

Self-use exit: `scope:m3-readiness` went through the loop on the real model: `needs_work` (packet missing) → `review export --record` → `ready` → `approval:m3-readiness/r8` recorded from the user's words "continue with milestone 3" → `conformance` ready with mappings and test evidence. Per section 21.6 the first implementation relied on the independent test suite and manual review and then passed its own loop; the obligation's annotation says so.

Known limits: evidence freshness is not evaluated (no workspace snapshots yet); packets have no diagrams; waivers and approvals are agent-recorded traceability, not authenticated identity; the conformance policy cannot yet tell a stale test report from a current one.

## Milestones 4 to 6

Not started. See the architecture document, sections 21.7 to 21.9. Each has a draft scope and a pending obligation in the self-model.
