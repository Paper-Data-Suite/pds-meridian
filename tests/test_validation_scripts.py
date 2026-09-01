from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.check_package import PackageValidationError, validate_wheel
from scripts.verify_concord_wheel import (
    EXPECTED_CONCORD_VERSION,
    EXPECTED_CONCORD_WHEEL_FILENAME,
    EXPECTED_CONCORD_WHEEL_SHA256,
    ConcordVerificationError,
    verify_concord_wheel,
)
from scripts.verify_core_wheel import (
    EXPECTED_CORE_WHEEL_FILENAME,
    CoreVerificationError,
    verify_core_wheel,
)
from scripts.verify_quillan_wheel import (
    EXPECTED_QUILLAN_WHEEL_FILENAME,
    QuillanVerificationError,
    verify_quillan_wheel,
)
from scripts.verify_scoreform_wheel import (
    EXPECTED_SCOREFORM_VERSION,
    EXPECTED_SCOREFORM_WHEEL_FILENAME,
    EXPECTED_SCOREFORM_WHEEL_SHA256,
    ScoreFormVerificationError,
    verify_scoreform_wheel,
)


def test_core_verifier_rejects_wrong_filename(tmp_path: Path) -> None:
    path = tmp_path / "renamed.whl"
    path.write_bytes(b"not a wheel")
    with pytest.raises(CoreVerificationError, match="Expected"):
        verify_core_wheel(path)


def test_core_verifier_rejects_wrong_bytes(tmp_path: Path) -> None:
    path = tmp_path / EXPECTED_CORE_WHEEL_FILENAME
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("placeholder.txt", "synthetic")
    with pytest.raises(CoreVerificationError, match="SHA-256 mismatch"):
        verify_core_wheel(path)


def test_scoreform_verifier_targets_exact_011_release() -> None:
    assert EXPECTED_SCOREFORM_VERSION == "0.11.0"
    assert EXPECTED_SCOREFORM_WHEEL_FILENAME == "scoreform-0.11.0-py3-none-any.whl"
    assert EXPECTED_SCOREFORM_WHEEL_SHA256 == (
        "8248c6a1cc8254b5f9df46440131d524f80da8662a0dc7864fdc982e501b4c44"
    )


def test_scoreform_verifier_rejects_wrong_filename(tmp_path: Path) -> None:
    path = tmp_path / "renamed.whl"
    path.write_bytes(b"not a wheel")
    with pytest.raises(ScoreFormVerificationError, match="Expected"):
        verify_scoreform_wheel(path)


def test_scoreform_verifier_rejects_wrong_bytes(tmp_path: Path) -> None:
    path = tmp_path / EXPECTED_SCOREFORM_WHEEL_FILENAME
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("placeholder.txt", "synthetic")
    with pytest.raises(ScoreFormVerificationError, match="SHA-256 mismatch"):
        verify_scoreform_wheel(path)


def test_quillan_verifier_rejects_wrong_filename(tmp_path: Path) -> None:
    path = tmp_path / "renamed.whl"
    path.write_bytes(b"not a wheel")
    with pytest.raises(QuillanVerificationError, match="Expected"):
        verify_quillan_wheel(path)


def test_quillan_verifier_rejects_wrong_bytes(tmp_path: Path) -> None:
    path = tmp_path / EXPECTED_QUILLAN_WHEEL_FILENAME
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("placeholder.txt", "synthetic")
    with pytest.raises(QuillanVerificationError, match="SHA-256 mismatch"):
        verify_quillan_wheel(path)


def test_concord_verifier_targets_exact_030_release() -> None:
    assert EXPECTED_CONCORD_VERSION == "0.3.0"
    assert EXPECTED_CONCORD_WHEEL_FILENAME == (
        "pds_concord-0.3.0-py3-none-any.whl"
    )
    assert EXPECTED_CONCORD_WHEEL_SHA256 == (
        "dd827f7059c91c79bd69b6190b3c673d6b3bbc02bc25fa666286bbf5883c5e12"
    )


def test_concord_verifier_rejects_wrong_filename(tmp_path: Path) -> None:
    path = tmp_path / "renamed.whl"
    path.write_bytes(b"not a wheel")
    with pytest.raises(ConcordVerificationError, match="Expected"):
        verify_concord_wheel(path)


def test_concord_verifier_rejects_wrong_bytes(tmp_path: Path) -> None:
    path = tmp_path / EXPECTED_CONCORD_WHEEL_FILENAME
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("placeholder.txt", "synthetic")
    with pytest.raises(ConcordVerificationError, match="SHA-256 mismatch"):
        verify_concord_wheel(path)


def test_package_checker_rejects_invalid_archive(tmp_path: Path) -> None:
    path = tmp_path / "invalid.whl"
    path.write_bytes(b"not a zip archive")
    with pytest.raises(PackageValidationError, match="readable ZIP"):
        validate_wheel(path)

def test_ci_wires_exact_scoreform_release_artifact() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert (
        "pds-scoreform/releases/download/v0.11.0/"
        "scoreform-0.11.0-py3-none-any.whl"
    ) in workflow
    assert 'python scripts/verify_scoreform_wheel.py "$env:SCOREFORM_WHEEL"' in workflow
    assert '--scoreform-wheel "$env:SCOREFORM_WHEEL"' in workflow


def test_ci_wires_exact_concord_release_artifact() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert (
        "pds-concord/releases/download/v0.3.0/"
        "pds_concord-0.3.0-py3-none-any.whl"
    ) in workflow
    assert 'python scripts/verify_concord_wheel.py "$env:CONCORD_WHEEL"' in workflow
    assert '".[dev,scoreform,quillan,concord]"' in workflow
    assert '--concord-wheel "$env:CONCORD_WHEEL"' in workflow


def test_cross_producer_acceptance_document_is_validation_guarded() -> None:
    checker = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    assert "cross-producer-synthetic-ingestion.md" in checker
    assert "producer-neutral != producer-semantic flattening" in checker
    assert "ScoreForm attempt != Concord Score history" in checker
    assert (
        "Academic Period definition != ingestion-time Grade-period assignment"
        in checker
    )

def test_academic_period_proficiency_installed_smoke_is_release_guarded() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    smoke_name = "smoke_test_academic_period_proficiency_wheel.py"

    assert smoke_name in validator
    assert smoke_name in sdist_checker


def test_grouping_signal_contract_installed_smoke_is_release_guarded() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    smoke_name = "smoke_test_grouping_signal_contract_wheel.py"

    assert smoke_name in validator
    assert smoke_name in sdist_checker
    assert "tests/test_grouping_signal_contract.py" in sdist_checker
    assert "tests/test_grouping_signal_storage_contract.py" in sdist_checker
    assert "tests/test_grouping_signal_diagnostics_contract.py" in sdist_checker


def test_grouping_signal_architecture_document_is_release_guarded() -> None:
    documentation_checker = Path("scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    document = "docs/architecture/core-grouping-signal-interchange.md"

    assert document in documentation_checker
    assert document in sdist_checker
    assert "issue #36 — implemented" in documentation_checker
    assert "issue #37 — implemented" in documentation_checker
    assert "issue #38 — implemented" in documentation_checker
    assert "issue #39 — implemented" in documentation_checker


def test_grouping_signal_contract_ci_uses_exact_core_release_and_validator() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")

    assert (
        "pds-core/releases/download/v0.6.3/"
        "pds_core-0.6.3-py3-none-any.whl"
    ) in workflow
    assert 'python scripts/verify_core_wheel.py "$env:PDS_CORE_WHEEL"' in workflow
    assert "python scripts/validate_repository.py" in workflow
    assert '--core-wheel "$env:PDS_CORE_WHEEL"' in workflow
    assert "smoke_test_grouping_signal_contract_wheel.py" in validator


def test_grouping_signal_policy_installed_smoke_is_release_guarded() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    smoke_name = "smoke_test_grouping_signal_policy_wheel.py"

    assert smoke_name in validator
    assert smoke_name in sdist_checker
    assert "tests/test_grouping_signal_policy.py" in sdist_checker
    assert "tests/test_grouping_signal_policy_storage.py" in sdist_checker
    assert "tests/test_grouping_signal_policy_integration.py" in sdist_checker
    assert "tests/test_grouping_signal_policy_storage_hardening.py" in sdist_checker
    assert "tests/test_grouping_signal_policy_package_boundaries.py" in sdist_checker


def test_grouping_signal_policy_architecture_document_is_release_guarded() -> None:
    documentation_checker = Path("scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    document = "docs/architecture/grouping-signal-derivation-policy.md"

    assert document in documentation_checker
    assert document in sdist_checker
    assert "issue #37 — implemented" in documentation_checker
    assert "issue #38 — implemented" in documentation_checker
    assert "issue #39 — implemented" in documentation_checker

def test_grouping_signal_generation_architecture_and_package_are_release_guarded(
) -> None:
    documentation_checker = Path("scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )
    wheel_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    document = "docs/architecture/grouping-signal-generation.md"

    assert document in documentation_checker
    assert document in sdist_checker
    assert "issue #38 — implemented" in documentation_checker
    assert "issue #39 — implemented" in documentation_checker

    for member in (
        "meridian/grouping_signal_derivation.py",
        "meridian/grouping_signal_derivation_storage.py",
        "meridian/grouping_signal_generation.py",
        "meridian/grouping_signal_generation_basis.py",
    ):
        assert member in wheel_checker
        assert member in sdist_checker

    for member in (
        "tests/test_grouping_signal_derivation.py",
        "tests/test_grouping_signal_derivation_storage.py",
        "tests/test_grouping_signal_derivation_storage_hardening.py",
        "tests/test_grouping_signal_generation.py",
        "tests/test_grouping_signal_generation_basis.py",
        "tests/test_grouping_signal_generation_integration.py",
        "tests/test_grouping_signal_derivation_package_boundaries.py",
    ):
        assert member in sdist_checker


def test_grouping_signal_generation_installed_smoke_is_release_guarded() -> None:
    validator = Path("scripts/validate_repository.py").read_text(
        encoding="utf-8"
    )
    sdist_checker = Path("scripts/check_sdist.py").read_text(
        encoding="utf-8"
    )

    assert "smoke_test_grouping_signal_generation_wheel.py" in validator
    assert "smoke_test_grouping_signal_generation_wheel.py" in sdist_checker
    assert "smoke_program_grouping_signal_generation.py" in sdist_checker


def test_grouping_signal_preview_review_release_is_guarded() -> None:
    documentation_checker = Path("scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )
    wheel_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")

    document = "docs/architecture/grouping-signal-preview-diagnostics.md"
    assert document in documentation_checker
    assert document in sdist_checker
    assert "issue #39 — implemented" in documentation_checker
    assert "issue #40 — implemented" in documentation_checker
    assert "issue #41 — next" in documentation_checker

    for member in (
        "meridian/grouping_signal_currentness.py",
        "meridian/grouping_signal_preview.py",
        "meridian/grouping_signal_preview_storage.py",
        "meridian/grouping_signal_preview_generation.py",
        "meridian/grouping_signal_preview_projection.py",
        "meridian/grouping_signal_review.py",
        "meridian/grouping_signal_review_storage.py",
        "meridian/grouping_signal_review_workflow.py",
    ):
        assert member in wheel_checker
        assert member in sdist_checker

    assert "smoke_test_grouping_signal_preview_review_wheel.py" in validator
    assert "smoke_test_grouping_signal_preview_review_wheel.py" in sdist_checker
    assert "smoke_program_grouping_signal_preview_review.py" in sdist_checker

def test_grouping_signal_export_release_is_guarded() -> None:
    documentation_checker = Path("scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )
    wheel_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")

    assert "grouping-signal-core-export.md" in documentation_checker
    assert "grouping-signal-core-export.md" in sdist_checker
    assert "issue #40 — implemented" in documentation_checker
    assert "issue #41 — next" in documentation_checker

    for member in (
        "meridian/grouping_signal_export.py",
        "meridian/grouping_signal_export_eligibility.py",
        "meridian/grouping_signal_export_workflow.py",
        "meridian/grouping_signal_export_receipt.py",
        "meridian/grouping_signal_export_storage.py",
        "meridian/grouping_signal_export_receipt_workflow.py",
        "meridian/grouping_signal_csv_export.py",
    ):
        assert member in wheel_checker
        assert member in sdist_checker

    assert "smoke_test_grouping_signal_export_wheel.py" in validator
    assert "smoke_program_grouping_signal_export.py" in sdist_checker
