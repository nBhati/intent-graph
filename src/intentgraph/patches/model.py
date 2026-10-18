"""Patch format (architecture section 12.1)."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..model import Annotation, EdgeRecord, NodeRecord, Provenance, is_valid_id


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AddNode(_Op):
    op: Literal["add_node"]
    record: NodeRecord


class AddEdge(_Op):
    op: Literal["add_edge"]
    record: EdgeRecord


class UpdateProperties(_Op):
    """Merge ``changes`` into ``properties``. A ``null`` value removes the property."""

    op: Literal["update_properties"]
    id: str
    changes: dict[str, Any]


class UpdateFields(_Op):
    """Replace envelope fields: label, description, lifecycle, provenance, annotations."""

    op: Literal["update_fields"]
    id: str
    label: str | None = None
    description: str | None = None
    lifecycle: Literal["proposed", "accepted", "superseded"] | None = None
    provenance: Provenance | None = None
    annotations: list[Annotation] | None = None


class AddAnnotation(_Op):
    op: Literal["add_annotation"]
    id: str
    annotation: Annotation


class Remove(_Op):
    """Remove a record. Prefer ``lifecycle: superseded`` for accepted records."""

    op: Literal["remove"]
    id: str


PatchOperation = Annotated[
    Union[AddNode, AddEdge, UpdateProperties, UpdateFields, AddAnnotation, Remove],
    Field(discriminator="op"),
]


class Patch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    patch_id: str
    base_revision: int = Field(ge=0)
    base_digest: str
    reason: str = ""
    operations: list[PatchOperation] = Field(min_length=1)

    @field_validator("patch_id")
    @classmethod
    def _check_patch_id(cls, value: str) -> str:
        if not is_valid_id(value):
            raise ValueError(f"invalid patch id {value!r}: expected 'prefix:slug' (e.g. 'patch:cancel-refinement-01')")
        return value
