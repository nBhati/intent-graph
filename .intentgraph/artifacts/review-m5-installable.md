# Review: Milestone 5: publish and validate the installable Python CLI

Scope `scope:m5-installable` · policy `policy:default-readiness@0.1` · model revision 24 · readiness **needs_work**

Design digest: `sha256:cdf8ee1ae8691a89c2e9b55d78d9a08cf6ef121a841be4628d4a7e3d43ad4c17`

## What are we trying to achieve?

_Goals and the requirements in scope._

- **The tool reports what it supports and what it does not, in machine-readable form** `req:capabilities-documented` (Requirement)
  - priority: must
- **A clean isolated install of the built wheel can initialize, persist, restart, query, patch, evaluate readiness, import evidence and reconcile** `req:clean-install-validated` (Requirement)
  - priority: must
- **Initialization is idempotent and never overwrites an existing project or unrelated agent instructions** `req:init-idempotent-non-destructive` (Requirement)
  - priority: must
- **The Python package published to PyPI is the primary installation route, with one intentgraph command** `req:pypi-package-primary` (Requirement)
  - priority: must
- **A corrupt snapshot can be recovered from a tool backup or a Git revision, previewed before applied** `req:recovery-from-backup-or-git` (Requirement)
  - priority: must
- **Review packets include a component diagram where the scope has structure to show** `req:review-diagram` (Requirement)
  - priority: should
- **Machine-readable responses carry a response version and change only additively within it** `req:stable-machine-responses` (Requirement)
  - priority: must
- **Removing the executable does not remove project models or evidence** `req:uninstall-preserves-project` (Requirement)
  - priority: must
- **Reinstalling or upgrading the tool preserves project files; migrations stay explicit** `req:upgrade-preserves-project` (Requirement)
  - priority: must
- **Worked examples cover refinement, an ambiguous requirement, stale evidence, a counterexample and an unsupported analysis, and are kept executable** `req:worked-examples-executable` (Requirement)
  - priority: must

## What will the user experience?

_Scenarios and experience elements._

(nothing in scope)


## How will the main parts cooperate?

_Structure, contracts and behavior._

- **Intent Graph package** `system:intentgraph` (System)
- **checks** `component:checks` (Component)
- **cli** `component:cli` (Component)
- **graph** `component:graph` (Component)
- **lenses** `component:lenses` (Component)
- **model** `component:model` (Component)
- **obligations** `component:obligations` (Component)
- **patches** `component:patches` (Component)
- **playbooks** `component:playbooks` (Component)
- **reports** `component:reports` (Component)
- **repository** `component:repository` (Component)
- **services** `component:services` (Component)
- **vocabulary** `component:vocabulary` (Component)
- **Report supported and unsupported capabilities with versions** `operation:capabilities` (Operation)
  - failures: []
  - inputs: {}
  - outputs: {'supported': 'list', 'unsupported': 'list with reason', 'versions': 'tool, format, vocabulary, response'}
- **Preview or apply recovery of the snapshot from a backup or Git revision** `operation:recover` (Operation)
  - failures: ['no_recovery_source', 'corrupt_snapshot', 'git_unavailable']
  - inputs: {'apply': 'boolean', 'from_backup': 'path', 'from_git': 'ref'}
  - outputs: {'content_digest': 'sha256', 'damaged_copy': 'path', 'revision': 'int', 'source': 'backup|git'}

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
- **CLI first; MCP optional and later** `decision:cli-first` (Decision)
  - rationale: Existing coding agents can invoke terminal commands; both interfaces must share application services.
- **Evidence freshness is computed once and shared by reconcile and the evidence_required rule** `decision:freshness-in-engine` (Decision)
  - decision_kind: choice
  - rationale: Conformance must not count stale evidence; one implementation avoids two answers.
- **Each relation declares its impact direction in the vocabulary** `decision:impact-direction-per-relation` (Decision) _(proposed)_
  - rationale: Keeps impact semantics in the versioned registry (data), not in Python branches; extensions can declare their own.
- **Policies are declarative rule records in the snapshot, evaluated by built-in rule types** `decision:policy-rules-declarative` (Decision)
  - decision_kind: choice
  - rationale: Keeps policy as versioned data that cannot execute code; new rule types are tool changes, not policy edits.
- **PyInstaller one-file bundles per platform, built in CI on native runners** `decision:pyinstaller-onefile` (Decision) _(superseded)_
  - decision_kind: choice
  - rationale: Mature, no code changes needed, data files bundled via add-data; cross-compilation is not attempted.
- **Python package; Pydantic records; NetworkX in memory as an index only** `decision:python-networkx-pydantic` (Decision)
  - rationale: Simple local implementation; typed records stay independent of the graph library so storage details do not define semantics.
- **The CLI envelope carries response_version; additive changes keep it, breaking changes bump it** `decision:response-version-field` (Decision)
  - decision_kind: choice
  - rationale: Agents and CI parse the envelope; a version field lets them detect incompatibility without guessing.
- **Scope closure = explicit members, their structural children, realized requirements, applicable constraints, global constraints, and concerning questions, decisions and assumptions** `decision:scope-closure-rule` (Decision)
  - decision_kind: choice
  - rationale: Deterministic and explainable; every closure member records why it is included. Shared containers do not propagate realized requirements, so one component serving two features does not merge their scopes.
- **Seed, progressive self-use, then external A/B evaluation** `decision:self-use-development` (Decision)
  - rationale: A capability cannot be mandatory for building its first implementation; record limitations rather than fabricate checks.
- **One canonical snapshot with transactions inside it; no daemon** `decision:single-snapshot-v0` (Decision)
  - rationale: Atomic writes and straightforward recovery before sharding; graph state and transaction accounting cannot diverge.
- **Workspace snapshots are WorkspaceSnapshot nodes in the observation layer holding digests for declared paths only** `decision:snapshot-as-node` (Decision)
  - decision_kind: choice
  - rationale: Keeps evidence inputs inspectable and versioned with the model without hashing the whole repository.
- **Distribute as a PyPI package; recommend uv tool install, offer pipx; defer standalone executables** `decision:uv-tool-install` (Decision)
  - decision_kind: choice
  - rationale: uv installs CLI tools in isolated environments and obtains a Python runtime automatically; an executable or npm-first distribution would add another packaging layer to the Python core.

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
- **Does a single snapshot remain practical at the first target project size?** `question:single-snapshot-scale` (Question)
  - blocking: False
  - status: open

## Component diagram

_Structure and dependencies among in-scope parts; derived from the model, not drawn by hand._

```mermaid
flowchart LR
    n0["checks"]
    n1["cli"]
    n2["graph"]
    n3["lenses"]
    n4["model"]
    n5["obligations"]
    n6["patches"]
    n7["playbooks"]
    n8["reports"]
    n9["repository"]
    n10["services"]
    n11["vocabulary"]
    n12["Intent Graph package"]
    n0 -->|depends_on (build)| n2
    n0 -->|depends_on (build)| n11
    n1 -->|depends_on (build)| n10
    n2 -->|depends_on (build)| n4
    n3 -->|depends_on (build)| n2
    n5 -->|depends_on (build)| n0
    n6 -->|depends_on (build)| n0
    n8 -->|depends_on (build)| n3
    n9 -->|depends_on (build)| n4
    n9 -->|depends_on (build)| n11
    n10 -->|depends_on (build)| n0
    n10 -->|depends_on (build)| n3
    n10 -->|depends_on (build)| n6
    n10 -->|depends_on (build)| n9
    n12 -->|contains| n0
    n12 -->|contains| n1
    n12 -->|contains| n2
    n12 -->|contains| n3
    n12 -->|contains| n4
    n12 -->|contains| n5
    n12 -->|contains| n6
    n12 -->|contains| n7
    n12 -->|contains| n8
    n12 -->|contains| n9
    n12 -->|contains| n10
    n12 -->|contains| n11
```

## Exclusions and deferrals

None recorded.

## Explanation

_No explanation written yet. The coding agent may add one; it is a judgment, not a computed check._

## Coverage

43 intent records of 43 closure members are listed above. Ids: `component:checks`, `component:cli`, `component:graph`, `component:lenses`, `component:model`, `component:obligations`, `component:patches`, `component:playbooks`, `component:reports`, `component:repository`, `component:services`, `component:vocabulary`, `constraint:no-hidden-state-between-calls`, `constraint:records-are-data`, `decision:agent-runs-language-tools`, `decision:cli-first`, `decision:freshness-in-engine`, `decision:impact-direction-per-relation`, `decision:policy-rules-declarative`, `decision:pyinstaller-onefile`, `decision:python-networkx-pydantic`, `decision:response-version-field`, `decision:scope-closure-rule`, `decision:self-use-development`, `decision:single-snapshot-v0`, `decision:snapshot-as-node`, `decision:uv-tool-install`, `operation:capabilities`, `operation:recover`, `question:default-mandatory-rules`, `question:readiness-default-obligations`, `question:single-snapshot-scale`, `req:capabilities-documented`, `req:clean-install-validated`, `req:init-idempotent-non-destructive`, `req:pypi-package-primary`, `req:recovery-from-backup-or-git`, `req:review-diagram`, `req:stable-machine-responses`, `req:uninstall-preserves-project`, `req:upgrade-preserves-project`, `req:worked-examples-executable`, `system:intentgraph`
