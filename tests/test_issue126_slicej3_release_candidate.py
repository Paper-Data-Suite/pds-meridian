"""J3 v0.4.3 migration: precise source identity without false publication."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import check_package, check_sdist

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_j3_active_candidate_version_has_one_identity() -> None:
    from meridian._version import __version__

    assert __version__ == "0.4.3"
    assert check_package.EXPECTED_VERSION == __version__
    assert check_sdist.EXPECTED_VERSION == __version__
    assert 'version = { attr = "meridian._version.__version__" }' in _read(
        "pyproject.toml"
    )
    assert check_sdist.EXPECTED_SDIST_FILENAME == "pds_meridian-0.4.3.tar.gz"


def test_j3_packaging_includes_new_notes_and_retains_v042_history() -> None:
    required = check_sdist.REQUIRED_MEMBERS
    forbidden = check_sdist.FORBIDDEN_EXACT_MEMBERS
    assert "docs/development/v0.4.3-release-notes.md" in required
    assert "docs/development/v0.4.2-release-notes.md" in required
    assert "docs/development/v0.4.2-release-audit.md" in forbidden
    assert "docs/development/v0.4.2-release-audit.md" not in required
    manifest = _read("MANIFEST.in")
    assert "recursive-include docs *.md" in manifest
    assert "exclude docs/development/v0.4.2-release-audit.md" in manifest
    source = _read("scripts/check_documentation.py")
    assert 'Path("docs/development/v0.4.3-release-notes.md")' in source


def test_j3_j1_j2_historical_labels_and_unpublished_wheel_unchanged() -> None:
    j1 = json.loads(_read("docs/development/issue126-slicej1-a1-a18-ledger.json"))
    j2 = json.loads(_read("docs/development/issue126-slicej2-a1-a18-ledger.json"))
    assert j1["environment"]["meridian_source_label"] == "0.4.2"
    assert j2["version_state"]["current_source_version"] == "0.4.2"
    assert j2["version_state"]["candidate_next_version"] == (
        "0.4.3_proposed_not_applied"
    )
    assert j2["provenance"]["unpublished_candidate_qualifies_D3"] is False
    assert j2["release_authorized"] is False
    assert j2["issue_close_authorized"] is False


def test_j3_notes_and_changelog_reject_premature_release_claims() -> None:
    notes = _read("docs/development/v0.4.3-release-notes.md")
    audit = _read("docs/development/issue126-slicej3-version-qualification.md")
    changelog = _read("CHANGELOG.md")
    assert "release candidate (not published)" in notes
    assert "#123" in notes and "#124" in notes
    assert "#125" in notes and "#126" in notes
    for token in (
        "PASS_WITH_TRANSCRIPT_LIMITATION",
        "Twine",
        "#133/#134",
        "not authorize closing Issue #126",
    ):
        assert token in notes
    assert "not merged, tagged or published" in audit
    assert "## 0.4.3 — release candidate" in changelog
    assert "## 0.4.2 — release candidate" in changelog


def test_j3_no_v042_active_version_pins_in_smoke_programs() -> None:
    candidates = (
        "scripts/smoke_program_attention.py",
        "scripts/smoke_program_grade_report_attention.py",
        "scripts/smoke_program_issue123_consequential_journey.py",
        "scripts/smoke_program_issue123_joined_journey.py",
        "scripts/smoke_program_issue123_populated_domain.py",
        "scripts/smoke_test_grouping_signal_contract_wheel.py",
    )
    for path in candidates:
        source = _read(path)
        assert '"0.4.2"' not in source, path
        assert '"0.4.3"' in source, path


def test_j3_no_release_tag_or_official_artifact_claim_in_ledger() -> None:
    j2 = json.loads(_read("docs/development/issue126-slicej2-a1-a18-ledger.json"))
    assert j2["d_levels"]["D3"] != "qualified"
    assert j2["d_levels"]["D4"] != "qualified"
    notes = _read("docs/development/v0.4.3-release-notes.md")
    assert "No v0.4.3 tag" in notes
    assert "latest verified GitHub release remains" in notes
