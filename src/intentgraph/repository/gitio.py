"""Git integration for historical baselines (architecture section 21.2: Git is a
workspace integration, not the canonical model store). Reports clearly when
Git is unavailable."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from pydantic import ValidationError

from ..errors import CorruptSnapshot, NotSupported
from ..model import Snapshot
from .layout import WorkspacePaths


def _git(root: Path, *args: str) -> str:
    exe = shutil.which("git")
    if exe is None:
        raise NotSupported("git executable not found; historical diffs need Git or a snapshot file", code="git_unavailable")
    proc = subprocess.run([exe, "-C", str(root), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise NotSupported(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()}", code="git_failed", details={"args": list(args)})
    return proc.stdout


def snapshot_at_ref(paths: WorkspacePaths, ref: str) -> Snapshot:
    """Load the model file as it was at a Git revision. The digest is verified
    so a snapshot that was hand-edited in history is still detected."""
    toplevel = Path(_git(paths.root, "rev-parse", "--show-toplevel").strip())
    rel = paths.model.resolve().relative_to(toplevel.resolve()).as_posix()
    raw = _git(paths.root, "show", f"{ref}:{rel}")
    try:
        snapshot = Snapshot.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise CorruptSnapshot(f"model at {ref} is not a valid snapshot: {exc}") from exc
    from ..model import compute_digest

    if snapshot.content_digest != compute_digest(snapshot):
        raise CorruptSnapshot(f"model at {ref} has a digest that does not match its content", details={"ref": ref})
    return snapshot
