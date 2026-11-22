"""#126 H1: isolate honest consumer behavior; #133/#134 remain separate owners.

These synthetic rows represent the public evidence shapes. They are NOT a
teacher-authorized #30 projection or an end-to-end Report 9 acceptance test.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace as NS
from typing import cast

import pytest

from meridian.benchmark_current_analysis import _student_results
from meridian.evidence import (
    EvidenceItem,
    NativePointValue,
    NativeScalarValue,
    NativeStateValue,
)
from meridian.report_menu_execution import _benchmark_item_observations


@dataclass(frozen=True)
class _Work:
    work_id: str


def _question(
    student: str,
    attempt: str,
    question: str,
    value: bool,
    *,
    state: str | None = None,
    work: _Work = _Work("synthetic_assessment"),
) -> tuple[EvidenceItem, ...]:
    target = NS(
        target_kind="question",
        target_id=question,
        parent_target=NS(target_kind="attempt", target_id=attempt),
        standard_ids=("RL.TS.11-12.4",),
    )
    rows = [
        cast(
            EvidenceItem,
            NS(
                item_id=f"{student}_{work.work_id}_{attempt}_{question}_correctness",
                target=target,
                provenance=NS(work=work),
                result_kind="question_correctness",
                value=NativeScalarValue(value),
            ),
        )
    ]
    if state is not None:
        rows.append(
            cast(
                EvidenceItem,
                NS(
                    item_id=f"{student}_{work.work_id}_{attempt}_{question}_state",
                    target=target,
                    provenance=NS(work=work),
                    result_kind="selected_response_state",
                    value=NativeStateValue(state),
                ),
            )
        )
    return tuple(rows)


def _attempt_score(student: str, attempt: str, earned: int) -> EvidenceItem:
    return cast(
        EvidenceItem,
        NS(
            item_id=f"{student}_{attempt}_total",
            result_kind="attempt_points",
            target=NS(target_kind="attempt", target_id=attempt),
            value=NativePointValue(earned, 6),
        ),
    )


def _one(observed: dict[str, tuple[EvidenceItem, ...]]):
    return _benchmark_item_observations(observed)


def test_single_observed_attempt_is_counted_without_scoring_policy() -> None:
    result = _one({"synthetic_01": _question("synthetic_01", "one", "q1", True)})
    assert len(result) == 1
    assert result[0].item_id == "synthetic_assessment / q1"
    assert result[0].correct_responses == 1
    assert result[0].incorrect_responses == 0
    assert result[0].standard_ids == ("RL.TS.11-12.4",)


def test_multi_observed_attempts_are_omitted_not_arbitrarily_selected() -> None:
    rows = (
        *_question("synthetic_29", "attempt_1", "q1", False),
        *_question("synthetic_29", "attempt_2", "q1", True),
    )
    assert _one({"synthetic_29": rows}) == ()
    # This is a deliberately documented #134 gap, not an acceptable final
    # interpretation of a teacher-resolved attempt selection.


def test_29_by_six_correction_fixture_exposes_report9_omission() -> None:
    observed: dict[str, tuple[EvidenceItem, ...]] = {}
    for index in range(1, 30):
        student = f"synthetic_{index:02d}"
        rows: list[EvidenceItem] = []
        for question in range(1, 7):
            if index == 29:
                rows.extend(_question(student, "attempt_1", f"q{question}", False))
                rows.extend(_question(student, "attempt_2", f"q{question}", True))
            else:
                rows.extend(_question(student, "attempt_1", f"q{question}", True))
        observed[student] = tuple(rows)
    result = _one(observed)
    assert len(result) == 6
    assert {row.item_id for row in result} == {
        f"synthetic_assessment / q{question}" for question in range(1, 7)
    }
    assert all(row.correct_responses == 28 for row in result)
    assert all(row.incorrect_responses == 0 for row in result)
    assert all(row.blank_responses == 0 for row in result)
    # Corrected Attempt 2 is not counted: #134 must resolve exact #30 state.


@pytest.mark.parametrize(
    "state,attribute",
    [("blank", "blank_responses"), ("ambiguous", "ambiguous_responses")],
)
def test_blank_or_ambiguous_native_state_never_becomes_correct(
    state: str, attribute: str
) -> None:
    rows = _question("synthetic_01", "attempt_1", "q1", True, state=state)
    result = _one({"synthetic_01": rows})
    assert len(result) == 1
    assert getattr(result[0], attribute) == 1
    assert result[0].correct_responses == 0


def test_duplicate_native_correctness_is_ambiguous() -> None:
    conflicting = _question("synthetic_01", "attempt_1", "q1", False)[0]
    conflicting.item_id += "_conflicting"
    rows = (
        *_question("synthetic_01", "attempt_1", "q1", True),
        conflicting,
    )
    result = _one({"synthetic_01": rows})
    assert result[0].ambiguous_responses == 1
    assert result[0].correct_responses == 0


def test_separate_work_sources_never_share_question_count() -> None:
    rows = (
        *_question("synthetic_01", "one", "q1", True, work=_Work("assessment_alpha")),
        *_question("synthetic_01", "one", "q1", False, work=_Work("assessment_beta")),
    )
    result = _one({"synthetic_01": rows})
    assert {row.item_id for row in result} == {
        "assessment_alpha / q1",
        "assessment_beta / q1",
    }


def test_report9_student_summary_never_selects_first_or_highest_score() -> None:
    students = (("synthetic_01", "Synthetic One"),)
    observed = {
        "synthetic_01": (
            _attempt_score("synthetic_01", "attempt_1", 0),
            _attempt_score("synthetic_01", "attempt_2", 6),
        )
    }
    result = _student_results(students, observed, {})
    assert len(result) == 1
    assert result[0].result_status == "valid"
    assert result[0].native_score is None
    assert result[0].selected_proficiency is None


def test_report9_single_score_and_absent_student_are_distinct() -> None:
    students = (("synthetic_01", "Synthetic One"), ("synthetic_02", "Synthetic Two"))
    observed = {"synthetic_01": (_attempt_score("synthetic_01", "one", 6),)}
    result = _student_results(students, observed, {})
    assert result[0].native_score == "6/6"
    assert result[1].native_score is None
    assert result[1].result_status == "not_assessed"
    assert result[1].tested is False


def test_report9_same_score_two_native_attempts_still_ambiguous() -> None:
    students = (("synthetic_01", "Synthetic One"),)
    observed = {
        "synthetic_01": (
            _attempt_score("synthetic_01", "attempt_1", 6),
            _attempt_score("synthetic_01", "attempt_2", 6),
        )
    }
    result = _student_results(students, observed, {})
    assert result[0].native_score is None


def test_empty_report9_observations_cannot_fabricate_zeroes() -> None:
    assert _one({"synthetic_01": ()}) == ()
    assert _one({}) == ()
