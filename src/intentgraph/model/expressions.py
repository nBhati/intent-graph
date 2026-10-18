"""Structured expressions: ``intent-expr/0.1`` (architecture section 7.2).

This validates the *shape* of an expression against a small explicit operator
set. It does not evaluate or prove anything. No ``eval``, Python source, or
shell text is ever accepted.
"""
from __future__ import annotations

from typing import Any

EXPRESSION_LANGUAGE = "intent-expr/0.1"

# op -> required keys (besides "op")
OPERATORS: dict[str, tuple[str, ...]] = {
    "always": ("arg",),
    "eventually": ("arg",),
    "not": ("arg",),
    "and": ("args",),
    "or": ("args",),
    "implies": ("left", "right"),
    "forall": ("variable", "domain_ref", "body"),
    "exists": ("variable", "domain_ref", "body"),
    "field_eq": ("variable", "field", "value"),
    "field_ne": ("variable", "field", "value"),
    "field_in": ("variable", "field", "values"),
}

_SCALAR = (str, int, float, bool, type(None))


def validate_expression(expr: Any, path: str = "expression") -> list[str]:
    """Return a list of error strings (empty when the expression is well-formed)."""
    errors: list[str] = []
    if not isinstance(expr, dict):
        return [f"{path}: expression must be an object"]
    op = expr.get("op")
    if not isinstance(op, str) or op not in OPERATORS:
        return [f"{path}: unsupported operator {op!r}; supported: {sorted(OPERATORS)}"]
    required = OPERATORS[op]
    allowed = set(required) | {"op"}
    for key in expr:
        if key not in allowed:
            errors.append(f"{path}: unexpected key {key!r} for operator {op!r}")
    for key in required:
        if key not in expr:
            errors.append(f"{path}: operator {op!r} requires {key!r}")
    if errors:
        return errors
    if op in ("always", "eventually", "not"):
        errors += validate_expression(expr["arg"], f"{path}.arg")
    elif op in ("and", "or"):
        args = expr["args"]
        if not isinstance(args, list) or len(args) < 2:
            errors.append(f"{path}.args: must be a list of at least two expressions")
        else:
            for i, a in enumerate(args):
                errors += validate_expression(a, f"{path}.args[{i}]")
    elif op == "implies":
        errors += validate_expression(expr["left"], f"{path}.left")
        errors += validate_expression(expr["right"], f"{path}.right")
    elif op in ("forall", "exists"):
        if not isinstance(expr["variable"], str) or not expr["variable"]:
            errors.append(f"{path}.variable: must be a non-empty string")
        if not isinstance(expr["domain_ref"], str):
            errors.append(f"{path}.domain_ref: must be a record id string")
        errors += validate_expression(expr["body"], f"{path}.body")
    elif op in ("field_eq", "field_ne"):
        if not isinstance(expr["variable"], str) or not isinstance(expr["field"], str):
            errors.append(f"{path}: variable and field must be strings")
        if not isinstance(expr["value"], _SCALAR):
            errors.append(f"{path}.value: must be a scalar")
    elif op == "field_in":
        if not isinstance(expr["variable"], str) or not isinstance(expr["field"], str):
            errors.append(f"{path}: variable and field must be strings")
        if not isinstance(expr["values"], list) or not all(isinstance(v, _SCALAR) for v in expr["values"]):
            errors.append(f"{path}.values: must be a list of scalars")
    return errors


def expression_refs(expr: Any) -> list[str]:
    """Record IDs referenced by an expression (``domain_ref`` fields)."""
    refs: list[str] = []
    if isinstance(expr, dict):
        if isinstance(expr.get("domain_ref"), str):
            refs.append(expr["domain_ref"])
        for v in expr.values():
            refs += expression_refs(v)
    elif isinstance(expr, list):
        for v in expr:
            refs += expression_refs(v)
    return refs
