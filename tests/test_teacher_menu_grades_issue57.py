from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_grades import (
    GradeMenuDependencies,
    GradeMenuEvidenceUnavailableError,
    GradePreviewPresentation,
    GradeReportPresentation,
    GradeReportRowPresentation,
    run_grade_preview_menu,
)


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _grade() -> GradePreviewPresentation:
    return GradePreviewPresentation(
        class_id="class_1",
        student_id="student_1",
        school_year="2026-2027",
        period_id="mp1",
        calendar_revision=4,
        family="standards_based",
        policy_title="Standards Grade",
        base_status="calculated",
        base_grade="87.5",
        freshness_status="current",
        freshness_reasons=(),
        override_applicability="applicable",
        effective_grade="91",
        effective_source="override",
        calculation_fingerprint="a" * 64,
        inputs_sha256="b" * 64,
        policy_id="standards_policy",
        policy_revision=2,
        policy_sha256="c" * 64,
        activation_revision=3,
        activation_sha256="d" * 64,
        override_revision=1,
        override_sha256="e" * 64,
    )


def _report() -> GradeReportPresentation:
    return GradeReportPresentation(
        class_id="class_1",
        school_year="2026-2027",
        period_id="mp1",
        calendar_revision=4,
        family="standards_based",
        requested_count=2,
        available_count=1,
        unavailable_count=1,
        stale_count=0,
        override_count=1,
        rows=(
            GradeReportRowPresentation(
                student_id="student_1",
                status="available",
                unavailable_reason=None,
                base_status="calculated",
                freshness_status="current",
                effective_grade="91",
                effective_source="override",
            ),
            GradeReportRowPresentation(
                student_id="student_2",
                status="unavailable",
                unavailable_reason="no_selected_grade",
                base_status=None,
                freshness_status=None,
                effective_grade=None,
                effective_source=None,
            ),
        ),
    )


def _deps() -> GradeMenuDependencies:
    return GradeMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        current_grade_loader=lambda *_args: _grade(),
        report_loader=lambda *_args: _report(),
    )


def test_current_grade_primary_screen_is_low_density() -> None:
    output = StringIO()
    run_grade_preview_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput(
            "1",
            "class_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "student_1",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Effective Grade: 91" in rendered
    assert "Effective source: override" in rendered
    assert "Policy: Standards Grade" in rendered
    assert "policy_sha256" not in rendered
    assert "calculation_fingerprint" not in rendered
    assert "no Grade, override, or snapshot was written" in rendered


def test_current_grade_technical_details_are_explicit() -> None:
    output = StringIO()
    run_grade_preview_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput(
            "1",
            "class_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "student_1",
            "t",
            "",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Technical details / provenance" in rendered
    assert f"policy_sha256: {'c' * 64}" in rendered
    assert f"activation_sha256: {'d' * 64}" in rendered
    assert "override_revision: 1" in rendered


def test_report_preview_is_bounded_and_does_not_freeze_snapshot() -> None:
    output = StringIO()
    run_grade_preview_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput(
            "2",
            "class_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "student_1,student_2",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "2 requested, 1 available, 1 unavailable" in rendered
    assert "student_1: 91 (override)" in rendered
    assert "student_2: no selected grade" in rendered
    assert "no ReportingSnapshot was frozen" in rendered


def test_missing_work_evidence_fails_closed() -> None:
    output = StringIO()

    def unavailable(*_args: object) -> GradePreviewPresentation:
        raise GradeMenuEvidenceUnavailableError(
            "conventional Grade preview requires explicit authorized work evidence"
        )

    deps = GradeMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        current_grade_loader=unavailable,
        report_loader=lambda *_args: _report(),
    )
    run_grade_preview_menu(
        dependencies=deps,
        input_fn=ScriptedInput(
            "1",
            "class_1",
            "2026-2027",
            "mp1",
            "4",
            "1",
            "student_1",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "could not be previewed safely" in rendered
    assert "explicit authorized work evidence" in rendered


@pytest.mark.parametrize(
    ("choice", "error"),
    [("m", ReturnToMainMenu), ("q", QuitPDS)],
)
def test_grade_preview_menu_preserves_shared_navigation(
    choice: str,
    error: type[BaseException],
) -> None:
    with pytest.raises(error):
        run_grade_preview_menu(
            dependencies=_deps(),
            input_fn=ScriptedInput(choice),
            output=StringIO(),
            clear_fn=lambda: None,
        )


def test_exact_scope_is_forwarded_to_current_loader() -> None:
    observed: list[tuple[object, ...]] = []

    def load(
        root: Path,
        class_id: str,
        student_id: str,
        period: AcademicPeriodRef,
        calendar_revision: int,
        family: str,
    ) -> GradePreviewPresentation:
        observed.append(
            (
                root,
                class_id,
                student_id,
                period,
                calendar_revision,
                family,
            )
        )
        return _grade()

    deps = GradeMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        current_grade_loader=load,  # type: ignore[arg-type]
        report_loader=lambda *_args: _report(),
    )
    run_grade_preview_menu(
        dependencies=deps,
        input_fn=ScriptedInput(
            "1",
            "class_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "student_1",
            "b",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert observed == [
        (
            Path("workspace"),
            "class_1",
            "student_1",
            AcademicPeriodRef("2026-2027", "mp1"),
            4,
            "standards_based",
        )
    ]
