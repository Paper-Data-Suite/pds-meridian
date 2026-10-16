"""#117 Slice 8: lossless plan restoration and source-bound teacher editing."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from test_issue117_benchmark_plan_authoring import (
    _annotations,
    _baseline,
    _save,
)
from test_issue117_benchmark_plan_menu import (
    ScriptedInput,
    _prepared,
    _run,
    _services,
)

from meridian.benchmark_plan_authoring import BenchmarkTeacherAnnotations
from meridian.benchmark_plan_notes import (
    BenchmarkPlanNotesError,
    load_benchmark_plan_notes,
    save_benchmark_plan_notes,
)
from meridian.benchmark_plan_storage import (
    list_benchmark_plan_revisions,
    load_latest_benchmark_plan_revision,
)
from meridian.menu_benchmark_planner import run_benchmark_planner_menu


def _latest(root: Path):
    return load_latest_benchmark_plan_revision(
        root, "class_1", "benchmark_mp1_assessment_1"
    )


def test_all_teacher_fields_roundtrip_without_report_metadata_leak(
    tmp_path: Path,
) -> None:
    original = _save(tmp_path, _annotations()).stored
    save_benchmark_plan_notes(tmp_path, original, _annotations())
    assert load_benchmark_plan_notes(tmp_path, original) == _annotations()
    save_benchmark_plan_notes(tmp_path, original, _annotations())  # Idempotent.
    assert not any(
        "meridian_benchmark_teacher_annotations" in (part or "")
        for row in original.revision.report.rows for part in row.values
    )
    with pytest.raises(BenchmarkPlanNotesError):
        save_benchmark_plan_notes(
            tmp_path, original,
            replace(_annotations(), interpretation="Unauthorized replacement"),
        )


def test_missing_notes_identifies_legacy_without_guessing(tmp_path: Path) -> None:
    original = _save(tmp_path, _annotations()).stored
    assert load_benchmark_plan_notes(tmp_path, original) is None
    other = replace(
        original, revision_sha256="f" * 64,
    )
    save_benchmark_plan_notes(tmp_path, original, _annotations())
    with pytest.raises(BenchmarkPlanNotesError, match="identity changed"):
        load_benchmark_plan_notes(tmp_path, other)


def test_corrupt_digest_and_missing_file_fail_closed(tmp_path: Path) -> None:
    original = _save(tmp_path, _annotations()).stored
    save_benchmark_plan_notes(tmp_path, original, _annotations())
    path = original.path.parent.parent / "teacher_annotations" / "1.json"
    content = path.read_bytes()
    path.write_bytes(content.replace(b"student_1", b"student_2", 1))
    with pytest.raises(BenchmarkPlanNotesError, match="digest"):
        load_benchmark_plan_notes(tmp_path, original)
    path.unlink()
    with pytest.raises(BenchmarkPlanNotesError, match="missing"):
        load_benchmark_plan_notes(tmp_path, original)


def test_restored_revision_keeps_student_membership_and_follow_up(
    tmp_path: Path,
) -> None:
    _run(
        tmp_path,
        "1", "teacher_1", "Original teacher observations", "n",
        "y", "Strategy group", "1,3", "Both need evidence practice", "n",
        "y", "1", "Reading analysis", "1,3", "Model claim and evidence",
        "2026-10-20", "2026-10-25", "q2", "reading.analysis",
        "planned", "Initial approach", "n",
        "y", "Exit ticket", "2026-10-25", "Review pending", "3",
        "reading.analysis", "Small conference", "Continue monitoring", "",
        "SAVE PLAN", "b",
    )
    original = _latest(tmp_path)
    prior = load_benchmark_plan_notes(tmp_path, original)
    assert prior is not None
    assert prior.groups[0].student_ids == ("student_1", "student_3")
    assert prior.responses[0].student_ids == ("student_1", "student_3")
    assert prior.follow_up is not None
    assert prior.follow_up.students_still_needing_support == ("student_3",)

    result = _run(
        tmp_path, "4",
        "n", "Revised observation after review",  # Replace interpretation.
        "", "", "", "",  # Keep four other sections.
        "SAVE PLAN", "b",
    )
    updated = _latest(tmp_path)
    revised = load_benchmark_plan_notes(tmp_path, updated)
    assert revised is not None
    assert updated.revision.plan_revision == 2
    assert revised.interpretation == "Revised observation after review"
    assert revised.groups == prior.groups
    assert revised.responses == prior.responses
    assert revised.follow_up == prior.follow_up
    assert (
        original.revision.report.preview_sha256
        != updated.revision.report.preview_sha256
    )
    assert load_benchmark_plan_notes(tmp_path, original) == prior
    assert "revision 2 saved" in result
    assert "Existing teacher entries can be kept" in result


def test_edit_rejects_corrupt_and_legacy_notes_without_new_revision(
    tmp_path: Path,
) -> None:
    _save(
        tmp_path, BenchmarkTeacherAnnotations(interpretation="Legacy plan"),
        plan_id="benchmark_mp1_assessment_1",
    )
    result = _run(tmp_path, "4", "b")
    assert "legacy revision" in result.lower()
    assert list_benchmark_plan_revisions(
        tmp_path, "class_1", "benchmark_mp1_assessment_1"
    ) == (1,)
    save_benchmark_plan_notes(
        tmp_path, _latest(tmp_path),
        BenchmarkTeacherAnnotations(interpretation="Legacy plan"),
    )
    path = _latest(tmp_path).path.parent.parent / "teacher_annotations" / "1.json"
    path.write_bytes(b"corrupt")
    result = _run(tmp_path, "4", "b")
    assert "failed verification" in result
    assert list_benchmark_plan_revisions(
        tmp_path, "class_1", "benchmark_mp1_assessment_1"
    ) == (1,)


def test_revoked_authorization_blocks_restoration(tmp_path: Path) -> None:
    _run(
        tmp_path, "1", "teacher_1", "Private notes", "n", "n", "n",
        "n", "SAVE PLAN", "b",
    )
    output = StringIO()
    def reject(_selected, _report):
        raise RuntimeError("No current authority")
    run_benchmark_planner_menu(
        report=_baseline(), prepared=_prepared(), revalidate=reject,
        input_fn=ScriptedInput("4"), output=output, services=_services(tmp_path),
    )
    assert "Private notes" not in output.getvalue()
    assert list_benchmark_plan_revisions(
        tmp_path, "class_1", "benchmark_mp1_assessment_1"
    ) == (1,)


def test_teacher_sees_accurate_message_on_notes_write_failure(
    tmp_path: Path,
) -> None:
    base = _services(tmp_path)
    def blocked(_root, _stored, _annotations):
        raise BenchmarkPlanNotesError("Simulated I/O failure")
    services = replace(base, notes_writer=blocked)
    output = StringIO()
    run_benchmark_planner_menu(
        report=_baseline(), prepared=_prepared(),
        revalidate=lambda *_: None,
        input_fn=ScriptedInput(
            "1", "teacher_1", "Initial notes", "n", "n", "n",
            "n", "SAVE PLAN", "b",
        ),
        output=output, services=services,
    )
    assert "was saved, but its editable draft" in output.getvalue()
    assert _latest(tmp_path).revision.plan_revision == 1
    assert load_benchmark_plan_notes(tmp_path, _latest(tmp_path)) is None
