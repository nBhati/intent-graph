"""Reconciliation findings (architecture section 16.2).

Each finding carries the *safe conclusion* the signal supports and the
follow-up it requires. Reachability and digests cannot reveal dependencies
that were never recorded, so absence of a finding is not a claim of
conformance.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..graph import GraphIndex
from ..repository import Repository
from ..repository.workspace import changed_since, resolve_root
from .freshness import Freshness
from .scope import scope_closure

LOCATOR_KINDS = ("CodeArtifact", "CodeSymbol", "TestCase")


class ReconcileFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    severity: str  # info | warning | blocker
    related_ids: list[str] = Field(default_factory=list)
    message: str
    safe_conclusion: str
    follow_up: str


def _finding(code: str, severity: str, related: list[str], message: str, conclusion: str, follow_up: str) -> ReconcileFinding:
    return ReconcileFinding(code=code, severity=severity, related_ids=related, message=message, safe_conclusion=conclusion, follow_up=follow_up)


def reconcile(index: GraphIndex, repo: Repository, freshness: dict[str, Freshness], *, scope_ids: set[str] | None = None, vocabulary=None) -> dict[str, Any]:
    manifest = repo.load_manifest()
    findings: list[ReconcileFinding] = []

    # Which records are in play.
    if scope_ids is None:
        in_play = set(index.nodes)
    else:
        in_play = set(scope_ids)
        for n in index.nodes.values():
            if n.kind == "Mapping" and set(n.properties.get("model_refs", [])) & scope_ids:
                in_play.add(n.id)
                in_play.update(n.properties.get("implementation_refs", []))
            if n.kind == "Evidence" and set(n.properties.get("supports", [])) & scope_ids:
                in_play.add(n.id)
        for e in index.snapshot.edges:
            if e.kind == "supports" and e.target in scope_ids:
                in_play.add(e.source)

    # 1. Locators.
    referenced_paths: dict[str, set[str]] = {}
    for n in sorted(index.nodes.values(), key=lambda n: n.id):
        if n.kind not in LOCATOR_KINDS or n.lifecycle == "superseded":
            continue
        repository = n.properties.get("repository", ".")
        rel = n.properties.get("path")
        if not rel:
            continue
        referenced_paths.setdefault(repository, set()).add(rel)
        if n.id not in in_play:
            continue
        try:
            root = resolve_root(repo.paths, manifest, repository)
        except Exception as exc:
            findings.append(_finding("unknown_root", "blocker", [n.id], f"{n.id}: {exc}", "The locator names a repository root this workspace does not configure.", "Configure the root in project.json or correct the record."))
            continue
        if not (root / rel).exists():
            findings.append(_finding("broken_locator", "blocker", [n.id], f"{n.id} ({n.kind}) points at {repository}:{rel}, which does not exist", "The mapping locator is broken.", "Update the mapping or restore the implementation."))
        elif n.kind == "CodeSymbol" and n.properties.get("resolution_status") != "resolved":
            findings.append(_finding("unresolved_symbol", "warning", [n.id], f"{n.id} has resolution_status {n.properties.get('resolution_status')!r}", "The file exists but the symbol claim is not resolved.", "Resolve with an extractor or explicit agent review."))

    # 2. Evidence freshness.
    for ev_id, f in sorted(freshness.items()):
        if ev_id not in in_play:
            continue
        if f.result == "failed":
            findings.append(_finding("test_failed", "blocker", [ev_id], f"{ev_id} reports result 'failed'", "The tested property failed in the recorded environment.", "Investigate and resolve, then resubmit evidence."))
        if f.artifact_available is False:
            findings.append(_finding("evidence_artifact_missing", "warning", [ev_id], f"{ev_id}: {'; '.join(r for r in f.reasons if 'artifact' in r)}", "The evidence grade cannot be upheld without its artifact; effective mode is agent_assertion.", "Restore the artifact or resubmit the evidence."))
        if f.source_changed:
            findings.append(_finding("source_changed", "warning", [ev_id], f"{ev_id}: declared inputs changed: {', '.join(f.source_changed[:8])}", "Prior evidence may be stale.", "Re-run the check against the current source and resubmit."))
        if f.model_scope_changed:
            findings.append(_finding("model_scope_changed", "warning", [ev_id], f"{ev_id}: the supported model content changed after submission", "The evidence was collected against earlier intent; its applicability is unknown.", "Review whether the change affects the evidence; resubmit if it does."))
        for r in f.reasons:
            if r.startswith("no WorkspaceSnapshot") or r.startswith("no declared inputs"):
                findings.append(_finding("evidence_unbound", "warning", [ev_id], f"{ev_id}: {r}", "Freshness cannot be established for this evidence.", "Resubmit with declared inputs so freshness can be tracked."))
            if r.startswith("dependency lockfile"):
                findings.append(_finding("lockfile_changed", "warning", [ev_id], f"{ev_id}: {r}", "Dependencies changed; a test against stale dependencies is not a check of the current build.", "Re-run with the current dependencies."))

    # 3. Unmapped source changes per root, against the latest WorkspaceSnapshot baseline.
    unmapped: dict[str, Any] = {}
    for repository in sorted(manifest.roots):
        snaps = [n for n in index.nodes.values() if n.kind == "WorkspaceSnapshot" and n.properties.get("repository") == repository]
        if not snaps:
            unmapped[repository] = {"available": False, "reason": "no WorkspaceSnapshot baseline for this root yet (run `intentgraph workspace snapshot`)", "paths": []}
            continue
        latest = max(snaps, key=lambda n: (n.properties.get("captured_at", ""), n.id))
        try:
            root = resolve_root(repo.paths, manifest, repository)
        except Exception as exc:
            unmapped[repository] = {"available": False, "reason": str(exc), "paths": []}
            continue
        change = changed_since(root, latest.properties.get("head", ""))
        change["baseline_snapshot"] = latest.id
        if change["available"]:
            known = set(referenced_paths.get(repository, set()))
            for snap in snaps:
                known.update(snap.properties.get("files", {}).keys())
            unknown = [p for p in change["paths"] if not any(p == k or p.startswith(k.rstrip("/") + "/") for k in known)]
            change["unmapped_paths"] = unknown
            change["mapped_paths"] = [p for p in change["paths"] if p not in unknown]
            if unknown:
                findings.append(_finding("unmapped_change", "info", [latest.id], f"{repository}: {len(unknown)} changed path(s) are not referenced by any mapping, symbol, test or evidence input: {', '.join(unknown[:10])}" + (" ..." if len(unknown) > 10 else ""),
                                         "Model coverage is incomplete for this change.", "Classify the change and link it (mapping, observation) or record it as out of scope."))
        unmapped[repository] = change

    blockers = [f for f in findings if f.severity == "blocker"]
    return {
        "findings": [f.model_dump(mode="json") for f in findings],
        "evidence": [f.to_dict() for _, f in sorted(freshness.items()) if f.evidence_id in in_play],
        "workspace": unmapped,
        "summary": {"blockers": len(blockers), "warnings": sum(1 for f in findings if f.severity == "warning"), "info": sum(1 for f in findings if f.severity == "info"),
                    "evidence_fresh": sum(1 for f in freshness.values() if f.evidence_id in in_play and f.fresh), "evidence_stale": sum(1 for f in freshness.values() if f.evidence_id in in_play and not f.fresh)},
        "coverage_note": "Findings reflect recorded locators, declared inputs and digests. Dependencies never recorded are not reported; treat absence as unknown.",
    }
