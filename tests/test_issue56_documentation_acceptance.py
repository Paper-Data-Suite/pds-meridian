from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_issue56_architecture_document_freezes_export_boundary() -> None:
    text = (
        ROOT / "docs" / "architecture" / "reporting-exports.md"
    ).read_text(encoding="utf-8")

    required = (
        "exact immutable ReportingSnapshot",
        "roster.extra:<exact_column_name>",
        "missing / blocked / insufficient / unavailable != numeric zero",
        "preview_sha256",
        "external-system write = no",
        "external-system acceptance claim = no",
        "quillan 0.10.1",
        "Issue #57 remains responsible",
    )
    for phrase in required:
        assert phrase in text


def test_issue56_user_docs_expose_local_non_authoritative_exports() -> None:
    root = (ROOT / "README").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "Issue #56" in root
    assert "reporting-exports.md" in root
    assert "Issue #56" in docs
    assert "reporting-exports.md" in docs
    assert "Issue #56" in changelog
    assert "Quillan v0.10.1" in changelog
