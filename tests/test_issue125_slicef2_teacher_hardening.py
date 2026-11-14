"""#125-F2: explicit prior-decision replacement and restart navigation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from test_issue125_slicef1_assessment_menu import inputs, review, ui

import meridian.menu_teacher_assessment_eligibility as menu


def prior_decision(
    student: int = 1, question: int = 1, *, status: str = "excluded"
) -> SimpleNamespace:
    r = review(student, question, safe=False)
    candidate = r.students[student - 1].items[question - 1]
    candidate.eligibility_status = status
    candidate.selected_eligibility_revision = 1
    candidate.selected_eligibility_disposition = status
    candidate.exceptions = (SimpleNamespace(code=f"previous_{status}"),)
    return r


def test_prior_decision_requires_explicit_opt_in() -> None:
    r = prior_decision()
    assert menu._enumerate_candidates(r) == ()
    assert menu._enumerate_replaceable(r) == (
        ("s1-q1", "Sample Student 1", "Question 1"),
    )
    assert menu._choose_source_ids(r, input_fn=inputs("A", "", "B"), **ui()) is None


@pytest.mark.parametrize("status", ["excluded", "pending", "unsupported", "included"])
def test_four_selected_dispositions_can_be_explicitly_reviewed(status: str) -> None:
    r = prior_decision(status=status)
    assert menu._choose_source_ids(r, input_fn=inputs("E", "1", "D"), **ui()) == (
        "s1-q1",
    )


@pytest.mark.parametrize(
    "exception_code",
    [
        "source_not_current",
        "multiple_items_same_native_target",
        "unknown_roster_student",
        "membership_no_decision",
    ],
)
def test_unsafe_prior_decision_not_offered(exception_code: str) -> None:
    r = prior_decision()
    r.students[0].items[0].exceptions = (SimpleNamespace(code=exception_code),)
    assert menu._enumerate_replaceable(r) == ()


@pytest.mark.parametrize("status", ["superseded", "withdrawn", "membership_stale"])
def test_non_teacher_status_never_offered_for_replacement(status: str) -> None:
    r = prior_decision(status=status)
    assert menu._enumerate_replaceable(r) == ()


def test_prior_decision_outside_authorization_not_offered() -> None:
    r = prior_decision()
    r.students[0].within_requested_authorization = False
    assert menu._enumerate_replaceable(r) == ()


def test_stale_publication_or_membership_hides_prior_decisions() -> None:
    r = prior_decision()
    r.source_status = "superseded"
    assert menu._enumerate_replaceable(r) == ()
    r.source_status = "current"
    r.membership_state = "no_decision"
    assert menu._enumerate_replaceable(r) == ()


def test_existing_replacement_requires_exact_item_opt_in() -> None:
    r = prior_decision()
    result = menu._exceptions(
        r, ("s1-q1",), input_fn=inputs("D"), common="included", **ui()
    )
    assert result is not None
    students, items = result
    assert students == ()
    assert len(items) == 1
    assert items[0].item_id == "s1-q1"
    assert items[0].disposition == "included"
    assert items[0].reason_codes == ()
    assert items[0].replace_existing is True


def test_replacement_preserves_explicit_item_exception() -> None:
    r = prior_decision()
    result = menu._exceptions(
        r,
        ("s1-q1",),
        input_fn=inputs("2", "1", "3", "D"),
        common="excluded",
        common_reason_codes=("eligibility.manual",),
        **ui(),
    )
    assert result is not None
    item = result[1][0]
    assert item.disposition == "pending"
    assert item.reason_codes == ("eligibility.manual",)
    assert item.replace_existing


def test_replacement_can_use_student_override_but_stays_exact() -> None:
    r = prior_decision()
    result = menu._exceptions(
        r, ("s1-q1",), input_fn=inputs("1", "1", "2", "D"), common="included", **ui()
    )
    assert result is not None
    assert result[0][0].disposition == "excluded"
    assert result[0][0].replace_existing
    assert result[1] == ()


def test_back_from_replacement_review_creates_no_plan() -> None:
    r = prior_decision()
    assert menu._exceptions(r, ("s1-q1",), input_fn=inputs("B"), **ui()) is None


def test_only_visible_item_page_numbers_are_selectable() -> None:
    rows = menu._enumerate_candidates(review(5, 6))
    result = menu._choose_paged_items(
        rows, input_fn=inputs("21", "", "N", "21", "D"), **ui()
    )
    assert result == (rows[20][0],)


def test_only_visible_exception_page_numbers_are_selectable() -> None:
    labels = tuple(f"Student {i}" for i in range(1, 30))
    selected = menu._choose_exception_target(
        labels, input_fn=inputs("25", "", "N", "25"), **ui()
    )
    assert selected == 24


def test_large_class_student_picker_pages_and_limits_choice() -> None:
    r = review(29, 6)
    selected = menu._choose_source_ids(r, input_fn=inputs("S", "N", "25", "D"), **ui())
    assert selected == tuple(f"s25-q{i}" for i in range(1, 7))


def test_recovery_can_be_entered_without_new_candidates() -> None:
    r = review(1, 1, safe=False)
    calls: list[str] = []
    result = menu._choose_source_ids(
        r,
        input_fn=inputs("R", "B"),
        recovery_handler=lambda: calls.append("opened"),
        **ui(),
    )
    assert calls == ["opened"]
    assert result is None


def test_recovery_without_handler_never_runs() -> None:
    r = review(1, 1, safe=False)
    assert menu._choose_source_ids(r, input_fn=inputs("R", "B"), **ui()) is None


def test_recovery_routes_to_existing_exact_receipt_inbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        menu, "run_teacher_action_recovery_menu", lambda **k: calls.append(k)
    )
    root = Path("/synthetic/workspace")
    session = object()
    diagnostics = object()
    menu._open_restart_recovery(
        root,
        cast(object, session),
        cast(object, diagnostics),
        input_fn=inputs("B"),
        **ui(),
    )
    assert len(calls) == 1
    args = cast(dict[str, object], calls[0])
    assert args["workspace_resolver"]() == root
    assert args["session_context"] is session
    assert args["diagnostics"] is diagnostics


def test_single_source_and_empty_candidate_group_never_guessed() -> None:
    r = review(1, 1, safe=False)
    assert menu._choose_source_ids(r, input_fn=inputs("B"), **ui()) is None


def test_deferred_existing_item_never_requests_replacement() -> None:
    r = prior_decision()
    result = menu._exceptions(
        r, ("s1-q1",), input_fn=inputs("2", "1", "D", "D"), **ui()
    )
    assert result is not None
    assert result[1][0].disposition is None
    assert result[1][0].replace_existing is False


def test_deferred_existing_student_never_requests_replacement() -> None:
    r = prior_decision()
    result = menu._exceptions(
        r, ("s1-q1",), input_fn=inputs("1", "1", "D", "D"), **ui()
    )
    assert result is not None
    assert result[0][0].disposition is None
    assert result[0][0].replace_existing is False
