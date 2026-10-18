import json
import subprocess

import pytest

from intentgraph.errors import InvalidInput, NotSupported
from intentgraph.patches import Patch
from intentgraph.repository import Repository
from intentgraph.services import Context, diff, patch_apply


def _goal(i):
    return {"op": "add_node", "record": {"id": i, "kind": "Goal", "label": i, "layer": "intent", "provenance": {"author_role": "user", "method": "t"}}}


def _apply(repo, pid, ops):
    snap = repo.load_snapshot()
    return patch_apply(repo, Patch.model_validate({"patch_id": pid, "base_revision": snap.revision, "base_digest": snap.content_digest, "operations": ops}))


def test_changes_since_uses_transactions(coaching_repo: Repository):
    _apply(coaching_repo, "patch:a", [_goal("goal:a"), {"op": "update_properties", "id": "operation:cancel-response", "changes": {"idempotent": False}}])
    _apply(coaching_repo, "patch:b", [{"op": "remove", "id": "goal:a"}, {"op": "update_fields", "id": "req:stop-active-response", "lifecycle": "accepted"}])
    res = diff(Context(coaching_repo), since=1)
    assert res["mode"] == "transactions" and res["from_revision"] == 1 and res["to_revision"] == 3
    assert res["added_ids"] == []  # added then removed
    assert res["removed_ids"] == ["goal:a"]
    assert res["updated_ids"] == ["operation:cancel-response", "req:stop-active-response"]
    assert [t["patch_id"] for t in res["transactions"]] == ["patch:a", "patch:b"]
    with pytest.raises(InvalidInput):
        diff(Context(coaching_repo), since=99)
    with pytest.raises(InvalidInput):
        diff(Context(coaching_repo))


def test_diff_against_file(coaching_repo: Repository, tmp_path):
    baseline = tmp_path / "old-model.json"
    baseline.write_text(coaching_repo.paths.model.read_text())
    _apply(coaching_repo, "patch:a", [_goal("goal:a"), {"op": "update_properties", "id": "operation:cancel-response", "changes": {"idempotent": False, "failures": None}},
                                       {"op": "update_fields", "id": "req:stop-active-response", "lifecycle": "accepted", "label": "renamed"},
                                       {"op": "remove", "id": "edge:decision-concerns-req"}])
    res = diff(Context(coaching_repo), file=baseline)
    assert res["mode"] == "file" and res["summary"] == {"added": 1, "removed": 1, "changed": 2}
    assert res["added"][0]["id"] == "goal:a" and res["removed"][0]["id"] == "edge:decision-concerns-req"
    changed = {c["id"]: c for c in res["changed"]}
    assert changed["operation:cancel-response"]["properties_changed"] == ["failures", "idempotent"]
    assert changed["req:stop-active-response"]["fields_changed"] == ["label", "lifecycle"]
    assert changed["req:stop-active-response"]["lifecycle"] == ["proposed", "accepted"]
    assert [t["patch_id"] for t in res["transactions_between"]] == ["patch:a"]
    # A hand-edited baseline is rejected like any other snapshot.
    data = json.loads(baseline.read_text()); data["revision"] = 7; baseline.write_text(json.dumps(data))
    with pytest.raises(Exception) as exc:
        diff(Context(coaching_repo), file=baseline)
    assert "digest" in str(exc.value)


def test_diff_against_git_ref(coaching_repo: Repository):
    root = coaching_repo.paths.root
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x", "HOME": str(root)}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base"], cwd=root, check=True, env=env)
    _apply(coaching_repo, "patch:a", [_goal("goal:a")])
    res = diff(Context(coaching_repo), git_ref="HEAD")
    assert res["mode"] == "git" and res["from_revision"] == 1 and res["to_revision"] == 2
    assert [a["id"] for a in res["added"]] == ["goal:a"]
    with pytest.raises(NotSupported) as exc:
        diff(Context(coaching_repo), git_ref="no-such-ref")
    assert exc.value.code == "git_failed"


def test_git_unavailable_is_reported(coaching_repo: Repository, monkeypatch):
    from intentgraph.repository import gitio
    monkeypatch.setattr(gitio.shutil, "which", lambda name: None)
    with pytest.raises(NotSupported) as exc:
        diff(Context(coaching_repo), git_ref="HEAD")
    assert exc.value.code == "git_unavailable" and exc.value.exit_code == 4
