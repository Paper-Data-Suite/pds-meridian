from __future__ import annotations

from pathlib import Path


def test_issue52_installed_smoke_is_exact_and_fresh_process() -> None:
    wrapper = Path("scripts/smoke_test_hybrid_grade_wheel.py").read_text(
        encoding="utf-8"
    )
    program = Path("scripts/smoke_program_hybrid_grade.py").read_text(
        encoding="utf-8"
    )
    reload_program = Path(
        "scripts/smoke_program_hybrid_grade_reload.py"
    ).read_text(encoding="utf-8")

    for token in (
        'metadata.version("pds-core") == "0.6.3"',
        'metadata.version("scoreform") == "0.11.0"',
        'metadata.version("quillan") == "0.10.2"',
        'metadata.version("pds-concord")',
        'importlib.util.find_spec("concord") is None',
        'import smoke_program_conventional_grade as conventional',
        'import smoke_program_standards_grade as standards',
        "assemble_hybrid_grade_calculation",
        "write_hybrid_grade_result_revision",
        "select_hybrid_grade_result_revision",
        "load_current_hybrid_grade_result",
        "Writing a hybrid Grade result must not select it.",
        "get_current_conventional_grade_result_revision",
        "get_current_standards_grade_result_revision",
        "Hybrid Grade layer mutated producer or v0.2/Grade-policy source state.",
    ):
        assert token in program

    assert '"PYTHONPATH"' in wrapper
    assert "RELOAD_PROGRAM" in wrapper
    assert "scoreform_wheel" in wrapper
    assert "quillan_wheel" in wrapper
    assert "concord_wheel" not in wrapper

    for token in (
        "load_current_hybrid_grade_result",
        "calculate_hybrid_grade",
        "hybrid_grade_result_snapshot_to_json_bytes",
        "Fresh-process calculation fingerprint changed.",
        "Fresh-process Grade read mutated producer or v0.2 source state.",
        "_assert_no_standalone_grade_results",
    ):
        assert token in reload_program


def test_issue52_installed_smoke_preserves_one_hybrid_authority() -> None:
    program = Path("scripts/smoke_program_hybrid_grade.py").read_text(
        encoding="utf-8"
    )
    for token in (
        'calculation_family="hybrid"',
        "HybridGradeConfiguration(",
        "activation_revision=2",
        "supersedes_revision=1",
        "expected_current_revision=1",
        "conventional=conventional_configuration",
        "standards_based=standards_configuration",
        "conventional_weight=CONVENTIONAL_WEIGHT",
        "standards_weight=STANDARDS_WEIGHT",
    ):
        assert token in program
