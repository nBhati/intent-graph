"""CLI behaviour in fresh processes: each call reconstructs state from files."""
import json
import subprocess
import sys
from pathlib import Path

from conftest import FIXTURES

CLI = [sys.executable, "-m", "intentgraph.cli.main"]


def run(*args, cwd: Path, expect: int):
    proc = subprocess.run([*CLI, "--json", *args], cwd=cwd, capture_output=True, text=True)
    assert proc.returncode == expect, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def test_full_cli_round_trip(tmp_path: Path):
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text("# Existing instructions\nKeep me.\n")
    out = run("init", "--name", "cli-demo", cwd=ws, expect=0)
    assert out["status"] == "ok" and out["data"]["created"] and out["data"]["pointer"]["status"] == "appended"
    assert (ws / "CLAUDE.md").read_text().startswith("# Existing instructions\nKeep me.")
    out = run("init", cwd=ws, expect=0)
    assert not out["data"]["created"] and out["data"]["pointer"]["status"] == "present"

    status = run("status", cwd=ws, expect=0)["data"]
    assert status["revision"] == 0

    patch = json.loads((FIXTURES / "coaching-patch.json").read_text())
    patch["base_revision"] = status["revision"]
    patch["base_digest"] = status["content_digest"]
    pfile = tmp_path / "patch.json"
    pfile.write_text(json.dumps(patch))

    out = run("patch", "validate", "--file", str(pfile), cwd=ws, expect=0)
    assert out["data"]["valid"]
    out = run("patch", "apply", "--file", str(pfile), cwd=ws, expect=0)
    assert out["data"]["revision"] == 1

    # Fresh process, nested cwd: state comes only from files.
    nested = ws / "lib" / "x"
    nested.mkdir(parents=True)
    status = run("status", cwd=nested, expect=0)["data"]
    assert status["revision"] == 1 and status["counts"]["nodes"] == 31
    assert status["outstanding"]["blocking_questions"] == ["question:cancel-scope"]
    assert status["outstanding"]["pending_obligations"] == ["obligation:cancel-late-arrival"]
    assert status["gates"]["status"] == "unsupported"

    # Stale base -> exit 3 with changed ids.
    out = run("patch", "apply", "--file", str(pfile), cwd=ws, expect=0)  # idempotent replay
    assert out["data"]["idempotent_replay"]
    patch["patch_id"] = "patch:second"
    pfile.write_text(json.dumps(patch))
    out = run("patch", "apply", "--file", str(pfile), cwd=ws, expect=3)
    assert out["status"] == "invalid" and out["error"]["code"] == "stale_base"
    assert "req:cancel-response" in out["error"]["details"]["changed_ids"]

    # Invalid candidate -> validate exits 2 and apply exits 3; nothing written.
    status = run("status", cwd=ws, expect=0)["data"]
    bad = {"patch_id": "patch:bad", "base_revision": 1, "base_digest": status["content_digest"], "operations": [
        {"op": "add_node", "record": {"id": "req:x", "kind": "Requirement", "label": "x", "layer": "intent", "provenance": {"author_role": "agent", "method": "t"}}}]}
    pfile.write_text(json.dumps(bad))
    out = run("patch", "validate", "--file", str(pfile), cwd=ws, expect=2)
    assert not out["data"]["valid"] and out["data"]["diagnostics"][0]["code"] == "invalid_property"
    out = run("patch", "apply", "--file", str(pfile), cwd=ws, expect=3)
    assert out["error"]["code"] == "validation_failed"
    assert run("status", cwd=ws, expect=0)["data"]["revision"] == 1

    out = run("vocabulary", "show", "depends_on", cwd=ws, expect=0)["data"]
    assert out["type"] == "relation" and out["definition"]["required_properties"] == ["dependency_kind"]
    out = run("vocabulary", "show", "Requirement", cwd=ws, expect=0)["data"]
    assert out["definition"]["properties"]["priority"]["enum"] == ["must", "should", "could"]
    run("vocabulary", "show", "Nope", cwd=ws, expect=3)

    out = run("view", "--focus", "operation:cancel-response", "--include", "parent_intent", cwd=ws, expect=0)["data"]
    assert "req:cancel-response" in out["selected_ids"]
    out = run("search", "--text", "late", cwd=ws, expect=0)["data"]
    assert out["count"] >= 2
    out = run("show", "req:cancel-response", cwd=ws, expect=0)["data"]
    assert {r["id"] for r in out["referenced_by"]} >= {"mapping:cancel-controller", "evidence:late-response-test"}

    out = run("check", cwd=ws, expect=0)["data"]
    assert not out["blocking"]
    out = run("rebuild", cwd=ws, expect=0)["data"]
    assert out["graph"] == {"nodes": 31, "edges": 20} and out["unresolved_references"] == []


def test_no_workspace_is_invalid_input(tmp_path: Path):
    out = run("status", cwd=tmp_path, expect=3)
    assert out["error"]["code"] == "workspace_not_found"


def test_human_output(tmp_path: Path):
    ws = tmp_path / "h"
    ws.mkdir()
    subprocess.run([*CLI, "init", "--no-pointer"], cwd=ws, check=True, capture_output=True)
    proc = subprocess.run([*CLI, "status"], cwd=ws, capture_output=True, text=True)
    assert proc.returncode == 0 and "revision 0" in proc.stdout
    assert not (ws / "AGENTS.md").exists()
