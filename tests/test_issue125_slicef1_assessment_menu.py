"""#125-F1: synthetic teacher menu selections, cancellation and routing."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import meridian.menu_teacher_assessment_eligibility as menu


def item(student: int, number: int, *, safe: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        source=SimpleNamespace(item_id=f"s{student}-q{number}"),
        evidence_label=f"Question {number}",
        candidate_for_explicit_review=safe,
    )


def review(
    count: int = 29, questions: int = 6, *, safe: bool = True
) -> SimpleNamespace:
    return SimpleNamespace(
        students=tuple(
            SimpleNamespace(
                student_id=f"s{n}",
                display_label=f"Sample Student {n}",
                within_requested_authorization=True,
                items=tuple(item(n, q, safe=safe) for q in range(1, questions + 1)),
            )
            for n in range(1, count + 1)
        ),
        exception_count=0,
        no_result_student_count=0,
        outside_authorization_scope_count=0,
        shared_items=(),
        unmatched_items=(),
    )


def inputs(*answers: str):
    it = iter(answers)
    return lambda prompt="": next(it)


def ui():
    return dict(output=io.StringIO(), clear_fn=lambda: None)


def test_29_by_6_candidates_are_distinct_and_bounded() -> None:
    rows = menu._enumerate_candidates(review())
    assert len(rows) == 174
    assert len({r[0] for r in rows}) == 174
    assert rows[0] == ("s1-q1", "Sample Student 1", "Question 1")


def test_unsafe_candidate_not_collected() -> None:
    r = review(2, 2)
    r.students[0].items[0].candidate_for_explicit_review = False
    r.students[1].within_requested_authorization = False
    assert tuple(x[0] for x in menu._enumerate_candidates(r)) == ("s1-q2",)


@pytest.mark.parametrize(
    "bad", ["", "B", "0", "-1", "2.0", "1,1", "1,", "1,9", "x", "½"]
)
def test_number_parser_rejects_unavailable_or_navigation(bad: str) -> None:
    assert menu._numbers(bad, 5, allow_many=True) is None


def test_number_parser_rejects_multiple_when_only_one_expected() -> None:
    assert menu._numbers("1,2", 5, allow_many=False) is None
    assert menu._numbers("2", 5, allow_many=False) == (2,)


def test_opt_in_all_selects_only_safe_candidates() -> None:
    r = review(3, 2)
    r.students[0].items[0].candidate_for_explicit_review = False
    chosen = menu._choose_source_ids(r, input_fn=inputs("A"), **ui())
    assert chosen == ("s1-q2", "s2-q1", "s2-q2", "s3-q1", "s3-q2")


def test_empty_enter_cancels_not_select_all() -> None:
    assert menu._choose_source_ids(review(), input_fn=inputs(""), **ui()) is None


def test_back_cancels_not_select_all() -> None:
    assert menu._choose_source_ids(review(), input_fn=inputs("B"), **ui()) is None


def test_student_selection_uses_display_index_not_ids() -> None:
    chosen = menu._choose_source_ids(review(3, 2), input_fn=inputs("S", "2,3"), **ui())
    assert chosen == ("s2-q1", "s2-q2", "s3-q1", "s3-q2")


def test_item_selection_pages_and_exact_ids() -> None:
    rows = menu._enumerate_candidates(review(5, 6))
    chosen = menu._choose_paged_items(
        rows, input_fn=inputs("1,2", "N", "22", "D"), **ui()
    )
    assert chosen == ("s1-q1", "s1-q2", "s4-q4")


def test_item_toggle_clears_selection() -> None:
    rows = menu._enumerate_candidates(review(1, 2))
    assert (
        menu._choose_paged_items(rows, input_fn=inputs("1", "1", "D"), **ui()) is None
    )


def test_item_paging_cancel_does_not_retire_anything() -> None:
    rows = menu._enumerate_candidates(review(6, 6))
    assert menu._choose_paged_items(rows, input_fn=inputs("1", "B"), **ui()) is None


def test_exception_student_override_and_deferral() -> None:
    r = review(2, 2)
    selected = tuple(row[0] for row in menu._enumerate_candidates(r))
    student_overrides, item_overrides = menu._exceptions(
        r, selected, input_fn=inputs("1", "2", "3", "2", "1", "D", "D"), **ui()
    )
    assert len(student_overrides) == 1
    assert student_overrides[0].student_id == "s2"
    assert student_overrides[0].disposition == "pending"
    assert student_overrides[0].reason_codes == ("eligibility.manual",)
    assert item_overrides[0].item_id == "s1-q1"
    assert item_overrides[0].disposition is None


def test_exception_back_cancels_batch() -> None:
    assert (
        menu._exceptions(review(1, 1), ("s1-q1",), input_fn=inputs("B"), **ui()) is None
    )


def test_exception_clear_removes_overrides() -> None:
    chosen = menu._exceptions(
        review(1, 1),
        ("s1-q1",),
        input_fn=inputs("2", "1", "2", "3", "D"),
        **ui(),
    )
    assert chosen == ((), ())


def _mock_run(monkeypatch: pytest.MonkeyPatch, *, confirm: str):
    events: list[str] = []
    r = review(1, 2)
    publication = SimpleNamespace(work=SimpleNamespace(class_id="class"))
    prepared = SimpleNamespace(
        authorized=SimpleNamespace(
            current_context=SimpleNamespace(publication=publication)
        )
    )
    grade_item = SimpleNamespace(grade_item_id="gi1")
    policy = SimpleNamespace(title="Teacher review")
    plan = SimpleNamespace(items=(), action_count=2, plan_sha256="c" * 64)
    deps = SimpleNamespace(policies=(policy,))
    monkeypatch.setattr(
        menu, "discover_guided_eligibility_grade_items", lambda *a, **k: (grade_item,)
    )
    monkeypatch.setattr(menu, "_choose_grade_item", lambda *a, **k: grade_item)
    monkeypatch.setattr(
        menu, "project_assessment_eligibility_review", lambda *a, **k: r
    )
    monkeypatch.setattr(menu, "_choose_source_ids", lambda *a, **k: ("s1-q1", "s1-q2"))
    monkeypatch.setattr(menu, "_choose_disposition", lambda *a, **k: "included")
    monkeypatch.setattr(menu, "_choose_policy", lambda *a, **k: policy)
    monkeypatch.setattr(menu, "_exceptions", lambda *a, **k: ((), ()))
    monkeypatch.setattr(menu, "resolve_menu_actor", lambda *a, **k: object())
    monkeypatch.setattr(menu, "capture_batch_pointer_witnesses", lambda *a, **k: ())
    monkeypatch.setattr(menu, "build_batch_eligibility_plan", lambda *a, **k: plan)
    monkeypatch.setattr(
        menu, "render_batch_eligibility_plan", lambda *a: "Exact plan review"
    )
    monkeypatch.setattr(
        menu,
        "execute_batch_with_sealed_progress",
        lambda *a, **k: (
            events.append("APPLIED") or SimpleNamespace(items=(), stopped=False)
        ),
    )
    monkeypatch.setattr(
        menu, "render_batch_execution_outcome", lambda *a: "Verified outcome"
    )
    stream = io.StringIO()
    menu.run_assessment_eligibility_menu(
        workspace_root=Path("/example"),
        prepared=cast(object, prepared),
        class_label="Synthetic class",
        assessment_title="Synthetic check",
        session_context=cast(object, SimpleNamespace()),
        dependencies=cast(object, deps),
        diagnostics=cast(object, SimpleNamespace()),
        input_fn=inputs("verified teacher", "", confirm, ""),
        output=stream,
        clear_fn=lambda: None,
    )
    return events, stream.getvalue()


@pytest.mark.parametrize("reply", ["", "B", "yes", "apply", "1"])
def test_no_academic_write_on_non_exact_confirmation(
    monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    events, output = _mock_run(monkeypatch, confirm=reply)
    assert not events
    assert "Cancelled" in output


def test_one_exact_apply_reaches_existing_e1_executor_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, output = _mock_run(monkeypatch, confirm="APPLY")
    assert events == ["APPLIED"]
    assert "Verified outcome" in output


def test_exception_picker_pages_and_returns_exact_index() -> None:
    labels = tuple(f"Sample Student {i}" for i in range(1, 30))
    assert (
        menu._choose_exception_target(labels, input_fn=inputs("N", "23"), **ui()) == 22
    )


def test_exception_picker_back_does_not_select_anything() -> None:
    labels = tuple(f"Item {i}" for i in range(1, 175))
    assert (
        menu._choose_exception_target(labels, input_fn=inputs("N", "B"), **ui()) is None
    )
