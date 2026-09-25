from __future__ import annotations

from pathlib import Path


def test_issue57_teacher_menu_architecture_documents_final_contract() -> None:
    text = Path("docs/architecture/teacher-main-menu.md").read_text(encoding="utf-8")
    for token in (
        "Eight-task application surface",
        "pds_core.menu_navigation",
        "Clear/redraw and information density",
        "Technical details / provenance",
        "Consequential actions",
        "Create Planning Signal",
        "#58 and #59 boundaries",
        "Installed qualification",
        "quillan      0.10.2",
        "no assignment, submission, review, feedback, diagnostic,",
    ):
        assert token in text


def test_issue57_active_docs_describe_bare_menu_and_current_quillan() -> None:
    readme = Path("README").read_text(encoding="utf-8")
    docs = Path("docs/README.md").read_text(encoding="utf-8")
    assert "`meridian` launches the teacher-facing application" in readme
    assert "`meridian menu`" in readme
    assert "Quillan v0.10.2" in readme
    assert "teacher-main-menu.md" in readme
    assert "Issue #57" in docs
    assert "teacher-main-menu.md" in docs
    assert "quillan==0.10.2" in docs
