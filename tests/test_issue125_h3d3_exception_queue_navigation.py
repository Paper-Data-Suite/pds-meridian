"""#125-H3D3: exception-first teacher review without extra academic authority."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from test_issue125_slicef1_assessment_menu import inputs, review, ui

import meridian.menu_teacher_assessment_eligibility as menu


def _with_issues(count: int = 25) -> SimpleNamespace:
    subject = review(1, 1)
    source = subject.students[0].items[0].source
    subject.exceptions = tuple(
        SimpleNamespace(
            code=f"exception_{i}",
            route="review-attempts" if i % 2 else "review-roster",
            student_id="s1",
            source=source,
        )
        for i in range(count)
    )
    subject.exception_count = len(subject.exceptions)
    subject.status_counts = (("eligibility_no_decision", 1),)
    subject.class_label = "Synthetic English class"
    subject.assessment_title = "Synthetic evidence check"
    subject.source_status = "current"
    subject.membership_state = "included"
    return subject


def test_exception_queue_pages_routes_and_canonical_ids_are_hidden() -> None:
    data = _with_issues()
    output = StringIO()
    permitted = menu._review_exception_queue(
        cast(object, data),
        input_fn=inputs("N", "P", "D"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert permitted
    assert "page 1/2" in rendered and "page 2/2" in rendered
    assert "Review attempts (#126)" in rendered
    assert "Review Core roster" in rendered
    assert "Synthetic English class" in rendered
    assert "No result (never zero): 0" in rendered
    assert "eligibility no decision: 1" in rendered
    assert "s1-q1" not in rendered
    assert "exception_24" not in rendered
    assert "exception 24" in rendered
    assert "\x1b[" not in rendered


def test_back_cancels_exception_review_without_entering_selection() -> None:
    data = _with_issues(1)
    assert not menu._review_exception_queue(
        cast(object, data), input_fn=inputs("B"), **ui()
    )


def test_exception_queue_never_infers_unauthorized_evidence_details() -> None:
    data = _with_issues(1)
    out_of_scope = data.students[0]
    out_of_scope.within_requested_authorization = False
    out_of_scope.items[0].evidence_label = "PRIVATE QUESTION LABEL"
    data.exceptions = (
        SimpleNamespace(
            code="outside_requested_authorization_scope",
            route="review-source",
            student_id="s1",
            source=out_of_scope.items[0].source,
        ),
    )
    data.exception_count = 1
    data.outside_authorization_scope_count = 1
    output = StringIO()
    assert menu._review_exception_queue(
        cast(object, data),
        input_fn=inputs("D"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Outside requested evidence scope" in rendered
    assert "Review source/publication" in rendered
    assert "PRIVATE QUESTION LABEL" not in rendered
    assert "Sample Student 1" not in rendered
    assert "s1-q1" not in rendered


def test_unknown_student_source_identity_is_not_printed() -> None:
    data = _with_issues(1)
    data.exceptions = (
        SimpleNamespace(
            code="unknown_roster_student",
            route="review-roster",
            student_id="RAW_UNKNOWN_ID",
            source=SimpleNamespace(item_id="RAW_ITEM_ID"),
        ),
    )
    out = StringIO()
    menu._review_exception_queue(
        cast(object, data),
        input_fn=inputs("D"),
        output=out,
        clear_fn=lambda: None,
    )
    assert "Unmatched/shared evidence" in out.getvalue()
    assert "RAW_UNKNOWN_ID" not in out.getvalue()
    assert "RAW_ITEM_ID" not in out.getvalue()


@pytest.mark.parametrize(
    "reply,exception_type", [("M", ReturnToMainMenu), ("Q", QuitPDS)]
)
def test_navigation_unwinds_to_existing_core_route(
    reply: str, exception_type: type[Exception]
) -> None:
    with pytest.raises(exception_type):
        menu._review_exception_queue(
            cast(object, _with_issues(1)), input_fn=inputs(reply), **ui()
        )


def test_notes_command_is_not_interpreted_as_batch_confirmation() -> None:
    output = StringIO()
    assert not menu._review_exception_queue(
        cast(object, _with_issues(1)),
        input_fn=inputs(":notes", "", "B"),
        output=output,
        clear_fn=lambda: None,
    )
    assert "other inputs do nothing" in output.getvalue()
    assert "Type APPLY" not in output.getvalue()


def test_no_exception_entry_needs_no_extra_teacher_prompt() -> None:
    data = _with_issues(0)

    def never_prompt(_prompt: str = "") -> str:
        raise AssertionError("No extra decision when nothing exceptional")

    assert menu._review_exception_queue(
        cast(object, data), input_fn=never_prompt, **ui()
    )


def test_manual_v_option_reopens_complete_queue() -> None:
    data = _with_issues(1)
    calls: list[bool] = []
    original = menu._review_exception_queue

    def spy(view: object, **kwargs: object) -> bool:
        calls.append(bool(kwargs.get("force")))
        return True

    try:
        menu._review_exception_queue = spy
        assert (
            menu._choose_source_ids(
                cast(object, data), input_fn=inputs("V", "B"), **ui()
            )
            is None
        )
    finally:
        menu._review_exception_queue = original
    assert calls == [True]


def test_no_exception_forced_view_shows_coverage() -> None:
    data = _with_issues(0)
    data.no_result_student_count = 2
    data.outside_authorization_scope_count = 1
    output = StringIO()
    assert menu._review_exception_queue(
        cast(object, data),
        input_fn=inputs("D"),
        output=output,
        clear_fn=lambda: None,
        force=True,
    )
    rendered = output.getvalue()
    assert "No exception conditions observed" in rendered
    assert "No result (never zero): 2" in rendered
    assert "Outside requested authorization: 1" in rendered


def test_menu_checks_exception_queue_before_scope_and_cancel_is_no_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    work = SimpleNamespace(class_id="synthetic_class")
    prepared = SimpleNamespace(
        authorized=SimpleNamespace(
            current_context=SimpleNamespace(publication=SimpleNamespace(work=work))
        )
    )
    selected_grade = SimpleNamespace(grade_item_id="synthetic_grade")
    monkeypatch.setattr(
        menu,
        "discover_guided_eligibility_grade_items",
        lambda *a, **k: (selected_grade,),
    )
    monkeypatch.setattr(menu, "_choose_grade_item", lambda *a, **k: selected_grade)
    monkeypatch.setattr(
        menu, "project_assessment_eligibility_review", lambda *a, **k: _with_issues(1)
    )
    monkeypatch.setattr(
        menu, "_choose_source_ids", lambda *a, **k: events.append("scope")
    )
    monkeypatch.setattr(
        menu,
        "execute_batch_with_sealed_progress",
        lambda *a, **k: events.append("WRITTEN"),
    )
    menu.run_assessment_eligibility_menu(
        workspace_root=Path("/synthetic"),
        prepared=cast(object, prepared),
        class_label="Synthetic English class",
        assessment_title="Synthetic evidence check",
        session_context=cast(object, SimpleNamespace()),
        dependencies=cast(object, SimpleNamespace(policies=())),
        diagnostics=cast(object, SimpleNamespace()),
        input_fn=inputs("B"),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert events == []
