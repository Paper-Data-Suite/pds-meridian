from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.check_package import PackageValidationError, validate_wheel
from scripts.verify_concord_wheel import (
    EXPECTED_CONCORD_WHEEL_FILENAME,
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
    EXPECTED_SCOREFORM_WHEEL_FILENAME,
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

def test_ci_wires_exact_concord_release_artifact() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert (
        "pds-concord/releases/download/v0.2.0/"
        "pds_concord-0.2.0-py3-none-any.whl"
    ) in workflow
    assert 'python scripts/verify_concord_wheel.py "$env:CONCORD_WHEEL"' in workflow
    assert '".[dev,scoreform,quillan,concord]"' in workflow
    assert '--concord-wheel "$env:CONCORD_WHEEL"' in workflow
