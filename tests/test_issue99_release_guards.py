import ast
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

def test_no_test_fixture_hard_codes_retired_grade_policy_schema_one() -> None:
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in sorted((root / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            is_grade_policy_revision = (
                isinstance(function, ast.Name)
                and function.id == "GradePolicyRevision"
            ) or (
                isinstance(function, ast.Attribute)
                and function.attr == "GradePolicyRevision"
            )
            if not is_grade_policy_revision:
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "schema_version"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value == "1"
                ):
                    offenders.append(
                        f"{path.relative_to(root)}:{node.lineno}"
                    )
    assert offenders == [], (
        "GradePolicyRevision test fixtures must use "
        "GRADE_POLICY_SCHEMA_VERSION, not retired literal schema '1': "
        + ", ".join(offenders)
    )

def test_issue99_installed_smoke_preserves_profile_floor_fixture() -> None:
    root = Path(__file__).resolve().parents[1]
    standards = (
        root / "scripts/smoke_program_standards_grade.py"
    ).read_text(encoding="utf-8")
    profile = (
        root / "scripts/smoke_program_profile_constrained_grade.py"
    ).read_text(encoding="utf-8")

    assert 'expected_level_id: str = "advanced"' in standards
    assert 'outcome.proficiency_level_id == expected_level_id' in standards
    assert 'expected_level_id="proficient"' in profile
    assert 'outcome.base_unrounded_grade == Decimal("90")' in profile
    assert 'outcome.profile_adjustment == "floor"' in profile
    assert 'outcome.unrounded_grade == Decimal("95")' in profile
