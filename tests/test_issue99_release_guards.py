from pathlib import Path

from meridian.grade_policy import GRADE_POLICY_SCHEMA_VERSION
from meridian.hybrid_grade import HYBRID_GRADE_ALGORITHM_VERSION
from meridian.standards_grade import STANDARDS_GRADE_ALGORITHM_VERSION
from meridian.standards_grade_profile import ProfileConstraintEvaluation


def test_issue99_release_versions_are_explicit() -> None:
    assert GRADE_POLICY_SCHEMA_VERSION == "2"
    assert STANDARDS_GRADE_ALGORITHM_VERSION == "2"
    assert HYBRID_GRADE_ALGORITHM_VERSION == "2"
    assert ProfileConstraintEvaluation is not None


def test_issue99_release_document_covers_followup_audits() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (
        root / "docs/architecture/profile-constrained-standards-grade.md"
    ).read_text(encoding="utf-8")
    for value in (
        "profile_constrained_mean",
        "matched",
        "not_matched",
        "indeterminate",
        "Issue #60",
        "Issue #61",
        "quillan 0.10.3",
    ):
        assert value in text
