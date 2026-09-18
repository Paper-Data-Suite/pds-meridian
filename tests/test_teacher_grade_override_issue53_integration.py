from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.effective_grade import resolve_effective_grade
from meridian.grade_policy import GradePolicyActor
from meridian.hybrid_grade_result import HybridGradeResultReference
from meridian.standards_grade_result import StandardsGradeResultReference
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
    get_current_teacher_grade_override_reference,
    list_teacher_grade_override_revisions,
    load_current_teacher_grade_override,
    load_teacher_grade_override_revision,
    write_teacher_grade_override_revision,
)
from meridian.teacher_grade_override_workflow import (
    TeacherGradeOverrideSelectedSource,
    TeacherGradeOverrideSourceResult,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "student_001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 17, 22, 30, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Path:
    class_root = tmp_path / "classes" / CLASS_ID
    class_root.mkdir(parents=True)
    (class_root / "roster.csv").write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "synthetic_class_2026,student_001,Synthetic,Student,1\n",
        encoding="utf-8",
    )
    return tmp_path


def _source_reference(
    family: str,
    *,
    revision: int,
    digest: str,
) -> GradeOverrideSourceResultReference:
    values = {
        "class_id": CLASS_ID,
        "student_id": STUDENT_ID,
        "school_year": PERIOD.school_year,
        "period_id": PERIOD.period_id,
        "calendar_revision": 1,
        "result_revision": revision,
        "result_sha256": digest,
    }
    if family == "conventional":
        reference = ConventionalGradeResultReference(**values)
    elif family == "standards_based":
        reference = StandardsGradeResultReference(**values)
    elif family == "hybrid":
        reference = HybridGradeResultReference(**values)
    else:
        raise AssertionError(f"unsupported family: {family}")
    return GradeOverrideSourceResultReference(
        family,  # type: ignore[arg-type]
        reference,
    )


def _selected_source(
    family: str,
    *,
    revision: int,
    digest: str,
    grade: str,
) -> TeacherGradeOverrideSelectedSource:
    return TeacherGradeOverrideSelectedSource(
        source=TeacherGradeOverrideSourceResult(
            source_result=_source_reference(
                family,
                revision=revision,
                digest=digest,
            ),
            source_status="calculated",
            base_grade=Decimal(grade),
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
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family=source.source_result.family,
        override_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision="override",
        source_result=source.source_result,
        replacement_grade=Decimal(replacement),
        withdrawn_override_reference=None,
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=rationale,
        decided_at=NOW + timedelta(minutes=revision),
    )


def _withdrawal(
    active: TeacherGradeOverrideDecision,
    *,
    revision: int,
) -> TeacherGradeOverrideDecision:
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family=active.calculation_family,
        override_revision=revision,
        supersedes_revision=revision - 1,
        decision="withdraw",
        source_result=active.source_result,
        replacement_grade=None,
        withdrawn_override_reference=teacher_grade_override_reference(active),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Withdraw the exact selected active override.",
        decided_at=NOW + timedelta(minutes=revision),
    )


def _select_latest(root: Path, decision: TeacherGradeOverrideDecision) -> None:
    preview = preview_teacher_grade_override_selection(
        root,
        teacher_grade_override_reference(decision),
    )
    commit_teacher_grade_override_selection_preview(root, preview)


@pytest.mark.parametrize(
    "family",
    ["conventional", "standards_based", "hybrid"],
)
def test_issue53_nonfloating_withdrawal_and_reactivation_are_explicit(
    tmp_path: Path,
    family: str,
) -> None:
    root = _workspace(tmp_path)
    source_v1 = _selected_source(
        family,
        revision=1,
        digest="a" * 64,
        grade="80.00",
    )
    first = _override(
        source_v1,
        revision=1,
        replacement="91.25",
        rationale="Override exact source revision 1.",
    )
    first_write = write_teacher_grade_override_revision(root, first)
    first_bytes = first_write.stored.content
    first_digest = first_write.stored.override_sha256

    assert get_current_teacher_grade_override_reference(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        first.calculation_family,
    ) is None
    before_selection = resolve_effective_grade(source_v1)
    assert before_selection.effective_grade == Decimal("80.00")
    assert before_selection.effective_source == "base"

    _select_latest(root, first)
    selected_first = load_current_teacher_grade_override(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        first.calculation_family,
    )
    assert selected_first is not None
    first_effective = resolve_effective_grade(
        source_v1,
        selected_override_reference=selected_first.reference,
        selected_override=selected_first.decision,
    )
    assert first_effective.effective_grade == Decimal("91.25")
    assert first_effective.effective_source == "override"

    source_v2 = _selected_source(
        family,
        revision=2,
        digest="b" * 64,
        grade="84.00",
    )
    still_v1 = resolve_effective_grade(
        source_v1,
        selected_override_reference=selected_first.reference,
        selected_override=selected_first.decision,
    )
    assert still_v1.effective_grade == Decimal("91.25")

    moved_source = resolve_effective_grade(
        source_v2,
        selected_override_reference=selected_first.reference,
        selected_override=selected_first.decision,
    )
    assert moved_source.override_applicability == "source_result_changed"
    assert moved_source.effective_grade == Decimal("84.00")
    assert moved_source.effective_source == "base"

    second = _override(
        source_v2,
        revision=2,
        replacement="94.50",
        rationale="Deliberately rebind through a new immutable decision.",
    )
    write_teacher_grade_override_revision(root, second)
    assert load_current_teacher_grade_override(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        second.calculation_family,
    ).reference == selected_first.reference
    _select_latest(root, second)
    selected_second = load_current_teacher_grade_override(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        second.calculation_family,
    )
    assert selected_second is not None
    rebound = resolve_effective_grade(
        source_v2,
        selected_override_reference=selected_second.reference,
        selected_override=selected_second.decision,
    )
    assert rebound.effective_grade == Decimal("94.50")
    assert rebound.effective_source == "override"

    withdrawn = _withdrawal(second, revision=3)
    write_teacher_grade_override_revision(root, withdrawn)
    before_withdrawal_selection = load_current_teacher_grade_override(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        second.calculation_family,
    )
    assert before_withdrawal_selection is not None
    assert before_withdrawal_selection.reference == selected_second.reference
    remains_active = resolve_effective_grade(
        source_v2,
        selected_override_reference=before_withdrawal_selection.reference,
        selected_override=before_withdrawal_selection.decision,
    )
    assert remains_active.effective_grade == Decimal("94.50")

    _select_latest(root, withdrawn)
    selected_withdrawal = load_current_teacher_grade_override(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        withdrawn.calculation_family,
    )
    assert selected_withdrawal is not None
    restored_base = resolve_effective_grade(
        source_v2,
        selected_override_reference=selected_withdrawal.reference,
        selected_override=selected_withdrawal.decision,
    )
    assert restored_base.override_applicability == "withdrawn"
    assert restored_base.effective_grade == Decimal("84.00")
    assert restored_base.effective_source == "base"

    reactivated = _override(
        source_v2,
        revision=4,
        replacement="96.00",
        rationale="Reactivation is a new immutable teacher decision.",
    )
    write_teacher_grade_override_revision(root, reactivated)
    _select_latest(root, reactivated)
    selected_reactivated = load_current_teacher_grade_override(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        reactivated.calculation_family,
    )
    assert selected_reactivated is not None
    final = resolve_effective_grade(
        source_v2,
        selected_override_reference=selected_reactivated.reference,
        selected_override=selected_reactivated.decision,
    )
    assert final.effective_grade == Decimal("96.00")
    assert final.effective_source == "override"
    assert list_teacher_grade_override_revisions(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        reactivated.calculation_family,
    ) == (1, 2, 3, 4)

    reloaded_first = load_teacher_grade_override_revision(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        reactivated.calculation_family,
        1,
    )
    assert reloaded_first.content == first_bytes
    assert reloaded_first.override_sha256 == first_digest
    assert reloaded_first.decision == first
