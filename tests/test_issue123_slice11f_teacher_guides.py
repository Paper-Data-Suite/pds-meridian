"""#123 Slice 11F: teacher-facing docs reflect actual route census and limits."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEACHER = ROOT / "docs/teacher-navigation-guide-issue123.md"
ADVANCED = ROOT / "docs/architecture/teacher-advanced-record-operations-issue123.md"
LEDGER = ROOT / "docs/architecture/issue123-slice11f-acceptance-ledger.md"
ROUTES = ROOT / "docs/architecture/issue123-slice11a-live-adoption.json"
MEASUREMENTS = ROOT / "docs/architecture/issue123-slice11b-interaction-contract.json"


def test_teacher_guide_covers_actual_main_menu_and_shortcuts() -> None:
    content = TEACHER.read_text(encoding="utf-8")
    for name in (
        "Review New Evidence",
        "Manage Grade Items",
        "Review Proficiency",
        "Preview Grades",
        "Overrides",
        "Snapshots",
        "Export",
        "Explain",
        "Reports",
        "Teacher Settings",
        "Planning Signal",
    ):
        if name == "Teacher Settings":
            assert "teacher settings" in content.lower()
        else:
            assert name in content
    for shortcut in ("`S`", "`C`", "`N`", "`P`", "`R`", "`T`", "`B`", "`M`", "`Q`"):
        assert shortcut in content
    assert "does not" in content.lower()
    assert "SIS" in content and "LMS" in content


def test_advanced_table_covers_all_eight_inventory_menus() -> None:
    census = json.loads(ROUTES.read_text(encoding="utf-8"))
    guide = ADVANCED.read_text(encoding="utf-8")
    assert set(census["teacher_menus"]) == {
        "grade_items",
        "proficiency",
        "grades",
        "overrides",
        "snapshots",
        "export",
        "explain",
        "planning_signal",
    }
    assert sum(len(menu["advanced"]) for menu in census["teacher_menus"].values()) == 44
    assert sum(len(menu["guided"]) for menu in census["teacher_menus"].values()) == 39
    for label in (
        "Grade Items",
        "Proficiency",
        "Grades",
        "Overrides",
        "Snapshots",
        "Export",
        "Explain",
        "Planning Signal (nested under Proficiency 10)",
    ):
        assert f"| {label} |" in guide
    assert "188" in guide and "not" in guide.lower()


def test_planning_signal_entry_is_not_misrepresented() -> None:
    guide = TEACHER.read_text(encoding="utf-8")
    assert "10. Create Planning Signal (named workflows)" in guide
    assert "choices 8–14" in guide
    assert "not a separate main-menu item" in guide


def test_acceptance_ledger_does_not_invent_legacy_metrics_or_ci() -> None:
    measurements = json.loads(MEASUREMENTS.read_text(encoding="utf-8"))
    ledger = LEDGER.read_text(encoding="utf-8")
    assert measurements["expected_input_calls"] == 25
    assert measurements["expected_class_chooser_appearances"] == 1
    assert measurements["expected_catalog_reads_for_initial_class_selection"] == 3
    assert measurements["latency_ms"] is None
    assert "1,752 passed, 8 skipped" in ledger
    assert "latency_ms" in ledger and "remains null" in ledger
    assert "No numeric improvement percentage" in ledger
    assert "No PR/CI pass" in ledger
    assert "Richer end-to-end installed-domain journey" in ledger
    assert "Measured before/after interaction baseline" in ledger


def test_docs_do_not_claim_release_or_direct_gradebook_writes() -> None:
    teacher = TEACHER.read_text(encoding="utf-8")
    advanced = ADVANCED.read_text(encoding="utf-8")
    ledger = LEDGER.read_text(encoding="utf-8")
    assert "not a published release" in teacher
    assert "not a substitute" in advanced
    assert "no release or merge is claimed" in ledger
    assert "does not" in teacher and "SIS" in teacher
