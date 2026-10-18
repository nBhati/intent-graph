"""Error types shared by all layers.

Exit-code convention (architecture section 12):
  0  success / no blocking findings
  2  completed check with blockers
  3  invalid input or stale revision
  4  unavailable dependency or internal execution failure
"""
from __future__ import annotations

from typing import Any


class IntentGraphError(Exception):
    """Base error. ``code`` is a stable machine-readable identifier."""

    exit_code = 4
    code = "internal_error"

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidInput(IntentGraphError):
    exit_code = 3
    code = "invalid_input"


class WorkspaceNotFound(InvalidInput):
    code = "workspace_not_found"


class IncompatibleWorkspace(InvalidInput):
    code = "incompatible_workspace"


class StaleBase(InvalidInput):
    code = "stale_base"


class ValidationFailed(InvalidInput):
    """Raised when a candidate model fails structural validation."""

    code = "validation_failed"


class CorruptSnapshot(IntentGraphError):
    exit_code = 4
    code = "corrupt_snapshot"


class LockTimeout(IntentGraphError):
    exit_code = 4
    code = "lock_timeout"


class NotSupported(IntentGraphError):
    exit_code = 4
    code = "not_supported"
