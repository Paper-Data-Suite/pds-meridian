from __future__ import annotations

import tomllib
from pathlib import Path

from meridian.quillan_adapter import QUILLAN_READER_VERSION
from meridian.scoreform_adapter import SCOREFORM_READER_VERSION
from scripts.verify_quillan_wheel import (
    EXPECTED_QUILLAN_VERSION,
    EXPECTED_QUILLAN_WHEEL_FILENAME,
    EXPECTED_QUILLAN_WHEEL_SHA256,
)
from scripts.verify_scoreform_wheel import (
    EXPECTED_SCOREFORM_VERSION,
    EXPECTED_SCOREFORM_WHEEL_FILENAME,
    EXPECTED_SCOREFORM_WHEEL_SHA256,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_issue61_exact_latest_direct_producer_artifacts_are_pinned() -> None:
    assert EXPECTED_SCOREFORM_VERSION == "0.12.0"
    assert EXPECTED_SCOREFORM_WHEEL_FILENAME == (
        "scoreform-0.12.0-py3-none-any.whl"
    )
    assert EXPECTED_SCOREFORM_WHEEL_SHA256 == (
        "84ad10ada72a99bebd5455d8c18a0725f9406f8279e57156f3e424efa5678d20"
    )

    assert EXPECTED_QUILLAN_VERSION == "0.10.5"
    assert EXPECTED_QUILLAN_WHEEL_FILENAME == "quillan-0.10.5-py3-none-any.whl"
    assert EXPECTED_QUILLAN_WHEEL_SHA256 == (
        "031e5a5455c222da6b9a7d8f72e7823dd4c61acde7d90ddce94b49d9bcbe123f"
    )


def test_issue61_package_extras_and_adapter_boundaries_move_together() -> None:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    optional = pyproject["project"]["optional-dependencies"]

    assert optional["scoreform"] == ["scoreform==0.12.0"]
    assert optional["quillan"] == ["quillan==0.10.5"]
    assert optional["concord"] == ["pds-concord==0.3.0"]

    assert SCOREFORM_READER_VERSION == "0.12.0"
    assert QUILLAN_READER_VERSION == "0.10.5"


def test_issue61_ci_uses_the_same_authenticated_release_artifacts() -> None:
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert (
        "pds-scoreform/releases/download/v0.12.0/"
        "scoreform-0.12.0-py3-none-any.whl"
    ) in workflow
    assert (
        "pds-quillan/releases/download/v0.10.5/"
        "quillan-0.10.5-py3-none-any.whl"
    ) in workflow

    assert "scoreform-0.11.0-py3-none-any.whl" not in workflow
    assert "quillan-0.10.3-py3-none-any.whl" not in workflow


def test_issue61_installed_smokes_bind_latest_direct_reader_versions() -> None:
    current_version_files = (
        "scripts/smoke_program_conventional_grade.py",
        "scripts/smoke_program_conventional_grade_reload.py",
        "scripts/smoke_program_cross_policy_adversarial.py",
        "scripts/smoke_program_grade_report_preview.py",
        "scripts/smoke_program_hybrid_grade.py",
        "scripts/smoke_program_proficiency_signal_export.py",
        "scripts/smoke_program_proficiency_signal_export_reload.py",
        "scripts/smoke_program_standards_grade.py",
        "scripts/smoke_test_wheel.py",
    )
    combined = "\n".join(
        (REPO_ROOT / relative).read_text(encoding="utf-8")
        for relative in current_version_files
    )

    assert "0.12.0" in combined
    assert "0.10.5" in combined
    assert "0.11.0" not in combined
    assert "0.10.3" not in combined


def test_issue61_promotion_requires_completed_substantive_audit() -> None:
    version_file = (REPO_ROOT / "meridian/_version.py").read_text(encoding="utf-8")
    audit = (
        REPO_ROOT / "docs/development/v0.3.0-release-audit.md"
    ).read_text(encoding="utf-8")

    assert '__version__: Final[str] = "0.3.0"' in version_file
    assert "Substantive blocker count: **0**" in audit
    assert "Release-preparation authorization: **AUTHORIZED**" in audit
    assert "Version promotion to `0.3.0`: **COMPLETED**" in audit
