"""#124 Slice A: read-only, reproducible source/controller-boundary census.

This is a *structural* inventory of calls in the existing guided bridge, not
an end-to-end timing measurement or a count of every user keystroke. It reads
Python source only, never imports producers or opens protected evidence.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pds.meridian.issue124.slicea.source_boundary.v1"
PATHS = (
    "meridian/menu_teacher_grade_items.py",
    "meridian/guided_grade_items.py",
    "meridian/grade_items_workflow.py",
    "meridian/teacher_evidence_inbox.py",
    "meridian/teacher_action_guided.py",
    "meridian/teacher_evidence_continuation.py",
)


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    found = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(found) != 1:
        raise ValueError(f"Expected exactly one top-level function: {name}.")
    return found[0]


def _call_name(call: ast.Call) -> str | None:
    value = call.func
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return None


def _calls(function: ast.FunctionDef) -> tuple[str, ...]:
    return tuple(
        name
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        if (name := _call_name(node)) is not None
    )


def _parsed(root: Path, rel: str) -> ast.Module:
    if rel not in PATHS:
        raise ValueError(f"Unapproved inventory source path: {rel}")
    path = root / rel
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Inventory source unavailable: {rel}")
    source = path.read_text(encoding="utf-8")
    return ast.parse(source, filename=rel)


def _requires(calls: tuple[str, ...], *names: str) -> None:
    missing = set(names).difference(calls)
    if missing:
        raise ValueError("Reviewed entry path drifted: " + ", ".join(sorted(missing)))


def audit(root: Path = ROOT) -> dict[str, Any]:
    """Audit the exact legacy flow without invoking or importing domain services."""
    bridge = _parsed(root, PATHS[0])
    create = _calls(_function(bridge, "_create_grade_item"))
    link = _calls(_function(bridge, "_link_work"))
    entry = _calls(_function(bridge, "run_grade_item_bridge"))
    context = _calls(
        _function(_parsed(root, PATHS[1]), "load_guided_grade_item_bridge_context")
    )
    source = _parsed(root, PATHS[3])
    discovery = _function(source, "teacher_evidence_discovery_request")
    inbox = _calls(_function(source, "load_teacher_evidence_inbox"))
    continuation = _calls(
        _function(_parsed(root, PATHS[5]), "resolve_teacher_evidence_continuation")
    )
    actions = _parsed(root, PATHS[4])
    action_names = {
        node.name for node in actions.body if isinstance(node, ast.FunctionDef)
    }
    _requires(
        create, "preview_new_grade_item", "prepare_grade_item_action", "_review_apply"
    )
    _requires(
        link, "preview_membership_link", "prepare_membership_action", "_review_apply"
    )
    _requires(
        entry,
        "_choose_existing_or_new",
        "_create_grade_item",
        "_choose_period",
        "_link_work",
    )
    _requires(
        context,
        "load_current_academic_work_registration",
        "load_current_academic_period_calendar",
    )
    _requires(inbox, "list_publication_diagnostics", "project_teacher_evidence_inbox")
    _requires(continuation, "discover_guided_eligibility_grade_items")
    if not {"prepare_grade_item_action", "prepare_membership_action"} <= action_names:
        raise ValueError("The #122 single-action domain ports changed.")
    published_only = any(
        isinstance(node, ast.keyword)
        and node.arg == "publication_kind"
        and isinstance(node.value, ast.Constant)
        and node.value.value == "academic_result_set"
        for node in ast.walk(discovery)
    )
    if not published_only:
        raise ValueError("Current evidence inbox publication kind drifted.")
    create_confirmations = create.count("_review_apply")
    link_confirmations = link.count("_review_apply")
    if (create_confirmations, link_confirmations) != (1, 1):
        raise ValueError("Baseline confirmation topology changed.")
    grade_review = _calls(
        _function(_parsed(root, PATHS[2]), "project_grade_items_review")
    )
    _requires(grade_review, "list_grade_item_ids", "_project_grade_item")
    return {
        "schema": SCHEMA,
        "measurement_kind": "static_ast_callsite_census_not_runtime_interactions",
        "legacy_new_item_path": {
            "separate_review_apply_call_sites": (
                create_confirmations + link_confirmations
            ),
            "grade_item_save_select_confirmations": create_confirmations,
            "membership_save_select_confirmations": link_confirmations,
            "direct_entry_controllers": ["_create_grade_item", "_link_work"],
            "technical_id_prompts_measured": False,
            "runtime_input_calls_measured": False,
            "duration_measured": False,
        },
        "read_boundaries": {
            "legacy_bridge_current_registration": True,
            "legacy_bridge_current_calendar": True,
            "grade_item_review_canonical_selection_projection": True,
            "inbox_discovery_current_academic_result_set_only": published_only,
            "inbox_reads_protected_payload_during_discovery": False,
            "registration_only_discovery_implemented_by_slice_a": False,
        },
        "existing_separate_domain_action_ports": sorted(
            ("prepare_grade_item_action", "prepare_membership_action")
        ),
        "future_requirements_not_yet_implemented": [
            "catalog_backed_registered_work_discovery",
            "typed_grade_item_work_period_readiness",
            "one_reviewed_composite_setup_confirmation",
            "exact_composite_action_recovery_and_idempotency",
            "installed_producer_and_classroom_acceptance",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(audit(args.repo.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
