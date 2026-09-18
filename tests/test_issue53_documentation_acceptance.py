from __future__ import annotations

from pathlib import Path

ARCHITECTURE = Path("docs/architecture/teacher-grade-overrides.md")


def test_issue53_architecture_freezes_exact_source_and_lifecycle_authority() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "Version-1 boundary",
        "conventional",
        "standards_based",
        "hybrid",
        "Exact source binding",
        "result_revision",
        "result_sha256",
        "There is no universal 0-100 clamp.",
        "Writing is not selection",
        "write revision != select revision",
        "Withdrawal lifecycle",
        "historical reselection as an audit-free undo mechanism",
    ):
        assert token in text


def test_issue53_architecture_freezes_nonfloating_freshness_and_precedence() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "Non-floating behavior after recalculation",
        "old override is non-applicable",
        "Source freshness versus override applicability",
        "source_result_stale",
        "Integrity failure is never silently reclassified as `no_override`",
        "Deterministic effective-Grade precedence",
        "effective_source = base | override | none",
    ):
        assert token in text


def test_issue53_architecture_documents_downstream_and_installed_handoff() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "#54 Grade preview handoff",
        "#55 ReportingSnapshot handoff",
        "Installed acceptance",
        "Core v0.6.3",
        "ScoreForm v0.11.0",
        "Quillan and Concord are deliberately absent",
        "fresh-process reload reproduces active authority",
        "base Grade regains precedence",
        "original source Grade-result bytes",
        "ADR 0005",
        "v0.3 umbrella issue #47",
    ):
        assert token in text


def test_issue53_repository_status_and_index_are_updated() -> None:
    readme = Path("README").read_text(encoding="utf-8")
    docs = Path("docs/README.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    for text in (readme, docs, changelog):
        assert "Issue #53" in text
        assert "override" in text.lower()
    assert "teacher-grade-overrides.md" in docs
    assert "teacher Grade overrides" in readme
    assert "effective Grade" in changelog
