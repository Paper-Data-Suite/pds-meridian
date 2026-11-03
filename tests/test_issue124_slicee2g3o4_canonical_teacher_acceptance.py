"""#124 E2G3O4: real synthetic canonical teacher setup acceptance.

The normal D -> period -> registered assessment -> S -> one APPLY path uses
real Core registration/calendar, Meridian Grade Item and membership storage,
original #122 receipts and E2C correlations. Only saved-profile lookup is
substituted with an explicit synthetic actor witness. No production workspace
or producer-owned student content is accessed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import pytest
from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.academic_work_registration_storage import write_academic_work_registration
from test_issue124_slicee2g3k_composite_canonical import (
    ACTOR,
    CLASS,
    GRADE,
    WORK,
    _all_bytes,
    _registration,
    _workspace,
)

from meridian import menu_teacher_assessment_discovery as discovery
from meridian import teacher_action_guided
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_preview import (
    AssessmentSetupPreview,
    load_assessment_setup_preview,
)
from meridian.assessment_setup_restart import inspect_stored_assessment_setup_restart
from meridian.grade_item_membership_storage import (
    list_grade_item_membership_revisions,
    load_current_grade_item_membership_decision,
)
from meridian.grade_item_storage import (
    get_current_grade_item_revision,
    list_grade_item_revisions,
)
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.menu_teacher_assessment_setup_review import (
    review_correlated_assessment_setup_once,
)
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_session import TeacherSessionContext


class _SyntheticIdentityProvider:
    """Only the saved profile's actor identity/fingerprint are injected."""

    def __init__(self, _store: object) -> None:
        pass

    def resolve_with_fingerprint(self) -> tuple[object, str]:
        return SimpleNamespace(actor_id=ACTOR.actor_id), ACTOR.profile_sha256


@dataclass
class _Journey:
    session: TeacherSessionContext
    output: str
    prompts: list[str] = field(default_factory=list)
    reviews: list[AssessmentSetupPreview] = field(default_factory=list)


def _journey(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    answers: tuple[str, ...],
    *,
    dependencies: GuidedGradeItemBridgeDependencies | None = None,
    on_confirmation: Callable[[], None] | None = None,
) -> _Journey:
    """Use the actual teacher discovery and correlated-APPLY controller."""
    monkeypatch.setattr(
        teacher_action_guided, "TeacherIdentityProvider", _SyntheticIdentityProvider
    )
    monkeypatch.setattr(discovery, "resolve_menu_actor", lambda *_: ACTOR)

    reviewed: list[AssessmentSetupPreview] = []

    def capture(*args: object, **kwargs: object) -> AssessmentSetupPreview:
        result = load_assessment_setup_preview(
            *args,
            **kwargs,  # type: ignore[arg-type]
        )
        reviewed.append(result)
        return result

    monkeypatch.setattr(discovery, "load_assessment_setup_preview", capture)
    commands = iter(answers)
    prompts: list[str] = []

    def read(prompt: str) -> str:
        prompts.append(prompt)
        answer = next(commands)
        if prompt == "Confirmation: " and on_confirmation is not None:
            on_confirmation()
        return answer

    output = StringIO()
    session = TeacherSessionContext(active_class_id=CLASS)
    discovery.run_teacher_assessment_discovery_menu(
        session_context=session,
        input_fn=read,
        output=output,
        clear_fn=lambda: None,
        workspace_resolver=lambda: root,
        assessment_bridge_dependencies=(
            GuidedGradeItemBridgeDependencies()
            if dependencies is None
            else dependencies
        ),
    )
    return _Journey(session, output.getvalue(), prompts, reviewed)


def _first_setup_answers(confirmation: str = "APPLY") -> tuple[str, ...]:
    return (
        "1",  # Marking Period 1
        "1",  # Synthetic Scene Study
        "S",  # Review setup
        "1",  # Explicit standards-proficiency purpose
        "Scene",  # Exact new title -> gi_scene
        "",  # No rationale
        ACTOR.actor_id,
        confirmation,
        "",  # Read outcome
    )


def _correlation(root: Path) -> object:
    rows = AssessmentSetupCorrelationStore(root, CLASS).list_records()
    assert len(rows) == 1
    return rows[0]


def test_teacher_menu_one_apply_creates_exact_canonical_relationship_and_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    journey = _journey(root, monkeypatch, _first_setup_answers())

    assert "Assessment relationship verified current." in journey.output
    assert journey.prompts.count("Confirmation: ") == 1
    assert len(journey.reviews) == 1
    assert journey.reviews[0].kind == "create_and_link"
    assert journey.session.active_work == WORK
    assert journey.session.active_grade_item_id == GRADE
    assert journey.session.active_publication_id is None

    assert get_current_grade_item_revision(root, CLASS, GRADE) == 1
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    decision = load_current_grade_item_membership_decision(root, CLASS, GRADE, WORK)
    assert decision is not None
    assert decision.decision.decision == "included"
    assert decision.decision.academic_period is not None
    assert decision.decision.academic_period.period.period_id == "mp1"
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == (1,)

    record = _correlation(root)
    assert record.stage == "membership_bound"
    assert record.grade_action_id is not None
    assert record.membership_action_id is not None
    assert record.grade_action_id != record.membership_action_id
    receipts = TeacherActionReceiptStore(root, CLASS).list_receipts()
    assert {item.preview.action_id for item in receipts} == {
        record.grade_action_id,
        record.membership_action_id,
    }
    restart = inspect_stored_assessment_setup_restart(root, journey.reviews[0], ACTOR)
    assert restart.disposition == "ready_verified"
    assert not restart.may_resume_automatically


def test_reopened_ready_assessment_is_a_zero_write_no_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _journey(root, monkeypatch, _first_setup_answers())
    before = _all_bytes(root)
    reopened = _journey(root, monkeypatch, ("1", "1", "S", ""))

    assert "Assessment relationship verified current." in reopened.output
    assert "Confirmation: " not in reopened.prompts
    assert len(reopened.reviews) == 1
    assert reopened.reviews[0].kind == "already_ready"
    assert reopened.session.active_work == WORK
    assert reopened.session.active_grade_item_id == GRADE
    assert _all_bytes(root) == before
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == (1,)


def test_cancel_at_complete_review_has_zero_canonical_or_receipt_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    before = _all_bytes(root)
    # B at the final confirmation, then B from the list and period screens.
    answers = (*_first_setup_answers("B")[:-1], "B", "B")
    journey = _journey(root, monkeypatch, answers)

    assert "Cancelled. No setup action requested." in journey.output
    assert journey.prompts.count("Confirmation: ") == 1
    assert journey.session.active_work is None
    assert journey.session.active_grade_item_id is None
    assert _all_bytes(root) == before
    assert list_grade_item_revisions(root, CLASS, GRADE) == ()
    assert AssessmentSetupCorrelationStore(root, CLASS).list_records() == ()


def test_registration_change_at_confirmation_blocks_before_any_action_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)

    def change_registration() -> None:
        write_academic_work_registration(
            root, _registration(2), expected_current_revision=1
        )
        rebuild_academic_catalog(root)

    journey = _journey(
        root,
        monkeypatch,
        _first_setup_answers(),
        on_confirmation=change_registration,
    )
    assert "Assessment setup is not verified ready." in journey.output
    assert journey.session.active_work is None
    assert list_grade_item_revisions(root, CLASS, GRADE) == ()
    assert AssessmentSetupCorrelationStore(root, CLASS).list_records() == ()
    assert TeacherActionReceiptStore(root, CLASS).list_receipts() == ()


def _selection_unavailable(*_args: object, **_kwargs: object) -> NoReturn:
    raise RuntimeError("Synthetic selection interruption after immutable write")


@pytest.mark.parametrize("interrupted", ["grade", "membership"])
def test_interrupted_original_action_cannot_be_recreated_or_claimed_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: str
) -> None:
    root = _workspace(tmp_path)
    default = GuidedGradeItemBridgeDependencies()
    if interrupted == "grade":
        from dataclasses import replace

        broken = replace(default, grade_item_selection_committer=_selection_unavailable)
    else:
        from dataclasses import replace

        broken = replace(default, membership_selection_committer=_selection_unavailable)

    journey = _journey(root, monkeypatch, _first_setup_answers(), dependencies=broken)
    assert "Assessment setup is not verified ready." in journey.output
    assert journey.session.active_work is None
    assert journey.session.active_grade_item_id is None
    assert len(journey.reviews) == 1
    original_review = journey.reviews[0]

    correlation = _correlation(root)
    assert correlation.grade_action_id is not None
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    if interrupted == "grade":
        assert correlation.stage == "grade_bound"
        assert correlation.membership_action_id is None
        assert get_current_grade_item_revision(root, CLASS, GRADE) is None
        assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == ()
        expected = "original_grade_action_pending"
    else:
        assert correlation.stage == "membership_bound"
        assert correlation.membership_action_id is not None
        assert get_current_grade_item_revision(root, CLASS, GRADE) == 1
        assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == (1,)
        assert (
            load_current_grade_item_membership_decision(root, CLASS, GRADE, WORK)
            is None
        )
        expected = "original_membership_action_pending"
    observed = inspect_stored_assessment_setup_restart(root, original_review, ACTOR)
    assert observed.disposition == expected
    assert not observed.may_resume_automatically

    # The same reviewed action cannot be reintroduced as a fresh APPLY after
    # an interrupted original attempt. No fresh prepared #122 IDs are issued.
    before = _all_bytes(root)
    input_called = False

    def forbidden_input(_prompt: str) -> str:
        nonlocal input_called
        input_called = True
        raise AssertionError("No duplicate APPLY prompt is authorized")

    outcome = review_correlated_assessment_setup_once(
        root,
        original_review,
        TeacherSessionContext(active_class_id=CLASS),
        actor=ACTOR,
        dependencies=default,
        input_fn=forbidden_input,
        output=StringIO(),
    )
    assert outcome.status == "requires_review"
    assert outcome.reason == "prior_correlated_action_requires_recovery"
    assert not input_called
    assert _all_bytes(root) == before


def test_cancel_before_purpose_choice_has_no_canonical_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    before = _all_bytes(root)
    journey = _journey(root, monkeypatch, ("1", "1", "S", "B", "B", "B"))
    assert "Choose Grade Item Purpose" in journey.output
    assert journey.session.active_work is None
    assert _all_bytes(root) == before
    assert AssessmentSetupCorrelationStore(root, CLASS).list_records() == ()
