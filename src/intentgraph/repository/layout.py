"""Workspace layout (architecture section 9.1)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DIR_NAME = ".intentgraph"


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path

    @property
    def dir(self) -> Path:
        return self.root / DIR_NAME

    @property
    def project(self) -> Path:
        return self.dir / "project.json"

    @property
    def model(self) -> Path:
        return self.dir / "model.json"

    @property
    def vocabulary(self) -> Path:
        return self.dir / "vocabulary"

    @property
    def agent_guide(self) -> Path:
        return self.dir / "agent-guide.md"

    @property
    def artifacts(self) -> Path:
        return self.dir / "artifacts"

    @property
    def cache(self) -> Path:
        return self.dir / "cache"

    @property
    def locks(self) -> Path:
        return self.dir / "locks"

    @property
    def write_lock(self) -> Path:
        return self.locks / "write.lock"

    def exists(self) -> bool:
        return self.project.is_file() and self.model.is_file()

    @staticmethod
    def find(start: Path) -> "WorkspacePaths | None":
        current = start.resolve()
        for candidate in [current, *current.parents]:
            paths = WorkspacePaths(candidate)
            if paths.project.is_file():
                return paths
        return None
