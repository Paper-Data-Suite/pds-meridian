"""#122 Slice 2: synthetic, class-local journal + read-only recovery.

No district data and no producer installations are required.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionCheckpoint,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_receipts import (
    CanonicalActionObservation,
    TeacherActionReceiptConflictError,
    TeacherActionReceiptLockError,
    TeacherActionReceiptStore,
    TeacherActionReceiptUnsafeError,
    assess_teacher_action_recovery,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


def _preview() -> TeacherActionPreview:
    return TeacherActionPreview(
        action_id="ab" * 16,
        kind="eligibility",
        scope=TeacherActionScope(
            workspace_sha256=A,
            class_id="class_one",
            grade_item_id="grade_one",
            school_year="2026-2027",
            academic_period_id="mp1",
            calendar_sha256=B,
            work_identity_sha256=C,
        ),
        actor=TeacherActionActor(
            actor_id="teacher-synthetic", profile_sha256=A, source="saved"
        ),
        target=TeacherActionTarget(
            family="eligibility",
            identity_sha256=D,
            revision=2,
            candidate_sha256=C,
            expected_current_revision=1,
            expected_current_sha256=B,
        ),
        basis=(
            TeacherActionBasis("authorization", A, B),
            TeacherActionBasis("publication", C, D),
        ),
        reviewed_decision_sha256=A,
    )


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "classes" / "class_one").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def store(root: Path) -> TeacherActionReceiptStore:
    return TeacherActionReceiptStore(root, "class_one")


def _canonical(
    target: str | None = C,
    current_rev: int | None = 1,
    current_digest: str | None = B,
    basis: str = "current",
) -> CanonicalActionObservation:
    return CanonicalActionObservation(  # type: ignore[arg-type]
        target_sha256=target,
        current_revision=current_rev,
        current_sha256=current_digest,
        current_basis=basis,
    )


def _assess(
    store: TeacherActionReceiptStore,
    observation: CanonicalActionObservation,
    p: TeacherActionPreview | None = None,
):
    return assess_teacher_action_recovery(store, p or _preview(), lambda _: observation)


def _record(p: TeacherActionPreview) -> TeacherActionRecord:
    return TeacherActionRecord(
        p.kind,
        p.target.identity_sha256,
        p.target.revision,
        p.target.candidate_sha256,
        "created",
    )


def test_read_absent_is_non_mutating(store: TeacherActionReceiptStore) -> None:
    assert store.load(_preview().action_id) is None
    assert not store.directory.exists()


def test_prepare_roundtrip_canonical_and_private(
    store: TeacherActionReceiptStore,
) -> None:
    p = _preview()
    receipt = store.prepare(p)
    assert receipt.generation == 1
    assert receipt.phase == "prepared"
    assert receipt.intent_sha256 == p.intent_sha256
    assert store.load(p.action_id) == receipt
    content = store.path_for(p.action_id).read_bytes()
    assert json.loads(content)["payload_sha256"]
    assert content.endswith(b"\n")
    assert not any(token in content for token in (b"student_work", b"scan_image"))
    if os.name != "nt":
        assert store.directory.stat().st_mode & 0o077 == 0
        assert store.path_for(p.action_id).stat().st_mode & 0o077 == 0


def test_prepare_idempotent_no_generation_increment(
    store: TeacherActionReceiptStore,
) -> None:
    p = _preview()
    first = store.prepare(p)
    assert store.prepare(p) == first


def test_existing_action_cannot_be_rebound_to_different_actor(
    store: TeacherActionReceiptStore,
) -> None:
    p = _preview()
    store.prepare(p)
    altered = replace(p, actor=replace(p.actor, actor_id="other"))
    with pytest.raises(TeacherActionReceiptConflictError, match="another"):
        store.prepare(altered)


def test_stable_journal_survives_new_store_instance(root: Path) -> None:
    p = _preview()
    first = TeacherActionReceiptStore(root, p.scope.class_id)
    first.prepare(p)
    other = TeacherActionReceiptStore(root, p.scope.class_id)
    assert other.load(p.action_id) is not None


def test_checkpoint_append_cas_and_history(store: TeacherActionReceiptStore) -> None:
    p = _preview()
    first = store.prepare(p)
    second = store.record_checkpoint(
        p,
        expected_generation=first.generation,
        checkpoint=TeacherActionCheckpoint("write", "completed"),
        observed_records=(_record(p),),
    )
    assert second.generation == 2
    assert second.phase == "in_progress"
    assert len(second.observed_records) == 1
    assert store.load(p.action_id) == second
    with pytest.raises(TeacherActionReceiptConflictError, match="Another writer"):
        store.record_checkpoint(
            p,
            expected_generation=first.generation,
            checkpoint=TeacherActionCheckpoint("selection_preview", "completed"),
        )


def test_out_of_order_checkpoint_and_record_erasures_rejected(
    store: TeacherActionReceiptStore,
) -> None:
    p = _preview()
    first = store.prepare(p)
    advanced = store.record_checkpoint(
        p,
        expected_generation=1,
        checkpoint=TeacherActionCheckpoint("selection_preview", "completed"),
        observed_records=(_record(p),),
    )
    with pytest.raises(TeacherActionReceiptConflictError, match="backwards"):
        store.record_checkpoint(
            p,
            expected_generation=2,
            checkpoint=TeacherActionCheckpoint("write", "completed"),
        )
    with pytest.raises(TeacherActionReceiptConflictError, match="discard"):
        store.record_checkpoint(
            p,
            expected_generation=2,
            checkpoint=TeacherActionCheckpoint("selection_commit", "unknown"),
            observed_records=(),
        )
    assert first.generation == 1 and advanced.generation == 2
    assert store.load(p.action_id) == advanced


def test_record_and_intent_validation_fail_closed(
    store: TeacherActionReceiptStore,
) -> None:
    with pytest.raises(TeacherActionReceiptUnsafeError, match="Unsafe class"):
        TeacherActionReceiptStore(store.root, "../outside")
    with pytest.raises(TeacherActionReceiptUnsafeError, match="Unsafe action"):
        store.path_for("../outside")
    with pytest.raises(TeacherActionReceiptUnsafeError, match="unregistered class"):
        TeacherActionReceiptStore(store.root, "not_present").prepare(
            replace(_preview(), scope=replace(_preview().scope, class_id="not_present"))
        )


@pytest.mark.parametrize(
    "payload",
    [
        b"{broken",
        b"{}",
        b"" * 4,
        b"{}\n",
        b"x" * (32 * 1024 + 1),
        b'{"payload":{},"payload":{},"payload_sha256":"x"}\n',
    ],
    ids=[
        "malformed_json",
        "empty_object",
        "empty_bytes",
        "noncanonical_newline",
        "oversized_payload",
        "duplicate_json_keys",
    ],
)
def test_corrupt_journal_rejected(
    store: TeacherActionReceiptStore, payload: bytes
) -> None:
    p = _preview()
    store.prepare(p)
    store.path_for(p.action_id).write_bytes(payload)
    with pytest.raises(TeacherActionReceiptUnsafeError):
        store.load(p.action_id)
    calls = []
    assessment = assess_teacher_action_recovery(
        store, p, lambda _: calls.append(1) or _canonical()
    )
    assert calls == [1]  # journal corruption does not suppress canonical reread
    assert assessment.status == "recovery_required"
    assert not assessment.can_resume_exact_selection


def test_symlinked_journal_file_rejected(
    store: TeacherActionReceiptStore, tmp_path: Path
) -> None:
    p = _preview()
    store.prepare(p)
    path = store.path_for(p.action_id)
    path.unlink()
    target = tmp_path / "outside"
    target.write_text("PRIVATE", encoding="utf8")
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    with pytest.raises(TeacherActionReceiptUnsafeError, match="link"):
        store.load(p.action_id)
    with pytest.raises(TeacherActionReceiptUnsafeError):
        store.prepare(p)
    assert target.read_text(encoding="utf8") == "PRIVATE"


def test_symlinked_directory_rejected(
    store: TeacherActionReceiptStore, tmp_path: Path
) -> None:
    external = tmp_path / "outside"
    external.mkdir()
    modules = store.root / "classes" / "class_one" / "modules"
    modules.mkdir()
    try:
        (modules / "meridian").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    with pytest.raises(TeacherActionReceiptUnsafeError, match="directory"):
        store.prepare(_preview())
    assert list(external.iterdir()) == []


def test_missing_receipt_never_replays_existing_revision(
    store: TeacherActionReceiptStore,
) -> None:
    observation = _canonical(C, 2, C)
    assessment = _assess(store, observation)
    assert assessment.reason == "missing_receipt_target_present"
    assert assessment.status == "recovery_required"
    assert not assessment.can_resume_exact_selection
    assert not store.directory.exists()


def test_clean_prewrite_block_classifies_without_fabricated_mutation(
    store: TeacherActionReceiptStore,
) -> None:
    store.prepare(_preview())
    assessment = _assess(store, _canonical(None, 1, B))
    assert assessment.status == "blocked_before_write"
    assert assessment.reason == "target_absent"


def test_crash_after_write_before_receipt_checkpoint(
    store: TeacherActionReceiptStore,
) -> None:
    store.prepare(_preview())
    assessment = _assess(store, _canonical(C, 1, B))
    assert assessment.status == "written_not_current"
    assert assessment.can_resume_exact_selection
    receipt = store.load(_preview().action_id)
    assert receipt is not None
    assert len(receipt.checkpoints) == 1


def test_crash_after_selection_without_receipt_finalization(
    store: TeacherActionReceiptStore,
) -> None:
    store.prepare(_preview())
    result = _assess(store, _canonical(C, 2, C))
    assert result.status == "already_applied"
    assert result.reason == "exact_current"
    assert not result.can_resume_exact_selection


@pytest.mark.parametrize(
    "target,current,basis,status,reason,resume",
    [
        (D, 1, "current", "conflict_requires_review", "target_digest_conflict", False),
        (C, 3, "current", "conflict_requires_review", "current_pointer_changed", False),
        (C, 2, "stale", "conflict_requires_review", "dependencies_changed", False),
        (C, 2, "unknown", "current_unverified", "current_pointer_unknown", False),
        (None, 1, "unknown", "recovery_required", "current_pointer_unknown", False),
    ],
)
def test_recovery_failure_matrix(
    store: TeacherActionReceiptStore,
    target: str | None,
    current: int,
    basis: str,
    status: str,
    reason: str,
    resume: bool,
) -> None:
    store.prepare(_preview())
    d = {1: B, 2: C, 3: D}[current]
    result = _assess(store, _canonical(target, current, d, basis))
    assert (result.status, result.reason, result.can_resume_exact_selection) == (
        status,
        reason,
        resume,
    )


def test_write_checkpoint_receipt_disagrees_with_canonical(
    store: TeacherActionReceiptStore,
) -> None:
    p = _preview()
    store.prepare(p)
    store.record_checkpoint(
        p,
        expected_generation=1,
        checkpoint=TeacherActionCheckpoint("write", "completed"),
        observed_records=(_record(p),),
    )
    result = _assess(store, _canonical(None, 1, B))
    assert result.reason == "receipt_canonical_divergence"
    assert result.status == "recovery_required"


def test_unverified_reader_fails_closed(store: TeacherActionReceiptStore) -> None:
    p = _preview()
    store.prepare(p)
    reader_called = []

    def broken(_preview: TeacherActionPreview) -> CanonicalActionObservation:
        reader_called.append(1)
        raise RuntimeError("private underlying failure")

    result = assess_teacher_action_recovery(store, p, broken)
    assert reader_called == [1]
    assert result.status == "recovery_required"
    assert result.reason == "canonical_read_failed"
    assert not result.can_resume_exact_selection


def test_stale_actor_review_rejected_even_when_receipt_exists(
    store: TeacherActionReceiptStore,
) -> None:
    p = _preview()
    store.prepare(p)
    modified = replace(p, actor=replace(p.actor, profile_sha256=B))
    result = _assess(store, _canonical(C, 2, C), modified)
    assert result.reason == "dependencies_changed"
    assert result.status == "conflict_requires_review"


def test_out_of_scope_class_refused(store: TeacherActionReceiptStore) -> None:
    with pytest.raises(TeacherActionReceiptUnsafeError, match="Class-scoped"):
        assess_teacher_action_recovery(
            store,
            replace(_preview(), scope=replace(_preview().scope, class_id="other")),
            lambda _: _canonical(),
        )


def test_write_failure_prepares_first_without_creating_canonical_record(
    store: TeacherActionReceiptStore,
) -> None:
    p = _preview()
    store.prepare(p)
    journal = store.load(p.action_id)
    assert journal is not None
    assert journal.phase == "prepared"
    assert not (store.directory.parent / "gi").exists()


def test_lock_conflict_rejects_second_writer(store: TeacherActionReceiptStore) -> None:
    p = _preview()
    store.prepare(p)
    with store._locked():
        with pytest.raises(TeacherActionReceiptLockError):
            store.record_checkpoint(
                p,
                expected_generation=1,
                checkpoint=TeacherActionCheckpoint("write", "unknown"),
            )


def test_no_write_can_be_replayed_from_receipt_only(
    store: TeacherActionReceiptStore,
) -> None:
    p = _preview()
    store.prepare(p)
    called = []

    def only_reader(q: TeacherActionPreview) -> CanonicalActionObservation:
        called.append(q.action_id)
        return _canonical(C, 1, B)

    state = assess_teacher_action_recovery(store, p, only_reader)
    assert state.can_resume_exact_selection
    assert called == [p.action_id]
    assert store.load(p.action_id).generation == 1  # type: ignore[union-attr]
