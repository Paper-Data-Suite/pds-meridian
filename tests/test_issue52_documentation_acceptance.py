from __future__ import annotations

from pathlib import Path

ARCHITECTURE = Path("docs/architecture/hybrid-grade-calculation.md")


def test_hybrid_architecture_freezes_one_policy_component_authority() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "One exact hybrid authority",
        "A hybrid Grade is not constructed from separately selected conventional",
        "The standalone family-gated #50/#51 calculation constructors remain intact",
        "The hybrid layer does not consume a selected standalone conventional Grade",
        "The hybrid layer does not consume a selected standalone standards "
        "Grade result",
        "one exact hybrid policy embeds both component configurations",
    ):
        assert token in text


def test_hybrid_architecture_freezes_arithmetic_state_and_freshness() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "An insufficient component enters the hybrid boundary",
        "Explicit exclusion and active-weight renormalization",
        "Calculated zero is still calculated",
        "Unrounded component composition",
        "Issue #52 introduces no universal 0-100 clamp",
        "Writing a result does not select it",
        "Historical dependency integrity is not currentness",
        "conventional_inputs_changed",
        "proficiency_results_changed",
        "algorithm_changed",
    ):
        assert token in text


def test_hybrid_architecture_preserves_downstream_v03_boundaries() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "teacher override",
        "Grade preview presentation",
        "ReportingSnapshot",
        "official school-system Grade",
        "issue #53",
    ):
        assert token in text



def test_issue52_repository_handoffs_and_installed_boundary_are_documented() -> None:
    readme = Path("README").read_text(encoding="utf-8")
    docs = Path("docs/README.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    for text in (readme, docs, changelog):
        assert "Issue #52" in text
        assert "hybrid" in text.lower()
    for token in (
        "Installed acceptance",
        "released ScoreForm v0.11.0",
        "Quillan v0.10.0",
        "Concord is deliberately absent",
        "no standalone conventional or standards Grade",
        "result is written or selected",
        "fresh-process reload",
        "producer plus v0.2/",
        "Teacher override records and precedence remain issue",
        "#53 work.",
    ):
        assert token in architecture
