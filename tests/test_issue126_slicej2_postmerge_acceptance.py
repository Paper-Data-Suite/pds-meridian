"""J2: postmerge evidence reconciliation, never a release approval."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/development/issue126-slicej2-a1-a18-ledger.json"
PLAN = ROOT / "docs/development/issue126-slicej2-postmerge-release-plan.md"
J1 = ROOT / "docs/development/issue126-slicej1-a1-a18-ledger.json"


def _data() -> dict[str, object]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_j2_all_eighteen_gates_and_historical_j1_preserved() -> None:
    data = _data()
    assert data["issue"] == 126 and data["schema_version"] == 2
    rows = data["acceptance"]
    assert [row["id"] for row in rows] == [f"A{i}" for i in range(1, 19)]
    assert len({row["gate"] for row in rows}) == 18
    for row in rows:
        assert row["overall_status"]
        for key in (
            "qualified_variant",
            "conditional_variant",
            "unsupported_variant",
            "deferred_variant",
        ):
            assert isinstance(row[key], str) and row[key].strip()
        assert row["source_test_paths"]
        for path in row["source_test_paths"]:
            assert path.startswith("tests/test_")
            assert (ROOT / path).is_file(), path
    historical = json.loads(J1.read_text(encoding="utf-8"))
    assert historical["stage"] == "J1 candidate; no final merge/release attestation"
    assert len(historical["acceptance"]) == 18


def test_exact_installed_evidence_is_kept_separate_from_official_release() -> None:
    data = _data()
    prov = data["provenance"]
    assert data["source_merge_commit"] == (
        "698903fa1db4ad43c32664eb64211d69ba3f987c"
    )
    assert prov["unpublished_installed_candidate_wheel_sha256"] == (
        "070eb11636830027b746e788f138a59f31487d0604e40e4c29a29684e2073024"
    )
    assert (
        prov["published_v042_wheel_sha256"]
        != prov["unpublished_installed_candidate_wheel_sha256"]
    )
    assert prov["unpublished_candidate_qualifies_D3"] is False
    assert data["release_authorized"] is False
    assert data["issue_close_authorized"] is False
    assert "not_published" in data["d_levels"]["D3"]
    assert "not_qualified" in data["d_levels"]["D4"]


def test_targeted_acceptance_qualified_without_upgrading_open_release_gate() -> None:
    data = _data()
    evidence = {row["id"]: row for row in data["operator_evidence"]}
    assert evidence["correction_29x6"]["result"] == "PASS"
    assert evidence["finding4_retake"]["result"] == "PASS_WITH_TRANSCRIPT_LIMITATION"
    assert evidence["interrupted_save"]["result"] == "PASS"
    rows = {row["id"]: row for row in data["acceptance"]}
    for item in ("A3", "A4", "A12", "A13", "A14", "A15"):
        assert "targeted_installed" in rows[item]["overall_status"]
    assert rows["A18"]["overall_status"] == "release_open"
    assert data["source_and_ci"]["J2_eight_CI_jobs"] == "not_run"
    assert "final_PR_head_eight_GitHub_CI_jobs_exact_SHA" in (
        data["outstanding_release_gates"]
    )


def test_version_identity_remains_consistent_through_future_migration() -> None:
    data = _data()
    # The J2 ledger records its historical 0.4.2-labelled candidate.
    # A later J3 bump must not require rewriting historical J2 evidence.
    assert data["version_state"]["current_source_version"] == "0.4.2"
    assert data["version_state"]["candidate_next_version"] == (
        "0.4.3_proposed_not_applied"
    )
    source = (ROOT / "meridian/_version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__: Final\[str\] = "(\d+\.\d+\.\d+)"', source)
    assert match is not None
    current_version = match.group(1)
    for script in ("scripts/check_package.py", "scripts/check_sdist.py"):
        checker = (ROOT / script).read_text(encoding="utf-8")
        assert f'EXPECTED_VERSION = "{current_version}"' in checker
    text = PLAN.read_text(encoding="utf-8")
    for word in (
        "#123",
        "#124",
        "#125",
        "#126",
        "v0.4.3",
        "8/8",
        "Twine",
        "#133",
        "#134",
    ):
        assert word.lower() in text.lower(), word
    assert "**not** a publish/merge authorization" in text
