from __future__ import annotations

from pathlib import Path


def test_issue43_installed_smoke_is_release_guarded() -> None:
    validator = Path("scripts/validate_repository.py").read_text(
        encoding="utf-8"
    )
    sdist_checker = Path("scripts/check_sdist.py").read_text(
        encoding="utf-8"
    )
    wrapper = Path("scripts/smoke_test_attention_wheel.py").read_text(
        encoding="utf-8"
    )
    program = Path("scripts/smoke_program_attention.py").read_text(
        encoding="utf-8"
    )

    assert "smoke_test_attention_wheel.py" in validator
    assert "smoke_test_attention_wheel.py" in sdist_checker
    assert "smoke_program_attention.py" in sdist_checker
    assert "tests/test_issue43_installed_acceptance.py" in sdist_checker

    assert '"--no-deps"' in wrapper
    assert "scoreform_wheel" not in wrapper
    assert "quillan_wheel" not in wrapper
    assert "concord_wheel" not in wrapper
    assert "smoke_program_grouping_signal_preview_review.py" in wrapper

    for required in (
        'metadata.version("pds-core") != "0.6.3"',
        "inspect_core_provider_entry_points",
        "diagnose_core_providers",
        "invoke_module_operations",
        "module_operations.capability_absent",
        "module_operations.evaluation_unavailable",
        "meridian_planning_review_selection_pending",
        "before != after_provider",
        "before != after_cli",
        '"attention"',
    ):
        assert required in program


def test_issue43_installed_smoke_checks_sibling_absence_and_privacy() -> None:
    program = Path("scripts/smoke_program_attention.py").read_text(
        encoding="utf-8"
    )

    for sibling in (
        '"scoreform"',
        '"quillan"',
        '"concord"',
        '"portia"',
        '"vitrine"',
        '"paper_data_suite"',
    ):
        assert sibling in program

    for forbidden in (
        '"student_id"',
        '"student_name"',
        '"percentage"',
        '"proficiency_level"',
        '"grouping_band"',
        '"grouping_dimension"',
    ):
        assert forbidden in program
