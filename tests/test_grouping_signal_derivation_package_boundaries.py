from __future__ import annotations

import ast
from pathlib import Path

PRODUCER_ROOTS = frozenset({"scoreform", "quillan", "concord", "portia", "vitrine"})
RUNTIME_MODULES = (
    Path("meridian/grouping_signal_derivation.py"),
    Path("meridian/grouping_signal_derivation_storage.py"),
    Path("meridian/grouping_signal_generation.py"),
    Path("meridian/grouping_signal_generation_basis.py"),
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


def test_issue38_runtime_imports_no_producer_package() -> None:
    for path in RUNTIME_MODULES:
        assert not (_import_roots(path) & PRODUCER_ROOTS), path


def test_issue38_runtime_does_not_construct_or_export_core_signals() -> None:
    forbidden = frozenset(
        {
            "pds_core.grouping_signals",
            "pds_core.grouping_signal_storage",
            "pds_core.grouping_signal_csv",
            "pds_core.grouping_signal_diagnostics",
        }
    )
    for path in RUNTIME_MODULES:
        assert not (_import_modules(path) & forbidden), path


def test_issue38_runtime_is_guarded_by_wheel_and_sdist_validation() -> None:
    wheel_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    for member in (
        "meridian/grouping_signal_derivation.py",
        "meridian/grouping_signal_derivation_storage.py",
        "meridian/grouping_signal_generation.py",
        "meridian/grouping_signal_generation_basis.py",
    ):
        assert member in wheel_checker
        assert member in sdist_checker

    for member in (
        "docs/architecture/grouping-signal-generation.md",
        "tests/test_grouping_signal_derivation.py",
        "tests/test_grouping_signal_derivation_storage.py",
        "tests/test_grouping_signal_derivation_storage_hardening.py",
        "tests/test_grouping_signal_generation.py",
        "tests/test_grouping_signal_generation_basis.py",
        "tests/test_grouping_signal_generation_integration.py",
        "tests/test_grouping_signal_derivation_package_boundaries.py",
    ):
        assert member in sdist_checker


def test_issue38_architecture_preserves_layer_and_identity_boundaries() -> None:
    document = Path("docs/architecture/grouping-signal-generation.md").read_text(
        encoding="utf-8"
    )

    for statement in (
        "grouping-signal derivation\n!=\nCore grouping_signal_set_v1 export",
        'derivation_id = "gsd_" + calculation_fingerprint',
        "same_level_same_band",
        "no `current.json`",
        "zero contributing bands",
        "current_basis_unavailable",
        "pds_core.grouping_signal_csv",
        "#38 deterministic grouping-signal generation — implemented",
        "#39 grouping-signal preview and diagnostics — implemented",
        "#40 Core/CSV grouping-signal export — implemented",
        "#41 teacher eligibility, proficiency, and planning-export workflows — next",
    ):
        assert statement in document


def test_active_package_boundary_tests_do_not_call_issue38_next() -> None:
    stale_phrases = (
        "issue #38 — next",
        "#38 deterministic grouping-signal generation — next",
    )
    for path in Path("tests").glob("test_*package_boundaries.py"):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in stale_phrases:
            assert phrase not in text, f"{path} still calls implemented #38 next"


def test_issue38_installed_smoke_is_release_guarded_and_signal_free() -> None:
    validator = Path("scripts/validate_repository.py").read_text(
        encoding="utf-8"
    )
    sdist_checker = Path("scripts/check_sdist.py").read_text(
        encoding="utf-8"
    )
    runner_path = Path("scripts/smoke_test_grouping_signal_generation_wheel.py")
    program_path = Path("scripts/smoke_program_grouping_signal_generation.py")
    program = program_path.read_text(encoding="utf-8")

    assert runner_path.name in validator
    assert runner_path.name in sdist_checker
    assert program_path.name in sdist_checker
    assert "generate_grouping_signal_derivation" in program
    assert "student.band == 2" in program
    assert 'write_disposition == "created"' in program
    assert 'write_disposition == "existing"' in program
    assert (
        "list_grouping_signal_ids(workspace, CLASS_ID) == ()"
        in program
    )
    assert 'find_spec("concord") is None' in program
    assert "write_grouping_signal(" not in program
