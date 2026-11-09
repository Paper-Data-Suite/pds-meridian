"""#125-H3A1: mixed-status safety, exact exceptions, terminal navigation.

These are synthetic regression tests, not a claim that all H3 acceptance is
complete. Native installed-producer and full-scale writes remain separate gates.
"""

from __future__ import annotations

import io
from collections import Counter
from dataclasses import replace

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from test_issue125_sliceb_assessment_projection import (
    eligibility_row,
    project,
    roster,
    student,
)
from test_issue125_slicef1_assessment_menu import (
    inputs,
    ui,
)
from test_issue125_slicef1_assessment_menu import (
    review as menu_review,
)
from test_issue125_slicef2_teacher_hardening import prior_decision

import meridian.assessment_eligibility_review as projection
import meridian.menu_teacher_assessment_eligibility as menu


def _mixed_review() -> projection.AssessmentEligibilityReview:
    unsupported = replace(
        eligibility_row("student_02", 2, status="unsupported"),
        selected_eligibility_revision=1,
        selected_eligibility_disposition="unsupported",
    )
    rows = (
        eligibility_row("student_01", 1),
        eligibility_row("student_01", 2, status="excluded"),
        eligibility_row("student_01", 3, status="included", operative=True),
        eligibility_row("student_01", 4, status="included"),
        eligibility_row("student_02", 1, status="pending"),
        unsupported,
        eligibility_row("student_03", 1, item_id="first_q1"),
        eligibility_row("student_03", 1, item_id="second_q1"),
        eligibility_row("non_roster_id", 3),
        eligibility_row(None, 4),
    )
    return project(rows, roster(*(student(i) for i in range(1, 5))))


def test_mixed_statuses_preserve_every_distinct_exception() -> None:
    view = _mixed_review()
    assert view.projected_item_count == 10
    assert len(view.students) == 4
    assert view.no_result_student_count == 1
    assert view.candidate_item_count == 1
    assert len(view.shared_items) == 1
    assert len(view.unmatched_items) == 1
    codes = Counter(issue.code for issue in view.exceptions)
    assert codes == {
        "previous_excluded": 1,
        "previous_pending": 1,
        "previous_unsupported": 1,
        "included_not_operative": 1,
        "multiple_items_same_native_target": 2,
        "unknown_roster_student": 1,
        "non_student_evidence": 1,
        "no_result_in_publication": 1,
    }
    assert {
        issue.route
        for issue in view.exceptions
        if issue.code.startswith("multiple_items_same_native_target")
    } == {"review-attempts"}


def test_exception_summary_precedes_roster_and_hides_source_ids() -> None:
    view = _mixed_review()
    text = projection.render_assessment_eligibility_preview(view)
    assert text.index("EXCEPTIONS — REVIEW BEFORE ANY BATCH ACTION") < text.index(
        "ROSTER COVERAGE AND CURRENT ELIGIBILITY"
    )
    assert "No result returned in this publication (not a zero)." in text
    assert "SHARED / NON-STUDENT EVIDENCE" in text
    assert "UNMATCHED STUDENT ATTRIBUTION" in text
    for item_id in ("first_q1", "second_q1", "non_roster_id"):
        assert item_id not in text
    assert "No grades, missing-result zeros" in text


def test_all_selects_only_one_safe_item_in_mixed_review() -> None:
    view = _mixed_review()
    assert menu._choose_source_ids(view, input_fn=inputs("A"), **ui()) == (
        "student_01_question_1",
    )
    assert menu._enumerate_replaceable(view) == (
        ("student_01_question_2", "Sample1 Student", "Question 2"),
        ("student_01_question_3", "Sample1 Student", "Question 3"),
        ("student_02_question_1", "Sample2 Student", "Question 1"),
        ("student_02_question_2", "Sample2 Student", "Question 2"),
    )


@pytest.mark.parametrize("status", ("withdrawn", "superseded", "stale"))
def test_noncurrent_source_blocks_all_candidates(status: str) -> None:
    view = project(
        (eligibility_row("student_01", 1),),
        roster(student(1)),
        source_status=status,
    )
    assert view.candidate_item_count == 0
    assert {e.code for e in view.exceptions} == {"source_not_current"}
    assert menu._enumerate_candidates(view) == ()
    assert menu._choose_source_ids(view, input_fn=inputs(""), **ui()) is None


@pytest.mark.parametrize("membership", ("no_decision", "excluded"))
def test_nonincluded_membership_never_yields_safe_candidate(
    membership: str,
) -> None:
    row = eligibility_row("student_01", 1, membership=membership)
    view = project((row,), roster(student(1)))
    assert view.candidate_item_count == 0
    assert "membership_" + membership in {e.code for e in view.exceptions}
    assert menu._enumerate_candidates(view) == ()


def test_invalid_membership_state_is_rejected_by_domain_model() -> None:
    from meridian.new_evidence_workflow import NewEvidenceWorkflowScopeError

    with pytest.raises(
        NewEvidenceWorkflowScopeError, match="membership_state is invalid"
    ):
        eligibility_row("student_01", 1, membership="stale")


def test_no_decision_with_selected_pointer_is_not_a_candidate() -> None:
    row = replace(
        eligibility_row("student_01", 1),
        selected_eligibility_revision=7,
    )
    view = project((row,), roster(student(1)))
    assert view.candidate_item_count == 0
    assert "eligibility_resolution_inconsistent" in {e.code for e in view.exceptions}


@pytest.mark.parametrize("status", ("included", "excluded", "pending"))
def test_selected_status_without_revision_is_not_replaceable(
    status: str,
) -> None:
    row = replace(
        eligibility_row("student_01", 1, status=status),
        selected_eligibility_revision=None,
    )
    view = project((row,), roster(student(1)))
    assert view.candidate_item_count == 0
    assert "eligibility_selection_unverifiable" in {e.code for e in view.exceptions}
    assert menu._enumerate_replaceable(view) == ()


def test_same_native_target_with_different_result_kinds_is_not_duplicate() -> None:
    first = eligibility_row("student_01", 1, item_id="first_kind")
    second = replace(
        eligibility_row("student_01", 1, item_id="second_kind"),
        result_kind="answer",
    )
    view = project((first, second), roster(student(1)))
    assert view.candidate_item_count == 2
    assert "multiple_items_same_native_target" not in {
        issue.code for issue in view.exceptions
    }


def test_duplicate_same_kind_blocks_both_native_targets() -> None:
    rows = (
        eligibility_row("student_01", 1, item_id="attempt_one"),
        eligibility_row("student_01", 1, item_id="attempt_two"),
        eligibility_row("student_01", 2),
    )
    view = project(rows, roster(student(1)))
    assert {x[0] for x in menu._enumerate_candidates(view)} == {"student_01_question_2"}
    assert (
        sum(e.code == "multiple_items_same_native_target" for e in view.exceptions) == 2
    )


def test_one_student_scope_never_selects_unauthorized_peers() -> None:
    view = menu_review(29, 6)
    view.students[3].within_requested_authorization = False
    selected = menu._choose_source_ids(view, input_fn=inputs("A"), **ui())
    assert selected is not None and len(selected) == 168
    assert not any(item_id.startswith("s4-") for item_id in selected)


def test_exact_overrides_leave_unselected_peers_unchanged() -> None:
    view = menu_review(2, 2)
    selection = ("s1-q1", "s1-q2", "s2-q1")
    result = menu._exceptions(
        view,
        selection,
        input_fn=inputs("1", "1", "2", "2", "3", "D", "D"),
        **ui(),
    )
    assert result is not None
    students, items = result
    assert len(students) == len(items) == 1
    assert students[0].student_id == "s1"
    assert students[0].disposition == "excluded"
    assert items[0].item_id == "s2-q1"
    assert items[0].disposition is None
    assert "s2-q2" not in selection


@pytest.mark.parametrize("status", ("included", "excluded", "pending", "unsupported"))
def test_prior_decisions_require_explicit_replacement(status: str) -> None:
    view = prior_decision(status=status)
    assert menu._enumerate_candidates(view) == ()
    assert menu._choose_source_ids(view, input_fn=inputs("E", "1", "D"), **ui()) == (
        "s1-q1",
    )
    assert menu._choose_source_ids(view, input_fn=inputs("A", "", "B"), **ui()) is None


@pytest.mark.parametrize(
    ("raw", "error"),
    (("M", ReturnToMainMenu), ("Q", QuitPDS)),
)
def test_shared_main_and_quit_unwind_instead_of_selecting(
    raw: str, error: type[Exception]
) -> None:
    with pytest.raises(error):
        menu._choose_source_ids(menu_review(1, 1), input_fn=inputs(raw), **ui())
    with pytest.raises(error):
        menu._choose_paged_items(
            menu._enumerate_candidates(menu_review(1, 1)),
            input_fn=inputs(raw),
            **ui(),
        )


def test_notes_text_is_not_a_bulk_confirmation() -> None:
    output = io.StringIO()
    selected = menu._choose_source_ids(
        menu_review(1, 1),
        input_fn=inputs(":notes", "", "B"),
        output=output,
        clear_fn=lambda: None,
    )
    assert selected is None
    assert "Choose A, S, I, E, R, V, B, M, or Q." in output.getvalue()
    assert menu._numbers(":notes", 2, allow_many=True) is None


def test_no_color_plain_text_still_exposes_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    stream = io.StringIO()
    assert (
        menu._choose_source_ids(
            menu_review(1, 1),
            input_fn=inputs("B"),
            output=stream,
            clear_fn=lambda: None,
        )
        is None
    )
    text = stream.getvalue()
    assert "Meridian" in text and "B. Back" in text
    assert "M. Main Menu" in text and "Q. Quit" in text
    assert "\x1b[" not in text


def test_undisplayed_page_selection_cannot_choose_hidden_item() -> None:
    view = menu_review(5, 6)
    text = io.StringIO()
    result = menu._choose_source_ids(
        view,
        input_fn=inputs("I", "21", "", "B", "B"),
        output=text,
        clear_fn=lambda: None,
    )
    assert result is None
    assert "Use listed item numbers" in text.getvalue()
