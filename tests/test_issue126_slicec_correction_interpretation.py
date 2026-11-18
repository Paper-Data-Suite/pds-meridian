"""#126-C: synthetic teacher testimony is separate from producer authority."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_issue126_sliceb_attempt_inventory import _attempt, _build, _case

from meridian.attempt_correction_interpretation import (
    AttemptInterpretationError,
    preview_attempt_interpretation,
    render_attempt_interpretation_preview,
)
from meridian.attempt_selection import AttemptProjectionReference


def _review_first():
    return _build(_case(size=29))


def _correction(review=None, *, reason="I examined the original paper"):
    return preview_attempt_interpretation(
        _review_first() if review is None else review,
        student_id="synthetic_student_01",
        treatment="teacher_reviewed_correction",
        original_attempt=_attempt("synthetic_student_01", 1),
        selected_attempts=(_attempt("synthetic_student_01", 2),),
        teacher_rationale=reason,
    )


def test_teacher_verified_omr_correction_keeps_exact_previous_attempt_history():
    result = _correction()
    assert len(result.facts) == 2
    assert result.facts[0].points == (0, 6)
    assert result.facts[1].points == (6, 6)
    assert result.facts[1].result_origin == "scan_review_manual"
    assert result.facts[1].scan_review_failure_reference
    assert not result.facts[0].operative_eligible
    assert result.intended_selected_attempts == (_attempt("synthetic_student_01", 2),)
    assert not result.needs_reassessment_decision
    assert "not producer-certified" in result.suggested_canonical_rationale
    assert result.can_continue_to_reviewed_action
    assert "NOT SAVED" in render_attempt_interpretation_preview(result)


def test_scan_review_origin_never_itself_certifies_original_relationship():
    result = preview_attempt_interpretation(
        _review_first(), student_id="synthetic_student_01", treatment="unresolved"
    )
    assert result.facts[1].result_origin == "scan_review_manual"
    assert result.original_attempt is None
    assert result.intended_selected_attempts == ()
    assert not result.can_continue_to_reviewed_action
    assert "NOT certified" in render_attempt_interpretation_preview(result)


def test_real_retake_can_select_second_without_inventing_correction():
    result = preview_attempt_interpretation(
        _review_first(),
        student_id="synthetic_student_02",
        treatment="teacher_reviewed_reassessment",
        selected_attempts=(_attempt("synthetic_student_02", 2),),
        teacher_rationale="A separate sitting with new student work",
    )
    assert result.treatment == "teacher_reviewed_reassessment"
    assert "separate performance" in result.suggested_canonical_rationale
    assert not result.needs_reassessment_decision


def test_two_selected_retake_attempts_require_separate_reassessment_decision():
    result = preview_attempt_interpretation(
        _review_first(),
        student_id="synthetic_student_02",
        treatment="teacher_reviewed_reassessment",
        selected_attempts=(
            _attempt("synthetic_student_02", 1),
            _attempt("synthetic_student_02", 2),
        ),
        teacher_rationale="Both sittings should contribute after review",
    )
    assert result.needs_reassessment_decision
    assert len(result.intended_selected_attempts) == 2
    assert "Separate #31" in render_attempt_interpretation_preview(result)


def test_original_excluded_evidence_remains_visible_but_not_selectable():
    with pytest.raises(AttemptInterpretationError, match="eligible"):
        preview_attempt_interpretation(
            _review_first(),
            student_id="synthetic_student_01",
            treatment="teacher_reviewed_correction",
            original_attempt=_attempt("synthetic_student_01", 2),
            selected_attempts=(_attempt("synthetic_student_01", 1),),
            teacher_rationale="Cannot reinclude excluded original",
        )


def test_correction_requires_one_exact_selected_and_distinct_original():
    for original, selected in (
        (None, (_attempt("synthetic_student_01", 2),)),
        (_attempt("synthetic_student_01", 2), (_attempt("synthetic_student_01", 2),)),
        (_attempt("synthetic_student_01", 1), ()),
    ):
        with pytest.raises(AttemptInterpretationError):
            preview_attempt_interpretation(
                _review_first(),
                student_id="synthetic_student_01",
                treatment="teacher_reviewed_correction",
                original_attempt=original,
                selected_attempts=selected,
                teacher_rationale="I inspected the paper",
            )


def test_unknown_relationship_cannot_embed_a_consequential_choice():
    with pytest.raises(AttemptInterpretationError, match="Unresolved"):
        preview_attempt_interpretation(
            _review_first(),
            student_id="synthetic_student_01",
            treatment="unresolved",
            selected_attempts=(_attempt("synthetic_student_01", 2),),
        )


def test_exact_source_and_subject_mismatch_rejected():
    review = _review_first()
    valid = _attempt("synthetic_student_01", 2)
    foreign = replace(
        valid,
        source_snapshot=AttemptProjectionReference(
            work=valid.source_snapshot.work,
            publication_id=valid.source_snapshot.publication_id,
            cache_key=valid.source_snapshot.cache_key,
            snapshot_digest="9" * 64,
        ),
    )
    for bad in (foreign, _attempt("synthetic_student_02", 2)):
        with pytest.raises(AttemptInterpretationError, match="exact current eligible"):
            preview_attempt_interpretation(
                review,
                student_id="synthetic_student_01",
                treatment="teacher_reviewed_correction",
                original_attempt=_attempt("synthetic_student_01", 1),
                selected_attempts=(bad,),
                teacher_rationale="Explicitly chosen but foreign",
            )


def test_duplicate_intended_selection_rejected_even_for_valid_attempts():
    value = _attempt("synthetic_student_02", 1)
    with pytest.raises(AttemptInterpretationError, match="distinct"):
        preview_attempt_interpretation(
            _review_first(),
            student_id="synthetic_student_02",
            treatment="teacher_reviewed_reassessment",
            selected_attempts=(value, value),
            teacher_rationale="Separate sittings",
        )


def test_outside_authorized_student_never_generates_a_preview():
    review = _build(_case(size=3, requested_ids={"synthetic_student_01"}))
    with pytest.raises(AttemptInterpretationError, match="authorized review"):
        preview_attempt_interpretation(
            review, student_id="synthetic_student_02", treatment="unresolved"
        )


def test_one_attempt_does_not_create_a_fake_correction_relationship():
    review = _build(_case(size=1, corrected=False, retake=False))
    with pytest.raises(AttemptInterpretationError, match="Multiple exact"):
        preview_attempt_interpretation(
            review,
            student_id="synthetic_student_01",
            treatment="teacher_reviewed_reassessment",
            selected_attempts=(_attempt("synthetic_student_01", 1),),
            teacher_rationale="Only one sitting",
        )


def test_reassessment_does_not_accept_correction_original_claim():
    with pytest.raises(AttemptInterpretationError, match="not applicable"):
        preview_attempt_interpretation(
            _review_first(),
            student_id="synthetic_student_02",
            treatment="teacher_reviewed_reassessment",
            original_attempt=_attempt("synthetic_student_02", 1),
            selected_attempts=(_attempt("synthetic_student_02", 2),),
            teacher_rationale="A separate performance",
        )


def test_rationale_required_bounded_and_not_interpreted_as_menu_command():
    with pytest.raises(AttemptInterpretationError, match="required"):
        _correction(reason="  ")
    with pytest.raises(AttemptInterpretationError, match="size limit"):
        _correction(reason="x" * 2_000)
    with pytest.raises(AttemptInterpretationError, match="control"):
        _correction(reason="bad\x1b[31m")
    result = _correction(reason=":notes is just teacher's literal explanation")
    assert ":notes" in result.suggested_canonical_rationale


def test_stale_source_and_current_selection_are_not_valid_write_previews():
    review = _review_first()
    for replaced in (
        replace(review, source_status="withdrawn"),
        replace(review, membership_state="excluded"),
        replace(
            review,
            students=(
                replace(review.students[0], selection_status="stale"),
                *review.students[1:],
            ),
        ),
    ):
        with pytest.raises(AttemptInterpretationError):
            _correction(replaced)


def test_preview_never_mutates_inventory_or_creates_canonical_decision():
    review = _review_first()
    before = repr(review)
    intent = _correction(review)
    assert repr(review) == before
    assert not hasattr(intent, "decision_revision")
    assert not hasattr(intent, "decision_sha256")
    assert not hasattr(intent, "actor")
    assert "Nothing was saved" in render_attempt_interpretation_preview(intent)
