"""Workspace snapshots (architecture section 16.1).

A snapshot identifies a repository root at capture time: Git HEAD when
available, tracked dirty files, untracked files, and content digests for the
declared paths. A Git commit alone is insufficient when files are modified or
untracked, so both are recorded. Each root has its own snapshot.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .. import TOOL_VERSION
from ..errors import InvalidInput
from ..model import digest_of
from .layout import WorkspacePaths
from .manifest import ProjectManifest

LOCKFILES = ("uv.lock", "poetry.lock", "requirements.txt", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "pubspec.lock", "Cargo.lock", "go.sum")


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def resolve_root(paths: WorkspacePaths, manifest: ProjectManifest, repository: str) -> Path:
    rel = manifest.roots.get(repository)
    if rel is None:
        raise InvalidInput(f"unknown repository root {repository!r}; configured roots: {sorted(manifest.roots)}", code="unknown_root", details={"roots": manifest.roots})
    root = (paths.root / rel).resolve()
    if not root.is_dir():
        raise InvalidInput(f"repository root {repository!r} -> {root} is not a directory", code="unknown_root")
    return root


def _safe_rel(root: Path, rel: str) -> Path | None:
    """Resolve ``rel`` under ``root``; None when it escapes the root."""
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


DEFAULT_IGNORES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".git", ".intentgraph", ".venv", "venv", ".tox", "dist", "build", ".dart_tool"}


def tree_files(root: Path, target: Path) -> list[Path]:
    """Files under ``target`` that count as source: Git-tracked plus untracked-but-not-ignored
    when Git is available, otherwise everything except well-known caches and build outputs."""
    rel = target.relative_to(root).as_posix()
    listing = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", rel)
    if listing is not None:
        return sorted(root / name for name in listing.split("\0") if name and (root / name).is_file())
    out = []
    for p in target.rglob("*"):
        if p.is_file() and not any(part in DEFAULT_IGNORES or part.endswith(".pyc") for part in p.relative_to(root).parts):
            out.append(p)
    return sorted(out)


def tree_digest(root: Path, target: Path) -> str:
    return digest_of([f"{p.relative_to(target).as_posix()}={file_digest(p)}" for p in tree_files(root, target)])


def _git(root: Path, *args: str) -> str | None:
    exe = shutil.which("git")
    if exe is None:
        return None
    proc = subprocess.run([exe, "-C", str(root), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return proc.stdout


def git_state(root: Path) -> dict[str, Any]:
    """HEAD, tracked dirty files and untracked files, or ``git_available: False``."""
    head = _git(root, "rev-parse", "HEAD")
    if head is None:
        return {"git_available": False, "head": "", "tracked_dirty": [], "untracked": [], "dirty": False}
    status = _git(root, "status", "--porcelain", "--untracked-files=all") or ""
    tracked, untracked = [], []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        code, name = line[:2], line[3:]
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        if name.startswith(".intentgraph/"):
            continue
        (untracked if code == "??" else tracked).append(name)
    return {"git_available": True, "head": head.strip(), "tracked_dirty": sorted(tracked), "untracked": sorted(untracked), "dirty": bool(tracked or untracked)}


def capture(paths: WorkspacePaths, manifest: ProjectManifest, repository: str, declared_paths: list[str], *, captured_at: str) -> dict[str, Any]:
    """Properties of a WorkspaceSnapshot node for ``repository`` and ``declared_paths``."""
    root = resolve_root(paths, manifest, repository)
    state = git_state(root)
    files: dict[str, str] = {}
    missing: list[str] = []
    for rel in sorted(set(declared_paths)):
        target = _safe_rel(root, rel)
        if target is None:
            raise InvalidInput(f"declared path {rel!r} escapes repository root {repository!r}", code="invalid_path")
        if target.is_file():
            files[rel] = file_digest(target)
        elif target.is_dir():
            files[rel] = tree_digest(root, target)
        else:
            missing.append(rel)
    locks = {name: file_digest(root / name) for name in LOCKFILES if (root / name).is_file()}
    rel_root = manifest.roots[repository]
    return {"repository": repository, "root_path": rel_root, **state, "files": files, "missing_paths": missing, "lockfiles": locks, "captured_at": captured_at, "tool_version": TOOL_VERSION}


def current_digests(root: Path, rel_paths: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for rel in rel_paths:
        target = _safe_rel(root, rel)
        if target is None or not target.exists():
            out[rel] = None
        elif target.is_dir():
            out[rel] = tree_digest(root, target)
        else:
            out[rel] = file_digest(target)
    return out


def changed_since(root: Path, head: str) -> dict[str, Any]:
    """Files changed in the working tree relative to ``head`` (tracked diffs plus untracked), or detection unavailable."""
    if not head or shutil.which("git") is None:
        return {"available": False, "reason": "git unavailable or no baseline HEAD", "paths": []}
    diff = _git(root, "diff", "--name-only", head)
    if diff is None:
        return {"available": False, "reason": f"baseline {head[:12]} is not reachable in this repository", "paths": []}
    changed = {line.strip() for line in diff.splitlines() if line.strip()}
    state = git_state(root)
    changed.update(state["untracked"])
    return {"available": True, "baseline_head": head, "current_head": state["head"], "paths": sorted(p for p in changed if not p.startswith(".intentgraph/"))}
