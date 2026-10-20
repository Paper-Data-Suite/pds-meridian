"""Issue #123 Slice 1: read-only, deterministic teacher menu navigation baseline.

This program examines *source*, not teacher workspaces. It must never import a
producer, open student data, change academic state, or prompt for credentials.

Usage from repository root:
    python scripts/issue123_navigation_audit.py --write-snapshot
    python scripts/issue123_navigation_audit.py --check
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal, cast

BASE_COMMIT: Final = "0e9afa0eeb879de1741c57bff3cd9b94f79f772f"
SNAPSHOT_PATH: Final = Path("docs/architecture/issue123-slice1-inventory.json")

# Git blob object IDs observed on the exact issue #123 branch at BASE_COMMIT.
# Changing these in later slices is an intentional, reviewed baseline update.
SOURCE_BLOBS: Final[dict[str, str]] = {
    "meridian/menu.py": "f7e7a868fe02608c2c1f3230d3af9efc5c77922b",
    "meridian/menu_grade_items.py": "e3d35ba10afde2ed6ee04a2a9c9eb937f6ca60a8",
    "meridian/menu_proficiency.py": "28199e1ff30c3aa3c092f452a3385199db54cb05",
    "meridian/menu_grades.py": "f418424434d1ec3805f32f144108cbb19817c4af",
    "meridian/menu_overrides.py": "fb7a386e57f5e5ed2c804f66d08c0c2a5ab63edb",
    "meridian/menu_snapshots.py": "30bb5085843db26a410815e70f88d9e5216a43ad",
    "meridian/menu_export.py": "f452c2301a05d3f99bb9738b969863dc75c08e32",
    "meridian/menu_explain.py": "ee7b28f772f14752cf10ccd295937708afbd6b36",
    "meridian/menu_planning_signal.py": "3db5af865984a0a57e02ce497c4c3f36e02b59d9",
    "meridian/menu_reports.py": "54873620cba04f8dce3a7dc1372bb65e61618844",
    "meridian/menu_teacher_evidence.py": "ca748f6fad64a27818612b4be4e10764b990ca19",
    "meridian/menu_teacher_grade_items.py": "36e732da0d6bb6d5eb594e0057aade5df760fd91",
    "meridian/menu_teacher_proficiency.py": "fb02a8f47d72cda29c460b2fa2c63a29eb95544e",
    "meridian/report_guided_selection.py": "5e01c2f2731578860e16e254e207a1998c48abc1",
    "meridian/report_live_catalog.py": "b8dd2fb202a61fb5373b4a55c92c424753b74ce0",
    "meridian/teacher_session.py": "531d93883de44b0ed7bf5cb7aad22040ec6dcb64",
    "tests/test_issue110_teacher_interface_contract.py": (
        "d521bf229f0f47ba0d42e62d9657aa0fe9b94710"
    ),
}

# Slice 3 threads dependencies without changing legacy prompts.
# The first 49-operation audit remains pinned to its historic Git tree.
REVIEWED_COMPOSITION_PATHS: Final[frozenset[str]] = frozenset(
    {
        "meridian/menu.py",
        "meridian/menu_grade_items.py",
        "meridian/menu_proficiency.py",
        "meridian/menu_grades.py",
        "meridian/menu_overrides.py",
        "meridian/menu_snapshots.py",
        "meridian/menu_export.py",
        "meridian/menu_explain.py",
        "meridian/menu_planning_signal.py",
        "meridian/menu_reports.py",
    }
)

# Category is the TARGET DISPOSITION of the existing route, not a claim it is
# guided today. "advanced" means its current manual implementation must be
# explicitly segregated; the issue may still require a new routine equivalent.
Disposition = Literal["routine", "advanced", "advanced-json"]


@dataclass(frozen=True, slots=True)
class Route:
    area: str
    option: str
    title: str
    handler: str
    disposition: Disposition
    slice: int


# Exhaustive human-reviewed option inventory from the eight original menus.
# Keep original numbering stable until subsequent slices deliberately update it.
ROUTES: Final[tuple[Route, ...]] = (
    Route(
        "grade_items", "1", "Review Grade Items", "_review_grade_items", "routine", 4
    ),
    Route(
        "grade_items",
        "2",
        "Review one Grade Item and work relationships",
        "_review_one_grade_item",
        "routine",
        4,
    ),
    Route(
        "grade_items",
        "3",
        "Author Grade Item revision",
        "_author_grade_item",
        "advanced",
        4,
    ),
    Route(
        "grade_items",
        "4",
        "Select Grade Item revision",
        "_select_grade_item",
        "advanced",
        4,
    ),
    Route(
        "grade_items",
        "5",
        "Author work membership revision",
        "_author_membership",
        "advanced",
        4,
    ),
    Route(
        "grade_items",
        "6",
        "Select work membership revision",
        "_select_membership",
        "advanced",
        4,
    ),
    Route(
        "proficiency",
        "1",
        "Review current Grade Item proficiency",
        "_review_grade_item",
        "routine",
        4,
    ),
    Route(
        "proficiency",
        "2",
        "Review current Academic Period proficiency",
        "_review_academic_period",
        "routine",
        4,
    ),
    Route(
        "proficiency",
        "3",
        "Review planning-signal readiness",
        "_review_planning",
        "routine",
        4,
    ),
    Route(
        "proficiency",
        "4",
        "Preview Grade Item proficiency calculation",
        "_preview_grade_item_calculation",
        "advanced",
        4,
    ),
    Route(
        "proficiency",
        "5",
        "Write Grade Item proficiency result",
        "_write_grade_item_result",
        "advanced",
        4,
    ),
    Route(
        "proficiency",
        "6",
        "Select Grade Item proficiency result",
        "_select_grade_item_result",
        "advanced",
        4,
    ),
    Route(
        "proficiency",
        "7",
        "Preview Academic Period proficiency calculation",
        "_preview_academic_period_calculation",
        "advanced",
        4,
    ),
    Route(
        "proficiency",
        "8",
        "Write Academic Period proficiency result",
        "_write_academic_period_result",
        "advanced",
        4,
    ),
    Route(
        "proficiency",
        "9",
        "Select Academic Period proficiency result",
        "_select_academic_period_result",
        "advanced",
        4,
    ),
    Route(
        "proficiency",
        "10",
        "Create Planning Signal (nested submenu)",
        "run_planning_signal_menu",
        "routine",
        7,
    ),
    Route("grades", "1", "Preview one current Grade", "_show_current", "routine", 5),
    Route(
        "grades", "2", "Preview a bounded Grade report", "_show_report", "routine", 5
    ),
    Route("overrides", "1", "Review current override", "_review_current", "routine", 5),
    Route(
        "overrides",
        "2",
        "Author a new override revision",
        "_author_override",
        "routine",
        5,
    ),
    Route(
        "overrides",
        "3",
        "Select the latest authored override",
        "_select_latest",
        "routine",
        5,
    ),
    Route(
        "overrides",
        "4",
        "Withdraw the current override",
        "_withdraw_override",
        "routine",
        5,
    ),
    Route("snapshots", "1", "List frozen ReportingSnapshots", "_list", "routine", 6),
    Route("snapshots", "2", "Inspect a ReportingSnapshot", "_inspect", "routine", 6),
    Route(
        "snapshots",
        "3",
        "Show current reporting-use selection",
        "_show_current",
        "routine",
        6,
    ),
    Route(
        "snapshots",
        "4",
        "Select an existing ReportingSnapshot",
        "_select",
        "routine",
        6,
    ),
    Route(
        "snapshots",
        "5",
        "Author a Reporting Definition revision",
        "_author_definition",
        "advanced",
        6,
    ),
    Route(
        "snapshots",
        "6",
        "Freeze a ReportingSnapshot",
        "_freeze_snapshot",
        "advanced-json",
        6,
    ),
    Route("export", "1", "List Export Profiles", "_profiles", "routine", 6),
    Route(
        "export",
        "2",
        "Inspect current Export Profile",
        "_inspect_profile",
        "routine",
        6,
    ),
    Route(
        "export",
        "3",
        "Author Export Profile revision",
        "_author_profile",
        "advanced",
        6,
    ),
    Route(
        "export",
        "4",
        "Select latest Export Profile revision",
        "_select_profile_latest",
        "advanced",
        6,
    ),
    Route(
        "export",
        "5",
        "Preview and export a ReportingSnapshot",
        "_prepare_export",
        "routine",
        6,
    ),
    Route("export", "6", "Review ExportReceipts", "_receipts", "routine", 6),
    Route("explain", "1", "Current Grade", "_run_current", "routine", 6),
    Route(
        "explain",
        "2",
        "Prior / current Grade comparison",
        "_run_comparison",
        "routine",
        6,
    ),
    Route("explain", "3", "Grade Item proficiency", "_run_grade_item", "routine", 6),
    Route(
        "explain",
        "4",
        "Academic Period proficiency",
        "_run_academic_period",
        "routine",
        6,
    ),
    Route("explain", "5", "Planning derivation", "_run_two_id", "routine", 6),
    Route("explain", "6", "Planning preview / review", "_run_two_id", "routine", 6),
    Route("explain", "7", "Planning export", "_run_two_id", "routine", 6),
    Route("explain", "8", "ExportReceipt provenance", "_run_two_id", "routine", 6),
    Route(
        "planning_signal", "1", "Review readiness", "_review_readiness", "routine", 7
    ),
    Route(
        "planning_signal",
        "2",
        "Write exact derivation",
        "_write_derivation",
        "advanced",
        7,
    ),
    Route(
        "planning_signal",
        "3",
        "Write planning preview",
        "_write_preview",
        "advanced",
        7,
    ),
    Route(
        "planning_signal",
        "4",
        "Review preview and diagnostics",
        "_review_diagnostics",
        "routine",
        7,
    ),
    Route(
        "planning_signal", "5", "Write teacher review", "_write_review", "routine", 7
    ),
    Route(
        "planning_signal", "6", "Select teacher review", "_select_review", "routine", 7
    ),
    Route(
        "planning_signal",
        "7",
        "Export accepted signal to Core",
        "_export_signal",
        "routine",
        7,
    ),
)

CONTROLLERS: Final[dict[str, str]] = {
    "grade_items": "meridian/menu_grade_items.py",
    "proficiency": "meridian/menu_proficiency.py",
    "grades": "meridian/menu_grades.py",
    "overrides": "meridian/menu_overrides.py",
    "snapshots": "meridian/menu_snapshots.py",
    "export": "meridian/menu_export.py",
    "explain": "meridian/menu_explain.py",
    "planning_signal": "meridian/menu_planning_signal.py",
}

# Reports are already guided and must not be regressed (#111).
REPORT_SCOPES: Final[tuple[str, ...]] = (
    "sis_gradebook_reconciliation",
    "student_current_grade_justification",
    "class_standards_profile",
    "student_proficiency_growth",
    "evidence_coverage",
    "grade_checkpoint_comparison",
    "marking_period_readiness",
    "assessment_impact",
    "benchmark_analysis_instructional_response",
)

RAW_MARKERS: Final[tuple[str, ...]] = (
    " id",
    " ids",
    "cache key",
    "sha256",
    "revision",
    "version",
)


def git_blob_sha(raw: bytes) -> str:
    """Compute Git's content-addressed blob SHA-1, without invoking Git."""
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()  # noqa: S324 - Git format


def _base_source(root: Path, rel: str) -> bytes:
    """Read pinned Git content without trusting a mutable working-tree source."""
    try:
        result = subprocess.run(
            ["git", "show", f"{BASE_COMMIT}:{rel}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"Cannot read reviewed baseline: {rel}") from error
    content = result.stdout
    expected = SOURCE_BLOBS[rel]
    if git_blob_sha(content) != expected:
        raise ValueError(f"Historic source blob is inconsistent: {rel}")
    return content


def _source_prompt_keys(rel: str, raw: bytes) -> Counter[tuple[str, str, str | None]]:
    """Compare exact prompt sites ignoring line shifts from optional injection."""
    visitor = _PromptVisitor(rel)
    visitor.visit(ast.parse(raw.decode("utf-8"), filename=rel))
    return Counter(
        (
            str(item["function"]),
            str(item["callee"]),
            item["prompt"] if isinstance(item["prompt"], str) else None,
        )
        for item in visitor.prompts
    )


def verify_sources(root: Path) -> None:
    """Preserve the historical baseline and quarantine unreviewed drift."""
    mismatches: list[str] = []
    for rel, expected in sorted(SOURCE_BLOBS.items()):
        original = _base_source(root, rel)
        current_path = root / rel
        if not current_path.is_file():
            mismatches.append(f"missing: {rel}")
            continue
        current = current_path.read_bytes()
        if git_blob_sha(original) != expected:
            mismatches.append(f"historical source changed: {rel}")
        elif current != original and rel not in REVIEWED_COMPOSITION_PATHS:
            mismatches.append(f"unreviewed live source drift: {rel}")
        elif current != original and rel.startswith("meridian/menu"):
            if _source_prompt_keys(rel, current) != _source_prompt_keys(rel, original):
                mismatches.append(f"prompt change needs inventory review: {rel}")
    if mismatches:
        raise ValueError(
            "Issue #123 source review baseline does not match:\n"
            + "\n".join(mismatches)
        )


def _prompt_literal(call: ast.Call) -> str | None:
    arg_index = (
        1 if isinstance(call.func, ast.Name) and call.func.id == "read_choice" else 0
    )
    if len(call.args) <= arg_index:
        return None
    arg = call.args[arg_index]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


class _PromptVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.function = "<module>"
        self.prompts: list[dict[str, object]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        before = self.function
        self.function = node.name if before == "<module>" else before + "." + node.name
        self.generic_visit(node)
        self.function = before

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        before = self.function
        self.function = node.name if before == "<module>" else before + "." + node.name
        self.generic_visit(node)
        self.function = before

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in (
            "read_choice",
            "input_fn",
        ):
            prompt = _prompt_literal(node)
            lowered = "" if prompt is None else prompt.casefold()
            self.prompts.append(
                {
                    "path": self.path,
                    "function": self.function,
                    "line": node.lineno,
                    "column": node.col_offset,
                    "callee": node.func.id,
                    "prompt": prompt,
                    "dynamic_prompt": prompt is None,
                    "raw_id_like": any(x in lowered for x in RAW_MARKERS),
                }
            )
        self.generic_visit(node)


def scan_prompts(root: Path) -> list[dict[str, object]]:
    paths = sorted(p for p in SOURCE_BLOBS if p.startswith("meridian/menu"))
    paths.append("meridian/report_guided_selection.py")
    prompts: list[dict[str, object]] = []
    for rel in paths:
        visitor = _PromptVisitor(rel)
        visitor.visit(ast.parse((root / rel).read_text(encoding="utf-8"), filename=rel))
        prompts.extend(visitor.prompts)
    return sorted(
        prompts,
        key=lambda item: (
            str(item["path"]),
            cast(int, item["line"]),
            cast(int, item["column"]),
        ),
    )


def verify_route_inventory(root: Path) -> None:
    """Require every inventoried handler and label to exist in the reviewed source.

    The source-blob lock above additionally ensures option dispatch did not drift
    while this static inventory was assembled. Future slices must replace the lock
    with more granular behavioral gates before intentionally changing those files.
    """
    observed = {(route.area, route.option) for route in ROUTES}
    if len(observed) != len(ROUTES):
        raise ValueError("Duplicate issue #123 route keys")
    if set(CONTROLLERS) != {route.area for route in ROUTES}:
        raise ValueError("Issue #123 controller coverage drift")
    for area, rel in CONTROLLERS.items():
        source = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        definitions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for route in (x for x in ROUTES if x.area == area):
            if route.handler not in definitions and not (
                area == "proficiency" and route.handler == "run_planning_signal_menu"
            ):
                raise ValueError(f"Missing handler: {rel}:{route.handler}")
            if route.title not in source and not (
                area == "proficiency" and route.option == "10"
            ):
                raise ValueError(f"Missing menu title: {rel}:{route.title}")
    report_text = (root / "meridian/report_guided_selection.py").read_text(
        encoding="utf-8"
    )
    if any(f'"{name}"' not in report_text for name in REPORT_SCOPES):
        raise ValueError("Report 1-9 guided selection inventory changed")
    main_text = (root / "meridian/menu.py").read_text(encoding="utf-8")
    if 'TeacherMenuTask("reports", 9, "Reports")' not in main_text:
        raise ValueError("Nine-task teacher menu changed")
    proficiency = (root / CONTROLLERS["proficiency"]).read_text(encoding="utf-8")
    if (
        'if choice == "10":' not in proficiency
        or "run_planning_signal_menu(" not in proficiency
    ):
        raise ValueError("Planning Signal nested route changed")


def make_inventory(root: Path) -> dict[str, object]:
    verify_sources(root)
    verify_route_inventory(root)
    prompts: list[dict[str, object]] = []
    source_paths = sorted(
        path for path in SOURCE_BLOBS if path.startswith("meridian/menu")
    ) + ["meridian/report_guided_selection.py"]
    for rel in source_paths:
        visitor = _PromptVisitor(rel)
        visitor.visit(ast.parse(_base_source(root, rel).decode("utf-8"), filename=rel))
        prompts.extend(visitor.prompts)
    prompts.sort(
        key=lambda item: (
            str(item["path"]),
            cast(int, item["line"]),
            cast(int, item["column"]),
        )
    )
    per_menu = Counter(str(item["path"]) for item in prompts)
    raw = Counter(str(item["path"]) for item in prompts if item["raw_id_like"])
    dynamic = Counter(str(item["path"]) for item in prompts if item["dynamic_prompt"])
    areas: dict[str, dict[str, int]] = {}
    for area, path in CONTROLLERS.items():
        areas[area] = {
            "operations": sum(route.area == area for route in ROUTES),
            "prompt_call_sites": per_menu[path],
            "literal_raw_identifier_sites": raw[path],
            "dynamic_prompt_sites": dynamic[path],
        }
    return {
        "schema": "pds.meridian.issue123.navigation_audit.v1",
        "baseline_commit": BASE_COMMIT,
        "source_git_blob_shas": dict(sorted(SOURCE_BLOBS.items())),
        "route_count": len(ROUTES),
        "routes": [asdict(route) for route in ROUTES],
        "guided_report_kinds": list(REPORT_SCOPES),
        "main_menu_task_count": 9,
        "planning_signal_entry": "Review Proficiency > 10. Create Planning Signal",
        "prompt_scan": {
            "rules": (
                "AST Call nodes of read_choice or input_fn; "
                "includes dynamic prompts and branch alternatives; "
                "excludes runtime repetition"
            ),
            "per_legacy_controller": areas,
            "all_scanned_sites": len(prompts),
            "all_literal_raw_identifier_sites": sum(raw.values()),
            "all_dynamic_prompt_sites": sum(dynamic.values()),
            "sites": prompts,
        },
        "separate_issue110_legacy_quarantine": {
            "expected_count": 188,
            "expected_sha256": (
                "2639c4eeb08692c4a7286eab52156a720496bd7552f28575c72c9cd2dfa5ae55"
            ),
            "scope": (
                "all meridian/menu*.py, with two exact issue121 "
                "Advanced identity exemptions"
            ),
        },
        "constraints": [
            (
                "No academic writes, report execution, authorization, "
                "producer reads, or live workspace scans in Slice 1"
            ),
            "AST prompt counts are static sites, not measured live keyboard presses",
            "Do not treat menu labels or session preferences as canonical authority",
            "Existing Advanced candidates are not yet hidden or migrated by Slice 1",
        ],
    }


def snapshot_bytes(root: Path) -> bytes:
    return (
        json.dumps(make_inventory(root), indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write-snapshot", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        expected = snapshot_bytes(root)
        destination = root / SNAPSHOT_PATH
        if args.write_snapshot:
            if destination.exists():
                raise ValueError(
                    "Snapshot already exists; never overwrite a frozen inventory"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(expected)
            print(f"Wrote {destination.relative_to(root)} ({len(expected)} bytes)")
        else:
            if not destination.is_file() or destination.read_bytes() != expected:
                raise ValueError(
                    "Issue #123 inventory differs from frozen reviewed sources"
                )
            print("Issue #123 Slice 1 inventory verified: 49 routes, 9 guided reports")
    except (OSError, SyntaxError, ValueError) as error:
        parser.exit(1, f"Issue #123 audit blocked: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
