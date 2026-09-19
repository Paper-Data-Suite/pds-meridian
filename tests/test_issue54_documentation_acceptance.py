from __future__ import annotations

from pathlib import Path

ARCHITECTURE = Path("docs/architecture/grade-report-preview-explanations.md")


def test_issue54_architecture_freezes_preview_and_snapshot_boundaries() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "Grade preview is advisory",
        "selected Grade may be stale and still be explainable",
        "One coherent observation",
        "grade_preview.currentness_conflict",
        "GradePreviewObservation",
        "is **not** a `ReportingSnapshot`",
        "Those remain issue #55",
        "official school-system record",
    ):
        assert token in text


def test_issue54_architecture_documents_all_family_explanations() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "total_points",
        "weighted_items",
        "weighted_categories",
        "AcademicPeriodProficiencyResultReference",
        'selection="revision"',
        "independently selected conventional or standards Grade results",
        "base unrounded Grade",
        "override replacement Grade",
        "source_result_stale",
    ):
        assert token in text


def test_issue54_architecture_documents_report_comparison_and_privacy() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "PriorReportingSnapshotGradeBasis",
        "snapshot-neutral",
        "does not infer a roster",
        "no_selected_grade",
        "Numeric deltas use exact Decimal arithmetic",
        "fails closed",
        "Opaque reference keys remain opaque",
        "existing authorization boundary",
        "Read-only guarantee",
    ):
        assert token in text


def test_issue54_repository_status_and_compatibility_are_documented() -> None:
    readme = Path("README").read_text(encoding="utf-8")
    docs = Path("docs/README.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    for text in (readme, docs, changelog):
        assert "Issue #54" in text
        assert "Grade preview" in text or "Grade/report preview" in text
    assert "grade-report-preview-explanations.md" in docs
    for token in (
        "pds-core      0.6.3",
        "scoreform     0.11.0",
        "quillan       0.10.0",
        "pds-concord   0.3.0",
        "Vitrine advanced to v0.3.0",
        "Portia",
        "nondependency",
    ):
        assert token in architecture
