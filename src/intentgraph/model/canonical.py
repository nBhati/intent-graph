"""Canonical serialization and digests (architecture section 9.2).

One shared routine computes the digest over the canonical payload excluding
the digest field itself. Arbitrary JSON serialization is not assumed to yield
stable hashes: records are sorted by ID, keys are sorted, UTF-8 is used,
non-finite numbers are rejected, and newline handling is fixed.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .records import Snapshot

DIGEST_PREFIX = "sha256:"


def canonical_dumps(data: Any) -> str:
    """Compact, key-sorted, UTF-8 JSON. Raises ``ValueError`` on NaN/Infinity."""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest_of(data: Any) -> str:
    return DIGEST_PREFIX + hashlib.sha256(canonical_dumps(data).encode("utf-8")).hexdigest()


def snapshot_payload(snapshot: Snapshot, *, include_digest: bool = False) -> dict[str, Any]:
    """The snapshot as a plain, canonically ordered dictionary."""
    data = snapshot.model_dump(mode="json")
    data["nodes"] = sorted(data["nodes"], key=lambda r: r["id"])
    data["edges"] = sorted(data["edges"], key=lambda r: r["id"])
    data["transactions"] = sorted(data["transactions"], key=lambda t: (t["result_revision"], t["patch_id"]))
    data["policies"] = sorted(data["policies"], key=lambda p: canonical_dumps(p))
    if not include_digest:
        data.pop("content_digest", None)
    return data


def compute_digest(snapshot: Snapshot) -> str:
    return digest_of(snapshot_payload(snapshot, include_digest=False))


def serialize_snapshot(snapshot: Snapshot) -> str:
    """Human-readable but deterministic file form (pretty-printed, sorted, trailing newline).

    The stored ``content_digest`` is always recomputed so a file never carries a
    digest that disagrees with its content.
    """
    payload = snapshot_payload(snapshot, include_digest=True)
    payload["content_digest"] = compute_digest(snapshot)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
