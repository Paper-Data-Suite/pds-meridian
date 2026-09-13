from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "docs/architecture/conventional-grade-calculation.md"


def test_issue50_pure_calculation_architecture_freezes_boundaries() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    required = (
        "GradePolicy family current\n    != GradePolicy activation",
        (
            "GradeItemRevision.weighting metadata\n"
            "    != executable GradePolicy configuration"
        ),
        "v0.2 attempt/reassessment state\n    != conventional Grade arithmetic",
        "2+ operative NativePointValue values\n    -> unresolved",
        "producer possible points != policy possible points",
        "missing or unresolved state != numeric zero",
        "There is no silent renormalization",
        "CONVENTIONAL_GRADE_ALGORITHM_VERSION = \"1\"",
        "Grade Item conventional input\n    != conventional Grade calculation",
        "!= ReportingSnapshot",
        "!= official Grade",
    )
    for token in required:
        assert token in text


def test_documentation_checker_requires_conventional_grade_architecture() -> None:
    checker = (ROOT / "scripts/check_documentation.py").read_text(encoding="utf-8")
    assert "conventional-grade-calculation.md" in checker
    assert "multiple_point_observations" in checker
    assert "possible_points_mismatch" in checker
    assert "CONVENTIONAL_GRADE_ALGORITHM_VERSION" in checker
