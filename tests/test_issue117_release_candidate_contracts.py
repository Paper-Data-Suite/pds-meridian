"""Issue #117: release-candidate identity and historical security notice."""
from __future__ import annotations

from pathlib import Path

import meridian
from scripts import check_package, check_sdist
from scripts.verify_core_wheel import (
    EXPECTED_CORE_VERSION,
    EXPECTED_CORE_WHEEL_FILENAME,
    EXPECTED_CORE_WHEEL_SHA256,
)

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_issue117_candidate_identity_and_exact_core_release() -> None:
    assert meridian.__version__ == "0.4.2"
    assert check_package.EXPECTED_VERSION == "0.4.2"
    assert check_sdist.EXPECTED_VERSION == "0.4.2"
    assert EXPECTED_CORE_VERSION == "0.6.6"
    assert EXPECTED_CORE_WHEEL_FILENAME == "pds_core-0.6.6-py3-none-any.whl"
    assert EXPECTED_CORE_WHEEL_SHA256 == (
        "d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301"
    )
    assert str(check_package.EXPECTED_CORE_REQUIREMENT) == "pds-core<0.7,>=0.6.5"


def test_issue117_security_notice_links_to_fixed_version() -> None:
    previous = _source("docs/development/v0.4.1-release-notes.md")
    current = _source("docs/development/v0.4.2-release-notes.md")
    assert "student-scope authorization defect" in previous
    assert "v0.4.2" in previous
    assert "student" in current
    assert "ReportingSnapshot" in current
    assert "v0.4.1 release artifacts" in current


def test_issue117_required_release_inventory_and_audit_separation() -> None:
    for required in (
        "meridian/publication_authorization_setup.py",
        "meridian/menu_teacher_authorization.py",
        "meridian/benchmark_plan_authoring.py",
        "meridian/menu_benchmark_planner.py",
        "meridian/benchmark_plan_notes.py",
        "meridian/benchmark_current_analysis.py",
        "scripts/installed_benchmark_helpers.py",
        "scripts/smoke_program_concord_benchmark_issue117.py",
        "scripts/smoke_test_concord_benchmark_issue117.py",
        "tests/test_issue117_installed_benchmark_journey.py",
        "tests/test_issue117_installed_concord_benchmark.py",
        "tests/test_issue117_benchmark_reassessment_revision.py",
        "docs/development/v0.4.2-release-notes.md",
        "tests/test_issue117_release_candidate_contracts.py",
    ):
        assert required in check_sdist.REQUIRED_MEMBERS
        assert (ROOT / required).is_file()
    for package_module in (
        "meridian/publication_authorization_setup.py",
        "meridian/menu_teacher_authorization.py",
        "meridian/benchmark_plan_authoring.py",
        "meridian/menu_benchmark_planner.py",
        "meridian/benchmark_plan_notes.py",
        "meridian/benchmark_current_analysis.py",
    ):
        assert f'"{package_module}"' in _source("scripts/check_package.py")
    audit = "docs/development/v0.4.2-release-audit.md"
    assert audit in check_sdist.FORBIDDEN_EXACT_MEMBERS
    assert audit not in check_sdist.REQUIRED_MEMBERS
    assert f"exclude {audit}" in _source("MANIFEST.in")
