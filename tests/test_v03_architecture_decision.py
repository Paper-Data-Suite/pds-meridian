from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / (
    "docs/decisions/"
    "0005-v03-grade-preview-and-reporting-snapshot-architecture.md"
)


def _adr() -> str:
    return ADR.read_text(encoding="utf-8")


def test_v03_architecture_freezes_semantic_separations() -> None:
    text = _adr()
    required = (
        "GradeItemRevision.weighting metadata != executable Grade policy",
        "missing or unresolved state != numeric zero",
        "Grade preview != ReportingSnapshot",
        "Grade preview != official Grade",
        "ReportingSnapshot != Core Publication Record",
        "ReportingSnapshot != Vitrine Portfolio Snapshot / Edition",
        "ReportingSnapshot != rendered/export artifact",
        "export != external-system write",
    )
    for token in required:
        assert token in text


def test_reporting_snapshot_is_meridian_owned_not_core_published() -> None:
    text = _adr()
    assert (
        "a `ReportingSnapshot` is a Meridian-owned immutable canonical record"
        in text
    )
    assert "It is not a Core Publication Record." in text
    assert "No new Core publication kind" in text
    assert "separate Core architecture and" in text


def test_override_precedence_is_explicit() -> None:
    text = _adr()
    assert "Conflicting active overrides" in text
    assert "Newest timestamp wins" in text
    assert "explicit supersession/current selection" in text


def test_architecture_records_current_release_baseline() -> None:
    text = _adr()
    for token in (
        "pds-meridian 0.2.0",
        "pds-core 0.6.3",
        "scoreform 0.11.0",
        "quillan 0.10.0",
        "pds-concord 0.3.0",
        "98d7596ce0eed26e4d56a17bbbbd644db3014259b56a45783a173fe8237af5e5",
        "8248c6a1cc8254b5f9df46440131d524f80da8662a0dc7864fdc982e501b4c44",
        "5dd4ed62b8bf39f7e11e6538d1c094929c6428dba81b254fe80d03c60d5114e9",
        "dd827f7059c91c79bd69b6190b3c673d6b3bbc02bc25fa666286bbf5883c5e12",
    ):
        assert token in text


def test_architecture_requires_latest_release_recheck() -> None:
    text = _adr()
    assert "check the latest non-prerelease GitHub Release" in text
    assert "newest compatible released contract" in text
    assert "never silently substitute a sibling checkout" in text
    assert "qualify exact supported distribution identities" in text


def test_decision_indexes_expose_adr_0005() -> None:
    decisions = (ROOT / "docs/decisions/README.md").read_text(encoding="utf-8")
    docs = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    assert "### ADR 0005" in decisions
    assert "ADR 0005 specializes ADRs 0001, 0002, 0003, and 0004" in decisions
    assert "Five accepted ADRs govern the repository:" in docs
    assert "ADR 0005" in docs
