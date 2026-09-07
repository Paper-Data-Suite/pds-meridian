from __future__ import annotations

from pathlib import Path

import meridian.attempt_selection_storage as attempt_storage
import meridian.reassessment_storage as reassessment_storage
from meridian.evidence import NativePointValue
from tests.cross_producer_attempts_support import (
    derive_scoreform_attempts,
    prepare_attempt_workspace,
    replace_first_with_second_attempt,
    select_both_scoreform_attempts,
)
from tests.cross_producer_proficiency_support import GRADE_ITEM_ID
from tests.cross_producer_test_support import SHARED_STUDENT_ID


def _scoreform_points_by_attempt(scenario: object) -> dict[int, int | float]:
    projected = getattr(scenario, "projected")["scoreform"].inventory
    result: dict[int, int | float] = {}
    for item in projected.items:
        if (
            item.subject is None
            or item.subject.student_id != SHARED_STUDENT_ID
            or item.result_kind != "attempt_points"
            or not isinstance(item.value, NativePointValue)
        ):
            continue
        if item.target.sequence is None:
            raise AssertionError("ScoreForm attempt target must carry a sequence.")
        result[item.target.sequence] = item.value.earned
    return result


def test_real_scoreform_selection_and_reassessment_do_not_rank_by_score(
    tmp_path: Path,
) -> None:
    scenario = prepare_attempt_workspace(tmp_path)
    derivation = derive_scoreform_attempts(scenario)

    assert derivation.status == "applicable"
    assert tuple(
        candidate.attempt.native.sequence
        for candidate in derivation.candidates
    ) == (1, 2)
    assert all(candidate.eligible_evidence for candidate in derivation.candidates)

    points = _scoreform_points_by_attempt(scenario)
    assert points == {1: 2, 2: 1}

    selection = select_both_scoreform_attempts(scenario, derivation)
    assert selection.status == "selected"
    assert selection.operative_selection
    assert selection.selected is not None
    assert tuple(
        attempt.native.sequence
        for attempt in selection.selected.decision.selected_attempts
    ) == (1, 2)

    reassessment = replace_first_with_second_attempt(scenario, selection)
    assert reassessment.status == "resolved"
    assert reassessment.operative_reassessment
    assert tuple(
        attempt.native.sequence
        for attempt in reassessment.contributing_attempts
    ) == (2,)
    assert reassessment.selected is not None
    relationship = reassessment.selected.decision.replacement_relationships[0]
    assert relationship.replacement_attempt.native.sequence == 2
    assert tuple(
        attempt.native.sequence for attempt in relationship.replaced_attempts
    ) == (1,)

    # The lower-scoring attempt contributes because the relationship is explicit,
    # not because Meridian inferred "latest", "highest", or another ranking.
    assert points[2] < points[1]


def test_real_quillan_and_concord_stay_outside_attempt_semantics(
    tmp_path: Path,
) -> None:
    scenario = prepare_attempt_workspace(tmp_path)

    for module_id in ("quillan", "concord"):
        work = scenario.mixed.publications[module_id].work
        derivation = attempt_storage.derive_attempt_candidates(
            scenario.mixed.root,
            work.class_id,
            GRADE_ITEM_ID,
            SHARED_STUDENT_ID,
            scenario.authorized[module_id],
        )
        assert derivation.status == "not_applicable"
        assert derivation.candidates == ()

        selection = attempt_storage.resolve_current_attempt_selection(
            scenario.mixed.root,
            work.class_id,
            GRADE_ITEM_ID,
            work,
            SHARED_STUDENT_ID,
            authorized_snapshot=scenario.authorized[module_id],
        )
        assert selection.status == "not_applicable"
        assert not selection.operative_selection

        reassessment = reassessment_storage.resolve_current_reassessment(
            scenario.mixed.root,
            work.class_id,
            GRADE_ITEM_ID,
            work,
            SHARED_STUDENT_ID,
            authorized_snapshot=scenario.authorized[module_id],
        )
        assert reassessment.status == "not_applicable"
        assert reassessment.contributing_attempts == ()
        assert not reassessment.operative_reassessment
