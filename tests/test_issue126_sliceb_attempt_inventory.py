"""#126-B: synthetic read-only attempt inventory, no real student records.

Test items intentionally bypass EvidenceProvenance's *producer publication* factory:
source authorization has already happened in the #125 review. These are
isolated immutable in-memory projection values, not a private ScoreForm read.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_attempt_inventory import (
    AssessmentAttemptInventoryScopeError,
    build_assessment_attempt_inventory,
    render_assessment_attempt_inventory,
)
from meridian.assessment_eligibility_review import (
    AssessmentEligibilityItem,
    AssessmentEligibilityReview,
    AssessmentEligibilityStudent,
)
from meridian.attempt_decisions_workflow import (
    AttemptDecisionCandidateRow,
    AttemptDecisionWorkflowProjection,
)
from meridian.attempt_selection import (
    AttemptNativeIdentity,
    AttemptObservationReference,
    AttemptProjectionReference,
    AttemptTargetReference,
)
from meridian.evidence import (
    EvidenceInventory,
    EvidenceItem,
    EvidenceTarget,
    EvidenceTargetIdentity,
    NativePointValue,
    NativeProvenance,
    NativeReference,
    NativeScalarValue,
    StudentSubject,
)
from meridian.evidence_eligibility import EvidenceSourceReference

_WORK = ModuleWorkRef("scoreform", "synthetic_class_126", "synthetic_check_126")
_GRADE_ITEM = "synthetic_grade_item_126"
_PUB = "pub_" + "a" * 32
_CACHE = "b" * 64
_DIGEST = "c" * 64


@dataclass(frozen=True)
class _Case:
    review: AssessmentEligibilityReview
    inventory: EvidenceInventory
    selections: dict[str, AttemptDecisionWorkflowProjection]


def _source() -> AttemptProjectionReference:
    return AttemptProjectionReference(
        work=_WORK,
        publication_id=_PUB,
        cache_key=_CACHE,
        snapshot_digest=_DIGEST,
    )


def _attempt(student_id: str, sequence: int) -> AttemptObservationReference:
    return AttemptObservationReference(
        source_snapshot=_source(),
        student_id=student_id,
        target=AttemptTargetReference(
            target_kind="attempt",
            target_id=f"attempt_{sequence}",
            owning_system=None,
            contract_version=None,
        ),
        native=AttemptNativeIdentity(identifier=None, sequence=sequence),
    )


def _fake_item(
    *,
    student_id: str,
    sequence: int,
    index: int,
    kind: str,
    value: NativePointValue | NativeScalarValue,
    scan_review: bool,
) -> EvidenceItem:
    """A typed immutable EvidenceItem with a synthetic public/native projection.

    Canonical producer/Core publication authoring is outside this pure-composer
    test; the production wrapper supplies a fully validated EvidenceInventory.
    """
    item = object.__new__(EvidenceItem)
    object.__setattr__(item, "item_id", f"item_{student_id}_{sequence}_{index}")
    object.__setattr__(item, "subject", StudentSubject(student_id))
    target = (
        EvidenceTarget(
            target_kind="attempt",
            target_id=f"attempt_{sequence}",
            sequence=sequence,
        )
        if index < 2
        else EvidenceTarget(
            target_kind="question",
            target_id=f"question_{index - 1}",
            parent_target=EvidenceTargetIdentity(
                target_kind="attempt", target_id=f"attempt_{sequence}"
            ),
            sequence=index - 1,
        )
    )
    object.__setattr__(item, "target", target)
    object.__setattr__(item, "result_kind", kind)
    object.__setattr__(item, "value", value)
    refs = (NativeReference(kind="attempt", sequence=sequence),)
    if scan_review:
        refs += (
            NativeReference(kind="review_failure", identifier="synthetic_failure"),
        )
    object.__setattr__(
        item, "provenance", SimpleNamespace(native=NativeProvenance(refs))
    )
    return item


def _student_items(
    student_id: str,
    sequence: int,
    earned: int,
    *,
    included: bool,
    scan_review: bool = False,
) -> tuple[tuple[EvidenceItem, ...], tuple[AssessmentEligibilityItem, ...]]:
    result_origin = "scan_review_manual" if scan_review else "pds2_scan"
    values = [
        ("attempt_points", NativePointValue(earned, 6)),
        ("result_origin", NativeScalarValue(result_origin)),
    ]
    values.extend(
        ("question_correctness", NativeScalarValue(i <= earned)) for i in range(1, 7)
    )
    evidence = []
    review = []
    for i, (kind, value) in enumerate(values):
        item = _fake_item(
            student_id=student_id,
            sequence=sequence,
            index=i,
            kind=kind,
            value=value,
            scan_review=scan_review,
        )
        evidence.append(item)
        review.append(
            AssessmentEligibilityItem(
                source=EvidenceSourceReference(
                    work=_WORK,
                    publication_id=_PUB,
                    cache_key=_CACHE,
                    snapshot_digest=_DIGEST,
                    item_id=item.item_id,
                ),
                student_id=student_id,
                evidence_label=f"Synthetic attempt {sequence}, item {i}",
                target_kind=item.target.target_kind,
                target_id=item.target.target_id,
                result_kind=kind,
                eligibility_status="included" if included else "excluded",
                selected_eligibility_revision=1,
                selected_eligibility_disposition="included" if included else "excluded",
                operative_included=included,
                candidate_for_explicit_review=False,
                exceptions=(),
            )
        )
    return tuple(evidence), tuple(review)


def _selection(
    student_id: str,
    *,
    candidates: tuple[int, ...],
    selected: tuple[int, ...],
    status: str = "selected",
) -> AttemptDecisionWorkflowProjection:
    assert set(selected) <= set(candidates)
    rows = tuple(
        AttemptDecisionCandidateRow(
            attempt=_attempt(student_id, number),
            eligible_evidence_count=8,
            selected_in_reviewed_decision=number in selected,
        )
        for number in candidates
    )
    return AttemptDecisionWorkflowProjection(
        status=status,
        resolution_status=status,
        class_id=_WORK.class_id,
        grade_item_id=_GRADE_ITEM,
        work=_WORK,
        student_id=student_id,
        source_snapshot=_source(),
        candidates=rows,
        reviewed_selected_attempts=tuple(
            _attempt(student_id, number) for number in selected
        ),
        selected_decision_revision=(
            1 if status in {"selected", "selected_none"} else None
        ),
        selected_decision_sha256=(
            "d" * 64 if status in {"selected", "selected_none"} else None
        ),
        current_policy_id=None,
        current_policy_revision=None,
        current_policy_sha256=None,
        minimum_selected=None,
        maximum_selected=None,
        operative_selection=status in {"selected", "selected_none"},
        stale_reason="membership_stale" if status == "stale" else None,
    )


def _case(
    *,
    size: int = 29,
    corrected: bool = True,
    retake: bool = True,
    requested_ids: set[str] | None = None,
) -> _Case:
    source_items: list[EvidenceItem] = []
    students: list[AssessmentEligibilityStudent] = []
    projections: dict[str, AttemptDecisionWorkflowProjection] = {}
    for i in range(1, size + 1):
        student_id = f"synthetic_student_{i:02d}"
        authorized = requested_ids is None or student_id in requested_ids
        if not authorized:
            students.append(
                AssessmentEligibilityStudent(
                    student_id=student_id,
                    display_label=f"Hidden Student {i}",
                    period="1",
                    items=(),
                    within_requested_authorization=False,
                )
            )
            continue
        expected = (
            ((1, 0, False), (2, 6, True))
            if i == 1 and corrected
            else (
                ((1, 4, False), (2, 5, False))
                if i == 2 and retake
                else ((1, 5, False),)
            )
        )
        review_items: list[AssessmentEligibilityItem] = []
        for number, earned, corrected_origin in expected:
            included = not (i == 1 and corrected and number == 1)
            native, eligibility = _student_items(
                student_id,
                number,
                earned,
                included=included,
                scan_review=corrected_origin,
            )
            source_items.extend(native)
            review_items.extend(eligibility)
        students.append(
            AssessmentEligibilityStudent(
                student_id=student_id,
                display_label=f"Synthetic Student {i:02d}",
                period="1",
                items=tuple(review_items),
                within_requested_authorization=True,
            )
        )
        candidates = (
            (2,) if i == 1 and corrected else ((1, 2) if i == 2 and retake else (1,))
        )
        projections[student_id] = _selection(
            student_id, candidates=candidates, selected=(candidates[-1],)
        )
    review = AssessmentEligibilityReview(
        class_id=_WORK.class_id,
        grade_item_id=_GRADE_ITEM,
        work=_WORK,
        publication_id=_PUB,
        cache_key=_CACHE,
        snapshot_digest=_DIGEST,
        source_status="current",
        membership_state="included",
        membership_revision=1,
        academic_period_id=None,
        academic_period_calendar_revision=None,
        students=tuple(students),
        shared_items=(),
        unmatched_items=(),
        exceptions=(),
        status_counts=(),
        projected_item_count=len(source_items),
        candidate_item_count=0,
        coverage_unavailable_student_count=0,
        outside_authorization_scope_count=sum(
            not s.within_requested_authorization for s in students
        ),
        class_label="Synthetic English 11",
        assessment_title="Synthetic Six-Question Assessment",
    )
    return _Case(review, EvidenceInventory(tuple(source_items)), projections)


def _build(case: _Case, **kwargs: object):
    return build_assessment_attempt_inventory(
        review=case.review,
        inventory=case.inventory,
        selection_projections=case.selections,
        supports_multiple_attempts=True,
        **kwargs,
    )


def test_classroom_29_students_six_question_scoreform_history_is_not_a_policy() -> None:
    case = _case()
    original_items = case.inventory.items
    result = _build(case)
    assert len(result.students) == 29
    first = result.students[0]
    assert first.student_id == "synthetic_student_01"
    assert len(first.attempts) == 2
    assert [r.point_result for r in first.attempts] == [(0, 6), (6, 6)]
    assert [r.current_selected for r in first.attempts] == [False, True]
    assert [r.operative_eligible for r in first.attempts] == [False, True]
    assert first.attempts[1].result_origin == "scan_review_manual"
    assert first.attempts[1].scan_review_failure_reference
    assert "multiple_attempts_relationship_unverified" in first.attention
    assert not result.students[2].needs_attention
    assert case.inventory.items == original_items  # immutable source unchanged


def test_distinct_retakes_remain_unclassified_and_selected_exactly() -> None:
    result = _build(_case())
    retake = result.students[1]
    assert [r.point_result for r in retake.attempts] == [(4, 6), (5, 6)]
    assert [r.current_selected for r in retake.attempts] == [False, True]
    assert "multiple_attempts_relationship_unverified" in retake.attention
    assert not retake.attempts[1].scan_review_failure_reference


def test_multiple_selected_attempts_require_separate_reassessment_state() -> None:
    case = _case()
    case.selections["synthetic_student_02"] = _selection(
        "synthetic_student_02", candidates=(1, 2), selected=(1, 2)
    )
    unresolved = _build(case)
    assert "reassessment_unresolved" in unresolved.students[1].attention
    resolved = _build(case, reassessment_statuses={"synthetic_student_02": "resolved"})
    assert resolved.students[1].reassessment_status == "resolved"
    assert "reassessment_unresolved" not in resolved.students[1].attention
    assert "multiple_attempts_relationship_unverified" in resolved.students[1].attention


def test_restricted_roster_scope_never_exposes_outside_students() -> None:
    requested = {"synthetic_student_01", "synthetic_student_02"}
    case = _case(requested_ids=requested)
    result = _build(case)
    assert len(result.students) == 2
    assert result.outside_requested_authorization_scope_count == 27
    preview = render_assessment_attempt_inventory(result, attention_only=False)
    assert "Hidden Student" not in preview
    assert "synthetic_student_03" not in preview
    assert "Synthetic Student 01" in preview


def test_nonattempt_capability_does_not_manufacture_an_academic_attempt() -> None:
    case = _case(size=1, corrected=False, retake=False)
    case.selections["synthetic_student_01"] = _selection(
        "synthetic_student_01", candidates=(), selected=(), status="not_applicable"
    )
    result = build_assessment_attempt_inventory(
        review=case.review,
        inventory=case.inventory,
        selection_projections=case.selections,
        supports_multiple_attempts=False,
    )
    assert result.students[0].attempts == ()
    assert result.students[0].selection_status == "not_applicable"


def test_exact_source_change_or_foreign_projection_fails_closed() -> None:
    case = _case(size=1, corrected=False, retake=False)
    altered_review = replace(case.review, snapshot_digest="9" * 64)
    with pytest.raises(AssessmentAttemptInventoryScopeError):
        build_assessment_attempt_inventory(
            review=altered_review,
            inventory=case.inventory,
            selection_projections=case.selections,
            supports_multiple_attempts=True,
        )
    foreign = _selection("synthetic_student_99", candidates=(1,), selected=(1,))
    with pytest.raises(AssessmentAttemptInventoryScopeError):
        build_assessment_attempt_inventory(
            review=case.review,
            inventory=case.inventory,
            selection_projections={"synthetic_student_99": foreign},
            supports_multiple_attempts=True,
        )


def test_conflicting_target_native_identity_is_rejected_even_in_history() -> None:
    case = _case(size=1)
    # Attempt 2 claims the same target as Attempt 1 while keeping native seq 2.
    altered = list(case.inventory.items)
    for item in altered:
        if item.item_id.endswith("_2_0"):
            object.__setattr__(
                item,
                "target",
                EvidenceTarget(
                    target_kind="attempt", target_id="attempt_1", sequence=2
                ),
            )
            break
    with pytest.raises(AssessmentAttemptInventoryScopeError, match="Contradictory"):
        _build(case)


def test_stale_publication_preserves_history_but_never_current_pointer() -> None:
    case = _case(size=1)
    stale = _Case(
        review=replace(case.review, source_status="superseded"),
        inventory=case.inventory,
        selections={},
    )
    result = _build(stale)
    first = result.students[0]
    assert len(first.attempts) == 2
    assert not any(item.current_selected for item in first.attempts)
    assert "publication_not_current" in first.attention
    assert first.selection_status is None


def test_plaintext_paging_and_technical_details_are_scoped() -> None:
    case = _case(size=29)
    result = _build(case)
    text = render_assessment_attempt_inventory(result, attention_only=False)
    assert "page 1/2" in text
    assert "synthetic_student_01" not in text
    assert "source points 0/6" in text
    assert "Item IDs:" not in text
    second = render_assessment_attempt_inventory(result, attention_only=False, page=2)
    assert "Synthetic Student 29" in second
    technical = render_assessment_attempt_inventory(result, technical_details=True)
    assert "Snapshot digest:" in technical
    assert "Item IDs:" in technical
    with pytest.raises(ValueError):
        render_assessment_attempt_inventory(result, page=0)
    with pytest.raises(ValueError):
        render_assessment_attempt_inventory(result, attention_only=False, page=3)


def test_missing_projection_coverage_not_converted_to_zero_or_missing_grade() -> None:
    case = _case(size=1, corrected=False, retake=False)
    review = replace(
        case.review,
        projected_item_count=0,
        students=(replace(case.review.students[0], items=()),),
    )
    empty = _Case(
        review=review,
        inventory=EvidenceInventory(()),
        selections={
            "synthetic_student_01": _selection(
                "synthetic_student_01", candidates=(), selected=(), status="no_decision"
            )
        },
    )
    result = _build(empty)
    student = result.students[0]
    assert student.attempts == ()
    assert "projection_coverage_unavailable" in student.attention
    assert "inferred zero" in render_assessment_attempt_inventory(result)


def test_stale_or_unauthorized_reassessment_projections_are_not_accepted() -> None:
    case = _case(size=1, corrected=False, retake=False)
    with pytest.raises(AssessmentAttemptInventoryScopeError):
        _build(case, reassessment_statuses={"synthetic_student_01": "resolved"})
    with pytest.raises(AssessmentAttemptInventoryScopeError):
        _build(case, reassessment_statuses={"synthetic_student_99": "resolved"})
