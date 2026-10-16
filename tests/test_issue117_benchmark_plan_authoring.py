"""Issue #117 Slice 6: teacher planning revisions preserve native evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.benchmark_analysis import (
    BenchmarkInstructionalGroup,
    BenchmarkStandardObservation,
    BenchmarkStudentResult,
    InstructionalResponse,
    TargetedInstructionResult,
    compose_benchmark_analysis,
)
from meridian.benchmark_plan_authoring import (
    BenchmarkPlanAuthoringError,
    BenchmarkPlanSourceChangedError,
    BenchmarkTeacherAnnotations,
    TeacherStandardAssessment,
    compose_teacher_benchmark_plan,
    save_teacher_benchmark_plan,
)
from meridian.benchmark_plan_storage import (
    BenchmarkPlanConflictError,
    list_benchmark_plan_revisions,
    load_benchmark_plan_revision,
    load_latest_benchmark_plan_revision,
)
from meridian.teacher_report import TeacherReportSourceReference
from meridian.teacher_report_render import render_teacher_report

NOW = datetime(2026, 10, 14, 17, tzinfo=UTC)
ROSTER = ("student_1", "student_2", "student_3")


def _baseline(*, changed_source: bool = False):
    return compose_benchmark_analysis(
        class_id="class_1",
        target_period=AcademicPeriodRef("2026-2027", "mp1"),
        calendar_revision=1,
        assessment_id="assessment_1",
        assessment_title="Synthetic Reading Benchmark",
        proficiency_levels=("developing", "meeting"),
        students=(
            BenchmarkStudentResult(
                "student_1", "Alex One", True, True, "valid", "8/10", "meeting"
            ),
            BenchmarkStudentResult(
                "student_2", "Bo Two", True, True, "missing_result"
            ),
            BenchmarkStudentResult(
                "student_3", "Cy Three", False, False, "not_assessed"
            ),
        ),
        standards=(
            BenchmarkStandardObservation(
                "reading.analysis", 2, 1, "Native standard evidence",
            ),
        ),
        source_references=(
            TeacherReportSourceReference(
                "publication", "assessment_1", "b" * 64 if changed_source else "a" * 64
            ),
        ),
        generated_at=NOW,
    )


def _annotations() -> BenchmarkTeacherAnnotations:
    return BenchmarkTeacherAnnotations(
        interpretation="Students need practice citing relevant textual evidence.",
        standards=(
            TeacherStandardAssessment(
                "reading.analysis", "challenging",
                "Compared the valid native results from this administration.", True,
            ),
        ),
        groups=(
            BenchmarkInstructionalGroup(
                "bubble_1", "Near threshold", ("student_1",),
                "Teacher-selected group for discussion",
            ),
        ),
        responses=(
            InstructionalResponse(
                "reteach_1", "small_group", "reading.analysis",
                ("student_1",), "Model evidence selection and reasoning",
                date(2026, 10, 20), date(2026, 10, 25),
                ("item_3",), ("reading.analysis",),
            ),
        ),
        follow_up=TargetedInstructionResult(
            "Short constructed response", date(2026, 10, 25),
            "New responses have not been scored for causal attribution.",
            ("student_1",), ("reading.analysis",),
            "One-to-one feedback", "Compare only like evidence.",
        ),
    )


def _save(tmp_path: Path, annotations: BenchmarkTeacherAnnotations, **updates: object):
    options = {
        "report": _baseline(),
        "annotations": annotations,
        "roster_student_ids": ROSTER,
        "plan_id": "plan_1",
        "teacher_id": "teacher_1",
        "assessment_id": "assessment_1",
        "confirmation": "SAVE PLAN",
        "saved_at": NOW,
    }
    options.update(updates)
    return save_teacher_benchmark_plan(tmp_path, **options)  # type: ignore[arg-type]


def test_authoring_preserves_assessment_rows_and_native_proficiency() -> None:
    original = _baseline()
    drafted = compose_teacher_benchmark_plan(
        original, _annotations(), roster_student_ids=ROSTER
    )
    assert drafted.preview_sha256 != original.preview_sha256
    assert drafted.source_references == original.source_references
    assert drafted.target_period == original.target_period
    assert drafted.generated_at == original.generated_at
    assert drafted.columns == original.columns
    assert all(
        item in drafted.rows
        for item in original.rows
        if item.values[6] == "no"
        and item.values[2] not in {"No response recorded", "No reassessment recorded"}
    )
    native = [
        row for row in drafted.rows
        if row.values[1] == "Configured proficiency"
    ]
    assert [(row.values[2], row.values[3]) for row in native] == [
        ("developing", None),
        ("meeting", "Alex One"),
    ]
    assert any(row.values[1] == "Teacher interpretation" for row in drafted.rows)
    assert any(row.values[2] == "Teacher judgment: Challenging" for row in drafted.rows)
    assert not any(row.values[2] == "No response recorded" for row in drafted.rows)
    assert not any(row.values[2] == "No reassessment recorded" for row in drafted.rows)
    markdown = render_teacher_report(drafted, "markdown").decode("utf-8")
    for index, section in enumerate((
        "Assessment Data", "Standards and Item Analysis",
        "Instructional Response", "Results from Targeted Instruction",
    ), start=1):
        assert f"## {index}. {section}" in markdown
    assert "causally attributed" in markdown
    assert "officially submitted or approved" in markdown


def test_empty_annotations_do_not_infer_a_response_or_proficiency() -> None:
    original = _baseline()
    drafted = compose_teacher_benchmark_plan(
        original, BenchmarkTeacherAnnotations(), roster_student_ids=ROSTER
    )
    assert drafted.preview_sha256 == original.preview_sha256
    assert drafted.rows == original.rows


def test_revising_same_draft_replaces_only_teacher_rows() -> None:
    first = compose_teacher_benchmark_plan(
        _baseline(), _annotations(), roster_student_ids=ROSTER
    )
    second = compose_teacher_benchmark_plan(
        first,
        BenchmarkTeacherAnnotations(
            interpretation="Now prioritize a different focus."
        ),
        roster_student_ids=ROSTER,
    )
    assert "Now prioritize" in render_teacher_report(second, "markdown").decode()
    assert "Model evidence selection" not in render_teacher_report(
        second, "markdown"
    ).decode()
    assert any(row.values[2] == "No response recorded" for row in second.rows)
    assert any(row.values[2] == "No reassessment recorded" for row in second.rows)
    assert second.source_references == first.source_references
    assert compose_teacher_benchmark_plan(
        second,
        BenchmarkTeacherAnnotations(interpretation="Now prioritize a different focus."),
        roster_student_ids=ROSTER,
    ).preview_sha256 == second.preview_sha256


@pytest.mark.parametrize("field", ("groups", "responses", "follow_up"))
def test_roster_boundary_rejects_outside_students(field: str) -> None:
    if field == "groups":
        annotations = BenchmarkTeacherAnnotations(groups=(
            BenchmarkInstructionalGroup(
                "group_1", "Not in roster", ("outsider",), "Teacher selected"
            ),
        ))
    elif field == "responses":
        annotations = BenchmarkTeacherAnnotations(responses=(
            InstructionalResponse(
                "response_1", "reteach", "reading.analysis", ("outsider",), "Practice"
            ),
        ))
    else:
        annotations = BenchmarkTeacherAnnotations(follow_up=TargetedInstructionResult(
            "Quiz", date(2026, 10, 25), "Teacher observed results", ("outsider",),
            (), "Additional support", "Notes",
        ))
    with pytest.raises(BenchmarkPlanAuthoringError):
        compose_teacher_benchmark_plan(
            _baseline(), annotations, roster_student_ids=ROSTER
        )


def test_no_teacher_strong_judgment_without_comparable_basis() -> None:
    for comparable, basis in ((False, "Evidence is comparable"), (True, "")):
        with pytest.raises(BenchmarkPlanAuthoringError):
            TeacherStandardAssessment("reading.analysis", "strong", basis, comparable)


def test_unknown_standard_cannot_be_classified() -> None:
    with pytest.raises(BenchmarkPlanAuthoringError):
        compose_teacher_benchmark_plan(
            _baseline(), BenchmarkTeacherAnnotations(standards=(
                TeacherStandardAssessment("other.standard", "unclassified", ""),
            )), roster_student_ids=ROSTER,
        )


def test_duplicate_groups_rejected_and_empty_roster_not_inferred() -> None:
    group = BenchmarkInstructionalGroup("group_1", "Group", (), "Teacher-created")
    with pytest.raises(BenchmarkPlanAuthoringError):
        BenchmarkTeacherAnnotations(groups=(group, group))
    with pytest.raises(BenchmarkPlanAuthoringError):
        compose_teacher_benchmark_plan(
            _baseline(), _annotations(), roster_student_ids=(),
        )


def test_no_plan_persistence_without_explicit_confirmation(tmp_path: Path) -> None:
    for confirmation in ("", "yes", "save plan"):
        with pytest.raises(BenchmarkPlanAuthoringError):
            _save(tmp_path, _annotations(), confirmation=confirmation)
    assert list_benchmark_plan_revisions(tmp_path, "class_1", "plan_1") == ()


def test_first_save_and_append_only_second_revision(tmp_path: Path) -> None:
    first = _save(tmp_path, _annotations())
    assert first.disposition == "created"
    assert first.stored.revision.plan_revision == 1
    assert first.stored.revision.currentness == "unverified"
    second = _save(
        tmp_path,
        BenchmarkTeacherAnnotations(interpretation="Revised teacher response"),
        expected_previous_revision_sha256=first.stored.revision_sha256,
        saved_at=NOW + timedelta(hours=2),
    )
    assert second.stored.revision.plan_revision == 2
    assert (
        second.stored.revision.previous_revision_sha256
        == first.stored.revision_sha256
    )
    assert second.stored.revision.created_at == first.stored.revision.created_at
    assert list_benchmark_plan_revisions(tmp_path, "class_1", "plan_1") == (1, 2)
    historical = load_benchmark_plan_revision(tmp_path, "class_1", "plan_1", 1)
    assert historical.revision_sha256 == first.stored.revision_sha256
    assert "Model evidence selection" in render_teacher_report(
        historical.revision.report, "markdown"
    ).decode()
    assert load_latest_benchmark_plan_revision(
        tmp_path, "class_1", "plan_1"
    ).revision_sha256 == second.stored.revision_sha256


def test_save_refuses_stale_revision_and_existing_plan_without_anchor(
    tmp_path: Path,
) -> None:
    first = _save(tmp_path, _annotations())
    with pytest.raises(BenchmarkPlanConflictError):
        _save(tmp_path, _annotations())
    with pytest.raises(BenchmarkPlanConflictError):
        _save(tmp_path, _annotations(), expected_previous_revision_sha256="0" * 64)
    assert first.stored.revision.plan_revision == 1


def test_save_rejects_changed_sources_and_modified_native_rows(tmp_path: Path) -> None:
    first = _save(tmp_path, _annotations())
    with pytest.raises(BenchmarkPlanSourceChangedError):
        _save(
            tmp_path, _annotations(), report=_baseline(changed_source=True),
            expected_previous_revision_sha256=first.stored.revision_sha256,
        )
    changed = _baseline()
    rows = list(changed.rows)
    native = next(
        index for index, row in enumerate(rows) if row.values[1] == "Participation"
    )
    old = rows[native]
    values = list(old.values)
    values[3] = "999"
    rows[native] = replace(old, values=tuple(values))
    from meridian.teacher_report import compose_teacher_report_preview

    forged = compose_teacher_report_preview(
        report_kind=changed.report_kind, title=changed.title,
        class_id=changed.class_id, target_period=changed.target_period,
        calendar_revision=changed.calendar_revision,
        source_references=changed.source_references, generated_at=changed.generated_at,
        summary=changed.summary, columns=changed.columns, rows=rows,
        diagnostics=changed.diagnostics,
    )
    with pytest.raises(BenchmarkPlanSourceChangedError):
        _save(tmp_path, _annotations(), report=forged,
              expected_previous_revision_sha256=first.stored.revision_sha256)


def test_no_source_references_or_naive_clock_cannot_save(tmp_path: Path) -> None:
    no_source = compose_benchmark_analysis(
        class_id="class_1", target_period=AcademicPeriodRef("2026-2027", "mp1"),
        calendar_revision=1, assessment_id="assessment_1", assessment_title="Synthetic",
        proficiency_levels=("meeting",),
        students=(),
        source_references=(),
        generated_at=NOW,
    )
    with pytest.raises(BenchmarkPlanAuthoringError):
        _save(tmp_path, BenchmarkTeacherAnnotations(), report=no_source)
    with pytest.raises(BenchmarkPlanAuthoringError):
        _save(tmp_path, BenchmarkTeacherAnnotations(), saved_at=datetime(2026, 10, 14))


def test_save_rejects_changed_teacher_and_assessment_identity(tmp_path: Path) -> None:
    first = _save(tmp_path, _annotations())
    for field, value in (
        ("teacher_id", "other_teacher"),
        ("assessment_id", "other_assessment"),
    ):
        with pytest.raises(BenchmarkPlanSourceChangedError):
            _save(tmp_path, _annotations(),
                  expected_previous_revision_sha256=first.stored.revision_sha256,
                  **{field: value})
