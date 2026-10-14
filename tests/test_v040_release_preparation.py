from __future__ import annotations

from pathlib import Path

import meridian
from scripts import check_package, check_sdist

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_v040_candidate_identity_and_artifact_guards_are_aligned() -> None:
    assert meridian.__version__ == "0.4.1"
    assert check_package.EXPECTED_VERSION == "0.4.1"
    assert check_sdist.EXPECTED_VERSION == "0.4.1"
    notes = _read("docs/development/v0.4.0-release-notes.md")
    assert "pds_meridian-0.4.0-py3-none-any.whl" in notes
    assert "pds_meridian-0.4.0.tar.gz" in notes


def test_v040_notes_are_packaged_and_audit_is_repository_only() -> None:
    notes = "docs/development/v0.4.0-release-notes.md"
    audit = "docs/development/v0.4.0-release-audit.md"
    manifest = _read("MANIFEST.in")
    assert notes in check_sdist.REQUIRED_MEMBERS
    assert audit in check_sdist.FORBIDDEN_EXACT_MEMBERS
    assert f"exclude {audit}" in manifest


def test_v040_release_docs_name_current_and_legacy_boundaries() -> None:
    notes = _read("docs/development/v0.4.0-release-notes.md")
    audit = _read("docs/development/v0.4.0-release-audit.md")
    for value in (
        "Core",
        "0.6.5",
        "ScoreForm",
        "0.13.0",
        "Quillan",
        "0.10.6",
        "Concord",
        "0.3.2",
        "ScoreForm 0.12.1",
        "Quillan 0.10.5",
        "Concord 0.3.0",
    ):
        assert value in notes + audit
    assert "six installed matrices" in audit
    assert "Status: **RELEASED AND VERIFIED**" in audit
    assert "67aa0cde4ed033ce8a5178a31330c121379940fa" in audit
    assert "actions/runs/38502495518" in audit
    assert "actions/runs/38504823155" in audit
    assert "releases/tag/v0.4.0" in audit
    assert "4bd4bfaf988a036e90c4bfa7e3bb2a915affba6ffde154af103cd9bbbf5879fe" in audit
    assert "dad3f4a2f0168cf86d66bdecb0e7c6e0bc7c00b5b98421f7aaee350e7504ed83" in audit
    assert (
        "Tag/publication authorization: **COMPLETED AFTER ALL GATES PASSED**" in audit
    )
