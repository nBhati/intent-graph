"""Application services: the single place where commands are implemented.

The CLI (and any later MCP server) calls these functions and formats their
dict results. Each call resolves the workspace, loads manifest and snapshot,
verifies the digest, validates records, performs its operation, and returns.
No memory is carried between calls (architecture section 8.4).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import CORE_VOCABULARY_VERSION, FORMAT_VERSION, TOOL_VERSION
from .checks import Diagnostic, has_blocking, validate_snapshot
from .errors import InvalidInput, ValidationFailed
from .graph import build_index
from .lenses import LensRequest, compute_lens, search_records
from .lenses.impact import ImpactRequest, compute_impact
from .model.diff import changes_since, diff_snapshots
from .model import Snapshot
from .patches import Patch, apply_patch, validate_patch
from .playbooks import POINTER_BEGIN, POINTER_END, agent_guide_text, pointer_text
from .repository import Repository
from .repository.store import atomic_write_text, utc_now
from .vocabulary import Vocabulary

AGENT_INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", ".cursorrules", "GEMINI.md")


class Context:
    """Everything one invocation needs, loaded fresh."""

    def __init__(self, repo: Repository):
        self.repo = repo
        self.manifest = repo.load_manifest()
        self.vocabulary: Vocabulary = repo.load_vocabulary()
        self.snapshot: Snapshot = repo.load_snapshot()

    @classmethod
    def open(cls, start: Path | None = None) -> "Context":
        return cls(Repository.find(start))

    def diagnostics(self) -> list[Diagnostic]:
        return validate_snapshot(self.snapshot, self.vocabulary, compat_unknown_kinds=self.manifest.compat_unknown_kinds)


def _diag_list(diags: list[Diagnostic]) -> list[dict[str, Any]]:
    return [d.model_dump(mode="json") for d in diags]


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def init_workspace(root: Path, *, name: str | None = None, project_id: str | None = None, pointer: bool = True) -> dict[str, Any]:
    repo, created = Repository.init(root, name=name, project_id=project_id)
    guide_written = False
    if not repo.paths.agent_guide.exists():
        atomic_write_text(repo.paths.agent_guide, agent_guide_text())
        guide_written = True
    pointer_result = _install_pointer(repo.paths.root) if pointer else {"status": "skipped"}
    manifest = repo.load_manifest()
    return {
        "created": created,
        "workspace": str(repo.paths.dir),
        "project_id": manifest.project_id,
        "format_version": manifest.format_version,
        "vocabulary_version": manifest.vocabulary_version,
        "agent_guide": str(repo.paths.agent_guide),
        "agent_guide_written": guide_written,
        "pointer": pointer_result,
    }


def _install_pointer(root: Path) -> dict[str, Any]:
    """Add a short pointer to the workspace's existing agent instruction file,
    preserving unrelated content. Idempotent via begin/end markers."""
    target = next((root / n for n in AGENT_INSTRUCTION_FILES if (root / n).is_file()), None)
    created = False
    if target is None:
        target = root / "AGENTS.md"
        created = True
    existing = target.read_text(encoding="utf-8") if target.is_file() else ""
    if POINTER_BEGIN in existing and POINTER_END in existing:
        return {"status": "present", "file": str(target)}
    text = pointer_text()
    new = text if not existing else existing.rstrip("\n") + "\n\n" + text
    atomic_write_text(target, new)
    return {"status": "created" if created else "appended", "file": str(target)}


# ---------------------------------------------------------------------------
# status / check / rebuild
# ---------------------------------------------------------------------------

def status(ctx: Context) -> dict[str, Any]:
    snap = ctx.snapshot
    diags = ctx.diagnostics()
    kinds = Counter(n.kind for n in snap.nodes)
    layers = Counter(r.layer for r in list(snap.nodes) + list(snap.edges))
    lifecycles = Counter(r.lifecycle for r in list(snap.nodes) + list(snap.edges))
    open_questions = [n.id for n in snap.nodes if n.kind == "Question" and n.properties.get("status") == "open"]
    blocking_questions = [n.id for n in snap.nodes if n.kind == "Question" and n.properties.get("status") == "open" and n.properties.get("blocking") is True]
    pending_obligations = [n.id for n in snap.nodes if n.kind == "Obligation" and n.properties.get("state") in ("pending", "failed", "blocked")]
    open_findings = [n.id for n in snap.nodes if n.kind == "Finding" and n.properties.get("state") == "open"]
    last = snap.transactions[-1].model_dump(mode="json") if snap.transactions else None
    return {
        "project_id": snap.project_id,
        "name": ctx.manifest.name,
        "workspace": str(ctx.repo.paths.dir),
        "revision": snap.revision,
        "content_digest": snap.content_digest,
        "format_version": snap.format_version,
        "vocabulary_version": snap.vocabulary_version,
        "vocabulary_extensions": ctx.vocabulary.extension_sources,
        "counts": {"nodes": len(snap.nodes), "edges": len(snap.edges), "by_kind": dict(sorted(kinds.items())), "by_layer": dict(sorted(layers.items())), "by_lifecycle": dict(sorted(lifecycles.items()))},
        "outstanding": {
            "open_questions": open_questions,
            "blocking_questions": blocking_questions,
            "pending_obligations": pending_obligations,
            "open_findings": open_findings,
            "proposed_records": sum(1 for r in list(snap.nodes) + list(snap.edges) if r.lifecycle == "proposed"),
        },
        "gates": {"status": "unsupported", "reason": "readiness policies and scoped gates are not implemented yet (milestone 3); review outstanding work manually"},
        "last_transaction": last,
        "structural": {"errors": sum(1 for d in diags if d.severity == "error"), "warnings": sum(1 for d in diags if d.severity == "warning")},
        "diagnostics": _diag_list(diags),
    }


def check(ctx: Context) -> dict[str, Any]:
    diags = ctx.diagnostics()
    return {
        "revision": ctx.snapshot.revision,
        "content_digest": ctx.snapshot.content_digest,
        "blocking": has_blocking(diags),
        "errors": sum(1 for d in diags if d.severity == "error"),
        "warnings": sum(1 for d in diags if d.severity == "warning"),
        "diagnostics": _diag_list(diags),
    }


def rebuild(ctx_start: Path | None = None) -> dict[str, Any]:
    repo = Repository.find(ctx_start)
    cleared = repo.clear_cache()
    ctx = Context(repo)
    index = build_index(ctx.snapshot, ctx.vocabulary)
    diags = ctx.diagnostics()
    unresolved = sorted({d.record_ids[-1] for d in diags if d.code in ("missing_endpoint", "dangling_reference") and d.record_ids})
    return {
        "revision": ctx.snapshot.revision,
        "content_digest": ctx.snapshot.content_digest,
        "cache_entries_cleared": cleared,
        "graph": {"nodes": index.graph.number_of_nodes(), "edges": index.graph.number_of_edges()},
        "unresolved_references": unresolved,
        "blocking": has_blocking(diags),
        "diagnostics": _diag_list(diags),
    }


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------

def vocabulary_show(ctx: Context, name: str) -> dict[str, Any]:
    if name in ctx.vocabulary.kinds:
        return {"type": "kind", "definition": ctx.vocabulary.describe_kind(name)}
    if name in ctx.vocabulary.relations:
        return {"type": "relation", "definition": ctx.vocabulary.describe_relation(name)}
    raise InvalidInput(f"unknown vocabulary name {name!r}", code="unknown_kind", details={"name": name})


def vocabulary_list(ctx: Context) -> dict[str, Any]:
    v = ctx.vocabulary
    return {
        "version": v.version,
        "extensions": v.extension_sources,
        "kinds": [{"name": k.name, "family": k.family, "layers": k.layers, "description": k.description} for k in v.kinds.values()],
        "relations": [{"name": r.name, "layers": r.layers, "direction": r.direction, "acyclic": r.acyclic, "description": r.description} for r in v.relations.values()],
    }


# ---------------------------------------------------------------------------
# view / search
# ---------------------------------------------------------------------------

def view(ctx: Context, request: dict[str, Any]) -> dict[str, Any]:
    try:
        req = LensRequest.model_validate(request)
    except ValidationError as exc:
        raise InvalidInput(f"invalid lens request: {exc.error_count()} error(s)", code="invalid_lens_request", details={"errors": json.loads(exc.json())}) from exc
    index = build_index(ctx.snapshot, ctx.vocabulary)
    return compute_lens(index, ctx.vocabulary, req).model_dump(mode="json")


def search(ctx: Context, **filters: Any) -> dict[str, Any]:
    hits = search_records(ctx.snapshot, **filters)
    return {"revision": ctx.snapshot.revision, "count": len(hits), "records": hits}


def impact(ctx: Context, request: dict[str, Any]) -> dict[str, Any]:
    try:
        req = ImpactRequest.model_validate(request)
    except ValidationError as exc:
        raise InvalidInput(f"invalid impact request: {exc.error_count()} error(s)", code="invalid_impact_request", details={"errors": json.loads(exc.json())}) from exc
    index = build_index(ctx.snapshot, ctx.vocabulary)
    return compute_impact(index, ctx.vocabulary, req).model_dump(mode="json")


def diff(ctx: Context, *, since: int | None = None, file: Path | None = None, git_ref: str | None = None) -> dict[str, Any]:
    """Exactly one of ``since`` (transaction-based), ``file`` (another snapshot) or ``git_ref`` (historical model)."""
    chosen = [x for x in (since, file, git_ref) if x is not None]
    if len(chosen) != 1:
        raise InvalidInput("diff needs exactly one of --since REVISION, --file SNAPSHOT or --git REF", code="invalid_input")
    if since is not None:
        try:
            data = changes_since(ctx.snapshot, since)
        except ValueError as exc:
            raise InvalidInput(str(exc), code="invalid_input") from exc
        return {"mode": "transactions", **data}
    if file is not None:
        from .repository.store import load_snapshot_file

        old = load_snapshot_file(Path(file))
        return {"mode": "file", "baseline": str(file), **diff_snapshots(old, ctx.snapshot).model_dump(mode="json")}
    from .repository.gitio import snapshot_at_ref

    old = snapshot_at_ref(ctx.repo.paths, git_ref)  # type: ignore[arg-type]
    return {"mode": "git", "baseline": git_ref, **diff_snapshots(old, ctx.snapshot).model_dump(mode="json")}


def show_record(ctx: Context, record_id: str) -> dict[str, Any]:
    rec = ctx.snapshot.get(record_id)
    if rec is None:
        raise InvalidInput(f"record {record_id!r} not found", code="unknown_record", details={"id": record_id})
    index = build_index(ctx.snapshot, ctx.vocabulary)
    return {
        "record": rec.model_dump(mode="json"),
        "outgoing": [e.model_dump(mode="json") for e in index.out_edges(record_id)],
        "incoming": [e.model_dump(mode="json") for e in index.in_edges(record_id)],
        "referenced_by": [{"id": r, "property": p} for r, p in index.referenced_by.get(record_id, [])],
    }


# ---------------------------------------------------------------------------
# patches
# ---------------------------------------------------------------------------

def load_patch(data: dict[str, Any]) -> Patch:
    try:
        return Patch.model_validate(data)
    except ValidationError as exc:
        raise InvalidInput(f"invalid patch: {exc.error_count()} error(s)", code="invalid_patch", details={"errors": json.loads(exc.json())}) from exc


def patch_validate(ctx: Context, patch: Patch) -> dict[str, Any]:
    result = validate_patch(ctx.snapshot, patch, ctx.vocabulary, compat_unknown_kinds=ctx.manifest.compat_unknown_kinds)
    return {
        "patch_id": patch.patch_id,
        "valid": result.valid,
        "idempotent_replay": result.idempotent_replay,
        "base_revision": ctx.snapshot.revision,
        "effects": result.effects(),
        "diagnostics": _diag_list(result.diagnostics),
    }


def patch_apply(repo: Repository, patch: Patch) -> dict[str, Any]:
    """Apply under the exclusive write lock, re-reading the snapshot first."""
    with repo.write_lock():
        ctx = Context(repo)
        result = apply_patch(ctx.snapshot, patch, ctx.vocabulary, applied_at=utc_now(), compat_unknown_kinds=ctx.manifest.compat_unknown_kinds)
        if result.idempotent_replay:
            assert result.transaction is not None
            return {
                "patch_id": patch.patch_id, "applied": True, "idempotent_replay": True,
                "revision": result.transaction.result_revision, "content_digest": ctx.snapshot.content_digest,
                "effects": result.effects(), "diagnostics": [],
            }
        if not result.valid:
            raise ValidationFailed(
                f"patch {patch.patch_id!r} rejected: candidate model has {sum(1 for d in result.diagnostics if d.severity == 'error')} error(s)",
                details={"diagnostics": _diag_list(result.diagnostics), "effects": result.effects()},
            )
        repo.write_snapshot(result.snapshot)
    return {
        "patch_id": patch.patch_id, "applied": True, "idempotent_replay": False,
        "revision": result.snapshot.revision, "content_digest": result.snapshot.content_digest,
        "effects": result.effects(), "diagnostics": _diag_list(result.diagnostics),
    }


def tool_info() -> dict[str, Any]:
    return {"tool_version": TOOL_VERSION, "format_version": FORMAT_VERSION, "core_vocabulary_version": CORE_VOCABULARY_VERSION}
