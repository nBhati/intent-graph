"""Milestone 5 validation (architecture section 21.8, revised): a clean, isolated install of the built
wheel via `uv tool install`, with no source tree on the path, runs the whole loop; reinstalling preserves
project files; uninstalling the tool leaves them intact.

Skipped when `uv` is unavailable. The wheel is built by the test unless INTENTGRAPH_WHEEL points at a
dist directory that already holds one.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UV = shutil.which("uv")

pytestmark = pytest.mark.skipif(UV is None, reason="uv not installed")


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    env_dist = os.environ.get("INTENTGRAPH_WHEEL")
    dist = Path(env_dist) if env_dist else tmp_path_factory.mktemp("dist")
    wheels = sorted(dist.glob("intentgraph-*.whl"))
    if not wheels:
        subprocess.run([UV, "build", "--wheel", "--out-dir", str(dist)], cwd=ROOT, check=True, capture_output=True)
        wheels = sorted(dist.glob("intentgraph-*.whl"))
    assert wheels, "no wheel built"
    return wheels[-1]


@pytest.fixture(scope="module")
def tool(wheel: Path, tmp_path_factory):
    """`intentgraph` installed into an isolated uv tool environment (own tool dir and bin dir)."""
    home = tmp_path_factory.mktemp("uvhome")
    env = {**os.environ, "UV_TOOL_DIR": str(home / "tools"), "UV_TOOL_BIN_DIR": str(home / "bin")}
    subprocess.run([UV, "tool", "install", "--python", sys.executable, str(wheel)], check=True, capture_output=True, env=env)
    exe = home / "bin" / "intentgraph"
    assert exe.is_file()
    return {"exe": exe, "env": env, "wheel": wheel}


def run(tool, *args, cwd: Path, expect=0):
    # A minimal environment: no PYTHONPATH, no source tree, cwd outside the repository.
    env = {"PATH": str(tool["exe"].parent) + os.pathsep + os.path.dirname(shutil.which("git") or "/usr/bin"), "HOME": str(cwd), "UV_TOOL_DIR": tool["env"]["UV_TOOL_DIR"], "UV_TOOL_BIN_DIR": tool["env"]["UV_TOOL_BIN_DIR"]}
    proc = subprocess.run([str(tool["exe"]), *args, "--json"], cwd=cwd, capture_output=True, text=True, env=env)
    assert proc.returncode == expect, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["response_version"] == "1"
    return out["data"]


def test_clean_install_runs_the_whole_loop(tool, tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    v = run(tool, "version", cwd=ws)
    assert v["tool_version"] == "0.1.0" and not v["bundled"]
    assert run(tool, "init", "--name", "clean", cwd=ws)["created"]
    st = run(tool, "status", cwd=ws)
    assert st["revision"] == 0 and (ws / ".intentgraph" / "model.json").is_file() and (ws / "AGENTS.md").is_file()
    patch = json.loads((ROOT / "tests" / "fixtures" / "coaching-patch.json").read_text())
    patch.update(base_revision=0, base_digest=st["content_digest"])
    (ws / "patch.json").write_text(json.dumps(patch))
    assert run(tool, "patch", "apply", "--file", "patch.json", cwd=ws)["revision"] == 1
    # Restart: every call is a fresh process; query and modify.
    assert run(tool, "search", "--text", "restart speech", "--kind", "Requirement", cwd=ws)["count"] == 1
    assert "req:cancel-response" in run(tool, "view", "--focus", "operation:cancel-response", "--include", "parent_intent", cwd=ws)["selected_ids"]
    st = run(tool, "status", cwd=ws)
    manifest = json.loads((ws / ".intentgraph" / "project.json").read_text()); manifest["roots"] = {".": ".", "app": "."}
    (ws / ".intentgraph" / "project.json").write_text(json.dumps(manifest))
    for rel in ("lib/coaching/playback_controller.dart", "backend/coaching/coordinator.py", "test/coaching/cancel_test.dart"):
        (ws / rel).parent.mkdir(parents=True, exist_ok=True); (ws / rel).write_text("stub\n")
    scope = {"patch_id": "patch:scope", "base_revision": st["revision"], "base_digest": st["content_digest"], "operations": [
        {"op": "add_node", "record": {"id": "scope:cancel", "kind": "Scope", "label": "Cancellation", "layer": "reconciliation", "lifecycle": "accepted",
                                      "properties": {"member_refs": ["component:response-coordinator", "req:cancel-response"], "status": "active"}, "provenance": {"author_role": "agent", "method": "t"}}},
        {"op": "update_properties", "id": "obligation:cancel-late-arrival", "changes": {"state": "satisfied"}}]}
    (ws / "scope.json").write_text(json.dumps(scope))
    run(tool, "patch", "apply", "--file", "scope.json", cwd=ws)
    assert run(tool, "readiness", "--scope", "scope:cancel", cwd=ws, expect=2)["status"] == "needs_work"
    run(tool, "review", "export", "--scope", "scope:cancel", "--record", cwd=ws)
    assert run(tool, "readiness", "--scope", "scope:cancel", cwd=ws)["status"] == "ready"
    (ws / "approval.json").write_text(json.dumps({"scope_ref": "scope:cancel", "recorded_by": "user", "source_statement": "build it"}))
    assert run(tool, "approval", "record", "--file", "approval.json", cwd=ws)["approval_status_after"]["status"] == "current"
    (ws / "ev.json").write_text(json.dumps({"id": "evidence:clean", "method": "unit_test", "result": "passed", "collection_mode": "agent_submitted_report", "supports": ["req:cancel-response"],
                                            "inputs": {"repository": "app", "paths": ["lib/coaching/playback_controller.dart"]}}))
    run(tool, "evidence", "submit", "--file", "ev.json", cwd=ws)
    assert run(tool, "reconcile", "--scope", "scope:cancel", cwd=ws)["conformance"]["status"] == "ready"
    (ws / "lib/coaching/playback_controller.dart").write_text("changed\n")
    rec = run(tool, "reconcile", "--scope", "scope:cancel", cwd=ws, expect=2)
    assert any(f["code"] == "source_changed" for f in rec["findings"])
    assert run(tool, "capabilities", cwd=ws)["supported"]["installation"][0].startswith("uv tool install")


def test_reinstall_and_uninstall_preserve_project_files(tool, tmp_path):
    ws = tmp_path / "proj2"
    ws.mkdir()
    run(tool, "init", "--name", "keep", cwd=ws)
    before = {p.relative_to(ws): p.read_bytes() for p in ws.rglob("*") if p.is_file()}
    # Reinstall (the upgrade path with a single published version) and a second init: nothing overwritten.
    subprocess.run([UV, "tool", "install", "--reinstall", "--python", sys.executable, str(tool["wheel"])], check=True, capture_output=True, env=tool["env"])
    out = run(tool, "init", cwd=ws)
    assert not out["created"] and out["pointer"]["status"] == "present"
    assert run(tool, "migrate", cwd=ws)["steps"] == []
    after = {p.relative_to(ws): p.read_bytes() for p in ws.rglob("*") if p.is_file()}
    assert after == before
    # Uninstall the tool: the project files remain and are still a valid snapshot.
    subprocess.run([UV, "tool", "uninstall", "intentgraph"], check=True, capture_output=True, env=tool["env"])
    assert not tool["exe"].exists()
    assert {p.relative_to(ws): p.read_bytes() for p in ws.rglob("*") if p.is_file()} == before
    from intentgraph.repository.store import load_snapshot_file
    assert load_snapshot_file(ws / ".intentgraph" / "model.json").revision == 0
    # Reinstall for any later tests in this module.
    subprocess.run([UV, "tool", "install", "--python", sys.executable, str(tool["wheel"])], check=True, capture_output=True, env=tool["env"])
