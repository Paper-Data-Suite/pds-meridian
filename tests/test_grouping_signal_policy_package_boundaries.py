from __future__ import annotations

import ast
from pathlib import Path

PRODUCER_ROOTS = frozenset({"scoreform", "quillan", "concord", "portia", "vitrine"})
RUNTIME_MODULES = (
    Path("meridian/grouping_signal_policy.py"),
    Path("meridian/grouping_signal_policy_storage.py"),
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


def _import_modules(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return frozenset(modules)


def test_issue37_runtime_imports_no_producer_package() -> None:
    for path in RUNTIME_MODULES:
        assert not (_import_roots(path) & PRODUCER_ROOTS), path


def test_issue37_runtime_does_not_import_core_grouping_signal_generation() -> None:
    forbidden = frozenset(
        {
            "pds_core.grouping_signals",
            "pds_core.grouping_signal_storage",
            "pds_core.grouping_signal_diagnostics",
        }
    )
    for path in RUNTIME_MODULES:
        assert not (_import_modules(path) & forbidden), path


def test_issue37_runtime_is_guarded_by_wheel_and_sdist_validation() -> None:
    wheel_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    for member in (
        "meridian/grouping_signal_policy.py",
        "meridian/grouping_signal_policy_storage.py",
    ):
        assert member in wheel_checker
        assert member in sdist_checker

    for member in (
        "docs/architecture/grouping-signal-derivation-policy.md",
        "tests/test_grouping_signal_policy.py",
        "tests/test_grouping_signal_policy_storage.py",
        "tests/test_grouping_signal_policy_integration.py",
        "tests/test_grouping_signal_policy_storage_hardening.py",
        "tests/test_grouping_signal_policy_package_boundaries.py",
        "scripts/smoke_test_grouping_signal_policy_wheel.py",
    ):
        assert member in sdist_checker


def test_issue37_installed_smoke_is_release_guarded_and_signal_free() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    smoke_path = Path("scripts/smoke_test_grouping_signal_policy_wheel.py")
    smoke = smoke_path.read_text(encoding="utf-8")

    assert smoke_path.name in validator
    assert smoke_path.name in sdist_checker
    assert "GroupingSignalDerivationPolicy" in smoke
    assert "write_grouping_signal_policy_revision" in smoke
    assert "select_grouping_signal_policy_revision" in smoke
    assert "load_current_grouping_signal_policy" in smoke
    assert "list_grouping_signal_ids(workspace, class_id) == ()" in smoke
    assert 'find_spec("concord") is None' in smoke
    assert "write_grouping_signal(" not in smoke


def test_issue37_architecture_preserves_layer_boundaries() -> None:
    document = Path(
        "docs/architecture/grouping-signal-derivation-policy.md"
    ).read_text(encoding="utf-8")

    for statement in (
        "Academic Period proficiency\n!=\ngrouping-signal policy",
        "grouping-signal policy\n!=\ngrouping-signal derivation",
        "grouping-signal derivation\n!=\nCore signal export",
        "Core signal export\n!=\nGroupPlan",
        "Meridian band count != Concord target group count",
        "same_level_same_band",
        "noncontributing",
        "blocking",
        "#38 deterministic grouping-signal generation — next",
    ):
        assert statement in document
