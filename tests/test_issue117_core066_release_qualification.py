"""Issue #117 exact Core 0.6.6 release identity and matrix wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import verify_core_wheel

CORE_SHA256 = "d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301"
CORE_WHEEL = "pds_core-0.6.6-py3-none-any.whl"
CORE_URL = (
    "https://github.com/Paper-Data-Suite/pds-core/releases/download/"
    "v0.6.6/" + CORE_WHEEL
)


def test_verifier_requires_exact_released_core_066_identity() -> None:
    assert verify_core_wheel.EXPECTED_CORE_VERSION == "0.6.6"
    assert verify_core_wheel.EXPECTED_CORE_WHEEL_FILENAME == CORE_WHEEL
    assert verify_core_wheel.EXPECTED_CORE_WHEEL_SHA256 == CORE_SHA256


def test_ci_fetches_and_validates_core_066_not_065() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert CORE_URL in workflow
    assert workflow.count(CORE_WHEEL) == 2
    assert 'python scripts/verify_core_wheel.py "$env:PDS_CORE_WHEEL"' in workflow
    assert "pds_core-0.6.5-py3-none-any.whl" not in workflow
    assert "releases/download/v0.6.5/" not in workflow
    assert "--core-wheel" in workflow
    assert "--scoreform-wheel" in workflow
    assert "--quillan-wheel" in workflow
    assert "--concord-wheel" in workflow


def test_installed_teacher_acceptance_requires_core_066() -> None:
    source = Path("scripts/smoke_program_guided_evidence_issue110.py").read_text(
        encoding="utf-8"
    )
    assert 'importlib.metadata.version("pds-core") != "0.6.6"' in source
    assert "Core installed version must be exactly 0.6.6." in source
    assert 'version("scoreform") != "0.13.0"' in source
    assert 'version("quillan") != "0.10.6"' in source


def test_historical_core_065_wheel_name_is_rejected(tmp_path: Path) -> None:
    historical = tmp_path / "pds_core-0.6.5-py3-none-any.whl"
    historical.write_bytes(b"synthetic historical artifact")
    with pytest.raises(verify_core_wheel.CoreVerificationError, match=CORE_WHEEL):
        verify_core_wheel.verify_core_wheel(historical)


def test_unverified_core_066_wheel_bytes_are_rejected(tmp_path: Path) -> None:
    fake = tmp_path / CORE_WHEEL
    fake.write_bytes(b"synthetic, not the actual released wheel")
    with pytest.raises(verify_core_wheel.CoreVerificationError, match="SHA-256"):
        verify_core_wheel.verify_core_wheel(fake)


def test_installed_core_065_metadata_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify_core_wheel.importlib.metadata,
        "version",
        lambda _name: "0.6.5",
    )
    with pytest.raises(verify_core_wheel.CoreVerificationError, match="0.6.6"):
        verify_core_wheel.verify_installed_core()


def test_declared_core_minor_contract_and_producer_extras_are_preserved() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    runtime = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert '"pds-core>=0.6.5,<0.7"' in runtime
    assert "scoreform" not in runtime
    assert "quillan" not in runtime
    assert "concord" not in runtime
    assert '"scoreform>=0.13.0"' in pyproject
    assert '"quillan>=0.10.6"' in pyproject
    assert '"pds-concord>=0.3.2"' in pyproject


def test_active_installed_smokes_pin_core_066_and_never_065() -> None:
    # Keep older installed acceptance programs aligned with the exact Core
    # release used by the six qualification matrices. This does not change
    # Meridian's >=0.6.5 runtime compatibility floor.
    active_smokes = (
        "scripts/smoke_program_attention.py",
        "scripts/smoke_program_conventional_grade.py",
        "scripts/smoke_program_conventional_grade_reload.py",
        "scripts/smoke_program_cross_policy_adversarial.py",
        "scripts/smoke_program_grade_report_attention.py",
        "scripts/smoke_program_grade_report_preview.py",
        "scripts/smoke_program_hybrid_grade.py",
        "scripts/smoke_program_issue59_operations.py",
        "scripts/smoke_program_proficiency_signal_export.py",
        "scripts/smoke_program_proficiency_signal_export_reload.py",
        "scripts/smoke_program_standards_grade.py",
        "scripts/smoke_program_storage_paths_issue102.py",
        "scripts/smoke_test_grouping_signal_contract_wheel.py",
        "scripts/smoke_test_wheel.py",
        "scripts/smoke_program_guided_evidence_issue110.py",
    )
    for relative in active_smokes:
        source = Path(relative).read_text(encoding="utf-8")
        assert "0.6.5" not in source, relative
        assert "0.6.6" in source, relative
