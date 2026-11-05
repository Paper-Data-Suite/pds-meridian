"""#124 Slice A: executable assertions on audited source boundaries only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.issue124_slicea_baseline_audit import PATHS, SCHEMA, _parsed, audit

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs/architecture/issue124-slicea-baseline.json"
NOTES = ROOT / "docs/architecture/issue124-slicea-source-contract.md"


def test_baseline_matches_frozen_controller_topology() -> None:
    result = audit(ROOT)
    baseline = json.loads(INVENTORY.read_text(encoding="utf-8"))
    assert result["schema"] == baseline["schema"] == SCHEMA
    assert result["legacy_new_item_path"] == baseline["legacy_new_item_path"]
    assert result["read_boundaries"] == baseline["read_boundaries"]
    assert (
        result["existing_separate_domain_action_ports"]
        == baseline["existing_separate_domain_action_ports"]
    )
    assert (
        result["future_requirements_not_yet_implemented"]
        == baseline["future_requirements_not_yet_implemented"]
    )
    assert result["legacy_new_item_path"]["separate_review_apply_call_sites"] == 2
    assert not result["legacy_new_item_path"]["runtime_input_calls_measured"]


def test_source_only_inventory_refuses_unapproved_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unapproved"):
        _parsed(tmp_path, "private/grades.csv")
    with pytest.raises(ValueError, match="unavailable"):
        _parsed(tmp_path, PATHS[0])


def test_inventory_documents_exact_scope_and_next_slices() -> None:
    raw = INVENTORY.read_text(encoding="utf-8")
    text = NOTES.read_text(encoding="utf-8")
    values = json.loads(raw)
    assert values["baseline_head"] == "c69e4e5ca9603ffe4b9295a6ac9f6e4fbe924a29"
    for tag in ("124-B", "124-C", "124-D", "124-E", "124-F", "124-G", "124-H"):
        assert tag in text
    for keyword in (
        "Core",
        "ScoreForm",
        "Quillan",
        "Concord",
        "one confirmation",
        "no protected",
    ):
        assert keyword in text
    assert "not a paired runtime benchmark" in text
    assert values["measurement_kind"] == (
        "static_ast_callsite_census_not_runtime_interactions"
    )
    assert values["current_branch"] == (
        "124-automatic-assessment-discovery-grade-item-setup"
    )
