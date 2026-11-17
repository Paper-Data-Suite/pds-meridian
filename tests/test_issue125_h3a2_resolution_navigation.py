"""#125-H3A2: fail-closed selected eligibility and nested menu boundaries.

All records and teacher inputs are synthetic. These tests do not authorize
academic action, change a producer source, or claim native 174-item writes.
"""

from __future__ import annotations

import io
from dataclasses import replace

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from test_issue125_sliceb_assessment_projection import (
    eligibility_row,
    project,
    roster,
    student,
)
from test_issue125_slicef1_assessment_menu import inputs, ui
from test_issue125_slicef1_assessment_menu import review as menu_review

import meridian.assessment_eligibility_review as projection
import meridian.menu_teacher_assessment_eligibility as menu


def _row_with_pointer(status: str, selection: str, *, operative: bool = False):
    """Model a contradictory projection; native authoring cannot produce it."""
    return replace(
        eligibility_row("student_01", 1, status="included"),
        eligibility_status=status,
        selected_eligibility_revision=7,
        selected_eligibility_disposition=selection,
        operative_included=operative,
    )


@pytest.mark.parametrize(
    ("displayed", "selected"),
    (
        ("included", "excluded"),
        ("excluded", "included"),
        ("pending", "excluded"),
        ("unsupported", "pending"),
    ),
)
def test_status_disagreeing_with_selected_pointer_is_stop(
    displayed: str, selected: str
) -> None:
    view = project((_row_with_pointer(displayed, selected),), roster(student(1)))
    item = view.students[0].items[0]
    assert any(
        issue.code == "eligibility_resolution_inconsistent" and issue.route == "stop"
        for issue in item.exceptions
    )
    assert item.candidate_for_explicit_review is False
    assert view.candidate_item_count == 0
    assert menu._enumerate_candidates(view) == ()
    assert menu._enumerate_replaceable(view) == ()
    rendered = projection.render_assessment_eligibility_preview(view)
    assert "eligibility resolution inconsistent" in rendered


@pytest.mark.parametrize(
    "displayed", ("no_decision", "excluded", "pending", "unsupported")
)
def test_nonincluded_status_cannot_be_operative(displayed: str) -> None:
    if displayed == "no_decision":
        row = replace(eligibility_row("student_01", 1), operative_included=True)
    else:
        row = _row_with_pointer(displayed, displayed, operative=True)
    view = project((row,), roster(student(1)))
    assert any(
        issue.code == "eligibility_resolution_inconsistent" and issue.route == "stop"
        for issue in view.students[0].items[0].exceptions
    )
    assert menu._enumerate_candidates(view) == ()
    assert menu._enumerate_replaceable(view) == ()


@pytest.mark.parametrize("status", ("included", "excluded", "pending", "unsupported"))
def test_consistent_selected_status_remains_reviewable(status: str) -> None:
    row = _row_with_pointer(status, status, operative=(status == "included"))
    view = project((row,), roster(student(1)))
    assert not any(
        issue.code == "eligibility_resolution_inconsistent" for issue in view.exceptions
    )
    assert menu._enumerate_replaceable(view) == (
        ("student_01_question_1", "Sample1 Student", "Question 1"),
    )
    assert menu._enumerate_candidates(view) == ()


def test_source_lifecycle_selection_is_not_an_eligibility_override() -> None:
    row = _row_with_pointer("included", "withdrawn")
    view = project((row,), roster(student(1)))
    codes = {issue.code for issue in view.exceptions}
    assert "source_lifecycle_decision" in codes
    assert "eligibility_resolution_inconsistent" in codes
    assert menu._enumerate_replaceable(view) == ()


def test_denied_prepared_object_never_reaches_core_roster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_roster(*args: object, **kwargs: object) -> None:
        raise AssertionError("Authorization must precede roster reads")

    monkeypatch.setattr(projection, "load_class_roster", unexpected_roster)
    with pytest.raises(
        projection.AssessmentEligibilityReviewScopeError,
        match="Expected an authorized GuidedProjectionResult",
    ):
        projection.project_assessment_eligibility_review(
            ".", grade_item_id="grade_125", prepared=object()
        )


@pytest.mark.parametrize(
    ("choice", "exception"),
    (("M", ReturnToMainMenu), ("Q", QuitPDS)),
)
def test_shared_navigation_unwinds_all_nested_exception_prompts(
    choice: str, exception: type[Exception]
) -> None:
    with pytest.raises(exception):
        menu._numbers(choice, 2, allow_many=False)
    with pytest.raises(exception):
        menu._choose_exception_target(
            ("One student", "Two students"), input_fn=inputs(choice), **ui()
        )
    with pytest.raises(exception):
        menu._choice_or_defer(input_fn=inputs(choice), **ui())
    with pytest.raises(exception):
        menu._exceptions(
            menu_review(1, 1),
            ("s1-q1",),
            input_fn=inputs(choice),
            **ui(),
        )


def test_notes_in_paged_selection_never_selects_an_item() -> None:
    output = io.StringIO()
    candidates = menu._enumerate_candidates(menu_review(2, 1))
    result = menu._choose_paged_items(
        candidates,
        input_fn=inputs(":notes", "", "B"),
        output=output,
        clear_fn=lambda: None,
    )
    assert result is None
    assert "Use listed item numbers" in output.getvalue()


def test_exact_item_unsupported_override_does_not_expand() -> None:
    chosen = menu._exceptions(
        menu_review(2, 2),
        ("s1-q1", "s2-q1"),
        input_fn=inputs("2", "1", "4", "D"),
        **ui(),
    )
    assert chosen is not None
    students, items = chosen
    assert students == ()
    assert len(items) == 1
    assert items[0].item_id == "s1-q1"
    assert items[0].disposition == "unsupported"
    assert items[0].reason_codes == ("eligibility.manual",)
    assert items[0].replace_existing is False


def test_whole_student_pending_override_is_bounded_to_selected_items() -> None:
    chosen = menu._exceptions(
        menu_review(2, 2),
        ("s1-q1", "s1-q2", "s2-q1"),
        input_fn=inputs("1", "1", "3", "D"),
        **ui(),
    )
    assert chosen is not None
    students, items = chosen
    assert len(students) == 1 and items == ()
    assert students[0].student_id == "s1"
    assert students[0].disposition == "pending"
    assert students[0].reason_codes == ("eligibility.manual",)
    # The exception is a choice over the exact *selected* item set;
    # it cannot authorize a future or unselected source publication.
    assert "s2-q2" not in ("s1-q1", "s1-q2", "s2-q1")


def test_notes_in_disposition_prompt_does_not_make_a_decision() -> None:
    assert menu._choice_or_defer(input_fn=inputs(":notes"), **ui()) == "back"
    assert menu._choice_or_defer(input_fn=inputs("APPLY"), **ui()) == "back"


def test_no_color_nested_exception_review_is_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    output = io.StringIO()
    assert (
        menu._exceptions(
            menu_review(1, 1),
            ("s1-q1",),
            input_fn=inputs("B"),
            output=output,
            clear_fn=lambda: None,
        )
        is None
    )
    text = output.getvalue()
    assert "Batch Exceptions" in text and "B. Cancel this batch" in text
    assert "\x1b[" not in text
