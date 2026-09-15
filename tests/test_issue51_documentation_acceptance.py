from __future__ import annotations

from pathlib import Path


def test_standards_grade_architecture_freezes_issue51_authority_and_arithmetic(
) -> None:
    text = Path("docs/architecture/standards-grade-calculation.md").read_text(
        encoding="utf-8"
    )
    for token in (
        "Selected does not automatically mean current",
        "Proficiency levels have no universal percentage meaning",
        "Version 1 supports only `weighted_mean`",
        "`exclude` removes both the value and its weight",
        "A policy-created zero does not manufacture a proficiency result",
        "Missing or unresolved proficiency is not numeric zero",
        "Version 1 has no hidden\n0-100 clamp",
        "final-stage rounding only",
        "Writing a result does not select it",
        "proficiency_results_changed",
        "Producer neutrality and source immutability",
    ):
        assert token in text


def test_standards_grade_architecture_preserves_future_v03_boundaries() -> None:
    text = Path("docs/architecture/standards-grade-calculation.md").read_text(
        encoding="utf-8"
    )
    for token in (
        "teacher override",
        "Grade preview presentation",
        "ReportingSnapshot",
        "official school-system Grade",
        "hybrid Grade calculation",
    ):
        assert token in text


def test_issue51_repository_handoffs_and_installed_boundary_are_documented() -> None:
    readme = Path("README").read_text(encoding="utf-8")
    docs = Path("docs/README.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    architecture = Path(
        "docs/architecture/standards-grade-calculation.md"
    ).read_text(encoding="utf-8")
    for text in (readme, docs, changelog):
        assert "Issue #51" in text
        assert "standards-based" in text.lower()
    for token in (
        "Installed acceptance",
        "released ScoreForm v0.11.0",
        "Quillan v0.10.0",
        "Concord is deliberately absent",
        "fresh-process reload",
        "producer-owned plus v0.2 proficiency source bytes remain unchanged",
    ):
        assert token in architecture
