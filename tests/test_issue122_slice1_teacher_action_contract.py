"""#122 Slice 1: contracts only; no academic or filesystem mutations."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionCheckpoint,
    TeacherActionContractError,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionResult,
    TeacherActionScope,
    TeacherActionTarget,
    teacher_action_outcome_message,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


def preview() -> TeacherActionPreview:
    return TeacherActionPreview(
        action_id="ab" * 16,
        kind="eligibility",
        scope=TeacherActionScope(
            workspace_sha256=A,
            class_id="english_12_pd2",
            grade_item_id="scene_summary_pacing",
            school_year="2026-2027",
            academic_period_id="mp1",
            calendar_sha256=B,
            work_identity_sha256=C,
        ),
        actor=TeacherActionActor(
            actor_id="teacher-example-id", profile_sha256=A, source="saved"
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
            TeacherActionBasis(
                role="authorization",
                identity_sha256=A,
                content_sha256=C,
            ),
            TeacherActionBasis(
                role="membership",
                identity_sha256=B,
                content_sha256=D,
                revision=2,
                selected_revision=2,
                selected_sha256=D,
            ),
            TeacherActionBasis(
                role="publication",
                identity_sha256=C,
                content_sha256=A,
            ),
        ),
        reviewed_decision_sha256=B,
    )


def exact_record(
    p: TeacherActionPreview, *, created: bool = True
) -> TeacherActionRecord:
    return TeacherActionRecord(
        family=p.kind,
        identity_sha256=p.target.identity_sha256,
        revision=p.target.revision,
        sha256=p.target.candidate_sha256,
        write_disposition="created" if created else "existing",
    )


def result(
    p: TeacherActionPreview,
    *,
    status: str = "applied",
    persisted: tuple[TeacherActionRecord, ...] | None = None,
    current_state: str = "matches",
    current_record: TeacherActionRecord | None = None,
    selection: str = "updated",
    reason: str | None = None,
) -> TeacherActionResult:
    record = exact_record(p)
    return TeacherActionResult(  # type: ignore[arg-type]
        action_id=p.action_id,
        intent_sha256=p.intent_sha256,
        target=p.target,
        status=status,
        persisted=(record,) if persisted is None else persisted,
        current_state=current_state,  # type: ignore[arg-type]
        current_record=(
            record
            if current_record is None and current_state == "matches"
            else current_record
        ),
        selection_disposition=selection,  # type: ignore[arg-type]
        reason_code=reason,
    )


def test_deterministic_intent_across_distinct_action_ids() -> None:
    p = preview()
    other_id = replace(p, action_id="cd" * 16)
    assert p.intent_sha256 == other_id.intent_sha256
    assert len(p.intent_sha256) == 64


@pytest.mark.parametrize(
    "changed",
    [
        lambda p: replace(p, actor=replace(p.actor, actor_id="different-actor")),
        lambda p: replace(p, actor=replace(p.actor, source="temporary")),
        lambda p: replace(p, actor=replace(p.actor, profile_sha256=B)),
        lambda p: replace(p, target=replace(p.target, expected_current_sha256=A)),
        lambda p: replace(p, target=replace(p.target, candidate_sha256=A)),
        lambda p: replace(p, scope=replace(p.scope, calendar_sha256=A)),
        lambda p: replace(p, scope=replace(p.scope, academic_period_id="mp2")),
        lambda p: replace(p, reviewed_decision_sha256=C),
        lambda p: replace(
            p, basis=(replace(p.basis[0], content_sha256=B), *p.basis[1:])
        ),
        lambda p: replace(p, make_current=False),
    ],
)
def test_important_change_invalidates_intent(changed: object) -> None:
    p = preview()
    assert callable(changed)
    assert changed(p).intent_sha256 != p.intent_sha256  # type: ignore[operator]


def test_reject_stale_pointer_without_digest() -> None:
    with pytest.raises(TeacherActionContractError, match="both revision and digest"):
        replace(preview().target, expected_current_sha256=None)


def test_reject_invalid_digest_and_revision() -> None:
    with pytest.raises(TeacherActionContractError, match="SHA-256"):
        replace(preview().target, candidate_sha256="BAD")
    with pytest.raises(TeacherActionContractError, match="positive revision"):
        replace(preview().target, revision=True)  # type: ignore[arg-type]


def test_reject_duplicate_and_unsorted_basis() -> None:
    p = preview()
    with pytest.raises(TeacherActionContractError, match="unique"):
        replace(p, basis=(p.basis[0], p.basis[0]))
    with pytest.raises(TeacherActionContractError, match="sorted"):
        replace(p, basis=tuple(reversed(p.basis)))


def test_reject_cross_family_mismatch() -> None:
    p = preview()
    with pytest.raises(TeacherActionContractError, match="differ"):
        replace(p, kind="grade_item")


def test_reject_missing_academic_calendar() -> None:
    p = preview()
    with pytest.raises(TeacherActionContractError, match="calendar digest"):
        replace(p.scope, calendar_sha256=None)


def test_applied_needs_exact_independent_canonical_record() -> None:
    p = preview()
    good = result(p)
    assert good.succeeded
    assert "made current" in teacher_action_outcome_message(good)
    altered = replace(exact_record(p), sha256=A)
    with pytest.raises(TeacherActionContractError, match="exact target"):
        result(p, current_record=altered)
    with pytest.raises(TeacherActionContractError, match="exact persisted"):
        result(p, persisted=(altered,))
    with pytest.raises(TeacherActionContractError, match="exact persisted"):
        result(p, persisted=())


def test_already_applied_must_be_existing_canonical_state() -> None:
    p = preview()
    stored = exact_record(p, created=False)
    item = result(
        p,
        status="already_applied",
        persisted=(stored,),
        current_record=stored,
        selection="existing",
    )
    assert item.succeeded
    assert teacher_action_outcome_message(item).startswith("Already applied")
    with pytest.raises(TeacherActionContractError, match="Already-applied"):
        result(p, status="already_applied", selection="created")


def test_blocked_before_write_cannot_contain_canonical_mutation() -> None:
    p = preview()
    blocked = result(
        p,
        status="blocked_before_write",
        persisted=(),
        current_state="not_checked",
        selection="not_attempted",
        reason="authorization_revoked",
    )
    assert not blocked.succeeded
    assert "No action record" in teacher_action_outcome_message(blocked)
    with pytest.raises(TeacherActionContractError, match="pre-write block"):
        result(
            p,
            status="blocked_before_write",
            current_state="not_checked",
            selection="not_attempted",
            reason="conflict",
        )


def test_written_not_current_and_unknown_have_distinct_truthful_messages() -> None:
    p = preview()
    partial = result(
        p,
        status="written_not_current",
        current_state="not_current",
        selection="not_attempted",
        reason="selector_cas_conflict",
    )
    uncertain = result(
        p,
        status="current_unverified",
        current_state="unknown",
        selection="unknown",
        reason="reload_failed",
    )
    assert not partial.succeeded and not uncertain.succeeded
    assert "not current" in teacher_action_outcome_message(partial)
    assert "could not be verified" in teacher_action_outcome_message(uncertain)


def test_conflict_and_recovery_never_claim_success() -> None:
    p = preview()
    for status in ("conflict_requires_review", "recovery_required"):
        item = result(
            p,
            status=status,
            persisted=(),
            current_state="unknown",
            selection="not_attempted",
            reason="reconcile_required",
        )
        assert not item.succeeded
        with pytest.raises(TeacherActionContractError, match="unresolved"):
            result(p, status=status, reason="reconcile_required")


def test_missing_failure_reason_rejected_and_bounded_reason_codes() -> None:
    p = preview()
    with pytest.raises(TeacherActionContractError, match="reason_code"):
        result(
            p,
            status="current_unverified",
            current_state="unknown",
            selection="unknown",
        )
    with pytest.raises(TeacherActionContractError, match="bounded key"):
        TeacherActionCheckpoint(
            stage="write", disposition="blocked", reason_code="student work"
        )


def test_checkpoint_trace_is_structured() -> None:
    record = result(preview())
    trace = (
        TeacherActionCheckpoint("preflight", "completed"),
        TeacherActionCheckpoint("receipt_prepared", "completed"),
        TeacherActionCheckpoint("write", "completed"),
        TeacherActionCheckpoint("selection_commit", "completed"),
        TeacherActionCheckpoint("verification", "completed"),
    )
    assert replace(record, checkpoints=trace).checkpoints == trace


def test_module_contract_is_side_effect_free(tmp_path: Path) -> None:
    # Construct/fingerprint records without a real PDS workspace or producer.
    p = preview()
    assert p.intent_sha256
    assert result(p).succeeded
    assert list(tmp_path.iterdir()) == []
