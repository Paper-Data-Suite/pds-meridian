"""#124 C1: teacher-reviewed, entirely read-only Grade Item setup proposal."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_choices import NamedAssessment, NamedAssessmentList
from meridian.assessment_setup_inventory import AssessmentSetupCandidate
from meridian.assessment_setup_preview import (
    AssessmentSetupPreviewError,
    prepare_assessment_setup_preview,
)
from meridian.guided_grade_items import GuidedGradeItemBridgeContext
from meridian.teacher_navigation_choices import TeacherChoice

WORK = ModuleWorkRef("scoreform", "english12", "scene_check")
YEAR = "2026-2027"


def fixture(
    *,
    state: str = "needs_create",
    pub: str = "current_results_verified",
    lifecycle: str = "active",
    grade_purpose: str = "standards_proficiency",
    period: str = "mp1",
    calendar: int = 3,
    duplicate_choices: bool = False,
) -> tuple[NamedAssessmentList, GuidedGradeItemBridgeContext]:
    candidate = cast(
        AssessmentSetupCandidate,
        SimpleNamespace(
            work=WORK,
            school_year=YEAR,
            period_id="mp1",
            registration_revision=2,
            calendar_revision=3,
            title="Scene Check",
            lifecycle=lifecycle,
            publication_id="pub_" + "a" * 32
            if pub == "current_results_verified"
            else None,
            setup_state=state,
            ready_grade_item_id="gi_scene" if state == "ready" else None,
            active_unlinked_grade_item_ids=("gi_scene",)
            if state == "choose_existing"
            else (),
        ),
    )
    choice = TeacherChoice(
        identity=("english12", "scoreform", "scene_check"),
        label="Scene Check",
        source="ScoreForm",
        status=(
            "Published results verified"
            if pub == "current_results_verified"
            else "No published results indexed"
        ),
        witness="registration=2;calendar=3",
    )
    named = NamedAssessment(
        candidate=candidate,
        choice=choice,
        publication_state=cast(Any, pub),
        historical_publication_count=1,
        registration_created_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    assessments = NamedAssessmentList("english12", YEAR, "mp1", (named,), (choice,))
    active_choice = SimpleNamespace(
        grade_item_id="gi_scene",
        title="Scene Grade",
        purpose=grade_purpose,
        selected_revision=4,
    )
    active = (active_choice, active_choice) if duplicate_choices else (active_choice,)
    p = SimpleNamespace(
        period_type="marking_period",
        display_label="Marking Period 1 · 2026-09-08 to 2026-11-13",
        assignment=SimpleNamespace(
            period=SimpleNamespace(school_year=YEAR, period_id=period),
            calendar_revision=calendar,
        ),
    )
    bridge = cast(
        GuidedGradeItemBridgeContext,
        SimpleNamespace(
            work=WORK,
            work_title="Scene Check",
            registration_revision=2,
            existing_grade_items=active,
            existing_grade_item_ids=("gi_scene",),
            periods=(p,),
        ),
    )
    return assessments, bridge


def preview(**changes: Any) -> Any:
    params = dict(
        purpose="standards_proficiency",
        actor_attribution="teacher_test",
    )
    params.update(changes)
    return prepare_assessment_setup_preview(*fixture(), work=WORK, **params)


def test_new_grade_item_requires_one_confirmation_and_no_automatic_weighting() -> None:
    result = preview()
    assert result.kind == "create_and_link"
    assert result.grade_item_id == "gi_scene_check"
    assert len(result.operations) == 4
    assert result.needs_confirmation
    assert result.grade_item_purpose == "standards_proficiency"
    assert "not configured" in result.weighting_message
    assert result.marking_period_id == "mp1"
    assert result.registration_revision == 2


def test_new_title_must_be_visible_and_still_produces_deterministic_identity() -> None:
    a = preview(new_title="Unit One Narrative")
    b = preview(new_title="Unit One Narrative")
    assert a.grade_item_id == "gi_unit_one_narrative"
    assert a.review_sha256 == b.review_sha256
    assert a.assessment_title == "Scene Check"


def test_existing_link_needs_only_membership_steps_and_explicit_choice() -> None:
    named, bridge = fixture(state="choose_existing")
    one = prepare_assessment_setup_preview(
        named,
        bridge,
        work=WORK,
        existing_grade_item_id="gi_scene",
        actor_attribution="teacher_test",
        purpose="standards_proficiency",
    )
    assert one.kind == "use_existing"
    assert one.selected_grade_item_revision == 4
    assert len(one.operations) == 2
    assert one.grade_item_title == "Scene Grade"


def test_existing_unlinked_never_autochooses_first_item() -> None:
    named, bridge = fixture(state="choose_existing")
    with pytest.raises(AssessmentSetupPreviewError, match="Choose one"):
        prepare_assessment_setup_preview(
            named,
            bridge,
            work=WORK,
            actor_attribution="teacher_test",
            purpose="standards_proficiency",
        )


def test_existing_purpose_mismatch_fails_closed() -> None:
    named, bridge = fixture(state="choose_existing")
    with pytest.raises(AssessmentSetupPreviewError, match="purpose differs"):
        prepare_assessment_setup_preview(
            named,
            bridge,
            work=WORK,
            existing_grade_item_id="gi_scene",
            actor_attribution="teacher_test",
            purpose="reporting_only",
        )


def test_ready_proposes_zero_operations_and_no_confirmation() -> None:
    named, bridge = fixture(state="ready")
    result = prepare_assessment_setup_preview(named, bridge, work=WORK)
    assert result.kind == "already_ready"
    assert result.operations == ()
    assert result.actor_attribution is None
    assert not result.needs_confirmation
    assert result.selected_grade_item_revision == 4


@pytest.mark.parametrize("state", ["ambiguous", "review_relationship"])
def test_unsafe_relationship_requires_human_review(state: str) -> None:
    named, bridge = fixture(state=state)
    with pytest.raises(AssessmentSetupPreviewError, match="needs review"):
        prepare_assessment_setup_preview(named, bridge, work=WORK)


@pytest.mark.parametrize(
    "pub", ["multiple_current_results", "withdrawn_results", "historical_results_only"]
)
def test_ambiguous_or_unavailable_publications_are_not_silently_used(pub: str) -> None:
    named, bridge = fixture(pub=pub)
    with pytest.raises(AssessmentSetupPreviewError, match="history needs review"):
        prepare_assessment_setup_preview(named, bridge, work=WORK)


def test_registered_only_can_prepare_but_cannot_claim_publication() -> None:
    named, bridge = fixture(pub="no_results_indexed")
    result = prepare_assessment_setup_preview(
        named,
        bridge,
        work=WORK,
        purpose="reporting_only",
        actor_attribution="teacher_test",
    )
    assert result.publication_id is None
    assert result.kind == "create_and_link"
    assert result.publication_label == "No published results indexed"


@pytest.mark.parametrize("lifecycle", ["cancelled", "closed"])
def test_noneligible_registration_cannot_enter_automatic_setup(lifecycle: str) -> None:
    named, bridge = fixture(lifecycle=lifecycle)
    with pytest.raises(AssessmentSetupPreviewError, match="active/planned"):
        prepare_assessment_setup_preview(named, bridge, work=WORK)


@pytest.mark.parametrize("period,calendar", [("mp2", 3), ("mp1", 2)])
def test_calendar_or_period_drift_requires_refresh(period: str, calendar: int) -> None:
    named, bridge = fixture(period=period, calendar=calendar)
    with pytest.raises(AssessmentSetupPreviewError, match="calendar changed"):
        prepare_assessment_setup_preview(named, bridge, work=WORK)


def test_teacher_must_choose_purpose_and_attribution_before_write() -> None:
    named, bridge = fixture()
    with pytest.raises(AssessmentSetupPreviewError, match="attribution"):
        prepare_assessment_setup_preview(
            named, bridge, work=WORK, purpose="reporting_only"
        )
    with pytest.raises(
        AssessmentSetupPreviewError, match="explicit Grade Item purpose"
    ):
        prepare_assessment_setup_preview(
            named, bridge, work=WORK, actor_attribution="teacher_test"
        )


def test_grade_item_identity_or_purpose_not_silently_retargeted() -> None:
    named, bridge = fixture(state="ready")
    with pytest.raises(AssessmentSetupPreviewError, match="retargeted"):
        prepare_assessment_setup_preview(
            named, bridge, work=WORK, existing_grade_item_id="another"
        )
    with pytest.raises(AssessmentSetupPreviewError, match="purpose differs"):
        prepare_assessment_setup_preview(
            named, bridge, work=WORK, purpose="reporting_only"
        )


def test_work_scope_and_duplicate_grade_choices_fail_closed() -> None:
    named, bridge = fixture(duplicate_choices=True)
    with pytest.raises(AssessmentSetupPreviewError, match="Duplicate Grade Item"):
        prepare_assessment_setup_preview(
            named,
            bridge,
            work=WORK,
            purpose="reporting_only",
            actor_attribution="teacher_test",
        )
    with pytest.raises(AssessmentSetupPreviewError, match="class/work disagree"):
        prepare_assessment_setup_preview(
            named,
            bridge,
            work=ModuleWorkRef("quillan", "english12", "other"),
        )


def test_no_write_side_ports_are_imported_or_called(tmp_path: Path) -> None:
    source = (
        Path(__file__).resolve().parents[1] / "meridian" / "assessment_setup_preview.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "commit_grade_item",
        "commit_membership",
        "prepare_grade_item_action(",
        "prepare_membership_action(",
        "verify_publication_manifest(",
        "TeacherActionReceiptStore(",
        "input(",
    ):
        assert forbidden not in source
    assert list(tmp_path.iterdir()) == []
