"""#125-C: synthetic, read-only exact selection, exception and CAS plan tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.assessment_eligibility_plan as batch
from meridian.assessment_eligibility_review import (
    AssessmentEligibilityException,
    AssessmentEligibilityItem,
    AssessmentEligibilityReview,
    AssessmentEligibilityStudent,
)
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.guided_eligibility import DEFAULT_GUIDED_ELIGIBILITY_POLICIES
from meridian.teacher_action_contract import TeacherActionActor

CLASS = "synthetic_english_12"
WORK = ModuleWorkRef("scoreform", CLASS, "question_check_125c")
PUB = "pub_" + "1" * 32
CACHE = "2" * 64
DIGEST = "3" * 64
MEMBER_DIGEST = "4" * 64
SELECTED_DIGEST = "5" * 64
ACTOR = TeacherActionActor("teacher_1", "6" * 64, "saved")
POLICY = DEFAULT_GUIDED_ELIGIBILITY_POLICIES[0]


def make_item(
    student_id: str | None,
    question: int,
    *,
    status: str | None = "no_decision",
    operative: bool = False,
    exception: str | None = None,
    candidate: bool | None = None,
) -> AssessmentEligibilityItem:
    suffix = f"{student_id or 'shared'}_question_{question}"
    issues = (
        (AssessmentEligibilityException(exception, "review-individual", student_id),)
        if exception
        else ()
    )
    disposition = (
        status if status in {"included", "excluded", "pending", "unsupported"} else None
    )
    return AssessmentEligibilityItem(
        source=EvidenceSourceReference(WORK, PUB, CACHE, DIGEST, suffix),
        student_id=student_id,
        evidence_label=f"Question {question}",
        target_kind="question",
        target_id=f"q{question}",
        result_kind="question_score",
        eligibility_status=status,
        selected_eligibility_revision=1 if disposition else None,
        selected_eligibility_disposition=disposition,
        operative_included=operative,
        candidate_for_explicit_review=(
            status == "no_decision" and not issues if candidate is None else candidate
        ),
        exceptions=issues,
    )


def make_review(
    *,
    student_count: int = 2,
    questions: int = 3,
    overrides: dict[tuple[str, int], AssessmentEligibilityItem] | None = None,
    shared: tuple[AssessmentEligibilityItem, ...] = (),
    source_status: str = "current",
    period: str = "mp1",
) -> AssessmentEligibilityReview:
    overrides = overrides or {}
    students = []
    issues = []
    all_items: list[AssessmentEligibilityItem] = []
    for index in range(1, student_count + 1):
        student_id = f"student_{index:02d}"
        items = tuple(
            overrides.get((student_id, q), make_item(student_id, q))
            for q in range(1, questions + 1)
        )
        students.append(
            AssessmentEligibilityStudent(
                student_id, f"Sample {index} Student", "2", items, True
            )
        )
        all_items.extend(items)
        for item in items:
            issues.extend(item.exceptions)
    all_items.extend(shared)
    for item in shared:
        issues.extend(item.exceptions)
    return AssessmentEligibilityReview(
        class_id=CLASS,
        grade_item_id="grade_item_125c",
        work=WORK,
        publication_id=PUB,
        cache_key=CACHE,
        snapshot_digest=DIGEST,
        source_status=source_status,
        membership_state="included",
        membership_revision=2,
        academic_period_id=period,
        academic_period_calendar_revision=3,
        students=tuple(students),
        shared_items=shared,
        unmatched_items=(),
        exceptions=tuple(issues),
        status_counts=(),
        projected_item_count=len(all_items),
        candidate_item_count=sum(
            item.candidate_for_explicit_review for item in all_items
        ),
        no_result_student_count=0,
        outside_authorization_scope_count=0,
        class_label="English 12",
        assessment_title="Synthetic six-question check",
    )


def ids(review: AssessmentEligibilityReview) -> tuple[str, ...]:
    return tuple(
        item.source.item_id for student in review.students for item in student.items
    )


def witnesses(
    review: AssessmentEligibilityReview, chosen: tuple[str, ...]
) -> tuple[batch.BatchEligibilityPointerWitness, ...]:
    indexed = {
        item.source.item_id: item
        for student in review.students
        for item in student.items
    }
    indexed.update({item.source.item_id: item for item in review.shared_items})
    return tuple(
        batch.BatchEligibilityPointerWitness(
            indexed[key].source,
            indexed[key].selected_eligibility_revision,
            SELECTED_DIGEST
            if indexed[key].selected_eligibility_revision is not None
            else None,
            2,
            MEMBER_DIGEST,
        )
        for key in chosen
    )


def plan(
    review: AssessmentEligibilityReview,
    selection: batch.BatchEligibilitySelection | None = None,
) -> batch.BatchEligibilityReviewPlan:
    selection = selection or batch.BatchEligibilitySelection(ids(review), "included")
    return batch.build_batch_eligibility_plan(
        review,
        selection,
        actor=ACTOR,
        policy=POLICY,
        witnesses=witnesses(review, selection.selected_item_ids),
    )


def test_29_by_6_is_174_exact_immutable_actions_without_writes() -> None:
    review = make_review(student_count=29, questions=6)
    result = plan(review)
    assert len(result.items) == 174
    assert result.action_count == 174
    assert result.blocked_count == 0
    assert len({item.source for item in result.items}) == 174
    assert result.membership_revision == 2
    assert result.membership_sha256 == MEMBER_DIGEST
    assert len(result.roster_and_source_sha256) == 64
    with pytest.raises(FrozenInstanceError):
        result.items[0].status = "blocked"  # type: ignore[misc]
    summary = batch.render_batch_eligibility_plan(result)
    assert "NOT APPLIED" in summary
    assert "proposed Include 174" in summary
    assert "Sample 1 Student / Question 1" in summary
    assert "student_01_question_1" not in summary
    assert "pub_" not in summary
    assert "cannot confirm" in summary


def test_selection_does_not_expand_to_unselected_items() -> None:
    review = make_review(student_count=2, questions=3)
    selection = batch.BatchEligibilitySelection(ids(review)[:1], "included")
    result = plan(review, selection)
    assert len(result.items) == 1
    assert result.action_count == 1


def test_student_and_item_override_precedence_and_fixed_expansion() -> None:
    review = make_review(student_count=2, questions=3)
    selected = ids(review)
    choice = batch.BatchEligibilitySelection(
        selected,
        "included",
        student_exceptions=(
            batch.BatchStudentException(
                "student_02", "excluded", ("eligibility.manual",), "Scan review"
            ),
        ),
        item_exceptions=(
            batch.BatchItemException("student_02_question_2", None),
            batch.BatchItemException("student_02_question_3", "included"),
        ),
    )
    result = plan(review, choice)
    states = {x.source.item_id: (x.status, x.disposition) for x in result.items}
    assert states["student_02_question_1"] == ("action", "excluded")
    assert states["student_02_question_2"] == ("deferred", None)
    assert states["student_02_question_3"] == ("action", "included")
    assert result.action_count == 5
    assert result.deferred_count == 1
    assert result.items[-3].rationale == "Scan review"


def test_previous_excluded_is_blocked_without_specific_replacement() -> None:
    old = make_item("student_01", 1, status="excluded", exception="previous_excluded")
    review = make_review(
        student_count=1, questions=1, overrides={("student_01", 1): old}
    )
    normal = plan(review)
    assert normal.blocked_count == 1
    assert (
        normal.items[0].status_reason == "replacement_requires_item_or_student_override"
    )
    choice = batch.BatchEligibilitySelection(
        ids(review),
        "included",
        item_exceptions=(
            batch.BatchItemException(
                "student_01_question_1", "included", replace_existing=True
            ),
        ),
    )
    changed = plan(review, choice)
    assert changed.action_count == 1
    assert changed.items[0].witness.selected_revision == 1
    assert changed.items[0].witness.selected_sha256 == SELECTED_DIGEST


def test_matching_prior_included_decision_is_unchanged_not_duplicate() -> None:
    old = make_item("student_01", 1, status="included", operative=True)
    review = make_review(
        student_count=1, questions=1, overrides={("student_01", 1): old}
    )
    result = plan(review)
    assert result.unchanged_count == 1
    assert result.action_count == 0
    assert result.items[0].status_reason == "existing_matching_selection"


def test_existing_included_to_excluded_needs_reason_and_explicit_replacement() -> None:
    old = make_item("student_01", 1, status="included", operative=True)
    review = make_review(
        student_count=1, questions=1, overrides={("student_01", 1): old}
    )
    choice = batch.BatchEligibilitySelection(
        ids(review), "excluded", ("eligibility.manual",)
    )
    assert plan(review, choice).blocked_count == 1
    changed = plan(
        review,
        batch.BatchEligibilitySelection(
            ids(review),
            "included",
            item_exceptions=(
                batch.BatchItemException(
                    "student_01_question_1",
                    "excluded",
                    ("eligibility.manual",),
                    replace_existing=True,
                ),
            ),
        ),
    )
    assert changed.action_count == 1
    assert changed.items[0].disposition == "excluded"


def test_unknown_or_shared_evidence_is_never_auto_actionable() -> None:
    shared = make_item(None, 1, exception="non_student_evidence")
    review = make_review(student_count=1, questions=1, shared=(shared,))
    choice = batch.BatchEligibilitySelection(
        (*ids(review), shared.source.item_id), "included"
    )
    result = plan(review, choice)
    assert len(result.items) == 2
    assert result.action_count == 1
    assert result.blocked_count == 1
    assert "Unmatched or shared evidence" in batch.render_batch_eligibility_plan(result)


def test_changed_publication_blocks_actions_but_preserves_review() -> None:
    review = make_review(student_count=1, questions=1, source_status="withdrawn")
    result = plan(review)
    assert result.action_count == 0
    assert result.blocked_count == 1
    assert result.items[0].status_reason == "source_not_current"


@pytest.mark.parametrize("status", ["excluded", "pending", "unsupported"])
def test_nonincluded_decisions_require_explicit_semantic_reason(status: str) -> None:
    with pytest.raises(batch.AssessmentEligibilityPlanError, match="reason"):
        batch.BatchEligibilitySelection(
            ("item_1",), cast(batch.TeacherDisposition, status)
        )
    with pytest.raises(batch.AssessmentEligibilityPlanError, match="reason"):
        batch.BatchItemException("item_1", cast(batch.TeacherDisposition, status))
    choice = batch.BatchEligibilitySelection(
        ("item_1",), cast(batch.TeacherDisposition, status), ("eligibility.manual",)
    )
    assert choice.disposition == status


def test_lifecycle_dispositions_and_inclusion_reasons_are_rejected() -> None:
    with pytest.raises(batch.AssessmentEligibilityPlanError):
        batch.BatchEligibilitySelection(
            ("item_1",),
            "withdrawn",  # type: ignore[arg-type]
        )
    with pytest.raises(batch.AssessmentEligibilityPlanError):
        batch.BatchEligibilitySelection(
            ("item_1",),
            "superseded",  # type: ignore[arg-type]
        )
    with pytest.raises(batch.AssessmentEligibilityPlanError, match="Include"):
        batch.BatchEligibilitySelection(
            ("item_1",), "included", ("eligibility.manual",)
        )


def test_duplicate_selection_or_override_rejected() -> None:
    with pytest.raises(batch.AssessmentEligibilityPlanError):
        batch.BatchEligibilitySelection(("item_1", "item_1"), "included")
    with pytest.raises(batch.AssessmentEligibilityPlanError):
        batch.BatchEligibilitySelection(
            ("item_1",),
            "included",
            item_exceptions=(
                batch.BatchItemException("item_1", None),
                batch.BatchItemException("item_1", None),
            ),
        )


def test_unselected_override_and_unmatched_student_exception_are_rejected() -> None:
    review = make_review(student_count=2, questions=1)
    selection = batch.BatchEligibilitySelection(
        ("student_01_question_1",),
        "included",
        item_exceptions=(batch.BatchItemException("student_02_question_1", None),),
    )
    with pytest.raises(batch.AssessmentEligibilityPlanError, match="outside selected"):
        plan(review, selection)
    with pytest.raises(batch.AssessmentEligibilityPlanError, match="no selected"):
        plan(
            review,
            batch.BatchEligibilitySelection(
                ("student_01_question_1",),
                "included",
                student_exceptions=(batch.BatchStudentException("student_02", None),),
            ),
        )


def test_selected_witnesses_must_be_exact_and_consistent() -> None:
    review = make_review(student_count=1, questions=2)
    choice = batch.BatchEligibilitySelection(ids(review), "included")
    exact = witnesses(review, choice.selected_item_ids)
    for invalid in (exact[:1], (exact[0], exact[0])):
        with pytest.raises(batch.AssessmentEligibilityPlanError):
            batch.build_batch_eligibility_plan(
                review, choice, actor=ACTOR, policy=POLICY, witnesses=invalid
            )
    with pytest.raises(batch.AssessmentEligibilityPlanStaleError):
        batch.build_batch_eligibility_plan(
            review,
            choice,
            actor=ACTOR,
            policy=POLICY,
            witnesses=(replace(exact[0], membership_sha256="f" * 64), exact[1]),
        )


def test_review_fingerprint_detects_roster_period_and_item_drift() -> None:
    review = make_review(student_count=1, questions=1)
    result = plan(review)
    batch.assert_batch_plan_review_current(result, review)
    changed_roster = replace(
        review,
        students=(replace(review.students[0], display_label="Another Student"),),
    )
    with pytest.raises(batch.AssessmentEligibilityPlanStaleError):
        batch.assert_batch_plan_review_current(result, changed_roster)
    with pytest.raises(batch.AssessmentEligibilityPlanStaleError):
        batch.assert_batch_plan_review_current(
            result, replace(review, academic_period_id="mp2")
        )
    changed_item = replace(review.students[0].items[0], target_id="q99")
    with pytest.raises(batch.AssessmentEligibilityPlanStaleError):
        batch.assert_batch_plan_review_current(
            result,
            replace(
                review,
                students=(replace(review.students[0], items=(changed_item,)),),
            ),
        )


def test_input_order_cannot_change_plan_identity() -> None:
    review = make_review(student_count=2, questions=2)
    chosen = ids(review)
    first = plan(review)
    second = plan(
        review,
        batch.BatchEligibilitySelection(tuple(reversed(chosen)), "included"),
    )
    assert first.plan_sha256 == second.plan_sha256
    assert first.items == second.items


def test_unqualified_policy_and_invalid_actor_rejected() -> None:
    review = make_review(student_count=1, questions=1)
    with pytest.raises(batch.AssessmentEligibilityPlanError):
        batch.build_batch_eligibility_plan(
            review,
            batch.BatchEligibilitySelection(ids(review), "included"),
            actor=cast(TeacherActionActor, "fake actor"),
            policy=POLICY,
            witnesses=witnesses(review, ids(review)),
        )
    with pytest.raises(batch.AssessmentEligibilityPlanError):
        batch.build_batch_eligibility_plan(
            review,
            batch.BatchEligibilitySelection(ids(review), "included"),
            actor=ACTOR,
            policy=replace(POLICY, policy_id="not_qualified"),
            witnesses=witnesses(review, ids(review)),
        )


def test_canonical_cas_capture_is_read_only_and_requires_matching_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=1)
    item = review.students[0].items[0]
    fake_authorized = SimpleNamespace(
        stored=SimpleNamespace(
            snapshot=SimpleNamespace(
                source=SimpleNamespace(
                    publication=SimpleNamespace(work=WORK, publication_id=PUB)
                )
            ),
            cache_key=CACHE,
            snapshot_digest=DIGEST,
        ),
        assessment=SimpleNamespace(source_status="current"),
    )
    monkeypatch.setattr(batch, "AuthorizedProjectionSnapshot", SimpleNamespace)
    monkeypatch.setattr(
        batch,
        "load_current_grade_item_membership_decision",
        lambda *args: SimpleNamespace(
            decision=SimpleNamespace(
                decision="included",
                membership_revision=2,
                academic_period=SimpleNamespace(
                    period=SimpleNamespace(period_id="mp1"), calendar_revision=3
                ),
            ),
            decision_sha256=MEMBER_DIGEST,
        ),
    )
    monkeypatch.setattr(
        batch,
        "load_current_evidence_eligibility_decision",
        lambda *args: None,
    )
    captured = batch.capture_batch_pointer_witnesses(
        "workspace", review, fake_authorized, (item.source.item_id,)
    )
    assert captured == witnesses(review, (item.source.item_id,))
    assert plan(review).action_count == 1
    fake_authorized.stored.snapshot_digest = "f" * 64
    with pytest.raises(batch.AssessmentEligibilityPlanStaleError):
        batch.capture_batch_pointer_witnesses(
            "workspace", review, fake_authorized, (item.source.item_id,)
        )


def test_cas_capture_detects_changed_selected_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=1)
    fake_authorized = SimpleNamespace(
        stored=SimpleNamespace(
            snapshot=SimpleNamespace(
                source=SimpleNamespace(
                    publication=SimpleNamespace(work=WORK, publication_id=PUB)
                )
            ),
            cache_key=CACHE,
            snapshot_digest=DIGEST,
        ),
        assessment=SimpleNamespace(source_status="current"),
    )
    monkeypatch.setattr(batch, "AuthorizedProjectionSnapshot", SimpleNamespace)
    monkeypatch.setattr(
        batch,
        "load_current_grade_item_membership_decision",
        lambda *args: SimpleNamespace(
            decision=SimpleNamespace(
                decision="included",
                membership_revision=2,
                academic_period=SimpleNamespace(
                    period=SimpleNamespace(period_id="mp1"), calendar_revision=3
                ),
            ),
            decision_sha256=MEMBER_DIGEST,
        ),
    )
    monkeypatch.setattr(
        batch,
        "load_current_evidence_eligibility_decision",
        lambda *args: SimpleNamespace(
            decision=SimpleNamespace(eligibility_revision=3, disposition="excluded"),
            decision_sha256=SELECTED_DIGEST,
        ),
    )
    with pytest.raises(batch.AssessmentEligibilityPlanStaleError):
        batch.capture_batch_pointer_witnesses(
            "workspace", review, fake_authorized, ids(review)
        )


def test_no_zero_item_batch_is_misrepresented_as_safely_actionable() -> None:
    review = make_review(student_count=1, questions=1)
    with pytest.raises(batch.AssessmentEligibilityPlanError, match="No exact item"):
        plan(review, batch.BatchEligibilitySelection((), "included"))


@pytest.mark.parametrize("disposition", ["excluded", "pending", "unsupported"])
def test_nonincluded_batch_actions_are_exact_and_reasoned(disposition: str) -> None:
    review = make_review(student_count=1, questions=2)
    choice = batch.BatchEligibilitySelection(
        ids(review),
        cast(batch.TeacherDisposition, disposition),
        ("eligibility.manual",),
        "Reviewed native evidence",
    )
    result = plan(review, choice)
    assert result.action_count == 2
    assert all(item.disposition == disposition for item in result.items)
    assert all(item.reason_codes == ("eligibility.manual",) for item in result.items)
    assert all(item.rationale == "Reviewed native evidence" for item in result.items)


def test_cas_witness_rejects_partial_pointer_or_bad_digest() -> None:
    review = make_review(student_count=1, questions=1)
    source = review.students[0].items[0].source
    with pytest.raises(batch.AssessmentEligibilityPlanError):
        batch.BatchEligibilityPointerWitness(source, 1, None, 2, MEMBER_DIGEST)
    with pytest.raises(batch.AssessmentEligibilityPlanError):
        batch.BatchEligibilityPointerWitness(source, None, "f" * 64, 2, MEMBER_DIGEST)
    with pytest.raises(batch.AssessmentEligibilityPlanError):
        batch.BatchEligibilityPointerWitness(source, None, None, 2, "not-a-digest")


def test_reasons_reject_unbounded_or_duplicate_contract_codes() -> None:
    invalid_reasons = (
        ("eligibility.manual", "eligibility.manual"),
        ("INCOMPATIBLE",),
        ("nonconforming code",),
        ("x" * 129,),
    )
    for codes in invalid_reasons:
        with pytest.raises(batch.AssessmentEligibilityPlanError):
            batch.BatchEligibilitySelection(("item_1",), "excluded", codes)
