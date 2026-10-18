"""Evidence freshness (architecture sections 16.1 and 16.2).

Computed once and shared by ``reconcile`` and the ``evidence_required`` rule
so conformance and reconciliation cannot disagree. Conservative by design:
evidence with no workspace snapshot or no declared inputs is stale as soon as
its root changed at all; a missing or altered artifact drops the effective
collection mode to ``agent_assertion``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..graph import GraphIndex
from ..model import NodeRecord, digest_of
from ..repository import Repository
from ..repository.workspace import current_digests, file_digest, git_state, resolve_root


@dataclass
class Freshness:
    evidence_id: str
    fresh: bool
    effective_collection_mode: str
    reasons: list[str] = field(default_factory=list)
    source_changed: list[str] = field(default_factory=list)
    model_scope_changed: bool = False
    artifact_available: bool | None = None
    result: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"evidence_id": self.evidence_id, "fresh": self.fresh, "effective_collection_mode": self.effective_collection_mode, "reasons": self.reasons,
                "source_changed": self.source_changed, "model_scope_changed": self.model_scope_changed, "artifact_available": self.artifact_available, "result": self.result}


def model_scope_digest(index: GraphIndex, supported_ids: list[str]) -> str:
    """Digest of the design content of the records an evidence claims to support."""
    items = []
    for rid in sorted(set(supported_ids)):
        n = index.nodes.get(rid)
        if n is None:
            items.append({"id": rid, "missing": True})
        else:
            items.append({"id": n.id, "kind": n.kind, "label": n.label, "description": n.description, "properties": n.properties, "lifecycle": n.lifecycle})
    return digest_of(items)


def supported_ids(index: GraphIndex, ev: NodeRecord) -> list[str]:
    ids = set(ev.properties.get("supports", []))
    ids.update(e.target for e in index.out_edges(ev.id, {"supports"}))
    return sorted(ids)


def evaluate_freshness(index: GraphIndex, repo: Repository) -> dict[str, Freshness]:
    manifest = repo.load_manifest()
    out: dict[str, Freshness] = {}
    root_state_cache: dict[str, dict[str, Any]] = {}
    for ev in sorted(index.snapshot.nodes, key=lambda n: n.id):
        if ev.kind != "Evidence" or ev.lifecycle == "superseded":
            continue
        props = ev.properties
        mode = props.get("collection_mode", "agent_assertion")
        f = Freshness(evidence_id=ev.id, fresh=True, effective_collection_mode=mode, result=props.get("result", ""))

        # Artifact availability.
        art = props.get("artifact_ref")
        if art:
            path = repo.paths.root / art
            if not path.is_file():
                f.artifact_available = False
                f.reasons.append(f"artifact {art} is missing")
            elif props.get("artifact_digest") and file_digest(path) != props["artifact_digest"]:
                f.artifact_available = False
                f.reasons.append(f"artifact {art} no longer matches its recorded digest")
            else:
                f.artifact_available = True
            if f.artifact_available is False and mode != "agent_assertion":
                f.effective_collection_mode = "agent_assertion"
                f.reasons.append(f"effective collection mode downgraded from {mode} to agent_assertion")

        # Model content it supports.
        recorded = props.get("model_scope_digest")
        if recorded:
            if model_scope_digest(index, supported_ids(index, ev)) != recorded:
                f.model_scope_changed = True
                f.fresh = False
                f.reasons.append("the model content this evidence supports changed after submission")
        else:
            f.reasons.append("no model_scope_digest recorded; model drift cannot be detected for this evidence")

        # Source inputs.
        snap_ref = props.get("workspace_snapshot_ref")
        snap = index.nodes.get(snap_ref) if snap_ref else None
        if snap is None or snap.kind != "WorkspaceSnapshot":
            f.fresh = False
            f.reasons.append("no WorkspaceSnapshot bound to this evidence; treated as stale (conservative)")
        else:
            repository = snap.properties.get("repository", ".")
            try:
                root = resolve_root(repo.paths, manifest, repository)
            except Exception as exc:  # unknown root: conservative
                f.fresh = False
                f.reasons.append(f"repository root {repository!r} cannot be resolved: {exc}")
                out[ev.id] = f
                continue
            files: dict[str, str] = snap.properties.get("files", {})
            if files:
                now = current_digests(root, sorted(files))
                changed = sorted(p for p, d in files.items() if now.get(p) != d)
                if changed:
                    f.source_changed = changed
                    f.fresh = False
                    f.reasons.append(f"declared inputs changed since capture: {', '.join(changed[:8])}" + (" ..." if len(changed) > 8 else ""))
            else:
                state = root_state_cache.setdefault(repository, git_state(root))
                if not state["git_available"]:
                    f.fresh = False
                    f.reasons.append("no declared inputs and no Git: cannot establish that the root is unchanged (conservative)")
                elif state["head"] != snap.properties.get("head") or state["dirty"]:
                    f.fresh = False
                    f.reasons.append("no declared inputs and the root changed since capture (HEAD moved or working tree dirty)")
            for name, digest in (snap.properties.get("lockfiles") or {}).items():
                target = root / name
                if not target.is_file() or file_digest(target) != digest:
                    f.fresh = False
                    f.reasons.append(f"dependency lockfile {name} changed since capture")
        out[ev.id] = f
    return out
