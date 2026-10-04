from __future__ import annotations

import tomllib
from pathlib import Path

from scripts.verify_core_wheel import (
    EXPECTED_CORE_VERSION,
    EXPECTED_CORE_WHEEL_FILENAME,
    EXPECTED_CORE_WHEEL_SHA256,
)


def test_issue102_exact_core_064_qualification_baseline() -> None:
    assert EXPECTED_CORE_VERSION == "0.6.4"
    assert EXPECTED_CORE_WHEEL_FILENAME == "pds_core-0.6.4-py3-none-any.whl"
    assert EXPECTED_CORE_WHEEL_SHA256 == (
        "48cea9317f2967bdc0f2d4c14349a56677c7c3f8211f0f33978ccb1a1c75859b"
    )

    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert (
        "pds-core/releases/download/v0.6.4/pds_core-0.6.4-py3-none-any.whl"
        in workflow
    )
    assert "pds_core-0.6.3-py3-none-any.whl" not in workflow


def test_issue102_runtime_core_floor_remains_compatible() -> None:
    with Path("pyproject.toml").open("rb") as source:
        project = tomllib.load(source)["project"]

    assert project["dependencies"] == ["pds-core>=0.6.3,<0.7"]


def test_issue102_installed_acceptance_is_core_only_and_prepared() -> None:
    core_programs = Path(
        "scripts/installed_qualification_core_programs.py"
    ).read_text(encoding="utf-8")
    smoke = Path(
        "scripts/smoke_program_storage_paths_issue102.py"
    ).read_text(encoding="utf-8")

    for token in (
        "smoke_program_storage_paths_issue102.py",
        '"storage-paths-issue102"',
        "run_core_program_smokes",
    ):
        assert token in core_programs

    for token in (
        'importlib.metadata.version("pds-core") != "0.6.4"',
        "LONG_ID_SIZE = 1024",
        "LONG_WORK_SIZE = 80",
        "write_grade_item_revision",
        "write_grade_item_membership_revision",
        "write_academic_period_proficiency_result_revision",
        "write_grade_policy_revision",
        "write_reporting_definition_revision",
        "write_reporting_snapshot",
        "write_export_profile_revision",
        "write_proficiency_scale_revision",
        "write_mapping_profile_revision",
        "select_reporting_snapshot",
        "select_export_profile",
        "STORAGE_PATH_KEY_MAX_LENGTH",
        "STORAGE_PATH_KEY_JSON_SHA256_FILENAME_MAX_LENGTH",
        "Fresh-process storage path key changed.",
        "Issue #102 acceptance changed Windows path policy.",
        "Issue #102 installed deep-path acceptance passed.",
    ):
        assert token in smoke

    assert "winreg.SetValue" not in smoke
    assert "LongPathsEnabled = 1" not in smoke


def test_issue102_release_guards_include_acceptance_and_documentation() -> None:
    sdist = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    docs = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    wheel = Path("scripts/check_package.py").read_text(encoding="utf-8")

    for member in (
        "scripts/smoke_program_storage_paths_issue102.py",
        "tests/test_issue102_final_qualification.py",
        "docs/architecture/canonical-storage-path-budgets.md",
    ):
        assert member in sdist

    assert "docs/architecture/canonical-storage-path-budgets.md" in docs
    assert "meridian/storage_path_keys.py" in wheel
    assert "meridian/storage_path_keys.py" in sdist


def test_issue102_documentation_records_predeployment_contract() -> None:
    document = Path(
        "docs/architecture/canonical-storage-path-budgets.md"
    ).read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    readme = Path("README").read_text(encoding="utf-8")
    docs_readme = Path("docs/README.md").read_text(encoding="utf-8")
    matrix = Path(
        "docs/development/installed-qualification-matrix.md"
    ).read_text(encoding="utf-8")

    for token in (
        "logical identifier != filesystem component",
        "Core-owned workspace identity != Meridian-owned storage key",
        "67",
        "79",
        "LongPathsEnabled",
        "pre-deployment",
        "no migration",
        "Core 0.6.4",
    ):
        assert token in document

    assert "Issue #102" in changelog
    assert "Core v0.6.4" in readme
    assert "canonical-storage-path-budgets.md" in docs_readme
    assert "Issue #102" in matrix
    assert "`0.6.4`" in matrix
