"""Vocabulary: kind schemas, relation endpoint rules, and extension resolution."""
from .registry import KindDef, PropertySpec, RelationDef, Vocabulary, load_core_vocabulary, validate_properties

__all__ = ["KindDef", "PropertySpec", "RelationDef", "Vocabulary", "load_core_vocabulary", "validate_properties"]
