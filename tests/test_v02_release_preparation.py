from __future__ import annotations

from pathlib import Path

import meridian
from scripts import check_package, check_sdist, verify_concord_wheel

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SUMMARY = (
    "Teacher-controlled evidence, proficiency, and planning exports "
    "for Paper Data Suite"
)


def test_v02_release_version_and_package_summary_are_frozen() -> None:
    assert meridian.__version__ == "0.2.0"
    assert check_package.EXPECTED_VERSION == "0.2.0"
    assert check_sdist.EXPECTED_VERSION == "0.2.0"
    assert check_package.EXPECTED_SUMMARY == EXPECTED_SUMMARY
    assert check_sdist.EXPECTED_SUMMARY == EXPECTED_SUMMARY

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'description = "{EXPECTED_SUMMARY}"' in pyproject


def test_concord_release_diagnostics_name_exact_v030() -> None:
    source = (ROOT / "scripts/verify_concord_wheel.py").read_text(
        encoding="utf-8"
    )

    assert verify_concord_wheel.EXPECTED_CONCORD_VERSION == "0.3.0"
    assert "version is not exactly 0.2.0" not in source
    assert "must be exactly 0.2.0" not in source
    assert "version is not exactly 0.3.0" in source
    assert "must be exactly 0.3.0" in source


def test_v02_audit_and_release_notes_use_nonrecursive_hash_boundary() -> None:
    documentation = (ROOT / "scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    audit_path = "docs/development/v0.2.0-release-audit.md"
    notes_path = "docs/development/v0.2.0-release-notes.md"

    assert audit_path in documentation
    assert notes_path in documentation
    assert f"exclude {audit_path}" in manifest
    assert audit_path not in check_sdist.REQUIRED_MEMBERS
    assert audit_path in check_sdist.FORBIDDEN_EXACT_MEMBERS
    assert notes_path in check_sdist.REQUIRED_MEMBERS

    for path in (
        "tests/test_v02_release_audit_policy_fairness.py",
        "tests/test_v02_release_audit_privacy_export.py",
        "tests/test_v02_release_audit_calculation_history.py",
        "tests/test_v02_release_audit_interoperability_boundaries.py",
        "tests/test_v02_release_audit_explanations_attention.py",
        "tests/test_v02_release_preparation.py",
    ):
        assert path in check_sdist.REQUIRED_MEMBERS

def test_release_status_documents_v02_boundary() -> None:
    readme = (ROOT / "README").read_text(encoding="utf-8")
    docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    security = (ROOT / "Security.md").read_text(encoding="utf-8")
    foundation = (
        ROOT / "docs/development/package-foundation.md"
    ).read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = (
        ROOT / "docs/development/v0.2.0-release-notes.md"
    ).read_text(encoding="utf-8")

    assert "#46 final v0.2.0 audit — implemented" in readme
    assert "#46 final v0.2.0 audit — implemented" in docs_readme
    assert "latest `0.2.x` release" in security
    assert "pds_concord-0.3.0-py3-none-any.whl" in foundation
    assert "pds_concord-0.2.0-py3-none-any.whl" not in foundation
    assert "## 0.2.0 — 2026-09-07" in changelog
    assert "zero blockers" in notes
    assert "stable, non-self-referential digest" in notes
    assert "pds_meridian-0.2.0-py3-none-any.whl" in notes
    assert "pds_meridian-0.2.0.tar.gz" in notes

def test_installed_smokes_do_not_pin_historical_meridian_release() -> None:
    stale: list[str] = []
    for path in sorted((ROOT / "scripts").glob("smoke*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "0.1.1" not in line:
                continue
            window = "\n".join(
                lines[max(0, index - 2) : min(len(lines), index + 3)]
            ).lower()
            if "meridian" in window or "pds-meridian" in window:
                stale.append(
                    f"{path.relative_to(ROOT)}:{index + 1}: {line.strip()}"
                )

    assert stale == []
