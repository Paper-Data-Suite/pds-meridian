from pathlib import Path

ISSUE44_SDIST_MEMBERS = (
    "docs/architecture/cross-producer-proficiency-scenarios.md",
    "tests/cross_producer_proficiency_support.py",
    "tests/cross_producer_attempts_support.py",
    "tests/cross_producer_aggregation_support.py",
    "tests/cross_producer_native_states_support.py",
    "tests/cross_producer_academic_period_support.py",
    "tests/cross_producer_correction_support.py",
    "tests/cross_producer_decision_history_support.py",
    "tests/test_cross_producer_proficiency_issue44.py",
    "tests/test_cross_producer_attempts_issue44.py",
    "tests/test_cross_producer_aggregation_issue44.py",
    "tests/test_cross_producer_policy_issue44.py",
    "tests/test_cross_producer_native_states_issue44.py",
    "tests/test_cross_producer_academic_period_issue44.py",
    "tests/test_cross_producer_lifecycle_issue44.py",
    "tests/test_cross_producer_correction_issue44.py",
    "tests/test_cross_producer_decision_history_issue44.py",
    "tests/test_cross_producer_boundaries_issue44.py",
    "tests/test_issue44_documentation_acceptance.py",
    "tests/test_issue44_packaging_acceptance.py",
)


def test_issue44_source_surfaces_are_sdist_guarded() -> None:
    sdist = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in ISSUE44_SDIST_MEMBERS:
        assert member in sdist


def test_issue44_does_not_enlarge_runtime_wheel_allowlist() -> None:
    wheel = Path("scripts/check_package.py").read_text(encoding="utf-8")
    for member in ISSUE44_SDIST_MEMBERS:
        assert member not in wheel


def test_issue44_producer_dependencies_remain_optional() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    project, optional = pyproject.split(
        "[project.optional-dependencies]",
        maxsplit=1,
    )
    dependencies = project.split("dependencies = [", maxsplit=1)[1]
    dependencies = dependencies.split("]", maxsplit=1)[0]

    assert "pds-core>=0.6.3,<0.7" in dependencies
    assert "scoreform" not in dependencies
    assert "quillan" not in dependencies
    assert "pds-concord" not in dependencies
    assert '"scoreform==0.11.0"' in optional
    assert '"quillan==0.10.0"' in optional
    assert '"pds-concord==0.3.0"' in optional
