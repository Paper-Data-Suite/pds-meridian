"""#124 E2G3O6: teacher input benchmark over real synthetic canonical stores.

These tests measure the currently implemented D -> period -> assessment -> S
route, not historical input counts or the still-unqualified five-wheel install.
"""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.academic_work_registration_storage import write_academic_work_registration
from test_issue124_slicee2g3k_composite_canonical import (
    CLASS,
    GRADE,
    WORK,
    _all_bytes,
    _registration,
    _workspace,
)
from test_issue124_slicee2g3o4_canonical_teacher_acceptance import (
    _first_setup_answers,
    _journey,
)
from test_issue124_slicee2g3o5_published_existing_acceptance import (
    _existing,
    _existing_answers,
    _publish,
)

from meridian import menu_teacher_assessment_discovery as discovery
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.grade_item_membership_storage import (
    list_grade_item_membership_revisions,
)
from meridian.grade_item_storage import list_grade_item_revisions
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_session import TeacherSessionContext

FORBIDDEN_ACADEMIC_PROMPTS = (
    "registration revision:",
    "publication id:",
    "publication digest:",
    "grade item id:",
    "grade item revision:",
    "membership revision:",
    "record sha256:",
    "moduleworkref:",
)


def _assert_one_reviewed_confirmation(prompts: list[str], expected_total: int) -> None:
    assert len(prompts) == expected_total
    assert prompts.count("Confirmation: ") == 1
    assert not any(
        keyword in prompt.casefold()
        for keyword in FORBIDDEN_ACADEMIC_PROMPTS
        for prompt in prompts
    )


def test_create_and_link_teacher_interaction_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    journey = _journey(root, monkeypatch, _first_setup_answers())
    _assert_one_reviewed_confirmation(journey.prompts, 9)
    assert "Assessment relationship verified current." in journey.output
    assert journey.session.active_work == WORK
    assert journey.session.active_grade_item_id == GRADE
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == (1,)


def test_published_assessment_does_not_add_teacher_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    published = _publish(root)
    journey = _journey(root, monkeypatch, _first_setup_answers())
    _assert_one_reviewed_confirmation(journey.prompts, 9)
    assert journey.session.active_publication_id == published.publication_id
    assert "Assessment relationship verified current." in journey.output


def test_existing_grade_item_link_teacher_interaction_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _existing(root)
    journey = _journey(root, monkeypatch, _existing_answers())
    _assert_one_reviewed_confirmation(journey.prompts, 8)
    assert journey.reviews[0].kind == "use_existing"
    assert journey.session.active_grade_item_id == GRADE
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == (1,)


def test_already_ready_has_four_inputs_and_no_confirmation_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _journey(root, monkeypatch, _first_setup_answers())
    before = _all_bytes(root)
    reopened = _journey(root, monkeypatch, ("1", "1", "S", ""))
    assert len(reopened.prompts) == 4
    assert reopened.prompts.count("Confirmation: ") == 0
    assert reopened.reviews[0].kind == "already_ready"
    assert reopened.session.active_work == WORK
    assert reopened.session.active_grade_item_id == GRADE
    assert _all_bytes(root) == before


def test_stale_registration_at_confirmation_has_no_duplicate_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)

    def drift() -> None:
        write_academic_work_registration(
            root, _registration(2), expected_current_revision=1
        )
        rebuild_academic_catalog(root)

    journey = _journey(
        root,
        monkeypatch,
        _first_setup_answers(),
        on_confirmation=drift,
    )
    _assert_one_reviewed_confirmation(journey.prompts, 9)
    assert "Assessment setup is not verified ready." in journey.output
    assert journey.session.active_grade_item_id is None
    assert list_grade_item_revisions(root, CLASS, GRADE) == ()
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == ()
    assert TeacherActionReceiptStore(root, CLASS).list_receipts() == ()
    assert AssessmentSetupCorrelationStore(root, CLASS).list_records() == ()


def test_ambiguous_setup_hint_refused_without_confirmation_or_write(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    before = _all_bytes(root)
    prompts: list[str] = []
    output = StringIO()

    def no_prompt(prompt: str) -> str:
        prompts.append(prompt)
        raise AssertionError("Ambiguous setup must not request input")

    outcome = discovery._offer_selected_assessment_setup(
        root,
        TeacherSessionContext(active_class_id=CLASS),
        WORK,
        year="2026-2027",
        period_id="mp1",
        registration_revision=1,
        setup_state="ambiguous",
        active_unlinked_ids=(),
        dependencies=GuidedGradeItemBridgeDependencies(),
        input_fn=no_prompt,
        output=output,
    )
    assert outcome is not None
    assert outcome.status == "requires_review"
    assert outcome.reason == "discovery_scope_or_relationship_requires_review"
    assert prompts == []
    assert _all_bytes(root) == before


def test_cancelled_registration_is_not_an_automatic_setup_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    write_academic_work_registration(
        root,
        replace(_registration(2), lifecycle="cancelled"),
        expected_current_revision=1,
    )
    rebuild_academic_catalog(root)
    before = _all_bytes(root)
    journey = _journey(root, monkeypatch, ("1", "1", "S", ""))
    assert "Cancelled registration" in journey.output
    assert "Assessment setup could not be verified safely." in journey.output
    assert "Confirmation: " not in journey.prompts
    assert journey.session.active_work is None
    assert _all_bytes(root) == before
    assert TeacherActionReceiptStore(root, CLASS).list_receipts() == ()
