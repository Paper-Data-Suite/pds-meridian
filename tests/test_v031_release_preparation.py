from __future__ import annotations

from pathlib import Path

import meridian
from scripts import check_package, check_sdist

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_v031_candidate_identity_and_artifact_guards_are_aligned() -> None:
    assert meridian.__version__ == "0.3.1"
    assert check_package.EXPECTED_VERSION == "0.3.1"
    assert check_sdist.EXPECTED_VERSION == "0.3.1"

    notes = _read("docs/development/v0.3.1-release-notes.md")
    assert "pds_meridian-0.3.1-py3-none-any.whl" in notes
    assert "pds_meridian-0.3.1.tar.gz" in notes


def test_v031_notes_are_packaged_and_audit_is_repository_only() -> None:
    notes = "docs/development/v0.3.1-release-notes.md"
    audit = "docs/development/v0.3.1-release-audit.md"
    manifest = _read("MANIFEST.in")

    assert notes in check_sdist.REQUIRED_MEMBERS
    assert audit not in check_sdist.REQUIRED_MEMBERS
    assert audit in check_sdist.FORBIDDEN_EXACT_MEMBERS
    assert f"exclude {audit}" in manifest


def test_v031_current_docs_name_exact_qualified_readers() -> None:
    for relative in (
        "README",
        "docs/README.md",
        "docs/development/package-foundation.md",
    ):
        document = _read(relative)
        assert "Meridian v0.3.1 is the prepared compatibility candidate" in document
        assert "Core v0.6.4" in document
        assert "ScoreForm v0.12.1" in document
        assert "Quillan v0.10.5" in document
        assert "Concord v0.3.0" in document


def test_v031_release_records_preserve_v030_history() -> None:
    notes = _read("docs/development/v0.3.0-release-notes.md")
    audit = _read("docs/development/v0.3.0-release-audit.md")

    for historical in (notes, audit):
        assert "ScoreForm 0.12.0" in historical or "scoreform==0.12.0" in historical
        assert "0.12.1" not in historical


def test_v031_release_only_actions_remain_owner_gated() -> None:
    audit = _read("docs/development/v0.3.1-release-audit.md")

    for required in (
        "RELEASE NOT AUTHORIZED",
        "exact post-merge `main` qualification",
        "freezing the exact `main` source commit",
        "creation and push of tag `v0.3.1`",
        "GitHub Release publication",
        "independent fresh-download",
    ):
        assert required in audit


def test_v031_installed_programs_require_the_candidate_version() -> None:
    active = "\n".join(
        _read(relative)
        for relative in (
            "scripts/smoke_program_attention.py",
            "scripts/smoke_program_grade_report_attention.py",
            "scripts/smoke_test_grouping_signal_contract_wheel.py",
        )
    )

    assert 'version("pds-meridian") == "0.3.1"' in active
    assert 'version("pds-meridian") != "0.3.1"' in active
    assert 'version("pds-meridian") == "0.3.0"' not in active
    assert 'version("pds-meridian") != "0.3.0"' not in active
