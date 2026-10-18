"""Repository: workspace discovery, initialization, snapshot load/save.

Guarantees (architecture sections 9.2 to 9.4):
  * A snapshot file always carries a digest that matches its content.
  * Writes go to a temporary file in the same directory, are flushed, and
    atomically replace the canonical file. An interrupted write leaves the
    previous readable snapshot in place.
  * Mutations happen under an exclusive write lock after re-reading the
    current snapshot, so revision checks are not racy.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from .. import CORE_VOCABULARY_VERSION, FORMAT_VERSION, TOOL_VERSION
from ..errors import CorruptSnapshot, IncompatibleWorkspace, InvalidInput, WorkspaceNotFound
from ..model import Snapshot, compute_digest, serialize_snapshot
from ..vocabulary import Vocabulary, load_core_vocabulary
from .layout import WorkspacePaths
from .lock import exclusive_lock
from .manifest import ProjectManifest

SUPPORTED_FORMAT_VERSIONS = {FORMAT_VERSION}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file in same dir + fsync + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".tmp-", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, _default_mode())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _default_mode() -> int:
    """0o666 masked by the process umask (mkstemp creates 0o600 files)."""
    current = os.umask(0)
    os.umask(current)
    return 0o666 & ~current


def _fsync_dir(directory: Path) -> None:
    if os.name == "nt":  # pragma: no cover
        return
    try:
        dfd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)


class Repository:
    def __init__(self, paths: WorkspacePaths):
        self.paths = paths

    # ---- discovery / creation -------------------------------------------
    @classmethod
    def find(cls, start: Path | None = None) -> "Repository":
        start = Path(start) if start is not None else Path.cwd()
        paths = WorkspacePaths.find(start)
        if paths is None:
            raise WorkspaceNotFound(f"no .intentgraph workspace found at or above {start}", details={"start": str(start)})
        return cls(paths)

    @classmethod
    def init(cls, root: Path, name: str | None = None, project_id: str | None = None) -> tuple["Repository", bool]:
        """Create a workspace. Idempotent: returns ``(repo, created)``. Refuses to
        overwrite an existing incompatible project."""
        root = root.resolve()
        paths = WorkspacePaths(root)
        repo = cls(paths)
        if paths.project.is_file():
            repo.load_manifest()  # raises if incompatible
            if not paths.model.is_file():
                raise IncompatibleWorkspace(f"{paths.project} exists but {paths.model} is missing; restore it from version control", details={"project": str(paths.project)})
            repo.load_snapshot()  # raises if corrupt
            return repo, False
        name = name or root.name
        pid = project_id or f"project:{_slug(name)}"
        if ":" not in pid:
            pid = f"project:{_slug(pid)}"
        paths.dir.mkdir(parents=True, exist_ok=True)
        for sub in (paths.vocabulary, paths.artifacts, paths.cache, paths.locks):
            sub.mkdir(exist_ok=True)
        (paths.cache / ".gitignore").write_text("*\n", encoding="utf-8")
        (paths.locks / ".gitignore").write_text("*\n", encoding="utf-8")
        manifest = ProjectManifest(
            project_id=pid,
            name=name,
            format_version=FORMAT_VERSION,
            vocabulary_version=CORE_VOCABULARY_VERSION,
            created_at=utc_now(),
            created_by_tool_version=TOOL_VERSION,
        )
        snapshot = Snapshot(vocabulary_version=CORE_VOCABULARY_VERSION, project_id=pid, revision=0)
        # Write the model first, then the manifest: the manifest's presence marks a complete workspace.
        repo.write_snapshot(snapshot)
        atomic_write_text(paths.project, json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")
        return repo, True

    # ---- manifest ----------------------------------------------------------
    def load_manifest(self) -> ProjectManifest:
        try:
            data = json.loads(self.paths.project.read_text(encoding="utf-8"))
            manifest = ProjectManifest.model_validate(data)
        except (OSError, ValueError, ValidationError) as exc:
            raise IncompatibleWorkspace(f"cannot read project manifest {self.paths.project}: {exc}") from exc
        if manifest.format_version not in SUPPORTED_FORMAT_VERSIONS:
            raise IncompatibleWorkspace(
                f"project format {manifest.format_version!r} is not supported by tool {TOOL_VERSION} (supported: {sorted(SUPPORTED_FORMAT_VERSIONS)}); an explicit migration is required",
                details={"format_version": manifest.format_version},
            )
        return manifest

    def load_vocabulary(self) -> Vocabulary:
        vocab = load_core_vocabulary()
        vocab.load_extensions(self.paths.vocabulary)
        return vocab

    # ---- snapshot ------------------------------------------------------------
    def load_snapshot(self, *, verify_digest: bool = True) -> Snapshot:
        try:
            raw = self.paths.model.read_text(encoding="utf-8")
        except OSError as exc:
            raise CorruptSnapshot(f"cannot read snapshot {self.paths.model}: {exc}") from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise CorruptSnapshot(f"snapshot {self.paths.model} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise CorruptSnapshot("snapshot must be a JSON object")
        fmt = data.get("format_version")
        if fmt not in SUPPORTED_FORMAT_VERSIONS:
            raise IncompatibleWorkspace(f"snapshot format {fmt!r} is not supported by tool {TOOL_VERSION}; an explicit migration is required", details={"format_version": fmt})
        try:
            snapshot = Snapshot.model_validate(data)
        except ValidationError as exc:
            raise CorruptSnapshot(f"snapshot records do not match the record envelope: {exc.error_count()} error(s)", details={"errors": json.loads(exc.json())[:20]}) from exc
        if verify_digest:
            expected = compute_digest(snapshot)
            if snapshot.content_digest != expected:
                raise CorruptSnapshot(
                    "snapshot content digest does not match its content; the file was edited outside the tool or is partially written",
                    details={"stored": snapshot.content_digest, "computed": expected},
                )
        return snapshot

    def write_snapshot(self, snapshot: Snapshot) -> Snapshot:
        """Serialize canonically (recomputing the digest) and atomically replace the file."""
        snapshot.content_digest = compute_digest(snapshot)
        atomic_write_text(self.paths.model, serialize_snapshot(snapshot))
        return snapshot

    @contextmanager
    def write_lock(self, timeout: float = 10.0) -> Iterator[None]:
        with exclusive_lock(self.paths.write_lock, timeout=timeout):
            yield

    def clear_cache(self) -> int:
        if not self.paths.cache.is_dir():
            return 0
        removed = 0
        for child in self.paths.cache.iterdir():
            if child.name == ".gitignore":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1
        return removed


def _slug(text: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    if not out or not out[0].isalpha():
        out = "p-" + out
    return out
