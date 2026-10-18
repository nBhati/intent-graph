"""Patch application (architecture sections 9.4 and 12.1).

``apply_patch`` is pure: it takes the current snapshot and returns a candidate
snapshot plus diagnostics. Persisting the candidate under the write lock is
the repository's job (see ``intentgraph.services``).

Rules:
  * The patch's base revision and digest must match the current snapshot.
    On a stale base, the IDs changed since that base are returned; the agent's
    interpretation is never silently rebased.
  * A repeated patch ID with identical operations is idempotent and returns
    the earlier result. The same ID with different content is an error.
  * The candidate must pass structural validation; otherwise nothing is applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..checks import Diagnostic, has_blocking, validate_snapshot
from ..errors import InvalidInput, StaleBase
from ..model import Snapshot, TransactionRecord, digest_of
from ..vocabulary import Vocabulary
from .model import AddAnnotation, AddEdge, AddNode, Patch, Remove, UpdateFields, UpdateProperties


@dataclass
class PatchResult:
    snapshot: Snapshot
    diagnostics: list[Diagnostic]
    added_ids: list[str] = field(default_factory=list)
    updated_ids: list[str] = field(default_factory=list)
    removed_ids: list[str] = field(default_factory=list)
    idempotent_replay: bool = False
    transaction: TransactionRecord | None = None

    @property
    def valid(self) -> bool:
        return not has_blocking(self.diagnostics)

    def effects(self) -> dict[str, Any]:
        return {"added_ids": sorted(self.added_ids), "updated_ids": sorted(self.updated_ids), "removed_ids": sorted(self.removed_ids)}


def operations_digest(patch: Patch) -> str:
    return digest_of([op.model_dump(mode="json") for op in patch.operations])


def changed_ids_since(snapshot: Snapshot, base_revision: int) -> list[str]:
    ids: set[str] = set()
    for t in snapshot.transactions:
        if t.result_revision > base_revision:
            ids.update(t.added_ids, t.updated_ids, t.removed_ids)
    return sorted(ids)


def _check_base(snapshot: Snapshot, patch: Patch) -> TransactionRecord | None:
    """Return a prior transaction for an idempotent replay, raise on stale/conflict, else None."""
    prior = next((t for t in snapshot.transactions if t.patch_id == patch.patch_id), None)
    if prior is not None:
        if prior.operations_digest == operations_digest(patch):
            return prior
        raise InvalidInput(
            f"patch id {patch.patch_id!r} was already applied with different content",
            code="patch_id_conflict",
            details={"patch_id": patch.patch_id, "applied_revision": prior.result_revision},
        )
    if patch.base_revision != snapshot.revision or patch.base_digest != snapshot.content_digest:
        raise StaleBase(
            f"patch base (revision {patch.base_revision}) does not match current snapshot (revision {snapshot.revision})",
            details={
                "base_revision": patch.base_revision,
                "base_digest": patch.base_digest,
                "current_revision": snapshot.revision,
                "current_digest": snapshot.content_digest,
                "changed_ids": changed_ids_since(snapshot, patch.base_revision),
            },
        )
    return None


def _apply_operations(snapshot: Snapshot, patch: Patch) -> PatchResult:
    candidate = snapshot.model_copy(deep=True)
    nodes = {n.id: n for n in candidate.nodes}
    edges = {e.id: e for e in candidate.edges}
    diags: list[Diagnostic] = []
    added: set[str] = set()
    updated: set[str] = set()
    removed: set[str] = set()

    def exists(rid: str) -> bool:
        return rid in nodes or rid in edges

    def record(rid: str):
        return nodes.get(rid) or edges.get(rid)

    for i, op in enumerate(patch.operations):
        where = f"operations[{i}] ({op.op})"
        if isinstance(op, (AddNode, AddEdge)):
            rid = op.record.id
            if exists(rid):
                diags.append(Diagnostic(code="id_exists", severity="error", message=f"{where}: id {rid!r} already exists", record_ids=[rid]))
                continue
            if isinstance(op, AddNode):
                nodes[rid] = op.record
            else:
                edges[rid] = op.record
            added.add(rid)
        elif isinstance(op, UpdateProperties):
            rec = record(op.id)
            if rec is None:
                diags.append(Diagnostic(code="unknown_record", severity="error", message=f"{where}: id {op.id!r} does not exist", record_ids=[op.id]))
                continue
            for key, value in op.changes.items():
                if value is None:
                    rec.properties.pop(key, None)
                else:
                    rec.properties[key] = value
            if op.id not in added:
                updated.add(op.id)
        elif isinstance(op, UpdateFields):
            rec = record(op.id)
            if rec is None:
                diags.append(Diagnostic(code="unknown_record", severity="error", message=f"{where}: id {op.id!r} does not exist", record_ids=[op.id]))
                continue
            for name in ("label", "description", "lifecycle", "provenance", "annotations"):
                value = getattr(op, name)
                if value is not None:
                    setattr(rec, name, value)
            if op.id not in added:
                updated.add(op.id)
        elif isinstance(op, AddAnnotation):
            rec = record(op.id)
            if rec is None:
                diags.append(Diagnostic(code="unknown_record", severity="error", message=f"{where}: id {op.id!r} does not exist", record_ids=[op.id]))
                continue
            rec.annotations.append(op.annotation)
            if op.id not in added:
                updated.add(op.id)
        elif isinstance(op, Remove):
            rec = record(op.id)
            if rec is None:
                diags.append(Diagnostic(code="unknown_record", severity="error", message=f"{where}: id {op.id!r} does not exist", record_ids=[op.id]))
                continue
            if rec.lifecycle == "accepted":
                diags.append(Diagnostic(code="removed_accepted_record", severity="warning", message=f"{where}: removing accepted record {op.id!r}; consider lifecycle 'superseded' to preserve history", record_ids=[op.id]))
            nodes.pop(op.id, None)
            edges.pop(op.id, None)
            if op.id in added:
                added.discard(op.id)
            else:
                removed.add(op.id)
                updated.discard(op.id)

    candidate.nodes = sorted(nodes.values(), key=lambda r: r.id)
    candidate.edges = sorted(edges.values(), key=lambda r: r.id)
    return PatchResult(snapshot=candidate, diagnostics=diags, added_ids=sorted(added), updated_ids=sorted(updated), removed_ids=sorted(removed))


def validate_patch(snapshot: Snapshot, patch: Patch, vocabulary: Vocabulary, *, compat_unknown_kinds: bool = False) -> PatchResult:
    """Compute the candidate and its diagnostics without committing. Raises
    ``StaleBase``/``InvalidInput`` for base or patch-id problems."""
    prior = _check_base(snapshot, patch)
    if prior is not None:
        return PatchResult(snapshot=snapshot, diagnostics=[], added_ids=list(prior.added_ids), updated_ids=list(prior.updated_ids), removed_ids=list(prior.removed_ids), idempotent_replay=True, transaction=prior)
    result = _apply_operations(snapshot, patch)
    if not has_blocking(result.diagnostics):
        result.diagnostics.extend(validate_snapshot(result.snapshot, vocabulary, compat_unknown_kinds=compat_unknown_kinds))
    return result


def apply_patch(snapshot: Snapshot, patch: Patch, vocabulary: Vocabulary, *, applied_at: str, compat_unknown_kinds: bool = False) -> PatchResult:
    """Validate and, if valid, produce the committed candidate (revision + 1,
    transaction appended, digest recomputed). The caller persists it."""
    from ..model import compute_digest

    result = validate_patch(snapshot, patch, vocabulary, compat_unknown_kinds=compat_unknown_kinds)
    if result.idempotent_replay or not result.valid:
        return result
    candidate = result.snapshot
    candidate.revision = snapshot.revision + 1
    transaction = TransactionRecord(
        patch_id=patch.patch_id,
        base_revision=snapshot.revision,
        result_revision=candidate.revision,
        applied_at=applied_at,
        reason=patch.reason,
        operations_digest=operations_digest(patch),
        added_ids=result.added_ids,
        updated_ids=result.updated_ids,
        removed_ids=result.removed_ids,
    )
    candidate.transactions.append(transaction)
    candidate.content_digest = compute_digest(candidate)
    result.transaction = transaction
    return result
