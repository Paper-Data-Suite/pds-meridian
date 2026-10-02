from pathlib import Path

DOC = Path("docs/architecture/grade-report-attention-summaries.md")


def test_issue58_architecture_document_records_attention_boundaries() -> None:
    text = DOC.read_text(encoding="utf-8")

    for token in (
        "meridian_grade_result_stale",
        "meridian_reporting_publication_changed",
        "meridian_reporting_snapshot_refresh_needed",
        "meridian_reporting_snapshot_selection_pending",
        "preview-grades",
        "open_preview_grades",
        "snapshots",
        "open_snapshots",
        "ReportingSnapshots never become attention merely because they are old.",
        "Export readiness is intentionally not attention.",
        "Successful empty evaluation remains distinct from unavailable evaluation.",
        "pds-core 0.6.3",
        "ScoreForm, Quillan, and Concord remain absent",
        "Issue #59",
        "Paper Data Suite issues #20, #22, and #23",
        "Issue #58 Grade/report attention summaries — implemented and qualified.",
    ):
        assert token in text


def test_issue58_active_docs_and_changelog_link_the_contract() -> None:
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    docs_index = Path("docs/README.md").read_text(encoding="utf-8")
    readme = Path("README").read_text(encoding="utf-8")

    assert "Issue #58 Grade/report attention summaries" in changelog
    assert "grade-report-attention-summaries.md" in docs_index
    assert "Grade/report attention" in readme
