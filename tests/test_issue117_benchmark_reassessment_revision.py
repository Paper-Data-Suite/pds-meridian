"""Issue #117: append-only Report 9 reassessment through teacher menus."""

from __future__ import annotations

from pathlib import Path

from test_issue117_benchmark_plan_menu import _run

from meridian.benchmark_plan_notes import load_benchmark_plan_notes
from meridian.benchmark_plan_storage import (
    list_benchmark_plan_revisions,
    load_benchmark_plan_revision,
    load_latest_benchmark_plan_revision,
)
from meridian.teacher_report_render import render_teacher_report

_CLASS = "class_1"
_PLAN = "benchmark_mp1_assessment_1"


def _first_plan(root: Path) -> None:
    result = _run(
        root,
        "1", "teacher_1", "Students need to cite precise evidence.",
        "n",  # No teacher-standard classification yet.
        "y", "Evidence practice", "1,3", "Cite relevant details", "n",
        "y", "1", "reading.analysis", "1,3", "Model text annotations",
        "2026-10-18", "2026-10-25", "", "", "planned", "", "n",
        "n", "SAVE PLAN", "b",
    )
    assert "revision 1 saved" in result


def _follow_up(root: Path, confirmation: str) -> str:
    return _run(
        root,
        "4", "", "", "", "", "n", "y",
        "Exit ticket", "2026-10-25", "Claims now reference text accurately.",
        "3", "", "Evidence conference", "Continue monitoring",
        "", confirmation, "b",
    )


def test_reassessment_appends_second_revision_and_preserves_first(
    tmp_path: Path,
) -> None:
    _first_plan(tmp_path)
    first = load_benchmark_plan_revision(tmp_path, _CLASS, _PLAN, 1)
    original_digest = first.revision_sha256
    original = load_benchmark_plan_notes(tmp_path, first)
    assert original is not None and original.follow_up is None
    assert original.groups and original.responses

    output = _follow_up(tmp_path, "SAVE PLAN")
    assert "revision 2 saved" in output
    assert list_benchmark_plan_revisions(tmp_path, _CLASS, _PLAN) == (1, 2)

    still_first = load_benchmark_plan_revision(tmp_path, _CLASS, _PLAN, 1)
    second = load_latest_benchmark_plan_revision(tmp_path, _CLASS, _PLAN)
    restored = load_benchmark_plan_notes(tmp_path, second)
    assert still_first.revision_sha256 == original_digest
    assert load_benchmark_plan_notes(tmp_path, still_first) == original
    assert restored is not None
    assert restored.interpretation == original.interpretation
    assert restored.groups == original.groups
    assert restored.responses == original.responses
    assert restored.standards == original.standards
    assert restored.follow_up is not None
    assert restored.follow_up.reassessment_tool == "Exit ticket"
    assert restored.follow_up.students_still_needing_support == ("student_3",)
    assert restored.follow_up.follow_up_source_id is None
    assert (
        second.revision.report.source_references
        == first.revision.report.source_references
    )
    assert b"Exit ticket" in render_teacher_report(second.revision.report, "markdown")


def test_cancelled_reassessment_leaves_prior_plan_untouched(
    tmp_path: Path,
) -> None:
    _first_plan(tmp_path)
    first = load_latest_benchmark_plan_revision(tmp_path, _CLASS, _PLAN)
    before = first.content
    notes = load_benchmark_plan_notes(tmp_path, first)
    output = _follow_up(tmp_path, "CANCEL")
    assert "Draft discarded" in output
    assert list_benchmark_plan_revisions(tmp_path, _CLASS, _PLAN) == (1,)
    current = load_latest_benchmark_plan_revision(tmp_path, _CLASS, _PLAN)
    assert current.content == before
    assert load_benchmark_plan_notes(tmp_path, current) == notes
