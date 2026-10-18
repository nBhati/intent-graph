"""Recovery of a damaged snapshot (architecture sections 9.3 and 9.5).

Sources: a backup written by ``migrate`` (``artifacts/backup-model-*.json``)
or the model at a Git revision. The damaged file is kept aside under
``artifacts/damaged-model-<timestamp>.json``; recovery writes atomically and
verifies the restored digest. Nothing is changed in preview mode.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import CorruptSnapshot, InvalidInput
from ..model import Snapshot, compute_digest
from .gitio import snapshot_at_ref
from .layout import WorkspacePaths
from .store import atomic_write_text, load_snapshot_file, serialize_snapshot, utc_now


def diagnose(paths: WorkspacePaths) -> dict[str, Any]:
    """Why the current snapshot cannot be used, or ``healthy``."""
    if not paths.model.is_file():
        return {"status": "missing", "detail": f"{paths.model} does not exist"}
    try:
        snap = load_snapshot_file(paths.model)
    except CorruptSnapshot as exc:
        return {"status": "corrupt", "detail": exc.message, "code": exc.code}
    except Exception as exc:  # incompatible format etc.
        return {"status": "unreadable", "detail": str(exc)}
    return {"status": "healthy", "revision": snap.revision, "content_digest": snap.content_digest}


def list_backups(paths: WorkspacePaths) -> list[dict[str, Any]]:
    out = []
    for f in sorted(paths.artifacts.glob("backup-model-*.json")):
        try:
            snap = load_snapshot_file(f)
            out.append({"path": str(f), "revision": snap.revision, "content_digest": snap.content_digest, "vocabulary_version": snap.vocabulary_version, "valid": True})
        except Exception as exc:
            out.append({"path": str(f), "valid": False, "detail": str(exc)})
    return out


def load_source(paths: WorkspacePaths, *, from_backup: Path | None, from_git: str | None) -> tuple[str, Snapshot]:
    if (from_backup is None) == (from_git is None):
        raise InvalidInput("recover needs exactly one of --from-backup PATH or --from-git REF", code="no_recovery_source")
    if from_backup is not None:
        return "backup", load_snapshot_file(Path(from_backup))
    return "git", snapshot_at_ref(paths, from_git)


def recover(paths: WorkspacePaths, *, from_backup: Path | None, from_git: str | None, apply: bool) -> dict[str, Any]:
    before = diagnose(paths)
    source, snap = load_source(paths, from_backup=from_backup, from_git=from_git)
    out: dict[str, Any] = {"current": before, "source": source, "revision": snap.revision, "content_digest": snap.content_digest, "vocabulary_version": snap.vocabulary_version,
                           "applied": False, "damaged_copy": None, "note": "Recovery restores the model file; readiness, approvals and evidence freshness are re-evaluated against the restored content."}
    if before["status"] == "healthy" and before["content_digest"] == snap.content_digest:
        out["note"] = "The current snapshot already matches the recovery source; nothing to do."
        return out
    if not apply:
        return out
    if paths.model.exists():
        damaged = paths.artifacts / f"damaged-model-{utc_now().replace(':', '').replace('-', '')}.json"
        paths.artifacts.mkdir(parents=True, exist_ok=True)
        atomic_write_text(damaged, paths.model.read_text(encoding="utf-8", errors="replace"))
        out["damaged_copy"] = str(damaged)
    snap.content_digest = compute_digest(snap)
    atomic_write_text(paths.model, serialize_snapshot(snap))
    restored = load_snapshot_file(paths.model)
    out["applied"] = True
    out["verified_digest"] = restored.content_digest
    manifest = json.loads(paths.project.read_text(encoding="utf-8"))
    if manifest.get("vocabulary_version") != snap.vocabulary_version:
        manifest["vocabulary_version"] = snap.vocabulary_version
        atomic_write_text(paths.project, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        out["manifest_vocabulary_updated"] = True
    return out
