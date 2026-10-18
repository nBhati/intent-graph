"""Transaction validation, optimistic concurrency, and atomic application."""
from .model import Patch, PatchOperation
from .apply import PatchResult, apply_patch, validate_patch

__all__ = ["Patch", "PatchOperation", "PatchResult", "apply_patch", "validate_patch"]
