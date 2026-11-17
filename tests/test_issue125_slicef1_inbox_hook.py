"""#125-F1: assessment-level menu action is opt-in and preserves old screens."""

from __future__ import annotations

import io
from types import SimpleNamespace

from meridian.menu_teacher_evidence import _render_review_summary


def _case(*, student_count: int = 2, shared: int = 1):
    inbox_item = SimpleNamespace(
        class_label="Synthetic class",
        work_title="Synthetic six-question check",
        producer_label="ScoreForm",
    )
    review = SimpleNamespace(
        student_count=student_count,
        evidence_count=student_count * 6 + shared,
        shared_evidence_count=shared,
        students=tuple(object() for _ in range(student_count)),
        shared_items=tuple(object() for _ in range(shared)),
    )
    return inbox_item, review


def test_existing_evidence_review_actions_unchanged_by_default() -> None:
    out = io.StringIO()
    actions = _render_review_summary(out, *_case())
    assert actions == ("students", "shared")
    assert "assessment eligibility" not in out.getvalue().casefold()


def test_batch_action_follows_existing_student_and_shared_routes() -> None:
    out = io.StringIO()
    actions = _render_review_summary(
        out, *_case(), assessment_eligibility_available=True
    )
    assert actions == ("students", "shared", "assessment_eligibility")
    assert "3. Review assessment eligibility (batch)" in out.getvalue()


def test_batch_works_as_only_option_for_empty_publication() -> None:
    out = io.StringIO()
    actions = _render_review_summary(
        out,
        *_case(student_count=0, shared=0),
        assessment_eligibility_available=True,
    )
    assert actions == ("assessment_eligibility",)
    assert "1. Review assessment eligibility (batch)" in out.getvalue()
