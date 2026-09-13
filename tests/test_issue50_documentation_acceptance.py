from __future__ import annotations

from pathlib import Path


def test_conventional_grade_architecture_records_final_acceptance_boundary() -> None:
    text = Path("docs/architecture/conventional-grade-calculation.md").read_text(
        encoding="utf-8"
    )
    for token in (
        "Installed ScoreForm acceptance",
        "released ScoreForm v0.11.0",
        "explicit #30 attempt selection",
        "explicit #31 reassessment",
        "writing a result does not select it",
        "fresh-process reload",
        "Quillan v0.10.0 scaled ratings are not conventional points",
        "Concord v0.3.0 scaled results are not conventional points",
        "producer-owned source bytes remain unchanged",
    ):
        assert token in text


def test_repository_handoffs_mark_issue50_implemented() -> None:
    readme = Path("README").read_text(encoding="utf-8")
    docs = Path("docs/README.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    for text in (readme, docs, changelog):
        assert "Issue #50" in text
        assert "conventional" in text.lower()
