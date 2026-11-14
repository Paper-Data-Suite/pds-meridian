"""#125-H3D5: denied/unsupported/status routing and terminal fallback regression.

Synthetic identities only; this is read-only qualification, not a new grant,
academic write, Notes service, or interprocess CAS/locked-store claim.
"""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from test_issue125_h3d3_exception_queue_navigation import _with_issues
from test_issue125_sliceb_assessment_projection import (
    eligibility_row,
    project,
    roster,
    student,
)
from test_issue125_slicef1_assessment_menu import inputs, ui

import meridian.menu_teacher_assessment_eligibility as menu


def _render(value: object, *answers: str) -> str:
    output = StringIO()
    assert menu._review_exception_queue(
        cast(object, value),
        input_fn=inputs(*(answers or ("D",))),
        output=output,
        clear_fn=lambda: None,
        force=True,
    )
    return output.getvalue()


def _row_with_teacher_status(question: int, status: str) -> object:
    row = eligibility_row("student_01", question, status=status)
    if status == "unsupported":
        return replace(
            row,
            selected_eligibility_revision=1,
            selected_eligibility_disposition="unsupported",
        )
    return row


def test_distinct_current_statuses_are_neither_missing_nor_grades() -> None:
    statuses = ("no_decision", "included", "excluded", "pending", "unsupported")
    rows = tuple(
        _row_with_teacher_status(number, status)
        for number, status in enumerate(statuses, start=1)
    )
    result = project(rows, roster(student(1)))
    output = _render(result)
    for status in statuses:
        assert f"eligibility {status.replace('_', ' ')}: 1" in output
    assert "No result (never zero): 0" in output
    assert "Current evidence status counts (not grades)" in output
    assert "Review existing eligibility" in output
    assert menu._enumerate_candidates(result) == (
        (
            rows[0].source.item_id,
            result.students[0].display_label,
            result.students[0].items[0].evidence_label,
        ),
    )


def test_no_returned_result_is_not_unsupported_or_zero() -> None:
    row = _row_with_teacher_status(1, "unsupported")
    result = project((row,), roster(student(1), student(2)))
    output = _render(result)
    assert "No result (never zero): 1" in output
    assert "eligibility unsupported: 1" in output
    assert "No academic records or eligibility decisions have been changed" in output
    assert "Sample2 Student" in output or "Sample2" in output
    assert menu._enumerate_candidates(result) == ()


def test_withdrawn_source_never_becomes_batch_eligible() -> None:
    result = project(
        (eligibility_row("student_01", 1),),
        roster(student(1)),
        source_status="withdrawn",
    )
    output = _render(result)
    assert "Source: withdrawn" in output
    assert "source not current" in output
    assert "Review source/publication" in output
    assert menu._enumerate_candidates(result) == ()
    assert menu._enumerate_replaceable(result) == ()


def test_membership_not_included_routes_to_grade_item_setup() -> None:
    result = project(
        (eligibility_row("student_01", 1, membership="no_decision"),),
        roster(student(1)),
    )
    output = _render(result)
    assert "membership no decision" in output
    assert "Review Grade Item setup" in output
    assert menu._enumerate_candidates(result) == ()


def test_conflicting_selection_history_is_stop_not_replacement() -> None:
    row = eligibility_row("student_01", 1, status="excluded")
    changed = replace(row, selected_eligibility_disposition="included")
    result = project((changed,), roster(student(1)))
    output = _render(result)
    assert "eligibility resolution inconsistent" in output
    assert "Stop; inspect exact source integrity" in output
    assert menu._enumerate_candidates(result) == ()
    assert menu._enumerate_replaceable(result) == ()


def test_competing_attempts_are_not_silently_chosen() -> None:
    rows = (
        eligibility_row("student_01", 1, item_id="RAW_ATTEMPT_ONE"),
        eligibility_row("student_01", 1, item_id="RAW_ATTEMPT_TWO"),
        eligibility_row("student_01", 2),
    )
    result = project(rows, roster(student(1)))
    output = _render(result)
    assert "multiple items same native target" in output
    assert "Review attempts (#126)" in output
    assert "RAW_ATTEMPT_ONE" not in output
    assert "RAW_ATTEMPT_TWO" not in output
    assert len(menu._enumerate_candidates(result)) == 1


def test_unknown_roster_evidence_is_exposed_without_fake_attribution() -> None:
    rows = (
        eligibility_row("student_01", 1),
        eligibility_row("RAW_UNKNOWN_STUDENT", 2, item_id="RAW_UNKNOWN_ITEM"),
    )
    result = project(rows, roster(student(1)))
    output = _render(result)
    assert "unknown roster student" in output
    assert "Review Core roster" in output
    assert "Unmatched/shared evidence" in output
    assert "RAW_UNKNOWN_STUDENT" not in output
    assert "RAW_UNKNOWN_ITEM" not in output
    assert len(menu._enumerate_candidates(result)) == 1


def test_nonstudent_evidence_never_mapped_to_roster_member() -> None:
    row = eligibility_row(None, 1, item_id="RAW_GROUP_ITEM")
    result = project((row,), roster(student(1)))
    output = _render(result)
    assert "non student evidence" in output
    assert "Review individual evidence" in output
    assert "shared/non-student: 1" in output
    assert "RAW_GROUP_ITEM" not in output
    assert menu._enumerate_candidates(result) == ()


@pytest.mark.parametrize(
    ("route", "display"),
    (
        ("review-source", "Review source/publication"),
        ("review-roster", "Review Core roster"),
        ("grade-items", "Review Grade Item setup"),
        ("review-eligibility", "Review existing eligibility"),
        ("review-attempts", "Review attempts (#126)"),
        ("review-individual", "Review individual evidence"),
        ("stop", "Stop; inspect exact source integrity"),
    ),
)
def test_each_exception_route_has_actionable_teacher_label(
    route: str, display: str
) -> None:
    result = _with_issues(0)
    result.exceptions = (
        SimpleNamespace(
            code="synthetic_condition",
            route=route,
            student_id="s1",
            source=result.students[0].items[0].source,
        ),
    )
    result.exception_count = 1
    output = _render(result)
    assert display in output
    assert "s1-q1" not in output


@pytest.mark.parametrize("reply", ("B", ""))
def test_exception_menu_back_never_enters_selection(reply: str) -> None:
    result = _with_issues(1)
    assert not menu._review_exception_queue(
        cast(object, result), input_fn=inputs(reply), **ui()
    )


@pytest.mark.parametrize(("reply", "error"), (("M", ReturnToMainMenu), ("Q", QuitPDS)))
def test_core_navigation_unwinds_from_exception_review(
    reply: str, error: type[Exception]
) -> None:
    with pytest.raises(error):
        menu._review_exception_queue(
            cast(object, _with_issues(1)), input_fn=inputs(reply), **ui()
        )


def test_no_color_plaintext_core_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    output = _render(_with_issues(1))
    assert "Assessment Exceptions — Read-Only Queue" in output
    assert "N. Next page" in output
    assert "M. Main Menu" in output
    assert "Q. Quit" in output
    assert "\x1b[" not in output
    assert "\033" not in output


def test_notes_is_inert_on_unsupported_core_prompt() -> None:
    output = StringIO()
    assert (
        menu._review_exception_queue(
            cast(object, _with_issues(1)),
            input_fn=inputs(":notes", "", "B"),
            output=output,
            clear_fn=lambda: None,
        )
        is False
    )
    assert "other inputs do nothing" in output.getvalue()
    assert "No academic records" in output.getvalue()
    assert "Type APPLY" not in output.getvalue()


def test_return_to_selection_preserves_exact_review_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, object]] = []
    data = _with_issues(1)
    work = SimpleNamespace(class_id="synthetic_125_class")
    prepared = SimpleNamespace(
        authorized=SimpleNamespace(
            current_context=SimpleNamespace(publication=SimpleNamespace(work=work))
        )
    )
    grade = SimpleNamespace(grade_item_id="synthetic_125_grade")

    monkeypatch.setattr(
        menu, "discover_guided_eligibility_grade_items", lambda *a, **k: (grade,)
    )
    monkeypatch.setattr(menu, "_choose_grade_item", lambda *a, **k: grade)

    def project_exact(root: Path, **kwargs: object) -> object:
        assert kwargs["grade_item_id"] == grade.grade_item_id
        assert kwargs["prepared"] is prepared
        assert kwargs["class_label"] == "Synthetic Class"
        assert kwargs["assessment_title"] == "Synthetic Test"
        observed.append(("project", root))
        return data

    monkeypatch.setattr(menu, "project_assessment_eligibility_review", project_exact)

    def select_exact(review: object, **_kwargs: object) -> None:
        assert review is data
        observed.append(("scope", review))
        return None

    monkeypatch.setattr(menu, "_choose_source_ids", select_exact)
    monkeypatch.setattr(
        menu,
        "execute_batch_with_sealed_progress",
        lambda *a, **k: pytest.fail("Read-only review must not execute actions"),
    )
    menu.run_assessment_eligibility_menu(
        workspace_root=Path("/synthetic/workspace"),
        prepared=cast(object, prepared),
        class_label="Synthetic Class",
        assessment_title="Synthetic Test",
        session_context=cast(object, SimpleNamespace()),
        dependencies=cast(object, SimpleNamespace(policies=())),
        diagnostics=cast(object, SimpleNamespace()),
        input_fn=inputs("D"),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert [name for name, _ in observed] == ["project", "scope"]


@pytest.mark.parametrize("failure", (PermissionError, RuntimeError))
def test_authorization_or_projection_unavailable_fails_closed(
    monkeypatch: pytest.MonkeyPatch, failure: type[Exception]
) -> None:
    work = SimpleNamespace(class_id="synthetic_125_class")
    prepared = SimpleNamespace(
        authorized=SimpleNamespace(
            current_context=SimpleNamespace(publication=SimpleNamespace(work=work))
        )
    )
    grade = SimpleNamespace(grade_item_id="synthetic_125_grade")
    monkeypatch.setattr(
        menu, "discover_guided_eligibility_grade_items", lambda *a, **k: (grade,)
    )
    monkeypatch.setattr(menu, "_choose_grade_item", lambda *a, **k: grade)

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise failure("RAW_PRIVATE_STUDENT_DETAILS")

    monkeypatch.setattr(menu, "project_assessment_eligibility_review", unavailable)
    monkeypatch.setattr(
        menu,
        "_choose_source_ids",
        lambda *a, **k: pytest.fail("No selection without authorized projection"),
    )
    monkeypatch.setattr(
        menu,
        "execute_batch_with_sealed_progress",
        lambda *a, **k: pytest.fail("No academic write without authorized review"),
    )
    output = StringIO()
    menu.run_assessment_eligibility_menu(
        workspace_root=Path("/synthetic/workspace"),
        prepared=cast(object, prepared),
        class_label="Synthetic Class",
        assessment_title="Synthetic Test",
        session_context=cast(object, SimpleNamespace()),
        dependencies=cast(object, SimpleNamespace(policies=())),
        diagnostics=cast(object, SimpleNamespace()),
        input_fn=inputs(""),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "no longer authorized" in rendered
    assert "No eligibility state was changed" in rendered
    assert "RAW_PRIVATE_STUDENT_DETAILS" not in rendered
