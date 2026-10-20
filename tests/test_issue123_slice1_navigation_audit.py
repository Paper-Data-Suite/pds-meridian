"""Issue #123 Slice 1: baseline is complete, reproducible and read-only."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

from issue123_navigation_audit import (  # noqa: E402
    BASE_COMMIT,
    CONTROLLERS,
    REPORT_SCOPES,
    ROUTES,
    SNAPSHOT_PATH,
    SOURCE_BLOBS,
    git_blob_sha,
    make_inventory,
    scan_prompts,
    snapshot_bytes,
    verify_route_inventory,
    verify_sources,
)


def test_slice1_is_pinned_to_reviewed_branch_and_source_blobs() -> None:
    assert BASE_COMMIT == "0e9afa0eeb879de1741c57bff3cd9b94f79f772f"
    assert len(SOURCE_BLOBS) == 17
    verify_sources(_REPO)
    verify_route_inventory(_REPO)


def test_slice1_exact_operation_inventory_covers_all_eight_menus() -> None:
    assert len(ROUTES) == 49
    assert Counter(route.area for route in ROUTES) == {
        "grade_items": 6,
        "proficiency": 10,
        "grades": 2,
        "overrides": 4,
        "snapshots": 6,
        "export": 6,
        "explain": 8,
        "planning_signal": 7,
    }
    assert set(CONTROLLERS) == {route.area for route in ROUTES}
    assert len({(route.area, route.option) for route in ROUTES}) == 49
    assert all(
        route.disposition in {"routine", "advanced", "advanced-json"}
        for route in ROUTES
    )
    assert all(route.slice in {4, 5, 6, 7} for route in ROUTES)
    assert [
        route.handler
        for route in ROUTES
        if (route.area, route.option) == ("proficiency", "10")
    ] == ["run_planning_signal_menu"]
    assert len(REPORT_SCOPES) == 9


def test_slice1_machine_inventory_is_frozen_and_byte_reproducible() -> None:
    expected = snapshot_bytes(_REPO)
    assert (_REPO / SNAPSHOT_PATH).read_bytes() == expected
    document = json.loads(expected)
    assert document["route_count"] == 49
    assert document["main_menu_task_count"] == 9
    assert document["baseline_commit"] == BASE_COMMIT
    assert len(document["guided_report_kinds"]) == 9
    scanned = document["prompt_scan"]
    assert scanned["all_scanned_sites"] == len(scanned["sites"])
    assert scanned["all_literal_raw_identifier_sites"] > 0
    assert all("line" in site and "function" in site for site in scanned["sites"])
    assert document["separate_issue110_legacy_quarantine"]["expected_count"] == 188


def test_scan_is_static_and_handles_literal_dynamic_and_nested_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import issue123_navigation_audit as audit

    menu = tmp_path / "meridian" / "menu_probe.py"
    menu.parent.mkdir(parents=True)
    menu.write_text(
        "def run_probe(input_fn):\n"
        '    read_choice(input_fn, "Class ID: ")\n'
        '    input_fn("Which class?")\n'
        "    def inner():\n"
        '        read_choice(input_fn, f"{name} ID: ")\n'
        "    return inner\n",
        encoding="utf-8",
    )
    report = tmp_path / "meridian" / "report_guided_selection.py"
    report.write_text("def noop():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(audit, "SOURCE_BLOBS", {"meridian/menu_probe.py": "a"})
    sites = scan_prompts(tmp_path)
    assert len(sites) == 3
    assert sum(bool(site["raw_id_like"]) for site in sites) == 1
    assert sum(bool(site["dynamic_prompt"]) for site in sites) == 1
    assert {site["function"] for site in sites} == {"run_probe", "run_probe.inner"}
    assert all(site["path"] == "meridian/menu_probe.py" for site in sites)


def test_git_blob_hash_uses_exact_git_object_format() -> None:
    assert git_blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_slice1_compatibility_contract_keeps_technical_inputs_quarantined() -> None:
    # #110's own test is also run by the slice runner; do not replace its
    # independent 188-site count/digest with this narrower #123 scanner.
    contract = (_REPO / "tests/test_issue110_teacher_interface_contract.py").read_text(
        encoding="utf-8"
    )
    assert (
        '"2639c4eeb08692c4a7286eab52156a720496bd7552f28575c72c9cd2dfa5ae55"' in contract
    )
    assert "_BASELINE_RAW_PROMPT_COUNT = 188" in contract
    inventory = make_inventory(_REPO)
    assert inventory["separate_issue110_legacy_quarantine"]["expected_count"] == 188
