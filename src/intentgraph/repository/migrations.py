"""Explicit, previewable, recoverable migrations (architecture section 9.5).

Storage format, vocabulary, policy and tool versions are separate. A
migration step is registered for one (from, to) vocabulary or format pair.
``preview`` applies the step to a copy and reports the diagnostics the model
would have afterwards; ``apply`` writes a backup first, then commits the
migrated snapshot with a transaction record so the change is visible in
``diff --since``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..model import Snapshot, TransactionRecord, compute_digest, digest_of

Step = Callable[[Snapshot], Snapshot]


@dataclass(frozen=True)
class Migration:
    id: str
    from_version: str
    to_version: str
    field: str  # "vocabulary_version" | "format_version"
    description: str
    step: Step


def _bump_vocab_0_1_to_0_2(snapshot: Snapshot) -> Snapshot:
    out = snapshot.model_copy(deep=True)
    out.vocabulary_version = "core/0.2"
    return out


MIGRATIONS: list[Migration] = [
    Migration(
        id="vocabulary-core-0.1-to-0.2",
        from_version="core/0.1",
        to_version="core/0.2",
        field="vocabulary_version",
        description="Additive: adds the Scope kind, Decision.decision_kind, Obligation.rule, Approval.policy_ref/model_revision, and Approval as a 'concerns' source. No record rewrites.",
        step=_bump_vocab_0_1_to_0_2,
    ),
]


def plan(snapshot: Snapshot, target_vocabulary: str) -> list[Migration]:
    """Ordered steps from the snapshot's vocabulary version to the target. Empty when current."""
    steps: list[Migration] = []
    current = snapshot.vocabulary_version
    guard = 0
    while current != target_vocabulary:
        nxt = next((m for m in MIGRATIONS if m.field == "vocabulary_version" and m.from_version == current), None)
        if nxt is None:
            raise LookupError(f"no migration path from vocabulary {current!r} to {target_vocabulary!r}")
        steps.append(nxt)
        current = nxt.to_version
        guard += 1
        if guard > 20:
            raise LookupError("migration path too long")
    return steps


def run(snapshot: Snapshot, steps: list[Migration], *, applied_at: str) -> Snapshot:
    out = snapshot
    for m in steps:
        base_revision = out.revision
        out = m.step(out)
        out.revision = base_revision + 1
        out.transactions.append(TransactionRecord(
            patch_id=f"patch:migrate-{m.id}", base_revision=base_revision, result_revision=out.revision, applied_at=applied_at,
            reason=f"migration {m.id}: {m.description}", operations_digest=digest_of({"migration": m.id}),
        ))
        out.content_digest = compute_digest(out)
    return out
