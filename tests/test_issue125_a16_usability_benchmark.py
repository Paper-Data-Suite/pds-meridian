"""#125-A16: measured individual versus assessment eligibility usability.

All students, results, teacher identity, and workspaces are synthetic. Native
measurements require the explicit isolated official-wheel benchmark runner.
"""

from __future__ import annotations

import os
import platform
import sys
from collections import Counter
from dataclasses import replace
from io import StringIO
from pathlib import Path
from time import perf_counter

import pytest
from test_issue125_sliceb_assessment_projection import (
    eligibility_row,
    project,
    roster,
)
from test_issue125_sliceb_assessment_projection import (
    student as sample_student,
)

from meridian import menu_teacher_assessment_eligibility as batch_menu

_NATIVE = os.environ.get("PDS_ISSUE125_A16_NATIVE_TEST") == "1"


class _ScriptedInput:
    """Record every real-menu input while returning a fixed teacher script."""

    def __init__(self, answers: tuple[str, ...]) -> None:
        self._answers = iter(answers)
        self.prompts: list[str] = []
        self.entered: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            answer = next(self._answers)
        except StopIteration as error:
            raise AssertionError(f"Unexpected teacher prompt: {prompt!r}") from error
        self.entered.append(answer)
        return answer

    def assert_exhausted(self) -> None:
        try:
            extra = next(self._answers)
        except StopIteration:
            return
        raise AssertionError(f"Unused scripted teacher input: {extra!r}")


class _ScreenCounter:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> None:
        self.count += 1


def _expected_disposition(student_id: str, target_id: str | None) -> str:
    if student_id == "student001":
        return "excluded"
    if student_id == "student002" and target_id == "question_1":
        return "pending"
    return "included"


def _disposition_choice(disposition: str) -> str:
    return {"included": "1", "excluded": "2", "pending": "3"}[disposition]


def _correctness_rows(review: object) -> tuple[tuple[object, object], ...]:
    return tuple(
        (student, item)
        for student in review.students
        for item in student.items
        if item.result_kind == "question_correctness"
    )


def _individual_answers(
    teacher_review: object, assessment_review: object, actor_id: str
) -> tuple[str, ...]:
    by_id = {
        item.source.item_id: (student.student_id, item.target_id)
        for student, item in _correctness_rows(assessment_review)
    }
    answers = ["1", "1", "1"]  # class, assessment, Review students
    for student_number, student in enumerate(teacher_review.students, start=1):
        answers.append(str(student_number))
        targets = tuple(
            (item_number, item)
            for item_number, item in enumerate(student.items, start=1)
            if item.item_id in by_id
        )
        assert len(targets) == 6
        for item_number, item in targets:
            student_id, target_id = by_id[item.item_id]
            answers.extend(
                (
                    str(item_number),  # evidence row
                    "1",  # Review eligibility
                    "1",  # current Grade Item
                    _disposition_choice(_expected_disposition(student_id, target_id)),
                    "1",  # policy
                    actor_id,
                    "",  # rationale
                    "1",  # Save and make current
                    "",  # read verified result
                    "B",  # return from evidence detail
                )
            )
        answers.append("B")  # return from this student's evidence rows
    answers.extend(("B", "B", "B", "B"))
    return tuple(answers)


def _batch_answers(assessment_review: object, actor_id: str) -> tuple[str, ...]:
    candidates = batch_menu._enumerate_candidates(assessment_review)
    correctness = batch_menu._filter_safe_candidates(candidates, "question correctness")
    assert len(candidates) == 406
    assert len(correctness) == 174

    answers = [
        "1",
        "1",
        "2",  # class, assessment, assessment batch action
        "1",  # current Grade Item
        "F",
        "question correctness",
    ]
    for start in range(0, len(correctness), 20):
        stop = min(start + 20, len(correctness))
        answers.append(",".join(str(number) for number in range(start + 1, stop + 1)))
        if stop < len(correctness):
            answers.append("N")
    answers.extend(("D", "1", "1"))  # selection done, Include, policy

    correctness_ids = {item_id for item_id, _student, _label in correctness}
    selected_rows = tuple(
        (student, item)
        for student in assessment_review.students
        for item in student.items
        if item.source.item_id in correctness_ids
    )
    student_index = next(
        index
        for index, student in enumerate(assessment_review.students, start=1)
        if student.student_id == "student001"
    )
    item_index = next(
        index
        for index, (student, item) in enumerate(selected_rows, start=1)
        if student.student_id == "student002" and item.target_id == "question_1"
    )
    assert student_index <= 20 and item_index <= 20
    answers.extend(
        (
            "1",
            str(student_index),
            "2",  # student001 -> Exclude
            "2",
            str(item_index),
            "3",  # student002 question 1 -> Pending
            "D",
            actor_id,
            "",  # common rationale
            "APPLY",
            "",  # read result
            "B",
            "B",
            "B",  # leave review, assessment list, inbox
        )
    )
    return tuple(answers)


def _assert_final_state(
    root: Path, grade_id: str, review: object
) -> tuple[dict[tuple[str, str | None], tuple[object, ...]], Counter[str]]:
    from meridian.evidence_eligibility_storage import (
        load_current_evidence_eligibility_decision,
    )

    decisions: dict[tuple[str, str | None], tuple[object, ...]] = {}
    counts: Counter[str] = Counter()
    correctness_ids = {
        item.source.item_id for _student, item in _correctness_rows(review)
    }
    for student in review.students:
        for item in student.items:
            current = load_current_evidence_eligibility_decision(
                root, review.class_id, grade_id, item.source
            )
            if item.source.item_id not in correctness_ids:
                assert current is None
                continue
            assert current is not None
            decision = current.decision
            expected = _expected_disposition(student.student_id, item.target_id)
            assert decision.disposition == expected
            assert decision.eligibility_revision == 1
            assert decision.reason_codes == (
                () if expected == "included" else ("eligibility.manual",)
            )
            assert decision.rationale is None
            assert decision.policy is not None
            key = (student.student_id, item.target_id)
            decisions[key] = (
                decision.disposition,
                decision.reason_codes,
                decision.rationale,
                decision.policy.policy_id,
                decision.policy.policy_version,
                decision.actor.actor_id,
            )
            counts[decision.disposition] += 1
    assert len(decisions) == 174
    assert counts == Counter({"included": 167, "excluded": 6, "pending": 1})
    return decisions, counts


def _assert_write_isolation(
    before: dict[str, bytes], after: dict[str, bytes], class_id: str
) -> int:
    prefix = f"classes/{class_id}/modules/meridian/"
    allowed = (
        prefix + "elig/",
        prefix + "teacher_action_receipts/",
        prefix + "assessment_eligibility_progress/",
    )
    changes = {
        key for key in before.keys() | after.keys() if before.get(key) != after.get(key)
    }
    assert changes
    assert not (before.keys() - after.keys())
    assert not tuple(key for key in changes if not key.startswith(allowed))
    return len(changes)


def test_batch_labels_distinguish_same_question_result_kinds() -> None:
    response = eligibility_row("student_01", 1, item_id="PRIVATE_SELECTED_RESPONSE")
    correctness = replace(
        eligibility_row("student_01", 1, item_id="PRIVATE_CORRECTNESS"),
        result_kind="question_correctness",
    )
    review = project((response, correctness), roster(sample_student(1)))

    candidates = batch_menu._enumerate_candidates(review)
    assert {row[2] for row in candidates} == {
        "Question 1 · Question score",
        "Question 1 · Question correctness",
    }
    filtered = batch_menu._filter_safe_candidates(candidates, "question correctness")
    assert len(filtered) == 1
    assert filtered[0][2] == "Question 1 · Question correctness"
    assert all("PRIVATE_" not in row[2] for row in candidates)


@pytest.mark.skipif(
    not _NATIVE, reason="Requires isolated official A16 five-wheel environment"
)
def test_installed_native_real_menu_individual_vs_batch_benchmark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run 174 equivalent decisions through both real production menus once."""
    from dataclasses import replace as dataclass_replace
    from importlib.metadata import version

    from test_issue124_slicee2g3k_composite_canonical import CLASS, _all_bytes
    from test_issue125_sliceg2a_canonical_batch_acceptance import _ready_native

    from meridian.menu_teacher_evidence import (
        default_teacher_evidence_inbox_menu_dependencies,
        run_teacher_evidence_inbox_menu,
    )
    from meridian.teacher_action_guided import PreparedGuidedAction
    from meridian.teacher_action_receipts import TeacherActionReceiptStore
    from meridian.teacher_evidence_review import project_teacher_evidence_review
    from meridian.teacher_session import TeacherSessionContext

    individual_base = tmp_path / "individual"
    batch_base = tmp_path / "batch"
    individual_base.mkdir()
    batch_base.mkdir()

    (
        individual_root,
        individual_grade,
        individual_prepared,
        individual_review,
        _individual_eligibility_dependencies,
        _individual_grade_item,
        individual_diagnostics,
        actor,
    ) = _ready_native(individual_base, monkeypatch, "scoreform")
    individual_teacher_review = project_teacher_evidence_review(
        individual_root, individual_prepared
    )
    assert len(individual_review.students) == 29
    assert individual_review.projected_item_count == 406
    assert len(_correctness_rows(individual_review)) == 174
    individual_answers = _individual_answers(
        individual_teacher_review, individual_review, actor.actor_id
    )
    assert len(individual_answers) == 1805
    individual_input = _ScriptedInput(individual_answers)
    individual_screens = _ScreenCounter()
    individual_output = StringIO()
    individual_dependencies = dataclass_replace(
        default_teacher_evidence_inbox_menu_dependencies(
            diagnostics=individual_diagnostics
        ),
        workspace_resolver=lambda: individual_root,
    )
    individual_receipts = TeacherActionReceiptStore(individual_root, CLASS)
    individual_receipts_before = {
        receipt.action_id for receipt in individual_receipts.list_receipts()
    }
    individual_bytes_before = _all_bytes(individual_root)
    individual_apply_seconds: list[float] = []
    original_apply = PreparedGuidedAction.apply

    def timed_apply(self: PreparedGuidedAction, *, confirmed: bool) -> object:
        started = perf_counter()
        try:
            return original_apply(self, confirmed=confirmed)
        finally:
            individual_apply_seconds.append(perf_counter() - started)

    with monkeypatch.context() as instrumentation:
        instrumentation.setattr(PreparedGuidedAction, "apply", timed_apply)
        individual_started = perf_counter()
        run_teacher_evidence_inbox_menu(
            dependencies=individual_dependencies,
            session_context=TeacherSessionContext(),
            input_fn=individual_input,
            output=individual_output,
            clear_fn=individual_screens,
        )
        individual_elapsed = perf_counter() - individual_started
    individual_input.assert_exhausted()
    individual_text = individual_output.getvalue()
    assert len(individual_input.entered) == 1805
    assert len(individual_apply_seconds) == 174
    assert individual_text.count("Choose Grade Item") == 174
    assert individual_text.count("Eligibility Policy") == 174
    assert individual_text.count("Eligibility Attribution") == 174
    assert individual_text.count("Review and Save Eligibility") == 174
    individual_new_receipts = {
        receipt.action_id for receipt in individual_receipts.list_receipts()
    } - individual_receipts_before
    assert len(individual_new_receipts) == 174
    individual_changed_paths = _assert_write_isolation(
        individual_bytes_before, _all_bytes(individual_root), CLASS
    )
    individual_decisions, individual_counts = _assert_final_state(
        individual_root, individual_grade, individual_review
    )
    print(
        "A16_INDIVIDUAL_CHECKPOINT "
        f"inputs={len(individual_input.entered)} "
        f"screens={individual_screens.count} confirmations=174 "
        f"elapsed_seconds={individual_elapsed:.3f} "
        f"canonical_seconds={sum(individual_apply_seconds):.3f} "
        f"changed_paths={individual_changed_paths}",
        flush=True,
    )

    (
        batch_root,
        batch_grade,
        batch_prepared,
        batch_review,
        _batch_eligibility_dependencies,
        _batch_grade_item,
        batch_diagnostics,
        batch_actor,
    ) = _ready_native(batch_base, monkeypatch, "scoreform")
    assert batch_actor.actor_id == actor.actor_id
    assert len(batch_review.students) == 29
    assert batch_review.projected_item_count == 406
    assert len(_correctness_rows(batch_review)) == 174
    batch_answers = _batch_answers(batch_review, batch_actor.actor_id)
    assert len(batch_answers) == 40
    batch_input = _ScriptedInput(batch_answers)
    batch_screens = _ScreenCounter()
    batch_output = StringIO()
    batch_dependencies = dataclass_replace(
        default_teacher_evidence_inbox_menu_dependencies(diagnostics=batch_diagnostics),
        workspace_resolver=lambda: batch_root,
    )
    batch_receipts = TeacherActionReceiptStore(batch_root, CLASS)
    batch_receipts_before = {
        receipt.action_id for receipt in batch_receipts.list_receipts()
    }
    batch_bytes_before = _all_bytes(batch_root)
    batch_execution_seconds: list[float] = []
    original_execute = batch_menu.execute_batch_with_sealed_progress

    def timed_execute(*args: object, **kwargs: object) -> object:
        started = perf_counter()
        try:
            return original_execute(*args, **kwargs)  # type: ignore[arg-type]
        finally:
            batch_execution_seconds.append(perf_counter() - started)

    with monkeypatch.context() as instrumentation:
        instrumentation.setattr(
            batch_menu, "execute_batch_with_sealed_progress", timed_execute
        )
        batch_started = perf_counter()
        run_teacher_evidence_inbox_menu(
            dependencies=batch_dependencies,
            session_context=TeacherSessionContext(),
            input_fn=batch_input,
            output=batch_output,
            clear_fn=batch_screens,
        )
        batch_elapsed = perf_counter() - batch_started
    batch_input.assert_exhausted()
    batch_text = batch_output.getvalue()
    assert len(batch_input.entered) == 40
    assert len(batch_execution_seconds) == 1
    assert batch_text.count("Choose Grade Item") == 1
    assert batch_text.count("Eligibility Policy") == 1
    assert batch_text.count("Eligibility Attribution") == 1
    assert batch_text.count("Review Exact Batch") == 1
    assert "Core roster students: 29" in batch_text
    assert "Batch Exceptions" in batch_text
    assert "Question correctness" in batch_text
    batch_new_receipts = {
        receipt.action_id for receipt in batch_receipts.list_receipts()
    } - batch_receipts_before
    assert len(batch_new_receipts) == 174
    batch_changed_paths = _assert_write_isolation(
        batch_bytes_before, _all_bytes(batch_root), CLASS
    )
    batch_decisions, batch_counts = _assert_final_state(
        batch_root, batch_grade, batch_review
    )

    assert individual_decisions == batch_decisions
    assert individual_counts == batch_counts
    assert len(individual_input.entered) > len(batch_input.entered) * 40
    assert individual_screens.count > batch_screens.count * 20
    hidden_ids = {
        individual_grade,
        batch_grade,
        *(
            item.source.item_id
            for _student, item in _correctness_rows(individual_review)
        ),
        *(item.source.item_id for _student, item in _correctness_rows(batch_review)),
    }
    assert hidden_ids.isdisjoint(individual_input.entered)
    assert hidden_ids.isdisjoint(batch_input.entered)

    package_versions = ",".join(
        f"{name}={version(name)}"
        for name in ("pds-core", "scoreform", "quillan", "pds-concord", "pds-meridian")
    )
    print(
        "A16_BENCHMARK "
        f"python={sys.version.split()[0]} platform={platform.platform()} "
        f"packages={package_versions} evidence=406 targets=174 other=232 "
        f"outcomes={dict(sorted(individual_counts.items()))} "
        f"individual_inputs={len(individual_input.entered)} "
        f"individual_screens={individual_screens.count} "
        "individual_confirmations=174 individual_grade_selections=174 "
        "individual_actor_policy_interactions=174 "
        f"individual_elapsed_seconds={individual_elapsed:.3f} "
        f"individual_canonical_seconds={sum(individual_apply_seconds):.3f} "
        f"individual_changed_paths={individual_changed_paths} "
        f"batch_inputs={len(batch_input.entered)} "
        f"batch_screens={batch_screens.count} "
        "batch_confirmations=1 batch_grade_selections=1 "
        "batch_actor_policy_interactions=1 "
        f"batch_elapsed_seconds={batch_elapsed:.3f} "
        f"batch_canonical_seconds={batch_execution_seconds[0]:.3f} "
        f"batch_changed_paths={batch_changed_paths} "
        "manual_canonical_ids=0 receipts_each=174 collateral_paths=0",
        flush=True,
    )
