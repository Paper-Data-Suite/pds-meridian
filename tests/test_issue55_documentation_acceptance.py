from __future__ import annotations

from pathlib import Path

ARCHITECTURE = Path("docs/architecture/reporting-snapshots.md")


def test_issue55_architecture_documents_ownership_and_integrity_boundaries() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "Meridian-owned canonical state",
        "ReportingSnapshotReference.snapshot_sha256",
        "payload_sha256",
        "no_selected_grade",
        "missing state becomes silent numeric zero",
        "official school-system record",
        "Vitrine Portfolio Snapshot",
        "ReportingSnapshot\n    != ExportProfile",
    ):
        assert token in text


def test_issue55_architecture_documents_freeze_selection_and_comparison() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "freeze_reporting_snapshot(...)",
        (
            "revalidate exact authorized projection bytes + Core "
            "publication/manifest state"
        ),
        "reporting_snapshot.currentness_conflict",
        "Freeze does not select",
        "compare-and-swap protection",
        "B supersedes A",
        "prior_reporting_snapshot_grade_basis_from_observation(...)",
        "compare_grade_preview_basis(...)",
        "no second comparison implementation exists",
    ):
        assert token in text


def test_issue55_architecture_documents_privacy_and_storage_topology() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "reporting_definitions/",
        "reporting_snapshots/",
        "reporting_snapshot_selections/",
        "Raw student",
        "Opaque provenance reference keys remain opaque",
        "protected source evidence is not copied",
    ):
        assert token in text


def test_issue55_architecture_documents_cli_and_installed_qualification() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "meridian reporting definitions list",
        "meridian reporting snapshots freeze",
        "meridian reporting snapshots compare",
        "meridian reporting selection select",
        "authorization-gated projection-cache loader",
        "pip check",
        "site-packages",
        "fresh process",
        "meridian.reporting_snapshot_cli",
    ):
        assert token in text
    assert "final teacher-facing menu design" in text


def test_issue55_status_reflects_completed_cli_and_installed_qualification() -> None:
    docs = Path("docs/README.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    for text in (docs, changelog):
        assert "Issue #55" in text
        assert "ReportingSnapshot" in text
        assert "bounded development CLI" in text
        assert "installed-wheel/fresh-process" in text
        assert "repository-wide" in text
        assert "remain issue #55 completion work" not in text
    assert "reporting-snapshots.md" in docs
