"""Versioned, declarative policies (architecture section 13.1).

A policy is data stored in the snapshot's ``policies`` list and changed only
through explicit ``set_policy`` patch operations. Rules name built-in rule
types; no policy can execute code. A readiness check never modifies a policy.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..checks import Diagnostic

RuleType = Literal[
    "structural_checks_pass",
    "blocking_questions_resolved",
    "requirements_realized",
    "operations_defined",
    "concurrency_sensitive_reviewed",
    "assumptions_not_refuted",
    "assumptions_acknowledged",
    "proposed_records_accepted",
    "review_packet_current",
    "evidence_required",
    "mappings_present",
]

COLLECTION_MODES = ["agent_assertion", "agent_submitted_report", "validated_report", "independent_capture"]


class PolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    rule: RuleType
    blocking: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    version: str
    kind: Literal["readiness", "conformance"]
    description: str = ""
    rules: list[PolicyRule] = Field(min_length=1)

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


def default_readiness_policy() -> dict[str, Any]:
    return Policy(
        id="policy:default-readiness", version="0.1", kind="readiness",
        description="Default pre-build readiness policy (v0). Projects may replace it with set_policy; the change is recorded.",
        rules=[
            PolicyRule(id="structural", rule="structural_checks_pass", description="Mandatory structural checks pass."),
            PolicyRule(id="questions", rule="blocking_questions_resolved", description="Blocking intent questions are resolved."),
            PolicyRule(id="realized", rule="requirements_realized", description="Every in-scope accepted requirement has a proposed realization or a documented deliberate deferral."),
            PolicyRule(id="operations", rule="operations_defined", description="Required interface input, output and failure behavior is defined."),
            PolicyRule(id="concurrency", rule="concurrency_sensitive_reviewed", description="A concurrency-sensitive process has its review obligation addressed."),
            PolicyRule(id="refuted", rule="assumptions_not_refuted", description="No in-scope assumption is refuted."),
            PolicyRule(id="assumptions", rule="assumptions_acknowledged", blocking=False, description="Unverified assumptions are listed for the reviewer."),
            PolicyRule(id="proposed", rule="proposed_records_accepted", blocking=False, description="Proposed records in scope are listed for acceptance."),
            PolicyRule(id="packet", rule="review_packet_current", description="The intent review packet covers the current design digest."),
        ],
    ).model_dump(mode="json")


def default_conformance_policy() -> dict[str, Any]:
    return Policy(
        id="policy:default-conformance", version="0.1", kind="conformance",
        description="Default post-build conformance policy (v0): must-requirements have mappings and passing evidence at least at report level.",
        rules=[
            PolicyRule(id="structural", rule="structural_checks_pass"),
            PolicyRule(id="mapped", rule="mappings_present", params={"kinds": ["Requirement"], "where": {"priority": ["must", "should"]}}),
            PolicyRule(id="tested", rule="evidence_required", params={"kinds": ["Requirement"], "where": {"priority": ["must"]}, "result": "passed", "min_collection_mode": "agent_submitted_report"},
                       description="An agent assertion is not executable evidence."),
        ],
    ).model_dump(mode="json")


def parse_policy(raw: dict[str, Any]) -> Policy:
    return Policy.model_validate(raw)


def validate_policies(policies: list[dict[str, Any]]) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    seen: set[str] = set()
    for raw in policies:
        pid = raw.get("id") if isinstance(raw, dict) else None
        try:
            pol = parse_policy(raw)
        except ValidationError as exc:
            diags.append(Diagnostic(code="invalid_policy", severity="error", message=f"policy {pid!r}: {exc.error_count()} schema error(s): {exc.errors()[0]['msg']}", record_ids=[pid] if isinstance(pid, str) else []))
            continue
        if pol.id in seen:
            diags.append(Diagnostic(code="duplicate_policy", severity="error", message=f"policy id {pol.id!r} appears more than once", record_ids=[pol.id]))
        seen.add(pol.id)
        rule_ids = [r.id for r in pol.rules]
        if len(set(rule_ids)) != len(rule_ids):
            diags.append(Diagnostic(code="invalid_policy", severity="error", message=f"policy {pol.id!r}: duplicate rule ids", record_ids=[pol.id]))
        for r in pol.rules:
            mode = r.params.get("min_collection_mode")
            if mode is not None and mode not in COLLECTION_MODES:
                diags.append(Diagnostic(code="invalid_policy", severity="error", message=f"policy {pol.id!r} rule {r.id!r}: unknown min_collection_mode {mode!r}", record_ids=[pol.id]))
    return diags
