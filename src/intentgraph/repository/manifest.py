from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectManifest(BaseModel):
    """``.intentgraph/project.json``: identity, versions, configured roots."""

    model_config = ConfigDict(extra="forbid")
    project_id: str
    name: str
    format_version: str
    vocabulary_version: str
    created_at: str
    created_by_tool_version: str
    # Repository roots: name -> path relative to the workspace root. Mappings, symbols,
    # tests and evidence inputs name a root by its key. A plain list is accepted and
    # each path becomes its own name.
    roots: dict[str, str] = Field(default_factory=lambda: {".": "."})

    @field_validator("roots", mode="before")
    @classmethod
    def _normalize_roots(cls, value):
        if isinstance(value, list):
            return {str(v): str(v) for v in value}
        return value
    # Unknown kinds are rejected unless this is true (section 5.6).
    compat_unknown_kinds: bool = False
