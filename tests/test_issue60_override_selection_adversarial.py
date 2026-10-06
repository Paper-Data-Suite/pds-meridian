from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from meridian.effective_grade import resolve_effective_grade
from meridian.grade_policy import GradePolicyActor
from meridian.teacher_grade_override import (
    TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
    TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideDecision,
    teacher_grade_override_reference,
)
from meridian.teacher_grade_override_lifecycle import (
    commit_teacher_grade_override_selection_preview,
    preview_teacher_grade_override_selection,
)
from meridian.teacher_grade_override_storage import (
    load_current_teacher_grade_override,
    write_teacher_grade_override_revision,
)
from meridian.teacher_grade_override_workflow import (
    TeacherGradeOverrideSelectedSource,
    TeacherGradeOverrideSourceResult,
)
from tests import test_effective_grade as effective_support
from tests import test_issue50_cross_producer_acceptance as issue50
from tests.cross_producer_attempts_support import prepare_attempt_workspace
from tests.cross_producer_test_support import SHARED_STUDENT_ID
from tests.cross_producer_workspace_support import SCOREFORM_WORK


@pytest.mark.parametrize(
    ("family", "status"),
    (
        ("conventional", "blocked"),
        ("conventional", "insufficient"),
        ("standards_based", "blocked"),
        ("standards_based", "insufficient"),
        ("hybrid", "blocked"),
        ("hybrid", "insufficient"),
    ),
)
def test_exact_override_can_replace_nonnumeric_base_without_clamp_or_rounding(
    family: str,
    status: str,
) -> None:
    source = effective_support.selected_source(
        family,
        status=status,
        grade=None,
    )
    decision = effective_support.active_override(
        source.source_result,
        replacement=Decimal("105.25"),
    )

    outcome = resolve_effective_grade(
        source,
        selected_override_reference=(
            effective_support.teacher_grade_override_reference(decision)
        ),
        selected_override=decision,
    )

    assert outcome.base_result_status == status
    assert outcome.base_grade is None
    assert outcome.override_applicability == "applicable"
    assert outcome.effective_source == "override"
    assert outcome.effective_grade == Decimal("105.25")


@pytest.mark.parametrize(
    "family",
    ("conventional", "standards_based", "hybrid"),
)
def test_stale_base_cannot_be_made_current_by_exact_override(family: str) -> None:
    source = effective_support.selected_source(
        family,
        freshness="stale",
        reasons=("inputs_changed",),
    )
    decision = effective_support.active_override(
        source.source_result,
        replacement=Decimal("105.25"),
    )

    outcome = resolve_effective_grade(
        source,
        selected_override_reference=(
            effective_support.teacher_grade_override_reference(decision)
        ),
        selected_override=decision,
    )

    assert outcome.override_applicability == "source_result_stale"
    assert outcome.override_reasons == ("source_result_stale",)
    assert outcome.effective_source == "none"
    assert outcome.effective_grade is None


def _selected_source_from_stored(
    reference,
    grade: Decimal,
) -> TeacherGradeOverrideSelectedSource:
    return TeacherGradeOverrideSelectedSource(
        source=TeacherGradeOverrideSourceResult(
            source_result=GradeOverrideSourceResultReference(
                "conventional",
                reference,
            ),
            source_status="calculated",
            base_grade=grade,
        ),
        freshness_status="current",
        freshness_reasons=(),
    )


def _override(
    source: TeacherGradeOverrideSelectedSource,
    *,
    revision: int,
    replacement: str,
    rationale: str,
) -> TeacherGradeOverrideDecision:
    reference = source.source_result.reference
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=reference.class_id,
        student_id=reference.student_id,
        target_period=issue50.PERIOD,
        calendar_revision=reference.calendar_revision,
        calculation_family=source.source_result.family,
        override_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision="override",
        source_result=source.source_result,
        replacement_grade=Decimal(replacement),
        withdrawn_override_reference=None,
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=rationale,
        decided_at=issue50.RESULT_TIME + timedelta(minutes=10 + revision),
    )


def _withdrawal(
    active: TeacherGradeOverrideDecision,
    *,
    revision: int,
) -> TeacherGradeOverrideDecision:
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=active.class_id,
        student_id=active.student_id,
        target_period=active.target_period,
        calendar_revision=active.calendar_revision,
        calculation_family=active.calculation_family,
        override_revision=revision,
        supersedes_revision=revision - 1,
        decision="withdraw",
        source_result=active.source_result,
        replacement_grade=None,
        withdrawn_override_reference=teacher_grade_override_reference(active),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Issue 60 explicitly withdraws the selected r2 override.",
        decided_at=issue50.RESULT_TIME + timedelta(minutes=10 + revision),
    )


def _select_override(root: Path, decision: TeacherGradeOverrideDecision) -> None:
    preview = preview_teacher_grade_override_selection(
        root,
        teacher_grade_override_reference(decision),
    )
    commit_teacher_grade_override_selection_preview(root, preview)


def test_result_selection_and_override_lifecycle_remain_explicit(
    tmp_path: Path,
) -> None:
    scenario = prepare_attempt_workspace(tmp_path)
    root = scenario.mixed.root

    item, item_sha256 = issue50._install_conventional_grade_item(root)
    membership, membership_sha256 = issue50._install_membership(
        root,
        item,
        item_sha256,
    )
    issue50._install_eligibility(
        root,
        scenario,
        membership,
        membership_sha256,
    )
    issue50._install_attempt_and_reassessment(
        root,
        scenario,
        membership_sha256,
    )
    issue50._install_grade_policy(root, item_sha256)

    work_evidence = (
        issue50.ConventionalGradeWorkEvidenceSpec(
            grade_item_id=issue50.GRADE_ITEM_ID,
            work=SCOREFORM_WORK,
            status="available",
            authorized_snapshots=(scenario.authorized["scoreform"],),
        ),
    )
    assembly = issue50.assemble_conventional_grade_calculation(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
        work_evidence,
    )
    assert assembly.outcome.status == "calculated"
    assert assembly.outcome.rounded_grade == Decimal("33.33")

    snapshot_one = issue50.create_conventional_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=issue50.RESULT_TIME,
    )
    written_one = issue50.write_conventional_grade_result_revision(
        root,
        snapshot_one,
        work_evidence=work_evidence,
    )
    issue50.select_conventional_grade_result_revision(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
        1,
        expected_current_result_revision=None,
    )
    selected_one = issue50.load_current_conventional_grade_result(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
    )
    assert selected_one is not None
    assert selected_one.reference == written_one.stored.reference

    source_one = _selected_source_from_stored(
        selected_one.reference,
        Decimal("33.33"),
    )
    override_one = _override(
        source_one,
        revision=1,
        replacement="105.25",
        rationale="Issue 60 binds exact override to selected Grade result r1.",
    )
    write_teacher_grade_override_revision(root, override_one)
    _select_override(root, override_one)
    selected_override_one = load_current_teacher_grade_override(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
        "conventional",
    )
    assert selected_override_one is not None

    effective_one = resolve_effective_grade(
        source_one,
        selected_override_reference=selected_override_one.reference,
        selected_override=selected_override_one.decision,
    )
    assert effective_one.override_applicability == "applicable"
    assert effective_one.effective_grade == Decimal("105.25")
    assert effective_one.effective_source == "override"

    snapshot_two = issue50.create_conventional_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=2,
        calculated_at=issue50.RESULT_TIME + timedelta(minutes=1),
    )
    written_two = issue50.write_conventional_grade_result_revision(
        root,
        snapshot_two,
        work_evidence=work_evidence,
    )

    # Writing r2 does not move the explicit current-result selector.
    assert issue50.get_current_conventional_grade_result_revision(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
    ) == 1
    still_one = issue50.load_current_conventional_grade_result(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
    )
    assert still_one is not None
    assert still_one.reference == written_one.stored.reference

    issue50.select_conventional_grade_result_revision(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
        2,
        expected_current_result_revision=1,
    )
    selected_two = issue50.load_current_conventional_grade_result(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
    )
    assert selected_two is not None
    assert selected_two.reference == written_two.stored.reference
    assert selected_two.reference != selected_one.reference

    source_two = _selected_source_from_stored(
        selected_two.reference,
        Decimal("33.33"),
    )

    # The selected r1 override cannot float onto explicitly selected r2.
    moved = resolve_effective_grade(
        source_two,
        selected_override_reference=selected_override_one.reference,
        selected_override=selected_override_one.decision,
    )
    assert moved.override_applicability == "source_result_changed"
    assert moved.override_reasons == ("source_result_mismatch",)
    assert moved.effective_grade == Decimal("33.33")
    assert moved.effective_source == "base"

    override_two = _override(
        source_two,
        revision=2,
        replacement="94.50",
        rationale="Issue 60 explicitly rebinds override authority to Grade r2.",
    )
    write_teacher_grade_override_revision(root, override_two)

    # Authoring a newer override revision still does not select it.
    before_override_two_selection = load_current_teacher_grade_override(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
        "conventional",
    )
    assert before_override_two_selection is not None
    assert before_override_two_selection.reference == selected_override_one.reference

    _select_override(root, override_two)
    selected_override_two = load_current_teacher_grade_override(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
        "conventional",
    )
    assert selected_override_two is not None
    rebound = resolve_effective_grade(
        source_two,
        selected_override_reference=selected_override_two.reference,
        selected_override=selected_override_two.decision,
    )
    assert rebound.override_applicability == "applicable"
    assert rebound.effective_grade == Decimal("94.50")
    assert rebound.effective_source == "override"

    withdrawal = _withdrawal(override_two, revision=3)
    write_teacher_grade_override_revision(root, withdrawal)

    # Writing the withdrawal is inert until that exact revision is selected.
    before_withdrawal_selection = load_current_teacher_grade_override(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
        "conventional",
    )
    assert before_withdrawal_selection is not None
    assert before_withdrawal_selection.reference == selected_override_two.reference
    still_overridden = resolve_effective_grade(
        source_two,
        selected_override_reference=before_withdrawal_selection.reference,
        selected_override=before_withdrawal_selection.decision,
    )
    assert still_overridden.effective_grade == Decimal("94.50")
    assert still_overridden.effective_source == "override"

    _select_override(root, withdrawal)
    selected_withdrawal = load_current_teacher_grade_override(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
        "conventional",
    )
    assert selected_withdrawal is not None
    restored = resolve_effective_grade(
        source_two,
        selected_override_reference=selected_withdrawal.reference,
        selected_override=selected_withdrawal.decision,
    )
    assert restored.override_applicability == "withdrawn"
    assert restored.override_reasons == ("selected_override_withdrawn",)
    assert restored.effective_grade == Decimal("33.33")
    assert restored.effective_source == "base"
