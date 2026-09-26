from __future__ import annotations

from pathlib import Path


def test_issue51_installed_smoke_is_exact_and_fresh_process() -> None:
    wrapper = Path("scripts/smoke_test_standards_grade_wheel.py").read_text(
        encoding="utf-8"
    )
    program = Path("scripts/smoke_program_standards_grade.py").read_text(
        encoding="utf-8"
    )
    reload_program = Path(
        "scripts/smoke_program_standards_grade_reload.py"
    ).read_text(encoding="utf-8")

    for token in (
        'metadata.version("pds-core") == "0.6.3"',
        'metadata.version("scoreform") == "0.11.0"',
        'metadata.version("quillan") == "0.10.2"',
        'metadata.version("pds-concord")',
        'importlib.util.find_spec("concord") is None',
        "assemble_standards_grade_calculation",
        "write_standards_grade_result_revision",
        "select_standards_grade_result_revision",
        "load_current_standards_grade_result",
        "Writing a standards Grade result must not select it.",
        "Standards Grade layer mutated producer or v0.2 proficiency source state.",
    ):
        assert token in program

    assert '"PYTHONPATH"' in wrapper
    assert "RELOAD_PROGRAM" in wrapper
    assert "scoreform_wheel" in wrapper
    assert "quillan_wheel" in wrapper
    assert "concord_wheel" not in wrapper

    for token in (
        "load_current_standards_grade_result",
        "calculate_standards_grade",
        "assemble_standards_grade_calculation",
        "assess_standards_grade_result_freshness",
        "Fresh-process calculation fingerprint changed.",
        "Fresh-process Grade read mutated producer or proficiency source state.",
    ):
        assert token in reload_program


def test_issue51_installed_smoke_starts_from_real_persisted_proficiency() -> None:
    program = Path("scripts/smoke_program_standards_grade.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "write_standard_proficiency_result_revision",
        "select_standard_proficiency_result_revision",
        "write_academic_period_proficiency_result_revision",
        "select_academic_period_proficiency_result_revision",
        "ResolvedAcademicPeriodProficiencyCandidate",
        'ModuleWorkRef("scoreform"',
        'ModuleWorkRef("quillan"',
    ):
        assert token in program
