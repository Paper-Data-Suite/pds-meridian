from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.check_package import PackageValidationError, validate_wheel
from scripts.verify_core_wheel import (
    EXPECTED_CORE_WHEEL_FILENAME,
    CoreVerificationError,
    verify_core_wheel,
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


def test_package_checker_rejects_invalid_archive(tmp_path: Path) -> None:
    path = tmp_path / "invalid.whl"
    path.write_bytes(b"not a zip archive")
    with pytest.raises(PackageValidationError, match="readable ZIP"):
        validate_wheel(path)
