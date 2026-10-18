# Data contract (format 0.1, vocabulary core/0.2)

Established in milestone 0. Changes to any of these are explicit, versioned changes.

## Identity

Record IDs are `prefix:slug` (`^[a-z][a-z0-9_]*:[A-Za-z0-9][A-Za-z0-9._/-]*$`). They are stable identities and are never derived from labels or file paths. Conventional prefixes: `goal:`, `req:`, `scenario:`, `question:`, `component:`, `interface:`, `operation:`, `entity:`, `state:`, `transition:`, `constraint:`, `decision:`, `assumption:`, `artifact:`, `symbol:`, `test:`, `mapping:`, `obligation:`, `finding:`, `assessment:`, `evidence:`, `approval:`, `edge:`, `patch:`. Prefixes are conventions; the kind is authoritative.

## Record envelope

| Field | Nodes | Edges | Meaning |
| --- | --- | --- | --- |
| `id` | required | required | Stable identity |
| `kind` | required | required | Versioned vocabulary kind or relation |
| `label` | required (may be empty) | optional | Human-readable name |
| `layer` | required | required | `intent` / `observation` / `reconciliation`; must be allowed by the kind |
| `description` | optional | optional | Markdown-compatible explanation |
| `properties` | validated per kind | validated per relation | Unknown properties are rejected |
| `lifecycle` | default `proposed` | default `proposed` | `proposed` / `accepted` / `superseded` |
| `provenance` | required | required | `author_role` (user/agent/tool/import), `method`, `source_refs`, `notes` |
| `annotations` | optional | optional | `{role, text, refs}`; roles: original_intent, interpretation, rationale, assumption, explanation, open_question, note |
| `source`, `target` | – | required | Endpoint node ids |

There is deliberately no universal `verified` flag. Acceptance (`lifecycle`), formalization (`properties.formalization` on Requirement), and verification (Evidence records) are different dimensions.

Property types: `string`, `integer`, `number`, `boolean`, `array` (with optional `items`), `object`, `ref` (a record id that must exist), `ref_list`. Expressions in `properties.expression` with `expression_language: intent-expr/0.1` use operators `always`, `eventually`, `not`, `and`, `or`, `implies`, `forall`, `exists`, `field_eq`, `field_ne`, `field_in`. Other expression languages are stored and reported as not interpreted.

## Snapshot (`.intentgraph/model.json`)

```json
{
  "format_version": "0.1",
  "vocabulary_version": "core/0.1",
  "project_id": "project:example",
  "revision": 12,
  "content_digest": "sha256:<hex>",
  "nodes": [], "edges": [], "policies": [], "transactions": []
}
```

Canonical form: records sorted by id, keys sorted, UTF-8, non-finite numbers rejected, `\n` newlines, trailing newline. The digest is SHA-256 over the compact canonical payload with `content_digest` removed. The file is pretty-printed but deterministic. Loading verifies the digest; a mismatch is reported as a corrupt snapshot (hand edit or partial write), never repaired silently.

`transactions` holds one summary per applied patch: `patch_id`, `base_revision`, `result_revision`, `applied_at`, `reason`, `operations_digest`, `added_ids`, `updated_ids`, `removed_ids`.

## Patch

```json
{"patch_id": "patch:slug", "base_revision": 12, "base_digest": "sha256:...", "reason": "...", "operations": [...]}
```

| op | fields | notes |
| --- | --- | --- |
| `add_node` | `record` | full node envelope |
| `add_edge` | `record` | full edge envelope |
| `update_properties` | `id`, `changes` | merge; `null` removes a key |
| `update_fields` | `id`, any of `label`, `description`, `lifecycle`, `provenance`, `annotations` | replaces the given fields |
| `add_annotation` | `id`, `annotation` | appends |
| `remove` | `id` | warns when removing an accepted record |
| `set_policy` | `policy` | create or replace a policy by id; validated against the policy schema |
| `remove_policy` | `id` | |

Rules: base revision and digest must match the current snapshot, else `stale_base` with `changed_ids`. A repeated `patch_id` with identical operations is an idempotent replay. The same id with different operations is `patch_id_conflict`. The candidate must pass structural validation or nothing is written. Application happens under the exclusive write lock after re-reading the snapshot.

## Impact and diff

`impact` request: `{"changed": [ids], "max_depth": 3, "relations": null | [kinds], "include_references": true, "max_candidates": 200}`. Each relation declares `impact` in the vocabulary: `incoming` (the source is affected when the target changes), `outgoing`, `both`, or `none`. Property references (`ref`/`ref_list`, expression `domain_ref`) always propagate from referent to referrer. The response lists candidates with `distance`, the `path` of steps (`via` is a relation kind or `property:<name>`), `reasons`, a `by_category` count, truncation, and a fixed `coverage_note` stating that only recorded reachability is reported.

`diff` modes: `--since N` (exact ids from transaction summaries, with the patches responsible), `--file PATH` or `--git REF` (record-level: `added`, `removed`, `changed` with `fields_changed`, `properties_changed`, and `lifecycle: [old, new]`). A baseline snapshot is digest-verified like the live one. Git absence or a bad ref is reported with exit code 4 (`git_unavailable`, `git_failed`).

## Scopes, policies, readiness

A `Scope` node (reconciliation layer) has `member_refs`, `status` (`draft`/`active`/`closed`) and `policy_ref`. Closure: explicit members; structural children via `contains`, `declares`, `exposes`; targets of `realizes`; scenarios refining in-scope requirements; constraints targeting closure members plus global constraints and their `assumption_refs`; questions, decisions and assumptions that `concerns` closure members. Every member carries a `reason`.

A policy is `{id, version, kind: readiness|conformance, description, rules: [{id, rule, blocking, params}]}` stored in `policies`. Rule types: `structural_checks_pass`, `blocking_questions_resolved`, `requirements_realized`, `operations_defined`, `concurrency_sensitive_reviewed`, `assumptions_not_refuted`, `assumptions_acknowledged`, `proposed_records_accepted`, `review_packet_current`, `evidence_required` (`kinds`, `where`, `result`, `min_collection_mode`, `methods`), `mappings_present` (`kinds`, `where`). Defaults `policy:default-readiness@0.1` and `policy:default-conformance@0.1` are installed at init.

`readiness` / `conformance` response: `status` (`ready` | `needs_work` | `blocked`), `scope`, `policy` (`id@version`), `model_revision`, `design_digest`, `closure` (members with reasons), `obligations` (blocking), `warnings` (non-blocking), `waived`, `approval` (`none` | `current` | `invalidated` with `changed_in_scope_ids`), `findings`, `note`. Obligation ids are deterministic: `obligation:<scope-slug>/<rule-id>/<target-id with ':' as '.'>`; `source` is `policy` or `model` (manual Obligation nodes in scope with state pending/failed/blocked). Exit code 0 when ready, 2 otherwise.

Design digest: SHA-256 over the policy reference plus the intent-layer closure records (id, kind, label, description, properties, lifecycle) and the intent-layer edges among them. Provenance, annotations, observation and reconciliation records are excluded, so approvals and evidence never change it.

Waiver: an Obligation node with the computed id, `state: waived`, `waiver: {authorized_by: "user", reason, ...}`. Without a user authorization and reason the waiver is reported as `invalid_waiver` and not honoured.

`review export --scope S [--record] [--out PATH]`: writes `artifacts/review-<slug>.md` and `.json` (sections, coverage ids, exclusions/deferrals, design digest, readiness status) and with `--record` applies an internal patch `patch:review-export/<slug>/<digest16>` creating or updating `review:<slug>` (ReviewArtifact, `scope_digest`) and its `depicts` edge.

`approval record --file F`: `{scope_ref, recorded_by: user|agent, source_statement, [approval_kind=build_authorization], [source_ref]}`. Refused with `scope_not_ready` unless readiness is `ready`. Creates `approval:<slug>/r<revision>` carrying `design_digest`, `policy_ref`, `model_revision`, and a `concerns` edge to the scope. Agent-recorded approvals are labelled as traceability, not authenticated identity.

`migrate [--apply]`: previews (default) or applies the registered vocabulary migrations from the snapshot's version to the tool's. Apply writes `artifacts/backup-model-rev<N>-<vocab>.json` first, records a `patch:migrate-<id>` transaction, and updates `project.json`. A model on an older vocabulary still loads; it reports `vocabulary_version_mismatch` until migrated.

## CLI response envelope

```json
{"command": "status", "tool_version": "0.0.1", "status": "ok|blocked|invalid|error", "data": {...}}
{"command": "patch", "tool_version": "0.0.1", "status": "invalid", "error": {"code": "stale_base", "message": "...", "details": {...}}}
```

Exit codes: 0 ok, 2 completed with blockers (check/validate found errors, lens overflow), 3 invalid input or stale revision, 4 unavailable dependency or internal failure.

Diagnostics are `{code, severity: error|warning, message, record_ids}`. Stable codes so far: `duplicate_id`, `duplicate_patch_id`, `vocabulary_version_mismatch`, `unknown_kind`, `unknown_relation`, `invalid_layer`, `invalid_property`, `invalid_expression`, `unsupported_expression_language`, `missing_endpoint`, `illegal_endpoint_kind`, `dangling_reference`, `containment_cycle`, `acyclic_relation_cycle`, `accepted_edge_to_superseded`, `id_exists`, `unknown_record`, `removed_accepted_record`, `invalid_policy`, `duplicate_policy`, `invalid_waiver`.

Error codes: `invalid_input`, `workspace_not_found`, `incompatible_workspace`, `stale_base`, `validation_failed`, `patch_id_conflict`, `invalid_patch`, `invalid_lens_request`, `unknown_record`, `unknown_kind`, `corrupt_snapshot`, `lock_timeout`, `not_supported`, `git_unavailable`, `git_failed`, `invalid_impact_request`, `unknown_scope`, `unknown_policy`, `scope_not_ready`, `invalid_approval`, `no_migration_path`, `internal_error`.

## Workspace layout

| Path | Role | In Git |
| --- | --- | --- |
| `.intentgraph/project.json` | identity, versions, roots, `compat_unknown_kinds` | yes |
| `.intentgraph/model.json` | canonical snapshot | yes |
| `.intentgraph/vocabulary/*.json` | project extensions (`{"namespace": "x", "kinds": [...], "relations": [...]}`) | yes |
| `.intentgraph/agent-guide.md` | agent entry instructions | yes |
| `.intentgraph/artifacts/` | referenced reports, diagrams, evidence | yes (modest) |
| `.intentgraph/cache/` | disposable | no |
| `.intentgraph/locks/` | transient | no |
