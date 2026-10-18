"""Vocabulary registry (architecture sections 5.5 and 5.6).

Core kinds are versioned and stable. Project extensions live in
``.intentgraph/vocabulary/*.json`` and use namespaced names such as
``piano:PracticeSection``; they declare a parent kind and inherit its layers
and properties. Unknown kinds are never silently interpreted as known ones.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..errors import InvalidInput

PropertyType = Literal["string", "integer", "number", "boolean", "array", "object", "ref", "ref_list"]
LAYERS = ("intent", "observation", "reconciliation")


class PropertySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: PropertyType
    enum: list[Any] | None = None
    required: bool = False
    description: str = ""
    items: "PropertySpec | None" = None


class KindDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    family: str = "Extension"
    layers: list[str] = Field(default_factory=list)
    description: str = ""
    properties: dict[str, PropertySpec] = Field(default_factory=dict)
    parent: str | None = None
    namespace: str | None = None
    examples: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "KindDef":
        for layer in self.layers:
            if layer not in LAYERS:
                raise ValueError(f"kind {self.name}: unknown layer {layer!r}")
        return self


class RelationDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    layers: list[str]
    direction: str = ""
    source_kinds: list[str]
    target_kinds: list[str]
    required_properties: list[str] = Field(default_factory=list)
    property_schema: dict[str, PropertySpec] = Field(default_factory=dict)
    acyclic: bool = False
    impact_rule: str = ""
    description: str = ""
    namespace: str | None = None

    def property_specs(self) -> dict[str, PropertySpec]:
        specs = dict(self.property_schema)
        for name in self.required_properties:
            spec = specs.get(name, PropertySpec(type="string"))
            specs[name] = spec.model_copy(update={"required": True})
        return specs


def _type_ok(spec: PropertySpec, value: Any) -> bool:
    t = spec.type
    if t == "string" or t == "ref":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "array":
        return isinstance(value, list)
    if t == "ref_list":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if t == "object":
        return isinstance(value, dict)
    return False


def validate_properties(specs: dict[str, PropertySpec], props: dict[str, Any], *, allow_unknown: bool = False) -> list[str]:
    """Validate a properties dictionary against property specs. Returns error strings."""
    errors: list[str] = []
    for name, spec in specs.items():
        if spec.required and name not in props:
            errors.append(f"missing required property {name!r}")
    for name, value in props.items():
        spec = specs.get(name)
        if spec is None:
            if not allow_unknown:
                errors.append(f"unknown property {name!r}")
            continue
        if not _type_ok(spec, value):
            errors.append(f"property {name!r}: expected {spec.type}, got {type(value).__name__}")
            continue
        if spec.enum is not None and value not in spec.enum:
            errors.append(f"property {name!r}: value {value!r} not in {spec.enum}")
        if spec.type == "array" and spec.items is not None:
            for i, item in enumerate(value):
                if not _type_ok(spec.items, item):
                    errors.append(f"property {name!r}[{i}]: expected {spec.items.type}")
                elif spec.items.enum is not None and item not in spec.items.enum:
                    errors.append(f"property {name!r}[{i}]: value {item!r} not in {spec.items.enum}")
    return errors


def reference_properties(specs: dict[str, PropertySpec], props: dict[str, Any]) -> list[tuple[str, str]]:
    """All (property_name, referenced_id) pairs declared as references."""
    out: list[tuple[str, str]] = []
    for name, spec in specs.items():
        value = props.get(name)
        if value is None:
            continue
        if spec.type == "ref" and isinstance(value, str):
            out.append((name, value))
        elif spec.type == "ref_list" and isinstance(value, list):
            out.extend((name, v) for v in value if isinstance(v, str))
    return out


class Vocabulary:
    def __init__(self, version: str):
        self.version = version
        self.kinds: dict[str, KindDef] = {}
        self.relations: dict[str, RelationDef] = {}
        self.extension_sources: list[str] = []

    # ---- registration -------------------------------------------------
    def add_kind(self, kind: KindDef) -> None:
        if kind.name in self.kinds:
            raise InvalidInput(f"duplicate kind definition {kind.name!r}", code="duplicate_kind")
        if kind.parent is not None:
            parent = self.kinds.get(kind.parent)
            if parent is None:
                raise InvalidInput(f"kind {kind.name!r}: unknown parent {kind.parent!r}", code="unknown_parent_kind")
            merged = dict(parent.properties)
            merged.update(kind.properties)
            kind = kind.model_copy(update={"properties": merged, "layers": kind.layers or list(parent.layers), "family": kind.family if kind.family != "Extension" else parent.family})
        if not kind.layers:
            raise InvalidInput(f"kind {kind.name!r}: no layers declared", code="invalid_kind_definition")
        self.kinds[kind.name] = kind

    def add_relation(self, rel: RelationDef) -> None:
        if rel.name in self.relations:
            raise InvalidInput(f"duplicate relation definition {rel.name!r}", code="duplicate_relation")
        self.relations[rel.name] = rel

    # ---- lookup -------------------------------------------------------
    def kind(self, name: str) -> KindDef | None:
        return self.kinds.get(name)

    def relation(self, name: str) -> RelationDef | None:
        return self.relations.get(name)

    def ancestors(self, kind_name: str) -> list[str]:
        """The kind itself followed by its parent chain."""
        chain: list[str] = []
        current: str | None = kind_name
        while current is not None and current in self.kinds and current not in chain:
            chain.append(current)
            current = self.kinds[current].parent
        return chain

    def endpoint_allowed(self, allowed: list[str], kind_name: str) -> bool:
        kind = self.kinds.get(kind_name)
        if kind is None:
            return False
        if "*" in allowed:
            return True
        for layer in kind.layers:
            if f"@{layer}" in allowed:
                return True
        return any(a in allowed for a in self.ancestors(kind_name))

    # ---- loading ------------------------------------------------------
    def load_extension_file(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InvalidInput(f"cannot read vocabulary extension {path}: {exc}", code="invalid_vocabulary_file") from exc
        namespace = data.get("namespace")
        if not isinstance(namespace, str) or not namespace or ":" in namespace:
            raise InvalidInput(f"vocabulary extension {path} must declare a simple 'namespace'", code="invalid_vocabulary_file")
        for raw in data.get("kinds", []):
            kind = KindDef.model_validate(raw)
            if not kind.name.startswith(namespace + ":"):
                raise InvalidInput(f"extension kind {kind.name!r} must be prefixed with {namespace!r}:", code="invalid_vocabulary_file")
            self.add_kind(kind.model_copy(update={"namespace": namespace}))
        for raw in data.get("relations", []):
            rel = RelationDef.model_validate(raw)
            if not rel.name.startswith(namespace + ":"):
                raise InvalidInput(f"extension relation {rel.name!r} must be prefixed with {namespace!r}:", code="invalid_vocabulary_file")
            self.add_relation(rel.model_copy(update={"namespace": namespace}))
        self.extension_sources.append(str(path))

    def load_extensions(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.json")):
            self.load_extension_file(path)

    def describe_kind(self, name: str) -> dict[str, Any]:
        kind = self.kinds[name]
        return kind.model_dump(mode="json", exclude_none=True)

    def describe_relation(self, name: str) -> dict[str, Any]:
        rel = self.relations[name]
        return rel.model_dump(mode="json", exclude_none=True)


_CORE_DIR = Path(__file__).parent / "core"


def load_core_vocabulary() -> Vocabulary:
    kinds_doc = json.loads((_CORE_DIR / "kinds.json").read_text(encoding="utf-8"))
    rels_doc = json.loads((_CORE_DIR / "relations.json").read_text(encoding="utf-8"))
    vocab = Vocabulary(kinds_doc["version"])
    for raw in kinds_doc["kinds"]:
        vocab.add_kind(KindDef.model_validate(raw))
    for raw in rels_doc["relations"]:
        vocab.add_relation(RelationDef.model_validate(raw))
    return vocab
