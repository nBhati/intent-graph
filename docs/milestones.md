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

## Milestone 2: self-model and agent views (in progress)

Started: `.intentgraph/` in this repository models Intent Graph itself (goals, key decisions, persistence requirements, and the obligations that the later milestones must discharge), each with source references into the architecture document.

Remaining: dependency slices beyond one explicit traversal, graph diffs between revisions, and a first real improvement planned and implemented with the seed's help, resumable from a fresh conversation.

## Milestones 3 to 6

Not started. See the architecture document, sections 21.6 to 21.9.
