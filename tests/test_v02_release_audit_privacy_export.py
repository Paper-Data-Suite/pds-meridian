from __future__ import annotations

import ast
from pathlib import Path

import pytest

import meridian

ATTENTION_MODULES = (
    "academic_period_attention.py",
    "planning_attention.py",
    "proficiency_attention.py",
    "attention_service.py",
    "attention_provider.py",
    "pds_operations.py",
)
FORBIDDEN_ATTENTION_IMPORT_PREFIXES = (
    "meridian.projection_cache",
    "meridian.evidence",
    "meridian.scoreform_adapter",
    "meridian.quillan_adapter",
    "meridian.concord_adapter",
    "scoreform",
    "quillan",
    "concord",
    "pds_concord",
)


def _module_path(name: str) -> Path:
    assert meridian.__file__ is not None
    return Path(meridian.__file__).resolve().parent / name


def _module_tree(name: str) -> ast.Module:
    path = _module_path(name)
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = tuple(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    assert len(matches) == 1
    return matches[0]


def _called_attribute_lines(
    function: ast.FunctionDef,
    attribute: str,
    *,
    receiver: str | None = None,
) -> tuple[int, ...]:
    lines: list[int] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if not isinstance(target, ast.Attribute):
            continue
        if target.attr != attribute:
            continue
        if receiver is not None:
            if not isinstance(target.value, ast.Name):
                continue
            if target.value.id != receiver:
                continue
        lines.append(node.lineno)
    return tuple(sorted(lines))


def _called_name_lines(
    function: ast.FunctionDef,
    name: str,
) -> tuple[int, ...]:
    return tuple(
        sorted(
            node.lineno
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
        )
    )


def _imported_modules(tree: ast.Module) -> tuple[str, ...]:
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    return tuple(imported)


def test_projection_cache_authorizes_before_protected_payload_read() -> None:
    tree = _module_tree("projection_cache.py")
    function = _function(tree, "load_authorized_projection_snapshot")

    authorization = _called_name_lines(function, "_authorize")
    protected_reads = _called_name_lines(function, "_stored_from_path")

    assert len(authorization) == 2
    assert len(protected_reads) == 1
    assert authorization[0] < protected_reads[0] < authorization[1]


def test_base_grade_item_explanation_does_not_open_protected_projection() -> None:
    tree = _module_tree("grade_item_proficiency_explanation.py")
    base = _function(tree, "explain_grade_item_proficiency")
    expansion = _function(tree, "expand_grade_item_evidence_detail")
    resolver = _function(tree, "_resolve_authorized_evidence_detail")

    forbidden_base_calls = {
        "inspect_evidence_diagnostic",
        "load_authorized_projection_snapshot",
        "_resolve_authorized_evidence_detail",
    }
    observed_base_calls = {
        node.func.id
        for node in ast.walk(base)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert observed_base_calls.isdisjoint(forbidden_base_calls)

    assert _called_name_lines(
        expansion,
        "_resolve_authorized_evidence_detail",
    )
    assert _called_name_lines(resolver, "inspect_evidence_diagnostic")


@pytest.mark.parametrize("module_name", ATTENTION_MODULES)
def test_attention_and_module_operations_do_not_import_raw_evidence_paths(
    module_name: str,
) -> None:
    imports = _imported_modules(_module_tree(module_name))
    forbidden = tuple(
        imported
        for imported in imports
        if any(
            imported == prefix or imported.startswith(f"{prefix}.")
            for prefix in FORBIDDEN_ATTENTION_IMPORT_PREFIXES
        )
    )
    assert forbidden == ()


def test_grouping_export_projects_only_through_core_signal_contract() -> None:
    tree = _module_tree("grouping_signal_export.py")
    imports = set(_imported_modules(tree))

    assert "pds_core.grouping_signals" in imports
    assert "concord" not in imports
    assert "pds_concord" not in imports

    function = _function(tree, "build_grouping_signal_export_candidate")
    direct_write_calls = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id.startswith("write_")
    }
    assert direct_write_calls == set()


def test_export_workflow_revalidates_immediately_before_export() -> None:
    tree = _module_tree("grouping_signal_export_workflow.py")
    function = _function(tree, "export_grouping_signal_to_core")

    initial = _called_name_lines(
        function,
        "resolve_grouping_signal_export_eligibility",
    )
    final = _called_name_lines(
        function,
        "revalidate_grouping_signal_export_eligibility",
    )
    writes = _called_name_lines(function, "write_grouping_signal")

    assert len(initial) == 1
    assert len(final) == 1
    assert len(writes) == 1
    assert initial[0] < final[0] < writes[0]
