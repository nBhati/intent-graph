"""``intentgraph`` command-line interface (architecture section 12).

Exit codes: 0 success / no blocking findings; 2 completed check with blockers;
3 invalid input or stale revision; 4 unavailable dependency or internal
failure. JSON output carries the precise status in every case.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .. import TOOL_VERSION, services
from ..errors import IntentGraphError

EXIT_OK = 0
EXIT_BLOCKED = 2
EXIT_INVALID = 3
EXIT_FAILURE = 4


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="intentgraph", description="Local, agent-operated model of software intent, design, mappings and evidence.")
    p.add_argument("--version", action="version", version=f"intentgraph {TOOL_VERSION}")
    p.add_argument("--json", action="store_true", help="emit a machine-readable JSON response")
    p.add_argument("--workspace", type=Path, default=None, help="directory at or below the workspace root (default: current directory)")
    # The same global flags are accepted after the subcommand (``intentgraph status --json``).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--workspace", type=Path, default=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", parents=[common], help="create project files and the agent entry pointer (idempotent)")
    s.add_argument("path", nargs="?", type=Path, default=Path("."))
    s.add_argument("--name", default=None)
    s.add_argument("--project-id", default=None)
    s.add_argument("--no-pointer", action="store_true", help="do not touch CLAUDE.md/AGENTS.md")

    sub.add_parser("status", parents=[common], help="current revision, counts, outstanding work and structural health")
    sub.add_parser("check", parents=[common], help="structural checks and current diagnostics")
    sub.add_parser("rebuild", parents=[common], help="discard caches, reconstruct indexes, report unresolved references")

    v = sub.add_parser("vocabulary", help="kind and relation definitions")
    vs = v.add_subparsers(dest="vocab_command", required=True)
    vs.add_parser("list", parents=[common])
    vshow = vs.add_parser("show", parents=[common])
    vshow.add_argument("name")

    s = sub.add_parser("view", parents=[common], help="compute a task-specific lens")
    s.add_argument("--request", type=Path, help="JSON file with a lens request")
    s.add_argument("--focus", nargs="*", default=None, help="focal node ids (alternative to --request)")
    s.add_argument("--depth", type=int, default=None)
    s.add_argument("--include", nargs="*", default=None, help="parent_intent constraints implementations findings neighbors")

    s = sub.add_parser("search", parents=[common], help="find records by text and structured filters")
    s.add_argument("--text", default="")
    s.add_argument("--kind", default=None)
    s.add_argument("--layer", default=None)
    s.add_argument("--lifecycle", default=None)
    s.add_argument("--limit", type=int, default=50)

    s = sub.add_parser("impact", parents=[common], help="dependency slice: recorded elements a change may affect")
    s.add_argument("--changed", nargs="+", required=True, help="changed record ids (nodes or edges)")
    s.add_argument("--depth", type=int, default=3)
    s.add_argument("--relations", nargs="*", default=None, help="restrict traversal to these relation kinds")
    s.add_argument("--no-references", action="store_true", help="do not follow property references")
    s.add_argument("--max-candidates", type=int, default=200)

    s = sub.add_parser("diff", parents=[common], help="changes between model revisions")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--since", type=int, help="ids changed after this revision (from transaction summaries)")
    g.add_argument("--file", type=Path, help="another snapshot file as the baseline")
    g.add_argument("--git", metavar="REF", help="the model at this Git revision as the baseline")

    s = sub.add_parser("readiness", parents=[common], help="evaluate pre-build obligations for a scope")
    s.add_argument("--scope", required=True)
    s.add_argument("--policy", default=None)
    s = sub.add_parser("conformance", parents=[common], help="evaluate post-build obligations for a scope")
    s.add_argument("--scope", required=True)
    s.add_argument("--policy", default=None)

    rv = sub.add_parser("review", help="graph-grounded review packets")
    rvs = rv.add_subparsers(dest="review_command", required=True)
    s = rvs.add_parser("export", parents=[common])
    s.add_argument("--scope", required=True)
    s.add_argument("--record", action="store_true", help="record/update the ReviewArtifact node for the scope")
    s.add_argument("--out", type=Path, default=None)

    ap = sub.add_parser("approval", help="source-backed user decisions")
    aps = ap.add_subparsers(dest="approval_command", required=True)
    s = aps.add_parser("record", parents=[common])
    s.add_argument("--file", type=Path, required=True, help="JSON: scope_ref, recorded_by, source_statement, [approval_kind], [source_ref]")

    po = sub.add_parser("policy", help="readiness and conformance policies")
    pos = po.add_subparsers(dest="policy_command", required=True)
    pos.add_parser("list", parents=[common])
    s = pos.add_parser("show", parents=[common])
    s.add_argument("id")

    s = sub.add_parser("migrate", parents=[common], help="preview (default) or apply explicit model migrations")
    s.add_argument("--apply", action="store_true")

    s = sub.add_parser("show", parents=[common], help="one record with its edges and referrers")
    s.add_argument("id")

    pt = sub.add_parser("patch", help="validated model updates")
    ps = pt.add_subparsers(dest="patch_command", required=True)
    for name in ("validate", "apply"):
        sp = ps.add_parser(name, parents=[common])
        sp.add_argument("--file", type=Path, required=True)
    return p


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IntentGraphError(f"cannot read JSON file {path}: {exc}", code="invalid_input") from exc
    if not isinstance(data, dict):
        raise IntentGraphError(f"{path} must contain a JSON object", code="invalid_input")
    return data


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    start = args.workspace
    cmd = args.command
    if cmd == "init":
        data = services.init_workspace(args.path, name=args.name, project_id=args.project_id, pointer=not args.no_pointer)
        return EXIT_OK, data
    if cmd == "rebuild":
        data = services.rebuild(start)
        return (EXIT_BLOCKED if data["blocking"] else EXIT_OK), data
    if cmd == "review":
        repo = services.Repository.find(start)
        data = services.review_export(repo, args.scope, record=args.record, out_path=args.out)
        return EXIT_OK, data
    if cmd == "approval":
        repo = services.Repository.find(start)
        return EXIT_OK, services.approval_record(repo, _read_json_file(args.file))
    if cmd == "migrate":
        repo = services.Repository.find(start)
        data = services.migrate(repo, apply=args.apply)
        return (EXIT_BLOCKED if data["blocking_after"] else EXIT_OK), data
    if cmd == "patch" and args.patch_command == "apply":
        repo = services.Repository.find(start)
        patch = services.load_patch(_read_json_file(args.file))
        return EXIT_OK, services.patch_apply(repo, patch)

    ctx = services.Context.open(start)
    if cmd == "status":
        data = services.status(ctx)
        return (EXIT_BLOCKED if data["structural"]["errors"] else EXIT_OK), data
    if cmd == "check":
        data = services.check(ctx)
        return (EXIT_BLOCKED if data["blocking"] else EXIT_OK), data
    if cmd == "vocabulary":
        if args.vocab_command == "list":
            return EXIT_OK, services.vocabulary_list(ctx)
        return EXIT_OK, services.vocabulary_show(ctx, args.name)
    if cmd == "view":
        if args.request is not None:
            request = _read_json_file(args.request)
        elif args.focus:
            request = {"focus": args.focus}
            if args.depth is not None:
                request["depth"] = args.depth
            if args.include is not None:
                request["include"] = args.include
        else:
            raise IntentGraphError("view requires --request FILE or --focus ID...", code="invalid_input")
        data = services.view(ctx, request)
        return (EXIT_BLOCKED if data["status"] == "overflow" else EXIT_OK), data
    if cmd == "search":
        return EXIT_OK, services.search(ctx, text=args.text, kind=args.kind, layer=args.layer, lifecycle=args.lifecycle, limit=args.limit)
    if cmd == "show":
        return EXIT_OK, services.show_record(ctx, args.id)
    if cmd in ("readiness", "conformance"):
        data = services.readiness(ctx, args.scope, policy_id=args.policy, kind=cmd)
        return (EXIT_OK if data["status"] == "ready" else EXIT_BLOCKED), data
    if cmd == "policy":
        return EXIT_OK, (services.policy_list(ctx) if args.policy_command == "list" else services.policy_show(ctx, args.id))
    if cmd == "impact":
        request: dict[str, Any] = {"changed": args.changed, "max_depth": args.depth, "include_references": not args.no_references, "max_candidates": args.max_candidates}
        if args.relations is not None:
            request["relations"] = args.relations
        return EXIT_OK, services.impact(ctx, request)
    if cmd == "diff":
        return EXIT_OK, services.diff(ctx, since=args.since, file=args.file, git_ref=args.git)
    if cmd == "patch" and args.patch_command == "validate":
        patch = services.load_patch(_read_json_file(args.file))
        data = services.patch_validate(ctx, patch)
        return (EXIT_OK if data["valid"] else EXIT_BLOCKED), data
    raise IntentGraphError(f"unknown command {cmd!r}", code="invalid_input")


def _status_name(code: int) -> str:
    return {EXIT_OK: "ok", EXIT_BLOCKED: "blocked", EXIT_INVALID: "invalid", EXIT_FAILURE: "error"}[code]


def _human(command: str, data: dict[str, Any]) -> str:
    lines: list[str] = []
    if command == "status":
        lines.append(f"{data['name']} ({data['project_id']}) revision {data['revision']} digest {data['content_digest'][:19]}...")
        c = data["counts"]
        lines.append(f"{c['nodes']} nodes, {c['edges']} edges; layers {c['by_layer']}; lifecycle {c['by_lifecycle']}")
        o = data["outstanding"]
        lines.append(f"outstanding: {len(o['open_questions'])} open questions ({len(o['blocking_questions'])} blocking), {len(o['pending_obligations'])} pending obligations, {len(o['open_findings'])} open findings, {o['proposed_records']} proposed records")
        lines.append(f"structural: {data['structural']['errors']} errors, {data['structural']['warnings']} warnings")
        g = data["gates"]
        if g["status"] == "evaluated":
            for sc in g["scopes"]:
                lines.append(f"gate {sc['scope']}: readiness {sc['readiness']}, {sc.get('blocking_obligations', '?')} blocking obligation(s), approval {sc.get('approval')}")
        else:
            lines.append(f"gates: {g['status']}")
    elif command in ("check", "rebuild"):
        lines.append(f"revision {data['revision']}: {'BLOCKING errors' if data['blocking'] else 'no blocking errors'}")
        if command == "rebuild":
            lines.append(f"graph: {data['graph']['nodes']} nodes, {data['graph']['edges']} edges; unresolved references: {data['unresolved_references'] or 'none'}")
    elif command == "init":
        lines.append(f"{'created' if data['created'] else 'existing'} workspace {data['workspace']} ({data['project_id']})")
        lines.append(f"agent pointer: {data['pointer']}")
    elif command == "search":
        lines.append(f"{data['count']} record(s)")
        for r in data["records"]:
            lines.append(f"  {r['id']}  [{r['kind']}/{r['lifecycle']}]  {r['label']}")
    elif command == "view":
        lines.append(f"lens {data['status']}: {len(data['selected_ids'])} records, {len(data['edges'])} edges, {len(data['boundary'])} boundary edges, revision {data['source_revision']}")
        for n in data["nodes"]:
            lines.append(f"  {n['id']}  [{n['kind']}/{n['lifecycle']}]  {n['label']}")
        for e in data["edges"]:
            lines.append(f"  {e['source']} -{e['kind']}-> {e['target']}")
        if data["message"]:
            lines.append(data["message"])
    elif command == "impact":
        lines.append(f"impact of {data['changed']} at revision {data['source_revision']}: {len(data['candidates'])} candidate(s) {data['by_category']}")
        for c in data["candidates"]:
            via = " <- ".join(f"{s['via']}" for s in reversed(c["path"]))
            lines.append(f"  d{c['distance']} {c['id']}  [{c['kind']}/{c['lifecycle']}]  {c['label']}   via {via}")
        if data["truncated"]:
            lines.append(f"truncated: {data['omitted_count']} more reachable record(s) omitted")
        lines.append(data["coverage_note"])
    elif command == "diff":
        if data["mode"] == "transactions":
            lines.append(f"revisions {data['from_revision']} -> {data['to_revision']}: {data['summary']} across {len(data['transactions'])} transaction(s)")
            for name in ("added_ids", "updated_ids", "removed_ids"):
                for i in data[name]:
                    lines.append(f"  {name[0]} {i}")
        else:
            lines.append(f"{data['mode']} baseline {data['baseline']} (rev {data['from_revision']}) -> rev {data['to_revision']}: {data['summary']}")
            for r in data["added"]:
                lines.append(f"  + {r['id']}  [{r['kind']}]  {r['label']}")
            for r in data["removed"]:
                lines.append(f"  - {r['id']}  [{r['kind']}]  {r['label']}")
            for r in data["changed"]:
                lines.append(f"  ~ {r['id']}  [{r['kind']}]  fields {r['fields_changed']} properties {r['properties_changed']}" + (f" lifecycle {r['lifecycle'][0]}->{r['lifecycle'][1]}" if r["lifecycle"] else ""))
    elif command in ("readiness", "conformance"):
        lines.append(f"{data['scope']} under {data['policy']}: {data['status'].upper()} at revision {data['model_revision']} (closure {data['closure']['count']} records, design digest {data['design_digest'][:23]}...)")
        for o in data["obligations"]:
            lines.append(f"  [{o['state']}] {o['id']}: {o['request']}  -> {', '.join(o['acceptable_resolution'])}")
        for o in data["warnings"]:
            lines.append(f"  [warning] {o['id']}: {o['request']}")
        for o in data["waived"]:
            lines.append(f"  [waived] {o['id']} by {o['waiver'].get('authorized_by')}: {o['waiver'].get('reason')}")
        lines.append(f"approval: {data['approval']}")
        lines.append(data["note"])
    elif command == "review":
        lines.append(f"review packet for {data['scope']} ({data['readiness_status']}) written to {data['markdown']}; covers {data['coverage']['intent_count']} intent records; digest {data['design_digest'][:23]}...")
        if data["recorded"]:
            lines.append(f"recorded ReviewArtifact -> revision {data['recorded']['revision']}")
    elif command == "approval":
        lines.append(f"recorded {data['approval_id']} for {data['scope']} at design digest {data['design_digest'][:23]}... (revision {data['revision']}); status after: {data['approval_status_after']['status']}")
    elif command == "migrate":
        lines.append(f"vocabulary {data['current_vocabulary']} -> {data['target_vocabulary']}: {len(data['steps'])} step(s); {'APPLIED' if data['applied'] else 'preview only'}; {'blocking errors after' if data['blocking_after'] else 'no blocking errors after'}")
        for st in data["steps"]:
            lines.append(f"  {st['id']}: {st['description']}")
        if data["backup"]:
            lines.append(f"backup: {data['backup']}")
    elif command == "policy":
        return json.dumps(data, indent=2, sort_keys=True)
    elif command == "patch":
        if "applied" in data:
            lines.append(f"applied {data['patch_id']} -> revision {data['revision']}{' (idempotent replay)' if data['idempotent_replay'] else ''}")
        else:
            eff = data["effects"]
            lines.append(f"{data['patch_id']}: {'valid' if data['valid'] else 'INVALID'}; +{len(eff['added_ids'])} added, ~{len(eff['updated_ids'])} updated, -{len(eff['removed_ids'])} removed")
    else:
        return json.dumps(data, indent=2, sort_keys=True)
    for d in data.get("diagnostics", []) + data.get("diagnostics_after", []) + data.get("findings", []):
        lines.append(f"  [{d['severity']}] {d['code']}: {d['message']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    envelope: dict[str, Any] = {"command": args.command, "tool_version": TOOL_VERSION}
    try:
        code, data = run(args)
        envelope["status"] = _status_name(code)
        envelope["data"] = data
    except IntentGraphError as exc:
        code = exc.exit_code
        envelope["status"] = _status_name(code)
        envelope["error"] = exc.to_dict()
    except Exception as exc:  # pragma: no cover - last resort
        code = EXIT_FAILURE
        envelope["status"] = "error"
        envelope["error"] = {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}", "details": {}}
    if args.json:
        print(json.dumps(envelope, indent=2, sort_keys=True))
    elif "error" in envelope:
        err = envelope["error"]
        print(f"error [{err['code']}]: {err['message']}", file=sys.stderr)
        if err["details"]:
            print(json.dumps(err["details"], indent=2, sort_keys=True), file=sys.stderr)
    else:
        try:
            print(_human(args.command, envelope["data"]))
        except Exception:  # never let a formatting problem hide a successful result
            print(json.dumps(envelope["data"], indent=2, sort_keys=True))
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
