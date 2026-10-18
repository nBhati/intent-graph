"""Readiness and conformance evaluation (architecture sections 13 to 13.3).

The engine is pure: it reads the index and returns obligations. It never
writes to the model and never touches its own policy. Computed obligations
have deterministic ids so a project can waive one explicitly by recording an
Obligation node with that id in state ``waived`` whose ``waiver`` names a user
authorization and a reason; an agent cannot waive by assertion.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..checks import Diagnostic
from ..errors import InvalidInput
from ..graph import GraphIndex
from ..model import NodeRecord
from ..vocabulary import Vocabulary
from .policy import COLLECTION_MODES, Policy, PolicyRule, parse_policy
from .scope import ClosureMember, design_digest, scope_closure

ObligationState = Literal["pending", "blocked", "waived"]


class ObligationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    rule: str
    blocking: bool
    state: ObligationState
    related_ids: list[str]
    request: str
    acceptable_resolution: list[str]
    source: Literal["policy", "model"]
    waiver: dict[str, Any] | None = None


class ReadinessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "needs_work", "blocked"]
    scope: str
    policy: str
    policy_kind: str
    model_revision: int
    content_digest: str
    design_digest: str
    closure: dict[str, Any]
    obligations: list[ObligationItem]
    warnings: list[ObligationItem]
    waived: list[ObligationItem]
    approval: dict[str, Any]
    findings: list[Diagnostic]
    note: str


class RuleContext:
    def __init__(self, index: GraphIndex, vocabulary: Vocabulary, scope: NodeRecord, closure: dict[str, ClosureMember], diagnostics: list[Diagnostic], digest: str):
        self.index = index
        self.vocabulary = vocabulary
        self.scope = scope
        self.closure = closure
        self.diagnostics = diagnostics
        self.design_digest = digest
        self.slug = scope.id.split(":", 1)[1]

    def nodes(self, kind: str, *, live: bool = True) -> list[NodeRecord]:
        out = [self.index.nodes[i] for i in self.closure if self.index.nodes[i].kind == kind]
        if live:
            out = [n for n in out if n.lifecycle != "superseded"]
        return sorted(out, key=lambda n: n.id)

    def oid(self, rule: PolicyRule, target: str | None) -> str:
        tail = target.replace(":", ".") if target else "scope"
        return f"obligation:{self.slug}/{rule.id}/{tail}"

    def item(self, rule: PolicyRule, target: str | None, kind: str, request: str, resolutions: list[str], related: list[str], state: ObligationState = "pending") -> ObligationItem:
        return ObligationItem(id=self.oid(rule, target), kind=kind, rule=rule.rule, blocking=rule.blocking, state=state, related_ids=related, request=request, acceptable_resolution=resolutions, source="policy")


def _matches(node: NodeRecord, params: dict[str, Any]) -> bool:
    kinds = params.get("kinds")
    if kinds and node.kind not in kinds:
        return False
    for key, allowed in (params.get("where") or {}).items():
        if node.properties.get(key) not in allowed:
            return False
    return True


# ---- rule implementations ---------------------------------------------------

def r_structural(ctx: RuleContext, rule: PolicyRule) -> list[ObligationItem]:
    errors = [d for d in ctx.diagnostics if d.severity == "error"]
    if not errors:
        return []
    ids = sorted({i for d in errors for i in d.record_ids})
    return [ctx.item(rule, None, "structural", f"Fix {len(errors)} structural error(s): " + "; ".join(d.message for d in errors[:5]), ["fix_structure"], ids)]


def r_questions(ctx: RuleContext, rule: PolicyRule) -> list[ObligationItem]:
    return [ctx.item(rule, q.id, "intent_question", f"Resolve blocking question: {q.label}", ["user_clarification"], [q.id], state="blocked")
            for q in ctx.nodes("Question") if q.properties.get("status") == "open" and q.properties.get("blocking") is True]


def r_realized(ctx: RuleContext, rule: PolicyRule) -> list[ObligationItem]:
    out = []
    for req in ctx.nodes("Requirement"):
        if req.lifecycle != "accepted":
            continue
        realized = any(ctx.index.nodes[e.source].lifecycle != "superseded" for e in ctx.index.in_edges(req.id, {"realizes"}) if e.source in ctx.index.nodes)
        deferred = any(
            ctx.index.nodes[e.source].kind == "Decision" and ctx.index.nodes[e.source].properties.get("decision_kind") in ("deferral", "exclusion") and ctx.index.nodes[e.source].lifecycle != "superseded"
            for e in ctx.index.in_edges(req.id, {"concerns"}) if e.source in ctx.index.nodes)
        if not realized and not deferred:
            out.append(ctx.item(rule, req.id, "realization", f"Propose a realization for requirement '{req.label}' (a design element with a `realizes` edge) or record a deferral/exclusion Decision concerning it.", ["realize", "deferral_decision"], [req.id]))
    return out


def r_operations(ctx: RuleContext, rule: PolicyRule) -> list[ObligationItem]:
    out = []
    for op in ctx.nodes("Operation"):
        missing = [k for k in ("inputs", "outputs", "failures") if k not in op.properties]
        if missing:
            out.append(ctx.item(rule, op.id, "interface_contract", f"Define {', '.join(missing)} for operation '{op.label}'.", ["define_contract"], [op.id]))
    return out


def r_concurrency(ctx: RuleContext, rule: PolicyRule) -> list[ObligationItem]:
    out = []
    for proc in ctx.nodes("Process"):
        if proc.properties.get("concurrency_sensitive") is not True:
            continue
        reviewed = any(
            ctx.index.nodes[e.source].kind == "Obligation" and ctx.index.nodes[e.source].properties.get("obligation_kind") == "concurrency_review" and ctx.index.nodes[e.source].properties.get("state") in ("satisfied", "waived")
            for e in ctx.index.in_edges(proc.id, {"concerns"}) if e.source in ctx.index.nodes)
        if not reviewed:
            out.append(ctx.item(rule, proc.id, "concurrency_review", f"Process '{proc.label}' is concurrency-sensitive: record a satisfied Obligation of kind concurrency_review concerning it, backed by a scenario-and-design review or a model check.", ["scenario_and_design", "model_check"], [proc.id]))
    return out


def r_refuted(ctx: RuleContext, rule: PolicyRule) -> list[ObligationItem]:
    return [ctx.item(rule, a.id, "refuted_assumption", f"Assumption '{a.label}' is refuted; revise the dependent design or supersede the assumption.", ["revise_design", "supersede_assumption"], [a.id])
            for a in ctx.nodes("Assumption") if a.properties.get("status") == "refuted"]


def r_assumptions(ctx: RuleContext, rule: PolicyRule) -> list[ObligationItem]:
    return [ctx.item(rule, a.id, "unverified_assumption", f"Assumption '{a.label}' is unverified; confirm it or accept the risk explicitly in review.", ["confirm_assumption", "accept_risk"], [a.id])
            for a in ctx.nodes("Assumption") if a.properties.get("status") == "unverified"]


def r_proposed(ctx: RuleContext, rule: PolicyRule) -> list[ObligationItem]:
    ids = sorted(i for i in ctx.closure if ctx.index.nodes[i].lifecycle == "proposed" and ctx.index.nodes[i].layer == "intent")
    if not ids:
        return []
    return [ctx.item(rule, None, "acceptance", f"{len(ids)} proposed record(s) in scope await acceptance or removal.", ["accept_records", "remove_records"], ids)]


def r_packet(ctx: RuleContext, rule: PolicyRule) -> list[ObligationItem]:
    for e in ctx.index.in_edges(ctx.scope.id, {"depicts"}):
        art = ctx.index.nodes.get(e.source)
        if art is not None and art.kind == "ReviewArtifact" and art.lifecycle != "superseded" and art.properties.get("scope_digest") == ctx.design_digest:
            return []
    return [ctx.item(rule, None, "review_packet", "Export the intent review packet for this scope at the current design digest (`intentgraph review export --scope ... --record`).", ["review_export"], [ctx.scope.id])]


def _evidence_for(ctx: RuleContext, target: str) -> list[NodeRecord]:
    found: dict[str, NodeRecord] = {}
    for referrer, prop in ctx.index.referenced_by.get(target, []):
        node = ctx.index.nodes.get(referrer)
        if node is not None and node.kind == "Evidence" and prop == "supports" and node.lifecycle != "superseded":
            found[node.id] = node
    for e in ctx.index.in_edges(target, {"supports"}):
        node = ctx.index.nodes.get(e.source)
        if node is not None and node.kind == "Evidence" and node.lifecycle != "superseded":
            found[node.id] = node
    return sorted(found.values(), key=lambda n: n.id)


def r_evidence(ctx: RuleContext, rule: PolicyRule) -> list[ObligationItem]:
    p = rule.params
    min_mode = p.get("min_collection_mode", "agent_submitted_report")
    min_rank = COLLECTION_MODES.index(min_mode)
    want_result = p.get("result", "passed")
    methods = p.get("methods")
    out = []
    for nid in sorted(ctx.closure):
        node = ctx.index.nodes[nid]
        if node.lifecycle == "superseded" or not _matches(node, p):
            continue
        evidence = _evidence_for(ctx, nid)
        ok = [ev for ev in evidence if ev.properties.get("result") == want_result and COLLECTION_MODES.index(ev.properties.get("collection_mode", "agent_assertion")) >= min_rank and (not methods or ev.properties.get("method") in methods)]
        if ok:
            continue
        weak = [ev for ev in evidence if ev.properties.get("result") == want_result]
        if weak:
            req = f"Evidence for '{node.label}' exists only at collection mode {', '.join(sorted({w.properties.get('collection_mode', '?') for w in weak}))}, below the required {min_mode}; submit a report-level or captured result."
        elif evidence:
            req = f"Evidence for '{node.label}' does not report result '{want_result}' ({', '.join(f'{e.id}={e.properties.get('result')}' for e in evidence)})."
        else:
            req = f"No evidence supports '{node.label}'; submit an Evidence record (result {want_result}, collection mode at least {min_mode})."
        out.append(ctx.item(rule, nid, "evidence", req, ["submit_evidence"], [nid] + [e.id for e in evidence]))
    return out


def r_mappings(ctx: RuleContext, rule: PolicyRule) -> list[ObligationItem]:
    out = []
    for nid in sorted(ctx.closure):
        node = ctx.index.nodes[nid]
        if node.lifecycle == "superseded" or not _matches(node, rule.params):
            continue
        mapped = any(ctx.index.nodes[r].kind == "Mapping" and prop == "model_refs" for r, prop in ctx.index.referenced_by.get(nid, []) if r in ctx.index.nodes)
        if not mapped:
            out.append(ctx.item(rule, nid, "mapping", f"No Mapping records an implementation for '{node.label}'.", ["record_mapping"], [nid]))
    return out


RULES = {
    "structural_checks_pass": r_structural,
    "blocking_questions_resolved": r_questions,
    "requirements_realized": r_realized,
    "operations_defined": r_operations,
    "concurrency_sensitive_reviewed": r_concurrency,
    "assumptions_not_refuted": r_refuted,
    "assumptions_acknowledged": r_assumptions,
    "proposed_records_accepted": r_proposed,
    "review_packet_current": r_packet,
    "evidence_required": r_evidence,
    "mappings_present": r_mappings,
}


# ---- waivers and model obligations ----------------------------------------

def _apply_waivers(ctx: RuleContext, items: list[ObligationItem]) -> tuple[list[ObligationItem], list[ObligationItem], list[Diagnostic]]:
    kept, waived, findings = [], [], []
    for item in items:
        node = ctx.index.nodes.get(item.id)
        if node is None or node.kind != "Obligation" or node.properties.get("state") != "waived":
            kept.append(item)
            continue
        waiver = node.properties.get("waiver") or {}
        if waiver.get("authorized_by") == "user" and isinstance(waiver.get("reason"), str) and waiver.get("reason"):
            waived.append(item.model_copy(update={"state": "waived", "waiver": waiver}))
        else:
            findings.append(Diagnostic(code="invalid_waiver", severity="warning", message=f"obligation {item.id!r} is marked waived but the waiver lacks a user authorization and reason; not honoured", record_ids=[item.id]))
            kept.append(item)
    return kept, waived, findings


def _model_obligations(ctx: RuleContext) -> list[ObligationItem]:
    out = []
    for node in sorted(ctx.index.snapshot.nodes, key=lambda n: n.id):
        if node.kind != "Obligation" or node.lifecycle == "superseded":
            continue
        state = node.properties.get("state")
        if state not in ("pending", "failed", "blocked"):
            continue
        scope_refs = set(node.properties.get("scope_refs", []))
        other_scopes = {r for r in scope_refs if r in ctx.index.nodes and ctx.index.nodes[r].kind == "Scope" and r != ctx.scope.id}
        if other_scopes and ctx.scope.id not in scope_refs:
            continue  # explicitly assigned to a different scope
        refs = scope_refs | {e.target for e in ctx.index.out_edges(node.id, {"concerns"})}
        if ctx.scope.id not in refs and not (refs & set(ctx.closure)):
            continue
        out.append(ObligationItem(
            id=node.id, kind=node.properties.get("obligation_kind", "manual"), rule=node.properties.get("rule", "model"), blocking=bool(node.properties.get("blocking")),
            state="blocked" if state == "blocked" else "pending", related_ids=sorted(refs), request=node.properties.get("request") or node.label,
            acceptable_resolution=list(node.properties.get("acceptable_resolution", [])), source="model",
        ))
    return out


def _approval_state(ctx: RuleContext, policy: Policy) -> dict[str, Any]:
    approvals = [n for n in ctx.index.snapshot.nodes if n.kind == "Approval" and n.lifecycle != "superseded"
                 and n.properties.get("approval_kind") == "build_authorization" and n.properties.get("scope_ref") == ctx.scope.id]
    if not approvals:
        return {"status": "none"}
    latest = max(approvals, key=lambda n: (n.properties.get("model_revision", -1), n.id))
    approved = latest.properties.get("design_digest")
    if approved == ctx.design_digest:
        return {"status": "current", "approval_id": latest.id, "design_digest": approved, "recorded_by": latest.properties.get("recorded_by"), "model_revision": latest.properties.get("model_revision")}
    since = latest.properties.get("model_revision", 0)
    changed = sorted({i for t in ctx.index.snapshot.transactions if t.result_revision > since for i in t.added_ids + t.updated_ids + t.removed_ids} & (set(ctx.closure) | {e.id for e in ctx.index.snapshot.edges}))
    changed = [i for i in changed if i in ctx.closure or (i in ctx.index.edges and ctx.index.edges[i].source in ctx.closure and ctx.index.edges[i].target in ctx.closure)]
    return {"status": "invalidated", "approval_id": latest.id, "approved_design_digest": approved, "current_design_digest": ctx.design_digest,
            "reason": "the design content of the approved scope changed after the approval", "changed_in_scope_ids": changed, "model_revision": since}


# ---- entry point --------------------------------------------------------------

def find_policy(snapshot_policies: list[dict[str, Any]], policy_id: str | None, kind: str) -> Policy:
    parsed = [parse_policy(p) for p in snapshot_policies]
    if policy_id is not None:
        for p in parsed:
            if p.id == policy_id:
                return p
        raise InvalidInput(f"unknown policy {policy_id!r}", code="unknown_policy", details={"available": [p.id for p in parsed]})
    candidates = [p for p in parsed if p.kind == kind]
    if not candidates:
        raise InvalidInput(f"no {kind} policy in the model; add one with a set_policy patch operation", code="unknown_policy")
    return candidates[0]


def evaluate(index: GraphIndex, vocabulary: Vocabulary, diagnostics: list[Diagnostic], scope_id: str, *, policy_id: str | None = None, kind: str = "readiness") -> ReadinessResult:
    scope = index.nodes.get(scope_id)
    if scope is None or scope.kind != "Scope":
        raise InvalidInput(f"{scope_id!r} is not a Scope record", code="unknown_scope", details={"id": scope_id})
    policy = find_policy(index.snapshot.policies, policy_id or (scope.properties.get("policy_ref") if kind == "readiness" else None), kind)
    closure = scope_closure(index, vocabulary, scope)
    digest = design_digest(index, set(closure), policy.ref)
    ctx = RuleContext(index, vocabulary, scope, closure, diagnostics, digest)

    items: list[ObligationItem] = []
    for rule in policy.rules:
        items.extend(RULES[rule.rule](ctx, rule))
    items.extend(_model_obligations(ctx))
    items, waived, findings = _apply_waivers(ctx, items)
    blocking = [i for i in items if i.blocking]
    warnings = [i for i in items if not i.blocking]
    if any(i.state == "blocked" for i in blocking):
        status = "blocked"
    elif blocking:
        status = "needs_work"
    else:
        status = "ready"
    approval = _approval_state(ctx, policy) if policy.kind == "readiness" else {"status": "not_applicable"}
    return ReadinessResult(
        status=status, scope=scope.id, policy=policy.ref, policy_kind=policy.kind, model_revision=index.snapshot.revision, content_digest=index.snapshot.content_digest,
        design_digest=digest,
        closure={"explicit": list(scope.properties.get("member_refs", [])), "count": len(closure),
                 "members": [{"id": m.id, "kind": m.kind, "reason": m.reason, "via": m.via} for m in sorted(closure.values(), key=lambda m: m.id)]},
        obligations=blocking, warnings=warnings, waived=waived, approval=approval, findings=findings,
        note="Readiness is the satisfaction of this policy with recorded content; it is not proof of correctness and not authority to change intended behavior.",
    )
