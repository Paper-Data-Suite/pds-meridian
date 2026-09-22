from __future__ import annotations

import ast
from pathlib import Path

RUNTIME_MODULES = (
    "meridian/reporting_snapshot.py",
    "meridian/reporting_snapshot_preview.py",
    "meridian/reporting_snapshot_record.py",
    "meridian/reporting_snapshot_storage.py",
    "meridian/reporting_snapshot_selection.py",
    "meridian/reporting_snapshot_freeze.py",
    "meridian/reporting_snapshot_comparison.py",
    "meridian/reporting_snapshot_cli.py",
)
PRODUCER_ROOTS = frozenset(
    {"scoreform", "quillan", "concord", "portia", "vitrine"}
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


def test_issue55_runtime_has_no_sibling_package_dependency() -> None:
    for member in RUNTIME_MODULES:
        path = Path(member)
        assert path.is_file(), member
        assert not (_import_roots(path) & PRODUCER_ROOTS), member


def test_wheel_guard_requires_all_issue55_runtime_modules() -> None:
    text = Path("scripts/check_package.py").read_text(encoding="utf-8")
    for member in RUNTIME_MODULES:
        assert member in text


def test_sdist_guard_requires_current_issue55_acceptance_surface() -> None:
    text = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        "docs/architecture/reporting-snapshots.md",
        *RUNTIME_MODULES,
        "tests/test_reporting_snapshot_contract_issue55.py",
        "tests/test_reporting_snapshot_preview_issue55.py",
        "tests/test_reporting_snapshot_record_issue55.py",
        "tests/test_reporting_snapshot_storage_issue55.py",
        "tests/test_reporting_snapshot_selection_issue55.py",
        "tests/test_reporting_snapshot_freeze_issue55.py",
        "tests/test_reporting_snapshot_comparison_issue55.py",
        "tests/test_issue55_documentation_acceptance.py",
        "tests/test_issue55_packaging_acceptance.py",
        "tests/test_cli_reporting_issue55.py",
        "tests/test_cli_reporting_live_issue55.py",
        "tests/test_reporting_snapshot_integration_issue55.py",
        "tests/test_reporting_snapshot_grade_families_issue55.py",
        "tests/test_reporting_snapshot_override_states_issue55.py",
        "tests/test_reporting_snapshot_adversarial_issue55.py",
        "tests/test_reporting_snapshot_historical_movement_issue55.py",
        "tests/test_issue55_installed_acceptance.py",
        "scripts/smoke_test_reporting_snapshot_wheel.py",
        "scripts/smoke_program_reporting_snapshot.py",
        "scripts/smoke_program_reporting_snapshot_reload.py",
    ):
        assert member in text


def test_documentation_checker_includes_issue55_architecture() -> None:
    text = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    assert "docs/architecture/reporting-snapshots.md" in text
