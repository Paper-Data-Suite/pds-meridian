from __future__ import annotations

from pathlib import Path


def test_issue53_installed_smoke_is_isolated_and_explicit() -> None:
    wrapper = Path("scripts/smoke_test_teacher_grade_override_wheel.py").read_text(
        encoding="utf-8"
    )
    program = Path("scripts/smoke_program_teacher_grade_override.py").read_text(
        encoding="utf-8"
    )
    active_reload = Path(
        "scripts/smoke_program_teacher_grade_override_reload_active.py"
    ).read_text(encoding="utf-8")
    withdrawn_reload = Path(
        "scripts/smoke_program_teacher_grade_override_reload_withdrawn.py"
    ).read_text(encoding="utf-8")

    for token in (
        '"PYTHONPATH"',
        '"PYTHONNOUSERSITE": "1"',
        '"pip", "check"',
        "ACTIVE_RELOAD",
        "WITHDRAWN_RELOAD",
        "scoreform_wheel",
    ):
        assert token in wrapper
    assert "quillan_wheel" not in wrapper
    assert "concord_wheel" not in wrapper

    for token in (
        "issue50._verify_installed_composition()",
        "_verify_override_module_origins()",
        "assemble_conventional_grade_calculation",
        "write_conventional_grade_result_revision",
        "select_conventional_grade_result_revision",
        "preview_teacher_grade_override_authoring",
        "commit_teacher_grade_override_authoring_preview",
        "Writing an override must not select it.",
        "preview_teacher_grade_override_selection",
        "commit_teacher_grade_override_selection_preview",
        "resolve_current_effective_grade",
        'REPLACEMENT_GRADE = Decimal("105.25")',
        "Persisted source result JSON changed.",
        "Persisted source result digest changed.",
        "issue50._assert_unchanged(producer)",
    ):
        assert token in program

    for token in (
        "load_current_teacher_grade_override",
        "resolve_effective_grade",
        "preview_teacher_grade_override_withdrawal",
        "commit_teacher_grade_override_withdrawal_preview",
        "Writing withdrawal must not select it.",
        "preview_teacher_grade_override_selection",
        "commit_teacher_grade_override_selection_preview",
        "Source result bytes changed.",
    ):
        assert token in active_reload

    for token in (
        "load_current_teacher_grade_override",
        "list_teacher_grade_override_revisions",
        "load_teacher_grade_override_revision",
        'selected.decision.decision == "withdraw"',
        'effective.override_applicability == "withdrawn"',
        'effective.effective_source == "base"',
        'history == (1, 2)',
        "Original override digest changed after withdrawal.",
        "Producer source changed",
    ):
        assert token in withdrawn_reload
