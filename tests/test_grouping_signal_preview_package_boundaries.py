from __future__ import annotations

import ast
from pathlib import Path

PRODUCER_ROOTS = frozenset({"scoreform", "quillan", "concord", "portia", "vitrine"})
RUNTIME_MODULES = (
    Path("meridian/grouping_signal_currentness.py"),
    Path("meridian/grouping_signal_preview.py"),
    Path("meridian/grouping_signal_preview_storage.py"),
    Path("meridian/grouping_signal_preview_generation.py"),
    Path("meridian/grouping_signal_review.py"),
    Path("meridian/grouping_signal_review_storage.py"),
    Path("meridian/grouping_signal_review_workflow.py"),
    Path("meridian/grouping_signal_preview_projection.py"),
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


def test_issue39_runtime_imports_no_producer_package() -> None:
    for path in RUNTIME_MODULES:
        assert not (_import_roots(path) & PRODUCER_ROOTS), path


def test_issue39_runtime_does_not_construct_or_export_core_signals() -> None:
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


def test_issue39_runtime_is_guarded_by_wheel_and_sdist_validation() -> None:
    wheel_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    for path in RUNTIME_MODULES:
        member = path.as_posix()
        assert member in wheel_checker
        assert member in sdist_checker

    for member in (
        "docs/architecture/grouping-signal-preview-diagnostics.md",
        "tests/test_grouping_signal_currentness.py",
        "tests/test_grouping_signal_preview.py",
        "tests/test_grouping_signal_preview_storage.py",
        "tests/test_grouping_signal_preview_generation.py",
        "tests/test_grouping_signal_review.py",
        "tests/test_grouping_signal_review_storage.py",
        "tests/test_grouping_signal_review_workflow.py",
        "tests/test_grouping_signal_preview_projection.py",
        "tests/test_grouping_signal_preview_package_boundaries.py",
        "scripts/smoke_test_grouping_signal_preview_review_wheel.py",
        "scripts/smoke_program_grouping_signal_preview_review.py",
    ):
        assert member in sdist_checker


def test_issue39_architecture_preserves_review_and_export_boundaries() -> None:
    document = Path(
        "docs/architecture/grouping-signal-preview-diagnostics.md"
    ).read_text(encoding="utf-8")

    for statement in (
        "Previewing does not export.",
        "Accepting does not export.",
        "Export happens only in #40.",
        'preview_id = "gsp_" + preview_fingerprint',
        'diagnostic_id = "gpd_" + sha256(structured diagnostic subject)',
        "accepted_for_export",
        "current at review time",
        "Blocking diagnostics cannot be acknowledged away.",
        "Writing a newer review does not select it",
        "Band 1",
        "display names",
        "#39 grouping-signal preview and diagnostics — implemented",
        "#40 Core/CSV grouping-signal export — implemented",
        "#41 teacher eligibility, proficiency, and planning-export workflows — next",
    ):
        assert statement in document


def test_active_package_boundary_tests_do_not_call_issue39_next() -> None:
    stale_phrases = (
        "issue #39 — next",
        "#39 grouping-signal preview and diagnostics — next",
    )
    for path in Path("tests").glob("test_*package_boundaries.py"):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in stale_phrases:
            assert phrase not in text, f"{path} still calls implemented #39 next"


def test_issue39_installed_smoke_is_release_guarded_and_export_free() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    runner_path = Path(
        "scripts/smoke_test_grouping_signal_preview_review_wheel.py"
    )
    program_path = Path(
        "scripts/smoke_program_grouping_signal_preview_review.py"
    )
    program = program_path.read_text(encoding="utf-8")

    assert runner_path.name in validator
    assert runner_path.name in sdist_checker
    assert program_path.name in sdist_checker
    assert "generate_grouping_signal_preview" in program
    assert "record_grouping_signal_review" in program
    assert "select_grouping_signal_review_revision" in program
    assert "build_grouping_signal_teacher_projection" in program
    assert 'find_spec("concord") is None' in program
    assert "list_grouping_signal_ids(workspace, CLASS_ID) == ()" in program
    assert "write_grouping_signal(" not in program
