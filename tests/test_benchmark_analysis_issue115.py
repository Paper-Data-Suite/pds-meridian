from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.benchmark_analysis import (
    BenchmarkAnalysisError,
    BenchmarkInstructionalGroup,
    BenchmarkItemObservation,
    BenchmarkStandardObservation,
    BenchmarkStudentResult,
    InstructionalResponse,
    TargetedInstructionResult,
    compose_benchmark_analysis,
)
from meridian.benchmark_plan_storage import (
    BENCHMARK_PLAN_RECORD_TYPE,
    BENCHMARK_PLAN_SCHEMA_VERSION,
    BenchmarkPlanRevision,
    list_benchmark_plan_revisions,
    load_latest_benchmark_plan_revision,
    write_benchmark_plan_revision,
)
from meridian.cli import main
from meridian.publication_authorization import (
    AUTHORIZATION_POLICY_RECORD_TYPE,
    AUTHORIZATION_POLICY_SCHEMA_VERSION,
    default_authorization_policy_path,
)
from meridian.teacher_report import (
    TeacherReportPreview,
    TeacherReportSourceReference,
    teacher_report_preview_to_json_bytes,
)
from meridian.teacher_report_render import render_teacher_report

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
SOURCE = TeacherReportSourceReference(
    "publication", "assessment_1", "a" * 64
)


def _preview() -> TeacherReportPreview:
    return compose_benchmark_analysis(
        class_id="class_1",
        target_period=AcademicPeriodRef("2026-2027", "mp1"),
        calendar_revision=1,
        assessment_id="assessment_1",
        assessment_title="Fall Benchmark",
        proficiency_levels=("advanced", "developing", "beginning"),
        students=(
            BenchmarkStudentResult(
                "student_1", "Ada One", True, True, "valid", "8/10", "advanced"
            ),
            BenchmarkStudentResult(
                "student_2", "Bo Two", True, True, "missing_result"
            ),
            BenchmarkStudentResult(
                "student_3", "Cy Three", False, False, "not_assessed"
            ),
        ),
        source_references=(SOURCE,),
        generated_at=NOW,
        groups=(
            BenchmarkInstructionalGroup(
                "bubble", "Bubble", ("student_2",), "Teacher-created conference group"
            ),
        ),
        standards=(
            BenchmarkStandardObservation(
                "math.1",
                2,
                1,
                "One selected proficiency result",
                "challenging",
                "Comparable native results",
                True,
            ),
        ),
        items=(
            BenchmarkItemObservation("q1", 1, 1, 1, 1, ("math.1",), "multiple choice"),
            BenchmarkItemObservation("q2", 0, 2, 0, 0, ("math.1",), None),
        ),
        responses=(
            InstructionalResponse(
                "response_1",
                "small_group",
                "math.1",
                ("student_2",),
                "Worked examples",
                date(2026, 10, 15),
                date(2026, 10, 22),
                ("q2",),
                ("math.1",),
            ),
        ),
        follow_up=TargetedInstructionResult(
            "Exit ticket",
            date(2026, 10, 22),
            "One valid follow-up result",
            ("student_2",),
            ("math.1",),
            "Additional modeled practice",
            "Continue support",
        ),
        teacher_interpretation="Students need more work explaining their reasoning.",
    )


def test_benchmark_preserves_native_semantics_and_four_sections() -> None:
    preview = _preview()
    assert preview.report_kind == "benchmark_analysis_instructional_response"
    values = "\n".join(value or "" for row in preview.rows for value in row.values)
    assert "Missing result\n1\ntested=2" in values
    assert "Optional group: Bubble" in values
    assert "q2\nDifficult item\n2/2 incorrect (100.0%)" in values
    assert "blanks=1; ambiguous=1" in values
    configured = [
        row.values[2]
        for row in preview.rows
        if row.values[1] == "Configured proficiency"
    ]
    assert configured == ["advanced", "developing", "beginning"]
    markdown = render_teacher_report(preview, "markdown").decode()
    for section in (
        "## 1. Assessment Data",
        "## 2. Standards and Item Analysis",
        "## 3. Instructional Response",
        "## 4. Results from Targeted Instruction",
    ):
        assert section in markdown
    assert "officially submitted or approved" in markdown
    assert teacher_report_preview_to_json_bytes(preview) == (
        teacher_report_preview_to_json_bytes(_preview())
    )


def test_optional_group_never_changes_selected_proficiency() -> None:
    without = compose_benchmark_analysis(
        class_id="class_1",
        target_period=AcademicPeriodRef("2026-2027", "mp1"),
        calendar_revision=1,
        assessment_id="assessment_1",
        assessment_title="Benchmark",
        proficiency_levels=("developing",),
        students=(
            BenchmarkStudentResult(
                "student_1", "Ada One", True, True, "valid", None, "developing"
            ),
        ),
        source_references=(SOURCE,),
        generated_at=NOW,
    )
    with_group = compose_benchmark_analysis(
        class_id="class_1",
        target_period=AcademicPeriodRef("2026-2027", "mp1"),
        calendar_revision=1,
        assessment_id="assessment_1",
        assessment_title="Benchmark",
        proficiency_levels=("developing",),
        students=(
            BenchmarkStudentResult(
                "student_1", "Ada One", True, True, "valid", None, "developing"
            ),
        ),
        source_references=(SOURCE,),
        generated_at=NOW,
        groups=(
            BenchmarkInstructionalGroup(
                "bubble", "Bubble", ("student_1",), "Teacher-selected"
            ),
        ),
    )
    base_rows = [
        row for row in without.rows if row.values[1] == "Configured proficiency"
    ]
    grouped_rows = [
        row for row in with_group.rows if row.values[1] == "Configured proficiency"
    ]
    assert [row.values[2:5] for row in base_rows] == [
        row.values[2:5] for row in grouped_rows
    ]


def test_missing_result_cannot_become_score_or_proficiency() -> None:
    with pytest.raises(BenchmarkAnalysisError):
        BenchmarkStudentResult(
            "student_1",
            "Ada One",
            True,
            True,
            "missing_result",
            "0",
            "developing",
        )


def test_missing_result_can_remain_distinct_without_claiming_tested() -> None:
    result = BenchmarkStudentResult(
        "student_1", "Ada One", True, False, "missing_result"
    )
    assert result.tested is False


def test_insufficient_evidence_and_extension_remain_explicit() -> None:
    result = BenchmarkStudentResult(
        "student_1", "Ada One", True, True, "insufficient_evidence"
    )
    response = InstructionalResponse(
        "response_1",
        "extension",
        "math.1",
        ("student_1",),
        "Novel application task",
    )
    assert result.selected_proficiency is None
    assert response.response_kind == "extension"


def test_plan_revisions_are_append_only_and_keep_history(tmp_path: Path) -> None:
    first = BenchmarkPlanRevision(
        BENCHMARK_PLAN_SCHEMA_VERSION,
        BENCHMARK_PLAN_RECORD_TYPE,
        "plan_1",
        1,
        "teacher_1",
        "class_1",
        "assessment_1",
        NOW,
        NOW,
        True,
        "current",
        _preview(),
    )
    stored_first = write_benchmark_plan_revision(tmp_path, first).stored
    second = BenchmarkPlanRevision(
        BENCHMARK_PLAN_SCHEMA_VERSION,
        BENCHMARK_PLAN_RECORD_TYPE,
        "plan_1",
        2,
        "teacher_1",
        "class_1",
        "assessment_1",
        NOW,
        NOW.replace(hour=16),
        True,
        "unverified",
        _preview(),
        stored_first.revision_sha256,
    )
    write_benchmark_plan_revision(tmp_path, second)
    assert list_benchmark_plan_revisions(tmp_path, "class_1", "plan_1") == (1, 2)
    assert load_latest_benchmark_plan_revision(
        tmp_path, "class_1", "plan_1"
    ).revision.plan_revision == 2


def test_cli_can_confirm_save_and_reopen_plan_revision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "benchmark.json"
    source.write_bytes(teacher_report_preview_to_json_bytes(_preview()))
    policy_path = default_authorization_policy_path(tmp_path)
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": AUTHORIZATION_POLICY_SCHEMA_VERSION,
                "record_type": AUTHORIZATION_POLICY_RECORD_TYPE,
                "policy_id": "teacher_local",
                "policy_version": "1",
                "workspace_root": str(tmp_path.resolve()),
                "grants": [
                    {
                        "class_id": "class_1",
                        "operations": [
                            "project_evidence",
                            "read_projection_cache",
                        ],
                        "purpose_ids": ["teacher_reporting"],
                        "producer_module_ids": ["scoreform"],
                        "publication_ids": [],
                        "student_ids": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(
        (
            "reports",
            "benchmark",
            "--input",
            str(source),
            "--workspace",
            str(tmp_path),
            "--class-id",
            "class_1",
            "--save-plan-id",
            "plan_1",
            "--teacher-id",
            "teacher_1",
            "--confirm-save",
            "--format",
            "json",
        )
    ) == 0
    saved_output = capsys.readouterr()
    assert "planner revision 1 created" in saved_output.err

    assert main(
        (
            "reports",
            "benchmark",
            "--workspace",
            str(tmp_path),
            "--class-id",
            "class_1",
            "--load-plan-id",
            "plan_1",
            "--format",
            "json",
        )
    ) == 0
    reopened = json.loads(capsys.readouterr().out)
    assert reopened["report_kind"] == "benchmark_analysis_instructional_response"
