import json
from pathlib import Path

import pytest

from intentgraph.model import Snapshot
from intentgraph.patches import Patch
from intentgraph.repository import Repository
from intentgraph.services import Context, patch_apply

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture_patch(name: str, snapshot: Snapshot) -> Patch:
    """Load a fixture patch and bind it to the given snapshot's revision/digest."""
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    data["base_revision"] = snapshot.revision
    data["base_digest"] = snapshot.content_digest
    return Patch.model_validate(data)


@pytest.fixture
def empty_repo(tmp_path: Path) -> Repository:
    repo, created = Repository.init(tmp_path / "ws", name="fixture")
    assert created
    return repo


@pytest.fixture
def coaching_repo(empty_repo: Repository) -> Repository:
    snap = empty_repo.load_snapshot()
    patch = load_fixture_patch("coaching-patch.json", snap)
    result = patch_apply(empty_repo, patch)
    assert result["applied"] and result["revision"] == 1
    return empty_repo


@pytest.fixture
def coaching_ctx(coaching_repo: Repository) -> Context:
    return Context(coaching_repo)
