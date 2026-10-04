"""Issue #59 installed operations/launcher acceptance guards."""

from __future__ import annotations

from pathlib import Path


def test_issue59_installed_smoke_is_in_prepared_core_matrix_and_sdist() -> None:
    core_programs = Path(
        "scripts/installed_qualification_core_programs.py"
    ).read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    assert "ISSUE59_OPERATIONS_PROGRAM" in core_programs
    assert "smoke_program_issue59_operations.py" in core_programs
    assert '"issue59-operations-seed"' in core_programs
    assert '"issue59-operations"' in core_programs
    assert "scripts/smoke_program_issue59_operations.py" in sdist_checker
    assert "tests/test_issue59_installed_acceptance.py" in sdist_checker


def test_issue59_installed_smoke_covers_profile_readiness_and_launcher() -> None:
    program = Path("scripts/smoke_program_issue59_operations.py").read_text(
        encoding="utf-8"
    )

    for required in (
        'metadata.version("pds-core") != "0.6.4"',
        '"paper_data_suite"',
        "inspect_core_provider_entry_points",
        "diagnose_core_providers",
        "profile.readiness_provider is None",
        "profile.attention_provider is None",
        "invoke_module_readiness",
        "invoke_module_attention",
        "invoke_module_operations",
        "ModuleReadinessReport",
        "ModuleAttentionReport",
        "create_class_metadata",
        "meridian.cli:main",
        '"--version"',
        '"--help"',
        "MERIDIAN_OWNER_ACTION_IDS",
        "owner_action_for_action_id",
        "before != after",
    ):
        assert required in program


def test_issue59_historical_attention_smoke_accepts_readiness_presence() -> None:
    program = Path("scripts/smoke_program_attention.py").read_text(
        encoding="utf-8"
    )
    issue43_guard = Path("tests/test_issue43_installed_acceptance.py").read_text(
        encoding="utf-8"
    )

    assert "ModuleReadinessReport" in program
    assert "profile.readiness_provider is None" in program
    assert "Meridian readiness must remain absent in #43." not in program
    assert "module_operations.capability_absent" not in issue43_guard
