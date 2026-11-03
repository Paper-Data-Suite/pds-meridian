"""#124 E2G3O3: normal teacher discovery -> original correlated one-APPLY review.

The controller is tested with fresh-preview and bound-review seams. Genuine
canonical #122 persistence and E2C durable original-action fencing remain
qualified by E2G3K/L/O2 and are not replaced with a new action engine.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian import menu_teacher_assessment_discovery as discovery
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.menu import default_teacher_menu_dependencies
from meridian.menu_teacher_assessment_setup_review import TeacherAssessmentReviewOutcome
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_session import TeacherSessionContext

CLASS = "english12"
WORK = ModuleWorkRef("scoreform", CLASS, "scene")
ACTOR = TeacherActionActor("teacher_local", "b" * 64, "saved")
YEAR = "2026-2027"
PERIOD = "mp1"


def _preview(kind: str = "create_and_link") -> AssessmentSetupPreview:
    from typing import Any, cast

    return AssessmentSetupPreview(
        kind=cast(Any, kind),
        work=WORK,
        class_id=CLASS,
        school_year=YEAR,
        registration_revision=1,
        registration_lifecycle="active",
        assessment_title="Scene Study",
        producer_label="ScoreForm",
        publication_label="Registered only",
        publication_id=None,
        grade_item_id="gi_scene",
        grade_item_title="Scene Grade",
        grade_item_purpose="standards_proficiency",
        selected_grade_item_revision=1 if kind != "create_and_link" else None,
        marking_period_id=PERIOD,
        marking_period_label="Marking Period 1",
        calendar_revision=1,
        actor_attribution=None if kind == "already_ready" else ACTOR.actor_id,
        rationale=None,
        operations=(),
        weighting_message="Not configured",
        review_sha256="a" * 64,
    )


def _context() -> SimpleNamespace:
    existing = SimpleNamespace(
        grade_item_id="gi_existing",
        purpose="standards_proficiency",
        display_label="Existing Scene Grade",
    )
    other = SimpleNamespace(
        grade_item_id="gi_other",
        purpose="reporting_only",
        display_label="Other Grade",
    )
    return SimpleNamespace(
        work=WORK,
        registration_revision=1,
        existing_grade_items=(existing, other),
        existing_grade_item_ids=("gi_existing", "gi_other"),
    )


def _offer(
    tmp_path: Path,
    answers: tuple[str, ...],
    *,
    setup_state: str = "needs_create",
    active_unlinked_ids: tuple[str, ...] = ("gi_existing",),
    status: str = "ready",
    preview: AssessmentSetupPreview | None = None,
    session: TeacherSessionContext | None = None,
) -> tuple[
    TeacherAssessmentReviewOutcome | None,
    str,
    object,
    object,
]:
    session = session or TeacherSessionContext(active_class_id=CLASS)
    stream = StringIO()
    commands = iter(answers)
    dependencies = GuidedGradeItemBridgeDependencies()
    reviewed = preview or _preview(
        "already_ready" if setup_state == "ready" else "create_and_link"
    )
    with (
        patch.object(
            discovery,
            "load_guided_grade_item_bridge_context",
            return_value=_context(),
        ),
        patch.object(
            discovery, "resolve_menu_actor", return_value=ACTOR
        ) as actor_resolver,
        patch.object(
            discovery, "load_assessment_setup_preview", return_value=reviewed
        ) as preview_loader,
        patch.object(
            discovery,
            "review_correlated_assessment_setup_once",
            return_value=TeacherAssessmentReviewOutcome(status, "verified"),
        ) as review,
    ):
        result = discovery._offer_selected_assessment_setup(
            tmp_path,
            session,
            WORK,
            year=YEAR,
            period_id=PERIOD,
            registration_revision=1,
            setup_state=setup_state,
            active_unlinked_ids=active_unlinked_ids,
            dependencies=dependencies,
            input_fn=lambda _: next(commands),
            output=stream,
        )
        if result is not None and result.status == "ready":
            review.assert_called_once()
        return result, stream.getvalue(), preview_loader, actor_resolver


def test_new_grade_item_requires_explicit_purpose_title_and_saved_actor(
    tmp_path: Path,
) -> None:
    outcome, message, preview_loader, actor_resolver = _offer(
        tmp_path,
        ("1", "Scene Grade", "", "teacher_local"),
    )
    assert outcome is not None and outcome.ready
    assert "Choose Grade Item Purpose" in message
    assert preview_loader.call_count == 1
    kwargs = preview_loader.call_args.kwargs
    assert kwargs["purpose"] == "standards_proficiency"
    assert kwargs["new_title"] == "Scene Grade"
    assert kwargs["existing_grade_item_id"] is None
    assert kwargs["actor_attribution"] == ACTOR.actor_id
    actor_resolver.assert_called_once()


def test_existing_grade_item_only_offers_explicit_unlinked_choices(
    tmp_path: Path,
) -> None:
    outcome, message, preview_loader, _ = _offer(
        tmp_path,
        ("1", "", "teacher_local"),
        setup_state="choose_existing",
        preview=_preview("use_existing"),
    )
    assert outcome is not None and outcome.ready
    assert "Existing Scene Grade" in message
    assert "Other Grade" not in message
    kwargs = preview_loader.call_args.kwargs
    assert kwargs["existing_grade_item_id"] == "gi_existing"
    assert kwargs["purpose"] == "standards_proficiency"
    assert kwargs["new_title"] is None


def test_ready_relationship_skips_actor_and_new_write_choices(
    tmp_path: Path,
) -> None:
    outcome, message, preview_loader, actor_resolver = _offer(
        tmp_path,
        (),
        setup_state="ready",
    )
    assert outcome is not None and outcome.ready
    assert message == ""
    actor_resolver.assert_not_called()
    kwargs = preview_loader.call_args.kwargs
    assert kwargs["purpose"] is None
    assert kwargs["actor_attribution"] is None
    assert kwargs["new_title"] is None


@pytest.mark.parametrize("answers", [("B",), ("1", "B")])
def test_cancellation_never_prepares_a_review(
    tmp_path: Path, answers: tuple[str, ...]
) -> None:
    result, _, preview_loader, actor_resolver = _offer(tmp_path, answers)
    assert result is None
    preview_loader.assert_not_called()
    actor_resolver.assert_not_called()


def test_unknown_relationship_state_fails_closed_before_any_input(
    tmp_path: Path,
) -> None:
    outcome, message, preview_loader, _ = _offer(tmp_path, (), setup_state="ambiguous")
    assert outcome is not None and outcome.status == "requires_review"
    preview_loader.assert_not_called()
    assert "could not be verified safely" in message


def test_conflicting_session_work_never_offers_a_review(tmp_path: Path) -> None:
    session = TeacherSessionContext(active_class_id=CLASS)
    session.select_work(ModuleWorkRef("quillan", CLASS, "another"))
    outcome, _, preview_loader, _ = _offer(
        tmp_path,
        (),
        session=session,
    )
    assert outcome is not None and outcome.status == "requires_review"
    preview_loader.assert_not_called()
    assert session.active_work != WORK


def test_source_registration_drift_refused_after_new_preview(tmp_path: Path) -> None:
    from dataclasses import replace

    outcome, _, preview_loader, _ = _offer(
        tmp_path,
        ("1", "Scene Grade", "", "teacher_local"),
        preview=replace(_preview(), registration_revision=2),
    )
    assert outcome is not None and outcome.status == "requires_review"
    preview_loader.assert_called_once()


def test_unavailable_existing_choice_does_not_invent_an_id(tmp_path: Path) -> None:
    outcome, message, preview_loader, _ = _offer(
        tmp_path,
        (),
        setup_state="choose_existing",
        active_unlinked_ids=(),
    )
    assert outcome is not None and outcome.status == "requires_review"
    preview_loader.assert_not_called()
    assert "could not be verified safely" in message


def test_cancelled_correlated_review_leaves_outcome_cancelled(tmp_path: Path) -> None:
    outcome, _, _, _ = _offer(
        tmp_path,
        ("1", "Scene Grade", "", "teacher_local"),
        status="cancelled",
    )
    assert outcome is not None and outcome.status == "cancelled"


def test_normal_menu_passes_trusted_bridge_to_discovery() -> None:
    from unittest.mock import Mock

    from meridian import menu

    bridge = Mock(spec=GuidedGradeItemBridgeDependencies)
    with patch.object(menu, "run_teacher_assessment_discovery_menu") as route:
        dependencies = default_teacher_menu_dependencies(
            assessment_bridge_dependencies=bridge,
            input_fn=lambda _: "B",
            output=StringIO(),
            clear_fn=lambda: None,
        )
        assert dependencies.discover_assessments is not None
        dependencies.discover_assessments()
    route.assert_called_once()
    assert route.call_args.kwargs["assessment_bridge_dependencies"] is bridge
    assert route.call_args.kwargs["session_context"] is dependencies.session_context


def test_controller_is_only_caller_of_correlated_review_not_a_writer() -> None:
    path = Path(discovery.__file__)
    content = path.read_text(encoding="utf-8")
    for forbidden in (
        "write_grade_item_revision(",
        "write_grade_item_membership_revision(",
        "select_grade_item_revision(",
        "select_grade_item_membership_revision(",
        "TeacherActionReceiptStore(",
    ):
        assert forbidden not in content


def _normal_discovery(
    tmp_path: Path,
    answers: tuple[str, ...],
    *,
    disposition: TeacherAssessmentReviewOutcome | None,
) -> tuple[str, object, TeacherSessionContext]:
    from datetime import UTC, datetime
    from unittest.mock import Mock

    from meridian.assessment_setup_choices import NamedAssessment, NamedAssessmentList
    from meridian.teacher_navigation_choices import TeacherChoice

    choice = TeacherChoice(
        identity=(CLASS, "scoreform", "scene"),
        label="Scene Study",
        source="ScoreForm",
        status="Needs Grade Item setup",
    )
    candidate = SimpleNamespace(
        work=WORK,
        title="Scene Study",
        registration_revision=1,
        setup_state="needs_create",
        active_unlinked_grade_item_ids=(),
    )
    named = NamedAssessmentList(
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        items=(
            NamedAssessment(
                candidate,
                choice,
                "no_results_indexed",
                0,
                datetime(2026, 9, 8, tzinfo=UTC),
            ),
        ),
        choices=(choice,),
    )
    session = TeacherSessionContext(active_class_id=CLASS)
    stream = StringIO()
    commands = iter(answers)
    handler = Mock(return_value=disposition)
    period = SimpleNamespace(
        period_id=PERIOD,
        label="Marking Period 1",
        sequence=1,
        period_type="marking_period",
        lifecycle="active",
    )
    with (
        patch.object(
            discovery,
            "load_class_metadata",
            return_value=SimpleNamespace(class_id=CLASS, school_year=YEAR),
        ),
        patch.object(
            discovery,
            "load_current_academic_period_calendar",
            return_value=SimpleNamespace(school_year=YEAR, periods=(period,)),
        ),
        patch.object(discovery, "load_named_assessment_choices", return_value=named),
        patch.object(discovery, "_offer_selected_assessment_setup", handler),
    ):
        discovery.run_teacher_assessment_discovery_menu(
            session_context=session,
            input_fn=lambda _: next(commands),
            output=stream,
            clear_fn=lambda: None,
            workspace_resolver=lambda: tmp_path,
            assessment_bridge_dependencies=GuidedGradeItemBridgeDependencies(),
        )
    return stream.getvalue(), handler, session


def test_normal_discovery_S_routes_exact_work_to_correlated_review(
    tmp_path: Path,
) -> None:
    message, handler, session = _normal_discovery(
        tmp_path,
        ("1", "1", "S", ""),
        disposition=TeacherAssessmentReviewOutcome("ready", "verified"),
    )
    handler.assert_called_once()
    args = handler.call_args.args
    kwargs = handler.call_args.kwargs
    assert args[0] == tmp_path
    assert args[1] is session
    assert args[2] == WORK
    assert kwargs["year"] == YEAR
    assert kwargs["period_id"] == PERIOD
    assert kwargs["registration_revision"] == 1
    assert kwargs["setup_state"] == "needs_create"
    assert "Review setup or verify current relationship" in message


def test_cancelled_setup_returns_to_list_without_second_attempt(
    tmp_path: Path,
) -> None:
    _, handler, session = _normal_discovery(
        tmp_path,
        ("1", "1", "S", "B", "B"),
        disposition=None,
    )
    handler.assert_called_once()
    assert session.active_work is None
    assert session.active_grade_item_id is None


def test_uncertain_setup_closes_discovery_snapshot_without_retry(
    tmp_path: Path,
) -> None:
    _, handler, session = _normal_discovery(
        tmp_path,
        ("1", "1", "S", ""),
        disposition=TeacherAssessmentReviewOutcome(
            "requires_review", "canonical_unknown"
        ),
    )
    handler.assert_called_once()
    assert session.active_work is None
