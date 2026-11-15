"""#125-H3D9: measured teacher-menu prompts and native producer exception walk.

Synthetic fixtures only. Does not claim a timed individual-workflow baseline,
optional Core Notes capability availability, or authorization to merge #125.
Native tests require explicitly qualified isolated official wheels.
"""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from test_issue125_h3d3_exception_queue_navigation import _with_issues
from test_issue125_slicef1_assessment_menu import review as synthetic_review

import meridian.menu_teacher_assessment_eligibility as menu

_NATIVE = os.environ.get("PDS_ISSUE125_H3D9_NATIVE_TEST") == "1"


class Transcript:
    def __init__(self, replies: tuple[str, ...]) -> None:
        self.replies = iter(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            return next(self.replies)
        except StopIteration as exc:
            raise AssertionError(f"Unexpected teacher prompt {prompt!r}") from exc


def _context() -> tuple[object, object, object]:
    grade = SimpleNamespace(grade_item_id="synthetic_grade_item")
    work = SimpleNamespace(class_id="synthetic_class")
    prepared = SimpleNamespace(
        authorized=SimpleNamespace(
            current_context=SimpleNamespace(publication=SimpleNamespace(work=work))
        )
    )
    policy = SimpleNamespace(title="Teacher reviewed eligibility")
    return grade, prepared, policy


def _exercise_teacher_menu(
    monkeypatch: pytest.MonkeyPatch,
    *,
    batch_review: object,
    grade: object,
    prepared: object,
    policy: object,
    replies: tuple[str, ...],
) -> tuple[Transcript, str, list[tuple[str, ...]]]:
    """Use real scope/disposition/policy/exception/confirmation menu prompts.

    Only external authority, plan, and storage boundaries are simulated. The
    meaningful interaction counts are from the actual installed menu logic.
    """
    applied: list[tuple[str, ...]] = []
    expected = tuple(row[0] for row in menu._enumerate_candidates(batch_review))
    assert expected
    plan = SimpleNamespace(items=(), action_count=len(expected), plan_sha256="c" * 64)
    monkeypatch.setattr(
        menu, "discover_guided_eligibility_grade_items", lambda *a, **k: (grade,)
    )
    monkeypatch.setattr(menu, "_choose_grade_item", lambda *a, **k: grade)

    def project_exact(*_args: object, **kwargs: object) -> object:
        assert kwargs["grade_item_id"] == grade.grade_item_id
        assert kwargs["prepared"] is prepared
        return batch_review

    monkeypatch.setattr(menu, "project_assessment_eligibility_review", project_exact)
    monkeypatch.setattr(menu, "resolve_menu_actor", lambda *_a: object())
    monkeypatch.setattr(menu, "capture_batch_pointer_witnesses", lambda *a: ())

    def plan_exact(_review: object, selection: object, **kwargs: object) -> object:
        assert _review is batch_review
        assert tuple(selection.selected_item_ids) == expected
        assert selection.disposition == "included"
        assert not selection.student_exceptions
        assert not selection.item_exceptions
        assert kwargs["policy"] is policy
        return plan

    monkeypatch.setattr(menu, "build_batch_eligibility_plan", plan_exact)
    monkeypatch.setattr(
        menu, "render_batch_eligibility_plan", lambda *_a: "Exact reviewed batch plan"
    )

    def fake_apply(_root: Path, current: object, **kwargs: object) -> object:
        assert current is plan and kwargs["confirmed"] is True
        assert kwargs["prepared"] is prepared
        assert kwargs["grade_item"] is grade
        applied.append(expected)
        return SimpleNamespace(stopped=False, items=())

    monkeypatch.setattr(menu, "execute_batch_with_sealed_progress", fake_apply)
    monkeypatch.setattr(
        menu, "render_batch_execution_outcome", lambda *_a: "Synthetic verified receipt"
    )
    transcript = Transcript(replies)
    output = StringIO()
    menu.run_assessment_eligibility_menu(
        workspace_root=Path("/synthetic-h3d9-no-writes"),
        prepared=cast(object, prepared),
        class_label="Synthetic English 12",
        assessment_title="Synthetic six-question assessment",
        session_context=cast(object, SimpleNamespace()),
        dependencies=cast(object, SimpleNamespace(policies=(policy,))),
        diagnostics=cast(object, SimpleNamespace()),
        input_fn=transcript,
        output=output,
        clear_fn=lambda: None,
    )
    return transcript, output.getvalue(), applied


def test_29_by_6_teacher_transcript_uses_one_apply_and_eight_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grade, prepared, policy = _context()
    data = synthetic_review(29, 6)
    transcript, output, applied = _exercise_teacher_menu(
        monkeypatch,
        batch_review=data,
        grade=grade,
        prepared=prepared,
        policy=policy,
        replies=("A", "1", "1", "D", "synthetic teacher", "", "APPLY", ""),
    )
    assert len(applied) == 1 and len(applied[0]) == 174
    assert len(set(applied[0])) == 174
    assert len(transcript.prompts) == 8
    assert transcript.prompts.count("Confirmation: ") == 1
    assert "Exact reviewed batch plan" in output
    assert "Synthetic verified receipt" in output
    assert "Type APPLY" in output
    print(
        "H3D9_TEACHER_TRANSCRIPT candidates=174 inputs=8 "
        "confirmations=1 canonical_writes=simulated"
    )


@pytest.mark.parametrize("reply", ("", "B", "apply", ":notes"))
def test_29_by_6_nonexact_confirmation_never_applies(
    monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    grade, prepared, policy = _context()
    transcript, output, applied = _exercise_teacher_menu(
        monkeypatch,
        batch_review=synthetic_review(29, 6),
        grade=grade,
        prepared=prepared,
        policy=policy,
        replies=("A", "1", "1", "D", "synthetic teacher", "", reply),
    )
    assert not applied
    assert len(transcript.prompts) == 7
    assert transcript.prompts.count("Confirmation: ") == 1
    assert "Cancelled. No eligibility actions or receipts created." in output


def test_exception_first_back_aborts_before_scope_and_canonical_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grade, prepared, policy = _context()
    data = _with_issues(1)
    monkeypatch.setattr(
        menu, "discover_guided_eligibility_grade_items", lambda *a, **k: (grade,)
    )
    monkeypatch.setattr(menu, "_choose_grade_item", lambda *a, **k: grade)
    monkeypatch.setattr(
        menu, "project_assessment_eligibility_review", lambda *a, **k: data
    )
    monkeypatch.setattr(
        menu,
        "_choose_source_ids",
        lambda *a, **k: pytest.fail("Scope entered after queue Back"),
    )
    monkeypatch.setattr(
        menu,
        "execute_batch_with_sealed_progress",
        lambda *a, **k: pytest.fail("Unconfirmed write"),
    )
    transcript = Transcript(("B",))
    menu.run_assessment_eligibility_menu(
        workspace_root=Path("/synthetic"),
        prepared=cast(object, prepared),
        class_label="Synthetic English 12",
        assessment_title="Synthetic assessment",
        session_context=cast(object, SimpleNamespace()),
        dependencies=cast(object, SimpleNamespace(policies=(policy,))),
        diagnostics=cast(object, SimpleNamespace()),
        input_fn=transcript,
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert len(transcript.prompts) == 1


@pytest.mark.parametrize("navigation,error", (("M", ReturnToMainMenu), ("Q", QuitPDS)))
def test_exception_first_core_navigation_propagates_without_apply(
    monkeypatch: pytest.MonkeyPatch,
    navigation: str,
    error: type[Exception],
) -> None:
    grade, prepared, policy = _context()
    monkeypatch.setattr(
        menu, "discover_guided_eligibility_grade_items", lambda *a, **k: (grade,)
    )
    monkeypatch.setattr(menu, "_choose_grade_item", lambda *a, **k: grade)
    monkeypatch.setattr(
        menu, "project_assessment_eligibility_review", lambda *a, **k: _with_issues(1)
    )
    monkeypatch.setattr(
        menu,
        "execute_batch_with_sealed_progress",
        lambda *a, **k: pytest.fail("Unconfirmed write"),
    )
    with pytest.raises(error):
        menu.run_assessment_eligibility_menu(
            workspace_root=Path("/synthetic"),
            prepared=cast(object, prepared),
            class_label="Synthetic English 12",
            assessment_title="Synthetic assessment",
            session_context=cast(object, SimpleNamespace()),
            dependencies=cast(object, SimpleNamespace(policies=(policy,))),
            diagnostics=cast(object, SimpleNamespace()),
            input_fn=Transcript((navigation,)),
            output=StringIO(),
            clear_fn=lambda: None,
        )


def test_denied_roster_scope_never_exposes_student_or_source_labels() -> None:
    data = _with_issues(1)
    denied = data.students[0]
    denied.within_requested_authorization = False
    denied.display_label = "PRIVATE_STUDENT_NAME"
    denied.items[0].evidence_label = "PRIVATE_QUESTION_LABEL"
    data.outside_authorization_scope_count = 1
    data.exceptions = (
        SimpleNamespace(
            code="outside_requested_authorization_scope",
            route="review-source",
            student_id=denied.student_id,
            source=denied.items[0].source,
        ),
    )
    output = StringIO()
    assert menu._review_exception_queue(
        cast(object, data),
        input_fn=Transcript(("D",)),
        output=output,
        clear_fn=lambda: None,
    )
    visible = output.getvalue()
    assert "Outside requested evidence scope" in visible
    assert "Outside requested authorization: 1" in visible
    assert "PRIVATE_STUDENT_NAME" not in visible
    assert "PRIVATE_QUESTION_LABEL" not in visible
    assert menu._enumerate_candidates(cast(object, data)) == ()


def test_distinct_unavailable_statuses_do_not_claim_missing_result_is_zero() -> None:
    data = _with_issues(1)
    data.no_result_student_count = 2
    data.outside_authorization_scope_count = 1
    data.status_counts = (
        ("eligibility_unsupported", 1),
        ("eligibility_no_decision", 1),
    )
    output = StringIO()
    assert menu._review_exception_queue(
        cast(object, data),
        input_fn=Transcript(("D",)),
        output=output,
        clear_fn=lambda: None,
    )
    visible = output.getvalue()
    assert "No result (never zero): 2" in visible
    assert "Outside requested authorization: 1" in visible
    assert "eligibility unsupported: 1" in visible
    assert "eligibility no decision: 1" in visible
    assert "0" not in visible.split("No result (never zero): 2", 1)[1].split("\n", 1)[0]


@pytest.mark.skipif(
    not _NATIVE, reason="Requires pinned installed official producer wheels"
)
@pytest.mark.parametrize("producer", ("scoreform", "quillan", "concord"))
def test_native_producer_exception_queue_is_read_only_and_source_accurate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    producer: str,
) -> None:
    from test_issue124_slicee2g3k_composite_canonical import _all_bytes
    from test_issue125_sliceg2a_canonical_batch_acceptance import _ready_native

    root, _grade, _prepared, data, _deps, _grade_item, _diagnostics, _actor = (
        _ready_native(tmp_path, monkeypatch, producer)
    )
    before = _all_bytes(root)
    items = menu._enumerate_candidates(data)
    assert len({key for key, _, _ in items}) == len(items)
    if producer == "scoreform":
        assert len(data.students) == 29
        assert len(items) >= 174
    display = StringIO()
    transcript = Transcript(("D",))
    assert menu._review_exception_queue(
        data,
        input_fn=transcript,
        output=display,
        clear_fn=lambda: None,
        force=True,
    )
    content = display.getvalue()
    assert "Current evidence status counts (not grades):" in content
    assert "EXCEPTIONS — REVIEW BEFORE BATCH ACTION" in content
    assert "No result (never zero)" in content
    assert "No academic records or eligibility decisions have been changed." in content
    assert "Type APPLY" not in content
    assert len(transcript.prompts) == 1
    assert _all_bytes(root) == before
    print(
        f"H3D9_NATIVE_REVIEW producer={producer} candidates={len(items)} "
        "inputs=1 zero_writes=1"
    )


@pytest.mark.skipif(
    not _NATIVE, reason="Requires pinned installed official producer wheels"
)
def test_native_scoreform_29x6_teacher_transcript_no_canonical_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_issue124_slicee2g3k_composite_canonical import _all_bytes
    from test_issue125_sliceg2a_canonical_batch_acceptance import _ready_native

    root, _grade_id, prepared, data, deps, grade, _diagnostics, _actor = _ready_native(
        tmp_path, monkeypatch, "scoreform"
    )
    candidates = menu._enumerate_candidates(data)
    assert len(data.students) == 29
    assert (
        sum(
            1
            for student in data.students
            for item in student.items
            if item.result_kind == "question_correctness"
            and item.candidate_for_explicit_review
        )
        == 174
    )
    assert len(candidates) >= 174
    before = _all_bytes(root)
    needs_exception_continue = bool(data.exceptions)
    answers = (("D",) if needs_exception_continue else ()) + (
        "A",
        "1",
        "1",
        "D",
        "synthetic teacher",
        "",
        "APPLY",
        "",
    )
    transcript, output, applied = _exercise_teacher_menu(
        monkeypatch,
        batch_review=data,
        grade=grade,
        prepared=prepared,
        policy=deps.policies[0],
        replies=answers,
    )
    assert len(applied) == 1 and len(applied[0]) == len(candidates)
    assert len(transcript.prompts) == 8 + int(needs_exception_continue)
    assert transcript.prompts.count("Confirmation: ") == 1
    assert "Synthetic verified receipt" in output
    assert _all_bytes(root) == before
    print(
        f"H3D9_NATIVE_TEACHER_29X6 candidates={len(candidates)} "
        "correctness_targets=174 "
        f"inputs={len(transcript.prompts)} substantive_apply=1 "
        "actual_canonical_writes=0"
    )
