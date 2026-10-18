"""Milestone 5: recovery, capabilities, versioned responses, review diagrams."""
import json
import subprocess
import sys

import pytest

from intentgraph.errors import CorruptSnapshot, InvalidInput
from intentgraph.repository import Repository
from intentgraph.services import Context, capabilities, migrate, recover, review_export, status, tool_info


def test_recover_from_backup_and_from_git(coaching_repo: Repository):
    paths = coaching_repo.paths
    # Produce a backup through a migration from an older vocabulary.
    snap = coaching_repo.load_snapshot(); snap.vocabulary_version = "core/0.1"; coaching_repo.write_snapshot(snap)
    applied = migrate(coaching_repo, apply=True)
    good = coaching_repo.load_snapshot()
    listing = recover(paths.root, from_backup=None, from_git=None, apply=False)
    assert listing["current"]["status"] == "healthy" and listing["backups"][0]["path"] == applied["backup"]
    # Damage the file.
    paths.model.write_text(paths.model.read_text()[:200])
    assert recover(paths.root, from_backup=None, from_git=None, apply=False)["current"]["status"] == "corrupt"
    with pytest.raises(CorruptSnapshot):
        Context(coaching_repo)
    preview = recover(paths.root, from_backup=applied["backup"], from_git=None, apply=False)
    assert not preview["applied"] and preview["revision"] == 1 and paths.model.read_text().endswith(paths.model.read_text()[-5:])
    done = recover(paths.root, from_backup=applied["backup"], from_git=None, apply=True)
    assert done["applied"] and done["verified_digest"] == done["content_digest"] and done["damaged_copy"]
    restored = coaching_repo.load_snapshot()
    assert restored.revision == 1 and restored.vocabulary_version == "core/0.1" and done.get("manifest_vocabulary_updated")
    assert json.loads(paths.project.read_text())["vocabulary_version"] == "core/0.1"
    # Git source.
    root = paths.root
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x", "HOME": str(root), "PATH": "/usr/bin:/bin"}
    coaching_repo.write_snapshot(good)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True); subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "good"], cwd=root, check=True, env=env)
    paths.model.unlink()
    assert recover(paths.root, from_backup=None, from_git=None, apply=False)["current"]["status"] == "missing"
    done = recover(paths.root, from_backup=None, from_git="HEAD", apply=True)
    assert done["applied"] and coaching_repo.load_snapshot().content_digest == good.content_digest
    with pytest.raises(InvalidInput):
        recover(paths.root, from_backup=applied["backup"], from_git="HEAD", apply=False)
    same = recover(paths.root, from_backup=None, from_git="HEAD", apply=True)
    assert not same["applied"] and "already matches" in same["note"]


def test_capabilities_and_version():
    info = tool_info()
    assert info["tool_version"] == "0.1.0" and info["response_version"] == "1" and info["format_version"] == "0.1"
    caps = capabilities()
    assert "reconcile" in caps["supported"]["commands"] and "evidence_required" in caps["supported"]["policy_rule_types"]
    assert caps["supported"]["installation"][0].startswith("uv tool install")
    unsupported = {u["capability"]: u["status"] for u in caps["unsupported"]}
    assert unsupported["standalone executables"] == "deferred" and unsupported["MCP server"] == "not implemented"


def test_envelope_carries_response_version(tmp_path):
    proc = subprocess.run([sys.executable, "-m", "intentgraph.cli.main", "version", "--json"], cwd=tmp_path, capture_output=True, text=True)
    out = json.loads(proc.stdout)
    assert proc.returncode == 0 and out["response_version"] == "1" and out["status"] == "ok" and out["data"]["tool_version"] == "0.1.0"
    proc = subprocess.run([sys.executable, "-m", "intentgraph.cli.main", "status", "--json"], cwd=tmp_path, capture_output=True, text=True)
    out = json.loads(proc.stdout)
    assert proc.returncode == 3 and out["response_version"] == "1" and out["error"]["code"] == "workspace_not_found"


def test_review_packet_diagram_from_fixture(coaching_repo: Repository):
    from intentgraph.patches import Patch
    from intentgraph.services import patch_apply
    snap = coaching_repo.load_snapshot()
    patch_apply(coaching_repo, Patch.model_validate({"patch_id": "patch:scope", "base_revision": snap.revision, "base_digest": snap.content_digest, "operations": [
        {"op": "add_node", "record": {"id": "scope:all", "kind": "Scope", "label": "All", "layer": "reconciliation", "lifecycle": "accepted", "properties": {"member_refs": ["system:coaching-app"], "status": "active"}, "provenance": {"author_role": "agent", "method": "t"}}}]}))
    out = review_export(coaching_repo, "scope:all")
    packet = json.loads(open(out["json"]).read())
    d = packet["diagram"]
    assert d["format"] == "mermaid" and d["text"].startswith("flowchart LR")
    assert "depends_on (runtime)" in d["text"] and "depends_on (build)" in d["text"] and "exposes" in d["text"]
    assert {"system:coaching-app", "component:playback-controller", "component:response-coordinator", "interface:response-events"} <= set(d["depicts"])
    md = open(out["markdown"]).read()
    assert "```mermaid" in md
    # Too little structure: no diagram.
    patch_apply(coaching_repo, Patch.model_validate({"patch_id": "patch:scope2", "base_revision": coaching_repo.load_snapshot().revision, "base_digest": coaching_repo.load_snapshot().content_digest, "operations": [
        {"op": "add_node", "record": {"id": "scope:one", "kind": "Scope", "label": "One", "layer": "reconciliation", "lifecycle": "accepted", "properties": {"member_refs": ["req:cancel-response"], "status": "active"}, "provenance": {"author_role": "agent", "method": "t"}}}]}))
    assert json.loads(open(review_export(coaching_repo, "scope:one")["json"]).read())["diagram"] is None
