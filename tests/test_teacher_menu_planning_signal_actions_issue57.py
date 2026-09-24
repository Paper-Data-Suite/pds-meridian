from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from meridian.menu_planning_signal import (
    PlanningSignalMenuDependencies,
    run_planning_signal_menu,
)
from meridian.menu_proficiency import ProficiencyMenuDependencies, run_proficiency_menu


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _projection() -> object:
    return SimpleNamespace(
        policy_title="Writing Support Groups",
        school_year="2026-2027",
        period_id="mp1",
        standard_id="NJSLSA.W1",
        dimension_id="writing_support",
        live_currentness=SimpleNamespace(state="current"),
        coverage=SimpleNamespace(
            roster_student_count=24,
            contributing_student_count=20,
            noncontributing_student_count=4,
        ),
        band_summaries=(),
        diagnostics=(),
        review_status=SimpleNamespace(decision=None, applicability=None),
    )


def _deps(log: list[str]) -> PlanningSignalMenuDependencies:
    readiness = SimpleNamespace(
        policy=SimpleNamespace(
            title="Writing Support Groups",
            target_period=SimpleNamespace(
                period=SimpleNamespace(school_year="2026-2027", period_id="mp1")
            ),
            standard_id="NJSLSA.W1",
            dimension_id="writing_support",
            band_count=3,
        ),
        generation_status="generated",
        blocker_codes=(),
        roster_student_count=24,
        contributing_student_count=20,
        noncontributing_student_count=4,
    )
    derivation_preview = SimpleNamespace(
        derivation_id="derivation_1",
        derivation_sha256="a" * 64,
        calculation_fingerprint="b" * 64,
        roster_student_count=24,
        contributing_student_count=20,
        noncontributing_student_count=4,
    )
    preview_write = SimpleNamespace(
        derivation_id="derivation_1",
        roster_student_count=24,
        contributing_student_count=20,
        noncontributing_student_count=4,
    )
    review_preview = SimpleNamespace(
        decision="rejected",
        review_revision=2,
        acknowledged_warning_ids=(),
        blocking_diagnostic_ids=(),
        actor_id="teacher_1",
        reviewed_at=datetime(2026, 9, 23, 23, 0, tzinfo=UTC),
        expected_current_review_revision=1,
    )
    selection_preview = SimpleNamespace(
        target_review_revision=2,
        target_decision="accepted_for_export",
        target_applicability=SimpleNamespace(status="current"),
        target_review_sha256="c" * 64,
        expected_current_review_revision=1,
    )
    export_preview = SimpleNamespace(
        signal_set=SimpleNamespace(
            signal_set_id="signal_1",
            created_at=datetime(2026, 9, 23, 23, 0, tzinfo=UTC),
        ),
        contributing_student_ids=("student_1", "student_2"),
        noncontributing_student_ids=("student_3",),
    )
    return cast(
        PlanningSignalMenuDependencies,
        SimpleNamespace(
            workspace_resolver=lambda: Path("workspace"),
            clock=lambda: datetime(2026, 9, 23, 23, 0, tzinfo=UTC),
            readiness_projector=lambda *_args: readiness,
            derivation_previewer=lambda *_args: derivation_preview,
            derivation_committer=lambda *_args: (
                log.append("derivation")
                or SimpleNamespace(
                    write_disposition="created",
                    derivation_id="derivation_1",
                    derivation_sha256="a" * 64,
                )
            ),
            preview_write_previewer=lambda *_args: preview_write,
            preview_write_committer=lambda *_args: (
                log.append("preview")
                or SimpleNamespace(
                    write_disposition="created",
                    preview_id="preview_1",
                    preview_sha256="d" * 64,
                    currentness_state="current",
                    warning_diagnostic_ids=(),
                    blocking_diagnostic_ids=(),
                )
            ),
            diagnostics_projector=lambda *_args: _projection(),
            review_authoring_previewer=lambda *_args: review_preview,
            review_authoring_committer=lambda *_args: (
                log.append("review")
                or SimpleNamespace(
                    write_disposition="created",
                    review_revision=2,
                    review_sha256="c" * 64,
                    decision="rejected",
                )
            ),
            review_selection_previewer=lambda *_args: selection_preview,
            review_selection_committer=lambda *_args: (
                log.append("select")
                or SimpleNamespace(
                    selection_disposition="updated",
                    selected_review_revision=2,
                    selected_decision="accepted_for_export",
                )
            ),
            export_previewer=lambda *_args: export_preview,
            export_committer=lambda *_args: (
                log.append("export")
                or SimpleNamespace(
                    core_write_disposition="created",
                    receipt_write_disposition="created",
                    core_signal_digest="e" * 64,
                    receipt_sha256="f" * 64,
                )
            ),
        ),
    )


def test_planning_signal_menu_exposes_complete_guided_stages() -> None:
    output = StringIO()
    run_planning_signal_menu(
        dependencies=_deps([]),
        input_fn=ScriptedInput("b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Write exact derivation" in rendered
    assert "Write planning preview" in rendered
    assert "Review preview and diagnostics" in rendered
    assert "Write teacher review" in rendered
    assert "Select teacher review" in rendered
    assert "Export accepted signal to Core" in rendered
    assert "No step creates Concord grouping state." in rendered


def test_derivation_write_requires_exact_write_confirmation() -> None:
    log: list[str] = []
    output = StringIO()
    run_planning_signal_menu(
        dependencies=_deps(log),
        input_fn=ScriptedInput(
            "2",
            "class_1",
            "support_groups",
            "no",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == []
    assert "does not create a #39 preview" in output.getvalue()


def test_preview_write_requires_separate_write_confirmation() -> None:
    log: list[str] = []
    run_planning_signal_menu(
        dependencies=_deps(log),
        input_fn=ScriptedInput(
            "3",
            "class_1",
            "support_groups",
            "derivation_1",
            "a" * 64,
            "no",
            "",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == []


def test_review_write_does_not_select_review() -> None:
    log: list[str] = []
    output = StringIO()
    run_planning_signal_menu(
        dependencies=_deps(log),
        input_fn=ScriptedInput(
            "5",
            "class_1",
            "support_groups",
            "preview_1",
            "d" * 64,
            "reject",
            "teacher_1",
            "WRITE",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == ["review"]
    assert "Current review selection was not changed." in output.getvalue()


def test_review_selection_requires_select_confirmation() -> None:
    log: list[str] = []
    run_planning_signal_menu(
        dependencies=_deps(log),
        input_fn=ScriptedInput(
            "6",
            "class_1",
            "support_groups",
            "preview_1",
            "d" * 64,
            "2",
            "c" * 64,
            "SELECT",
            "",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == ["select"]


def test_core_export_requires_export_confirmation() -> None:
    log: list[str] = []
    output = StringIO()
    run_planning_signal_menu(
        dependencies=_deps(log),
        input_fn=ScriptedInput(
            "7",
            "class_1",
            "support_groups",
            "preview_1",
            "d" * 64,
            "signal_1",
            "",
            "EXPORT",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == ["export"]
    assert "No Concord state was created." in output.getvalue()


def test_review_proficiency_reaches_create_planning_signal() -> None:
    output = StringIO()
    menu_deps = ProficiencyMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        grade_item_loader=lambda *_args: cast(object, object()),
        academic_period_loader=lambda *_args: cast(object, object()),
        planning_loader=lambda *_args: cast(object, object()),
    )  # type: ignore[arg-type]
    run_proficiency_menu(
        dependencies=menu_deps,
        planning_dependencies=_deps([]),
        input_fn=ScriptedInput("10", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "10. Create Planning Signal" in rendered
    assert "Create Planning Signal" in rendered
