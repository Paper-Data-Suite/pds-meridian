from pathlib import Path


def test_conventional_grade_result_architecture_is_documented() -> None:
    text = Path(
        "docs/architecture/conventional-grade-calculation.md"
    ).read_text(encoding="utf-8")
    required = (
        "ConventionalGradeResultSnapshot",
        "writing result revision != selecting result revision",
        "subject_key",
        "compare-and-swap",
        "current.json",
        "calendar_scope_changed",
        "activation_changed",
        "policy_changed",
        "inputs_changed",
        "algorithm_changed",
        "Freshness is diagnostic",
        "not a Grade preview, teacher override, ReportingSnapshot",
        "same caller-bounded authorized evidence scope",
    )
    for token in required:
        assert token in text


def test_documentation_checker_requires_result_contract_tokens() -> None:
    text = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    for token in (
        "ConventionalGradeResultSnapshot",
        "writing result revision != selecting result revision",
        "calendar_scope_changed",
        "algorithm_changed",
        "Freshness is diagnostic",
    ):
        assert token in text
