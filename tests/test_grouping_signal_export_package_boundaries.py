from __future__ import annotations

import ast
from pathlib import Path

PRODUCER_ROOTS = frozenset(
    {"scoreform", "quillan", "concord", "portia", "vitrine"}
)
RUNTIME_MODULES = (
    Path("meridian/grouping_signal_export.py"),
    Path("meridian/grouping_signal_export_eligibility.py"),
    Path("meridian/grouping_signal_export_workflow.py"),
    Path("meridian/grouping_signal_export_receipt.py"),
    Path("meridian/grouping_signal_export_storage.py"),
    Path("meridian/grouping_signal_export_receipt_workflow.py"),
    Path("meridian/grouping_signal_csv_export.py"),
)


def _import_roots(path: Path) -> frozenset[str]:
    tree = ast.parse(
        path.read_text(encoding="utf-8"),
        filename=path.as_posix(),
    )
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".", 1)[0])
    return frozenset(roots)


def test_issue40_has_no_sibling_runtime_dependency() -> None:
    for path in RUNTIME_MODULES:
        assert not (_import_roots(path) & PRODUCER_ROOTS), path


def test_issue40_release_files_are_guarded() -> None:
    wheel_checker = Path("scripts/check_package.py").read_text(
        encoding="utf-8"
    )
    sdist_checker = Path("scripts/check_sdist.py").read_text(
        encoding="utf-8"
    )

    for path in RUNTIME_MODULES:
        member = path.as_posix()
        assert member in wheel_checker
        assert member in sdist_checker

    for member in (
        "docs/architecture/grouping-signal-core-export.md",
        "tests/test_grouping_signal_export.py",
        "tests/test_grouping_signal_export_eligibility.py",
        "tests/test_grouping_signal_export_workflow.py",
        "tests/test_grouping_signal_export_receipt_workflow.py",
        "tests/test_grouping_signal_csv_export.py",
        "tests/test_grouping_signal_export_package_boundaries.py",
        "scripts/smoke_test_grouping_signal_export_wheel.py",
        "scripts/smoke_program_grouping_signal_export.py",
    ):
        assert member in sdist_checker


def test_issue40_handoff_and_boundaries() -> None:
    text = Path(
        "docs/architecture/grouping-signal-core-export.md"
    ).read_text(encoding="utf-8")

    for statement in (
        "accepted_for_export",
        "review_selection_changed",
        "source.snapshot_digest = derivation.derivation_sha256",
        "partial_core_write_success",
        "representation_scope = complete_signal",
        "No Concord dependency",
        "#40 Core/CSV grouping-signal export — implemented",
        "#41 teacher eligibility, proficiency, and planning-export workflows — next",
    ):
        assert statement in text
