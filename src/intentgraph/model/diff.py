"""Record-level differences between two snapshots (milestone 2).

Two sources of difference are offered because v0 keeps only the current
snapshot in the workspace:

* ``changes_since`` uses the transaction summaries inside the snapshot and is
  exact about *which ids* changed since a revision and by which patch.
* ``diff_snapshots`` compares two full snapshots (for example the current file
  against a Git revision) and reports field-level changes.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_dumps
from .records import Record, Snapshot


class RecordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    record_type: str  # node | edge
    fields_changed: list[str] = Field(default_factory=list)
    properties_changed: list[str] = Field(default_factory=list)
    lifecycle: list[str] | None = None  # [old, new] when it changed


class RecordSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    record_type: str
    label: str
    layer: str
    lifecycle: str


class SnapshotDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_revision: int
    to_revision: int
    from_digest: str
    to_digest: str
    same_project: bool
    added: list[RecordSummary]
    removed: list[RecordSummary]
    changed: list[RecordChange]
    transactions_between: list[dict[str, Any]]
    summary: dict[str, int]


def _summary(rec: Record, rtype: str) -> RecordSummary:
    return RecordSummary(id=rec.id, kind=rec.kind, record_type=rtype, label=rec.label, layer=rec.layer, lifecycle=rec.lifecycle)


def _records(snapshot: Snapshot) -> dict[str, tuple[Record, str]]:
    out: dict[str, tuple[Record, str]] = {}
    for n in snapshot.nodes:
        out[n.id] = (n, "node")
    for e in snapshot.edges:
        out[e.id] = (e, "edge")
    return out


def diff_snapshots(old: Snapshot, new: Snapshot) -> SnapshotDiff:
    a, b = _records(old), _records(new)
    added = [_summary(*b[i]) for i in sorted(set(b) - set(a))]
    removed = [_summary(*a[i]) for i in sorted(set(a) - set(b))]
    changed: list[RecordChange] = []
    for rid in sorted(set(a) & set(b)):
        ra, ta = a[rid]
        rb, tb = b[rid]
        da, db = ra.model_dump(mode="json"), rb.model_dump(mode="json")
        if canonical_dumps(da) == canonical_dumps(db):
            continue
        fields = [k for k in sorted(set(da) | set(db)) if canonical_dumps(da.get(k)) != canonical_dumps(db.get(k))]
        pa, pb = da.get("properties", {}), db.get("properties", {})
        props = [k for k in sorted(set(pa) | set(pb)) if canonical_dumps(pa.get(k)) != canonical_dumps(pb.get(k))]
        changed.append(RecordChange(
            id=rid, kind=rb.kind, record_type=tb if ta == tb else f"{ta}->{tb}", fields_changed=fields, properties_changed=props,
            lifecycle=[ra.lifecycle, rb.lifecycle] if ra.lifecycle != rb.lifecycle else None,
        ))
    between = [t.model_dump(mode="json") for t in new.transactions if t.result_revision > old.revision] if new.project_id == old.project_id else []
    return SnapshotDiff(
        from_revision=old.revision, to_revision=new.revision, from_digest=old.content_digest, to_digest=new.content_digest,
        same_project=old.project_id == new.project_id, added=added, removed=removed, changed=changed, transactions_between=between,
        summary={"added": len(added), "removed": len(removed), "changed": len(changed)},
    )


def changes_since(snapshot: Snapshot, revision: int) -> dict[str, Any]:
    """Ids changed after ``revision`` according to the transaction summaries."""
    if revision > snapshot.revision:
        raise ValueError(f"revision {revision} is newer than the current revision {snapshot.revision}")
    txs = [t for t in snapshot.transactions if t.result_revision > revision]
    added: dict[str, str] = {}
    updated: dict[str, str] = {}
    removed: dict[str, str] = {}
    for t in txs:
        for i in t.added_ids:
            added[i] = t.patch_id
        for i in t.updated_ids:
            updated.setdefault(i, t.patch_id)
        for i in t.removed_ids:
            removed[i] = t.patch_id
            added.pop(i, None)
            updated.pop(i, None)
    current = {r.id for r in snapshot.nodes} | {r.id for r in snapshot.edges}
    return {
        "from_revision": revision, "to_revision": snapshot.revision, "to_digest": snapshot.content_digest,
        "transactions": [t.model_dump(mode="json") for t in txs],
        "added_ids": sorted(i for i in added if i in current),
        "updated_ids": sorted(i for i in updated if i in current and i not in added),
        "removed_ids": sorted(removed),
        "summary": {"added": len([i for i in added if i in current]), "updated": len([i for i in updated if i in current and i not in added]), "removed": len(removed)},
    }
