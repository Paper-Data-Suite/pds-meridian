from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.cli as cli
from meridian.grade_items_workflow import (
    GradeItemMembershipReviewRow,
    GradeItemReviewRow,
    GradeItemsReview,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="test_1",
)
DECIDED_AT = datetime(2026, 9, 1, 20, tzinfo=UTC)


def _empty_review() -> GradeItemsReview:
    return GradeItemsReview(
        schema_version=1,
        class_id=CLASS_ID,
        items=(),
        active_count=0,
        archived_count=0,
        unselected_count=0,
        membership_relationship_count=0,
        membership_included_count=0,
        membership_excluded_count=0,
        membership_unselected_count=0,
    )


def _review() -> GradeItemsReview:
    membership = GradeItemMembershipReviewRow(
        work=WORK,
        revision_count=3,
        latest_persisted_revision=3,
        selected_revision=2,
        selected_revision_sha256="b" * 64,
        selection_state="selected_historical",
        decision="included",
        grade_item_revision_basis=1,
        grade_item_revision_sha256_basis="a" * 64,
        grade_item_basis_state="historical_grade_item_basis",
        registration_revision=7,
        academic_period_school_year="2026-2027",
        academic_period_id="q1",
        academic_period_calendar_revision=4,
        actor_id="teacher_local",
        decided_at=DECIDED_AT,
    )
    item = GradeItemReviewRow(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        revision_count=2,
        latest_persisted_revision=2,
        selected_revision=1,
        selected_revision_sha256="a" * 64,
        selection_state="selected_historical",
        title="Unit 1 Assessment",
        purpose="standards_proficiency",
        status="active",
        weighting=None,
        created_at=DECIDED_AT,
        revised_at=DECIDED_AT,
        memberships=(membership,),
    )
    return GradeItemsReview(
        schema_version=1,
        class_id=CLASS_ID,
        items=(item,),
        active_count=1,
        archived_count=0,
        unselected_count=0,
        membership_relationship_count=1,
        membership_included_count=1,
        membership_excluded_count=0,
        membership_unselected_count=0,
    )


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "grade-items",
        CLASS_ID,
        "--workspace",
        "synthetic-workspace",
        *extra,
    )


def test_workflow_help_exposes_grade_items_review(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = capsys.readouterr().out
    normalized = " ".join(output.split())
    assert "grade-items" in normalized
    assert (
        "Review explicit Grade Item and membership selector state"
        in normalized
    )


def test_grade_items_json_is_deterministic_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}

    def fake_project(workspace_root: str, class_id: str) -> GradeItemsReview:
        observed["call"] = (workspace_root, class_id)
        return _review()

    monkeypatch.setattr(cli, "project_grade_items_review", fake_project)

    assert cli.main(_arguments("--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)

    assert observed["call"] == ("synthetic-workspace", CLASS_ID)
    assert payload["schema_version"] == 1
    assert payload["summary"]["active_count"] == 1
    item = payload["items"][0]
    assert item["latest_persisted_revision"] == 2
    assert item["selected_revision"] == 1
    assert item["selection_state"] == "selected_historical"
    membership = item["memberships"][0]
    assert membership["latest_persisted_revision"] == 3
    assert membership["selected_revision"] == 2
    assert membership["grade_item_basis_state"] == "historical_grade_item_basis"
    assert membership["academic_period"] == {
        "school_year": "2026-2027",
        "period_id": "q1",
        "calendar_revision": 4,
    }


def test_grade_items_text_names_explicit_selected_and_latest_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "project_grade_items_review", lambda *args: _review())

    assert cli.main(_arguments()) == 0
    output = capsys.readouterr().out

    assert "Grade Items review: synthetic_class_2026" in output
    assert "Unit 1 Assessment" in output
    assert "selected_historical" in output
    assert "selected=1" in output
    assert "latest=2" in output
    assert "scoreform/test_1" in output
    assert "selected=2" in output
    assert "latest=3" in output
    assert "2026-2027/q1@calendar-4" in output
    assert "historical_grade_item_basis" in output


def test_empty_grade_items_review_is_not_inferred_from_other_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "project_grade_items_review",
        lambda *args: _empty_review(),
    )

    assert cli.main(_arguments()) == 0
    output = capsys.readouterr().out

    assert "No canonical Grade Items exist for this class." in output
    assert "No Grade Item was inferred from publications or dates." in output
