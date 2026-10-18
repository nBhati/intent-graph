"""Intent review packet (architecture section 14).

The tool selects the underlying records deterministically from the scope
closure and records the scope digest and coverage. The agent may add an
explanation section; the packet's structural coverage is checkable, the
faithfulness of prose is not.
"""
from __future__ import annotations

from typing import Any

from ..graph import GraphIndex
from ..model import NodeRecord
from ..obligations.scope import ClosureMember

SECTIONS: list[tuple[str, list[str], str]] = [
    ("What are we trying to achieve?", ["Goal", "Requirement"], "Goals and the requirements in scope."),
    ("What will the user experience?", ["Actor", "Scenario", "Screen", "Control", "Interaction", "PresentationRule"], "Scenarios and experience elements."),
    ("How will the main parts cooperate?", ["System", "Component", "ExternalSystem", "Interface", "Operation", "Port", "Process", "Action", "Event", "State", "Transition", "Entity", "ValueType", "Message", "Store"], "Structure, contracts and behavior."),
    ("Which rules, assumptions and decisions matter?", ["Constraint", "Assumption", "Decision"], "Cross-cutting rules, dependencies on uncertain facts, and chosen alternatives (including deferrals)."),
    ("What is still open?", ["Question"], "Unresolved intent."),
]


def build_review_packet(index: GraphIndex, scope: NodeRecord, closure: dict[str, ClosureMember], design_digest: str, policy_ref: str, readiness_status: str) -> dict[str, Any]:
    by_kind: dict[str, list[NodeRecord]] = {}
    for m in closure.values():
        n = index.nodes[m.id]
        if n.layer != "intent":
            continue
        by_kind.setdefault(n.kind, []).append(n)
    sections = []
    covered: list[str] = []
    for title, kinds, blurb in SECTIONS:
        entries = []
        for kind in kinds:
            for n in sorted(by_kind.get(kind, []), key=lambda n: n.id):
                entry = {"id": n.id, "kind": n.kind, "label": n.label, "description": n.description, "lifecycle": n.lifecycle,
                         "reason": closure[n.id].reason, "properties": _public_props(n)}
                if n.kind == "Decision" and n.properties.get("decision_kind") in ("deferral", "exclusion"):
                    entry["deferral_of"] = [e.target for e in index.out_edges(n.id, {"concerns"})]
                entries.append(entry)
                covered.append(n.id)
        sections.append({"title": title, "blurb": blurb, "entries": entries})
    exclusions = [{"id": n.id, "label": n.label, "concerns": [e.target for e in index.out_edges(n.id, {"concerns"})]}
                  for n in sorted(by_kind.get("Decision", []), key=lambda n: n.id) if n.properties.get("decision_kind") in ("deferral", "exclusion")]
    return {
        "scope": scope.id, "scope_label": scope.label, "policy": policy_ref, "design_digest": design_digest, "model_revision": index.snapshot.revision,
        "readiness_status": readiness_status, "coverage": {"ids": sorted(covered), "closure_count": len(closure), "intent_count": len(covered)},
        "exclusions_and_deferrals": exclusions, "sections": sections,
        "explanation": {"author": None, "text": "", "note": "Optional agent-written explanation. Structural coverage above is checkable; prose faithfulness still needs human review."},
    }


def _public_props(n: NodeRecord) -> dict[str, Any]:
    hide = {"expression"}  # formal expressions are summarized by their language, not dumped
    out = {k: v for k, v in n.properties.items() if k not in hide}
    if "expression" in n.properties:
        out["expression"] = f"<{n.properties.get('expression_language', 'expression')}>"
    return out


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [f"# Review: {packet['scope_label']}", "",
             f"Scope `{packet['scope']}` · policy `{packet['policy']}` · model revision {packet['model_revision']} · readiness **{packet['readiness_status']}**", "",
             f"Design digest: `{packet['design_digest']}`", ""]
    for s in packet["sections"]:
        lines += [f"## {s['title']}", "", f"_{s['blurb']}_", ""]
        if not s["entries"]:
            lines += ["(nothing in scope)", ""]
        for e in s["entries"]:
            tag = "" if e["lifecycle"] == "accepted" else f" _({e['lifecycle']})_"
            lines.append(f"- **{e['label']}** `{e['id']}` ({e['kind']}){tag}")
            if e["description"]:
                lines.append(f"  {e['description']}")
            interesting = {k: v for k, v in e["properties"].items() if k in ("priority", "status", "blocking", "decision_kind", "rationale", "constraint_kind", "scope", "expected_outcome", "steps", "inputs", "outputs", "failures", "concurrency_sensitive", "answer", "impact")}
            for k, v in interesting.items():
                lines.append(f"  - {k}: {v}")
            if e.get("deferral_of"):
                lines.append(f"  - deferral/exclusion of: {', '.join(e['deferral_of'])}")
        lines.append("")
    lines += ["## Exclusions and deferrals", ""]
    if packet["exclusions_and_deferrals"]:
        lines += [f"- {x['label']} (`{x['id']}`) concerning {', '.join(x['concerns'])}" for x in packet["exclusions_and_deferrals"]]
    else:
        lines.append("None recorded.")
    lines += ["", "## Explanation", "", packet["explanation"]["text"] or "_No explanation written yet. The coding agent may add one; it is a judgment, not a computed check._", "",
              "## Coverage", "", f"{packet['coverage']['intent_count']} intent records of {packet['coverage']['closure_count']} closure members are listed above. Ids: " + ", ".join(f"`{i}`" for i in packet["coverage"]["ids"]), ""]
    return "\n".join(lines)
