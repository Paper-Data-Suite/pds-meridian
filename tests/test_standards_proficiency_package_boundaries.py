from __future__ import annotations

import ast
from pathlib import Path

PRODUCER_ROOTS = frozenset({"scoreform", "quillan", "concord", "portia", "vitrine"})
RUNTIME_MODULES = (
    Path("meridian/standards_proficiency.py"),
    Path("meridian/standards_proficiency_storage.py"),
)


def _import_roots(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".", 1)[0])
    return frozenset(roots)


def test_generic_standards_proficiency_runtime_imports_no_producer_package() -> None:
    for path in RUNTIME_MODULES:
        assert not (_import_roots(path) & PRODUCER_ROOTS), path


def test_issue34_runtime_is_guarded_by_wheel_and_sdist_validation() -> None:
    wheel_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    for member in (
        "meridian/standards_proficiency.py",
        "meridian/standards_proficiency_storage.py",
    ):
        assert member in wheel_checker
        assert member in sdist_checker

    for member in (
        "docs/architecture/standards-proficiency-calculation.md",
        "tests/test_standards_proficiency.py",
        "tests/test_standards_proficiency_storage.py",
        "tests/test_standards_proficiency_results.py",
        "tests/test_standards_proficiency_result_storage.py",
        "tests/test_standards_proficiency_freshness.py",
        "tests/test_standards_proficiency_integration.py",
        "tests/test_standards_proficiency_package_boundaries.py",
    ):
        assert member in sdist_checker


def test_installed_interpretation_smoke_extends_through_issue34() -> None:
    smoke = Path("scripts/smoke_test_grade_items_wheel.py").read_text(
        encoding="utf-8"
    )
    for symbol in (
        "StandardProficiencyCalculationPolicy",
        "calculate_standard_proficiency",
        "create_standard_proficiency_result_snapshot",
        "write_standard_proficiency_result_revision",
        "select_standard_proficiency_result_revision",
        "load_current_standard_proficiency_result",
        "assess_standard_proficiency_result_freshness",
        "below_minimum_performance_observations",
        "blocking_exclusion",
        "native_state",
        "unresolved_mode_tie",
        "median_even",
    ):
        assert symbol in smoke

    # Preserve the established Windows-safe installed-smoke execution pattern.
    assert 'smoke_program = root / "installed_interpretation_smoke.py"' in smoke
    assert "_run([str(python), str(smoke_program)], outside)" in smoke
