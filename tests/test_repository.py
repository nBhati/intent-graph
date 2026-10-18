import json
import os
import threading
import time

import pytest

from intentgraph.errors import CorruptSnapshot, IncompatibleWorkspace, LockTimeout, WorkspaceNotFound
from intentgraph.repository import Repository
from intentgraph.repository import store as store_mod


def test_find_walks_up(coaching_repo: Repository, tmp_path):
    nested = coaching_repo.paths.root / "src" / "deep"
    nested.mkdir(parents=True)
    assert Repository.find(nested).paths == coaching_repo.paths
    with pytest.raises(WorkspaceNotFound):
        Repository.find(tmp_path / "elsewhere")


def test_init_is_idempotent_and_refuses_incompatible(tmp_path):
    repo, created = Repository.init(tmp_path / "ws", name="x")
    assert created
    again, created2 = Repository.init(tmp_path / "ws", name="x")
    assert not created2 and again.load_snapshot().revision == 0
    manifest = json.loads(repo.paths.project.read_text())
    manifest["format_version"] = "9.0"
    repo.paths.project.write_text(json.dumps(manifest))
    with pytest.raises(IncompatibleWorkspace):
        Repository.init(tmp_path / "ws", name="x")


def test_hand_edited_snapshot_is_detected(coaching_repo: Repository):
    data = json.loads(coaching_repo.paths.model.read_text())
    data["nodes"][0]["label"] = "edited by hand"
    coaching_repo.paths.model.write_text(json.dumps(data))
    with pytest.raises(CorruptSnapshot) as exc:
        coaching_repo.load_snapshot()
    assert exc.value.details["stored"] != exc.value.details["computed"]


def test_partial_file_is_detected(coaching_repo: Repository):
    text = coaching_repo.paths.model.read_text()
    coaching_repo.paths.model.write_text(text[: len(text) // 2])
    with pytest.raises(CorruptSnapshot):
        coaching_repo.load_snapshot()


def test_interrupted_write_leaves_previous_snapshot(coaching_repo: Repository, monkeypatch):
    before = coaching_repo.paths.model.read_text()
    snap = coaching_repo.load_snapshot()
    snap.revision = 99

    def boom(src, dst):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(store_mod.os, "replace", boom)
    with pytest.raises(OSError):
        coaching_repo.write_snapshot(snap)
    monkeypatch.undo()
    assert coaching_repo.paths.model.read_text() == before
    assert coaching_repo.load_snapshot().revision == 1
    assert not [p for p in coaching_repo.paths.dir.iterdir() if ".tmp-" in p.name]


def test_write_lock_is_exclusive(coaching_repo: Repository):
    acquired = threading.Event()
    release = threading.Event()

    def holder():
        with coaching_repo.write_lock():
            acquired.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    assert acquired.wait(5)
    start = time.monotonic()
    with pytest.raises(LockTimeout):
        with coaching_repo.write_lock(timeout=0.3):
            pass
    assert time.monotonic() - start < 3
    release.set()
    t.join()
    with coaching_repo.write_lock(timeout=1):
        pass


def test_written_file_is_group_readable(coaching_repo: Repository):
    mode = coaching_repo.paths.model.stat().st_mode & 0o777
    assert mode & 0o044 or os.umask(0) == 0o077  # readable unless umask forbids
