"""#123 Slice 11L: source-level proof that final claims match acceptance evidence."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "architecture"
LEDGER = DOCS / "issue123-slice11f-acceptance-ledger.md"
DECISION = DOCS / "issue123-slice11l-final-reconciliation.md"
CENSUS = DOCS / "issue123-slice11a-live-adoption.json"
BENCHMARK = DOCS / "issue123-slice11h-comparative-interaction.md"
JOINED = DOCS / "issue123-slice11k-joined-installed-acceptance.md"


def test_final_route_count_matches_frozen_crosswalk_and_discoverability() -> None:
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    counts = census["counts"]
    assert counts["original_routes"] == 49
    assert counts["guided_live_routes"] == 39
    assert counts["advanced_live_routes"] == 44
    assert counts["teacher_mode_live_routes"] == 83
    assert counts["guided_report_kinds_preserved"] == 9
    rows = census["teacher_menus"]
    assert sum(len(row["guided"]) for row in rows.values()) == 39
    assert sum(len(row["advanced"]) for row in rows.values()) == 44
    assert rows["proficiency"]["guided"]["10"] == [
        "Create Planning Signal (named workflows)",
        "run_planning_signal_menu",
    ]
    assert sorted(map(int, rows["planning_signal"]["guided"])) == list(range(8, 15))
    assert sorted(map(int, rows["planning_signal"]["advanced"])) == list(range(1, 8))
    for path in (LEDGER, DECISION):
        text = path.read_text(encoding="utf-8")
        for statement in ("49 historical", "39 named", "44 Advanced", "nine"):
            assert statement in text, (path, statement)


def test_paired_benchmark_is_not_misrepresented_as_11b_or_real_latency() -> None:
    legacy = json.loads(
        (DOCS / "issue123-slice11b-interaction-contract.json").read_text(
            encoding="utf-8"
        )
    )
    assert legacy["expected_input_calls"] == 25
    assert legacy["latency_ms"] is None
    bench = BENCHMARK.read_text(encoding="utf-8")
    assert "| Input calls, including pauses/back | 16 | 13 |" in bench
    assert "| Technical canonical ID prompts | 12 | 0 |" in bench
    assert "| Repeated `Class ID` prompts beyond first | 3 | 0 |" in bench
    for path in (LEDGER, DECISION):
        text = path.read_text(encoding="utf-8")
        for marker in ("16", "13", "12", "25", "latency_ms"):
            assert marker in text, (path, marker)
        assert (
            "No numeric improvement percentage" in text
            or "no hardware-independent latency result" in text
        )


def test_joined_installed_journey_claims_are_bounded_by_real_source() -> None:
    program = (ROOT / "scripts" / "smoke_program_issue123_joined_journey.py").read_text(
        encoding="utf-8"
    )
    for marker in (
        "run_named_grade_item_review",
        "run_named_grade_item_proficiency",
        "run_named_current_grade_review",
        "run_named_grade_item_proficiency_explanation",
        "run_named_planning_readiness",
        "assert base._tree(root) == selected_before",
        "nav.choose_class(base.OTHER)",
    ):
        assert marker in program
    assert "cannot be verified or is not configured" in program
    joined = JOINED.read_text(encoding="utf-8")
    assert "read-only" in joined
    assert "does **not** prove" in joined
    for path in (LEDGER, DECISION):
        text = path.read_text(encoding="utf-8")
        assert "not configured" in text
        assert "ReportingSnapshot" in text
        assert "authorization" in text
        assert "does not" in text.lower() or "not demonstrated" in text


def test_ci_and_owner_decision_are_historical_not_self_approval() -> None:
    ledger = LEDGER.read_text(encoding="utf-8")
    decision = DECISION.read_text(encoding="utf-8")
    for text in (ledger, decision):
        for ref in ("#137", "#138", "#139", "8/8", "11L"):
            assert ref in text
        assert "draft PR #142" in text
        assert "no release or merge is claimed" in text
        assert "owner" in text.lower()
        assert "not" in text.lower()
    assert "11L CI pending" in ledger
    assert "do not merge" in ledger.lower()
