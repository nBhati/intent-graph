import json

import pytest

from intentgraph.errors import InvalidInput
from intentgraph.model import Snapshot, compute_digest
from intentgraph.repository import Repository
from intentgraph.services import Context, migrate, status


def _downgrade_to_0_1(repo: Repository) -> None:
    """Simulate a workspace written by the previous tool version."""
    snap = repo.load_snapshot()
    snap.vocabulary_version = "core/0.1"
    repo.write_snapshot(snap)
    data = json.loads(repo.paths.project.read_text())
    data["vocabulary_version"] = "core/0.1"
    repo.paths.project.write_text(json.dumps(data))


def test_old_vocabulary_is_readable_but_flagged(coaching_repo: Repository):
    _downgrade_to_0_1(coaching_repo)
    st = status(Context(coaching_repo))
    assert st["vocabulary_version"] == "core/0.1" and any(d["code"] == "vocabulary_version_mismatch" for d in st["diagnostics"])


def test_migration_preview_then_apply_with_backup(coaching_repo: Repository):
    _downgrade_to_0_1(coaching_repo)
    before = coaching_repo.paths.model.read_text()
    preview = migrate(coaching_repo, apply=False)
    assert [s["id"] for s in preview["steps"]] == ["vocabulary-core-0.1-to-0.2"] and not preview["applied"] and not preview["blocking_after"]
    assert coaching_repo.paths.model.read_text() == before
    applied = migrate(coaching_repo, apply=True)
    assert applied["applied"] and applied["revision"] == 2
    snap = coaching_repo.load_snapshot()
    assert snap.vocabulary_version == "core/0.2" and snap.transactions[-1].patch_id == "patch:migrate-vocabulary-core-0.1-to-0.2"
    assert snap.content_digest == compute_digest(snap)
    backup = json.loads(open(applied["backup"]).read())
    assert backup["vocabulary_version"] == "core/0.1" and backup["revision"] == 1
    assert json.loads(coaching_repo.paths.project.read_text())["vocabulary_version"] == "core/0.2"
    again = migrate(coaching_repo, apply=True)
    assert again["steps"] == [] and not again["applied"]


def test_unknown_version_has_no_path(coaching_repo: Repository):
    snap = coaching_repo.load_snapshot()
    snap.vocabulary_version = "core/9.9"
    coaching_repo.write_snapshot(snap)
    with pytest.raises(InvalidInput) as exc:
        migrate(coaching_repo, apply=False)
    assert exc.value.code == "no_migration_path"
