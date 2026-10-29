"""#123 Slice 11A: live menu adoption census and static reachability gates.

This is a source-level acceptance inventory, not a student-data or installed-wheel
integration test. It does not evaluate authorization or carry academic truth.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / "docs/architecture/issue123-slice11a-live-adoption.json"
sys.path.insert(0, str(ROOT / "scripts"))

from issue123_navigation_audit import REPORT_SCOPES, ROUTES  # noqa: E402


def _census() -> dict[str, object]:
    return json.loads(CENSUS.read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing menu function: {name}")


def _is_navigation_context_present(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "navigation_context"
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.IsNot)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value is None
    )


def _labels(branch: list[ast.stmt]) -> dict[str, str]:
    for statement in branch:
        if not isinstance(statement, ast.Expr):
            continue
        call = statement.value
        if (
            not isinstance(call, ast.Call)
            or not isinstance(call.func, ast.Name)
            or call.func.id != "write_lines"
        ):
            continue
        options: dict[str, str] = {}
        for arg in call.args[1:]:
            if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                continue
            match = re.fullmatch(r"([1-9][0-9]*)\. (.+)", arg.value)
            if match:
                number, title = match.groups()
                assert number not in options
                options[number] = title
        if options:
            return options
    return {}


def _teacher_mode_choices(
    source: str, menu_function: str
) -> tuple[dict[str, str], dict[str, str]]:
    fn = _function(ast.parse(source), menu_function)
    for node in ast.walk(fn):
        if not isinstance(node, ast.If) or not _is_navigation_context_present(
            node.test
        ):
            continue
        teacher = _labels(node.body)
        legacy = _labels(node.orelse)
        if teacher and legacy:
            return teacher, legacy
    raise AssertionError(f"Teacher and legacy menu branches missing: {menu_function}")


def _choice_condition(test: ast.expr, number: str) -> bool:
    return any(
        isinstance(part, ast.Compare)
        and isinstance(part.left, ast.Name)
        and part.left.id == "choice"
        and len(part.ops) == 1
        and isinstance(part.ops[0], ast.Eq)
        and len(part.comparators) == 1
        and isinstance(part.comparators[0], ast.Constant)
        and part.comparators[0].value == number
        for part in ast.walk(test)
    )


def _handler_in_choice(fn: ast.FunctionDef, number: str, handler: str) -> bool:
    for node in ast.walk(fn):
        if not isinstance(node, ast.If) or not _choice_condition(node.test, number):
            continue
        for stmt in node.body:
            if any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == handler
                for child in ast.walk(stmt)
            ):
                return True
    return False


def test_live_inventory_is_exact_and_covers_all_original_routes() -> None:
    data = _census()
    assert data["schema"] == "pds.meridian.issue123.live_adoption.v1"
    assert data["reviewed_head"] == "cf1709ba3c97b0ad51e298cbee4973ab1557b440"
    menus = data["teacher_menus"]
    crosswalk = data["original_route_crosswalk"]
    assert isinstance(menus, dict) and isinstance(crosswalk, dict)
    assert len(menus) == 8
    actual_routes = {(r.area, r.option) for r in ROUTES}
    mapped_routes = {
        (area, number) for area, rows in crosswalk.items() for number in rows
    }
    assert len(actual_routes) == 49 and actual_routes == mapped_routes
    assert len(REPORT_SCOPES) == 9
    assert sum(len(row["guided"]) for row in menus.values()) == 39
    assert sum(len(row["advanced"]) for row in menus.values()) == 44
    assert data["counts"] == {
        "original_routes": 49,
        "guided_live_routes": 39,
        "advanced_live_routes": 44,
        "teacher_mode_live_routes": 83,
        "guided_report_kinds_preserved": 9,
    }
    for area, row in menus.items():
        guided = row["guided"]
        advanced = row["advanced"]
        assert not set(guided) & set(advanced)
        numbers = sorted(int(n) for n in (*guided, *advanced))
        assert numbers == list(range(1, len(numbers) + 1))
        for original, targets in crosswalk[area].items():
            assert original.isdecimal()
            for target in targets:
                destination, _, option = target.rpartition("/")
                target_area = destination or area
                target_option = option if destination else target
                assert target_option in menus[target_area]["guided"]


def test_each_teacher_menu_shows_exact_guided_and_explicit_advanced_routes() -> None:
    menus = _census()["teacher_menus"]
    for area, row in menus.items():
        source = (ROOT / row["file"]).read_text(encoding="utf-8")
        choices, legacy = _teacher_mode_choices(source, row["function"])
        expected = {
            **{n: title for n, (title, _handler) in row["guided"].items()},
            **{n: f"Advanced: {title}" for n, title in row["advanced"].items()},
        }
        assert choices == expected, f"Teacher menu drift: {area}"
        for old_route in (r for r in ROUTES if r.area == area):
            assert old_route.option in legacy, (area, old_route.option)
        assert len(choices) == len(set(choices))


def test_named_route_handlers_are_reachable_by_their_displayed_option() -> None:
    for area, row in _census()["teacher_menus"].items():
        source = (ROOT / row["file"]).read_text(encoding="utf-8")
        fn = _function(ast.parse(source), row["function"])
        for number, (_title, handler) in row["guided"].items():
            assert _handler_in_choice(fn, number, handler), (area, number, handler)


def test_planning_is_nested_and_the_legacy_interface_remains_optional() -> None:
    proficiency = (ROOT / "meridian/menu_proficiency.py").read_text(encoding="utf-8")
    main = (ROOT / "meridian/menu.py").read_text(encoding="utf-8")
    planning = (ROOT / "meridian/menu_planning_signal.py").read_text(encoding="utf-8")
    assert "run_planning_signal_menu(" in proficiency
    assert "navigation_context=navigation_context" in proficiency
    assert "run_planning_signal_menu(" not in main
    assert '"7. Advanced: Export accepted signal to Core"' in planning
    assert '"7. Export accepted signal to Core"' in planning
    assert '"14. Export accepted Planning Signal to Core by name"' in planning


def test_named_planning_and_explain_controllers_do_not_ask_for_raw_ids() -> None:
    root = ROOT / "meridian"
    modules = sorted(root.glob("menu_teacher_named_planning_*.py")) + sorted(
        root.glob("menu_teacher_named_explain_*.py")
    )
    assert len(modules) >= 15
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "read_choice":
                continue
            if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
                continue
            prompt = node.args[1].value
            if not isinstance(prompt, str):
                continue
            # Teacher attribution is an existing verified first-party identity
            # prompt, not a request to transcribe an academic record identifier.
            if prompt == "Teacher actor ID: ":
                continue
            lower = prompt.casefold()
            assert not any(
                token in lower
                for token in (" id", " ids", "sha256", "cache key", "revision")
            ), (path.name, prompt)


def test_original_technical_prompt_quarantine_and_reports_remain_present() -> None:
    contract = (ROOT / "tests/test_issue110_teacher_interface_contract.py").read_text(
        encoding="utf-8"
    )
    assert "_BASELINE_RAW_PROMPT_COUNT = 188" in contract
    assert (
        "2639c4eeb08692c4a7286eab52156a720496bd7552f28575c72c9cd2dfa5ae55" in contract
    )
    assert (ROOT / "tests/test_report_guided_selection_issue111.py").is_file()
    assert (ROOT / "tests/test_issue123_slice3_navigation_context.py").is_file()


def test_planning_gateway_forwards_verified_context_without_raw_id_prompt(
    monkeypatch: object,
) -> None:
    """Option 10 stays in place and delegates to the named/Advanced submenu."""
    from io import StringIO
    from unittest.mock import MagicMock

    import meridian.menu_proficiency as menu

    context = MagicMock()
    seen: list[dict[str, object]] = []

    def nested(**kwargs: object) -> None:
        seen.append(kwargs)

    monkeypatch.setattr(menu, "run_planning_signal_menu", nested)
    choices = iter(("10", "B"))
    output = StringIO()
    menu.run_proficiency_menu(
        dependencies=MagicMock(),
        action_dependencies=MagicMock(),
        period_action_dependencies=MagicMock(),
        navigation_context=context,
        input_fn=lambda prompt="": next(choices),
        output=output,
        clear_fn=lambda: None,
    )
    assert len(seen) == 1
    assert seen[0]["navigation_context"] is context
    assert "10. Create Planning Signal (named workflows)" in output.getvalue()
    assert "10. Advanced: Create Planning Signal" not in output.getvalue()
    nested_source = (ROOT / "meridian/menu_planning_signal.py").read_text(
        encoding="utf-8"
    )
    assert '"8. Review Planning Signal readiness by policy name"' in nested_source
    assert '"14. Export accepted Planning Signal to Core by name"' in nested_source
    assert '"1. Advanced: Review readiness (exact policy ID)"' in nested_source
    assert '"7. Advanced: Export accepted signal to Core"' in nested_source
