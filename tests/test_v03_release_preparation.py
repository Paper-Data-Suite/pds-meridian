from __future__ import annotations

from pathlib import Path

import meridian
from scripts import check_package, check_sdist

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SUMMARY = (
    "Teacher-controlled evidence, proficiency, Grades, reporting, and planning "
    "for Paper Data Suite"
)


def test_v03_candidate_version_and_package_summary_are_promoted() -> None:
    assert meridian.__version__ == "0.3.0"
    assert check_package.EXPECTED_VERSION == "0.3.0"
    assert check_sdist.EXPECTED_VERSION == "0.3.0"
    assert check_package.EXPECTED_SUMMARY == EXPECTED_SUMMARY
    assert check_sdist.EXPECTED_SUMMARY == EXPECTED_SUMMARY

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'description = "{EXPECTED_SUMMARY}"' in pyproject


def test_v03_release_notes_are_packaged_and_audit_stays_repository_only() -> None:
    notes = "docs/development/v0.3.0-release-notes.md"
    audit = "docs/development/v0.3.0-release-audit.md"
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert notes in check_sdist.REQUIRED_MEMBERS
    assert audit not in check_sdist.REQUIRED_MEMBERS
    assert audit in check_sdist.FORBIDDEN_EXACT_MEMBERS
    assert f"exclude {audit}" in manifest


def test_v03_release_framing_names_current_candidate_and_exact_siblings() -> None:
    readme = (ROOT / "README").read_text(encoding="utf-8")
    docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    foundation = (
        ROOT / "docs/development/package-foundation.md"
    ).read_text(encoding="utf-8")
    security = (ROOT / "Security.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = (
        ROOT / "docs/development/v0.3.0-release-notes.md"
    ).read_text(encoding="utf-8")

    for document in (readme, docs_readme, foundation):
        assert "Core v0.6.4" in document
        assert "ScoreForm v0.12.0" in document
        assert "Quillan v0.10.5" in document
        assert "Concord v0.3.0" in document

    assert "Meridian v0.3.0 is the promoted release candidate" in readme
    assert "Meridian v0.3.0 is the promoted release candidate" in docs_readme
    assert "Meridian v0.3.0 is the promoted release candidate" in foundation
    assert (
        "Security fixes for the v0.3 line target the latest `0.3.x` release."
        in security
    )
    assert "## 0.3.0 — 2026-10-06" in changelog
    assert "Issue #61 final v0.3.0 release audit" in changelog
    assert "zero open substantive blockers" in notes
    assert "pds_meridian-0.3.0-py3-none-any.whl" in notes
    assert "pds_meridian-0.3.0.tar.gz" in notes


def test_v03_release_state_records_completed_publication() -> None:
    audit = (
        ROOT / "docs/development/v0.3.0-release-audit.md"
    ).read_text(encoding="utf-8")
    release_authorization = audit.split("## Release authorization", maxsplit=1)[1]

    assert "Candidate package version: **0.3.0**" in audit
    candidate_states = (
        "Candidate qualification: **PENDING**",
        "Candidate qualification: **CONFORMS**",
    )
    assert sum(state in release_authorization for state in candidate_states) == 1
    assert (
        "Tag/publication authorization: **AUTHORIZED — COMPLETED**"
        in release_authorization
    )
    assert "Fresh-download verification: **CONFORMS**" in release_authorization
    assert "134b56209b031bc3a294551836ee96d1f97c291d" in release_authorization
    assert (
        "https://github.com/Paper-Data-Suite/pds-meridian/releases/tag/v0.3.0"
        in release_authorization
    )
