from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProjectManifest(BaseModel):
    """``.intentgraph/project.json``: identity, versions, configured roots."""

    model_config = ConfigDict(extra="forbid")
    project_id: str
    name: str
    format_version: str
    vocabulary_version: str
    created_at: str
    created_by_tool_version: str
    # Repository roots (relative to the workspace root) whose files mappings may reference.
    roots: list[str] = Field(default_factory=lambda: ["."])
    # Unknown kinds are rejected unless this is true (section 5.6).
    compat_unknown_kinds: bool = False
