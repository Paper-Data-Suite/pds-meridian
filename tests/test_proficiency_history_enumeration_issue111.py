from __future__ import annotations

from meridian.academic_period_proficiency_storage import (
    list_academic_period_proficiency_result_standard_ids,
)
from tests import test_academic_period_proficiency_storage as support


def test_history_enumeration_includes_unselected_result_families(tmp_path) -> None:
    workspace = support.root(tmp_path)
    first = support.period_result_snapshot(revision=1)
    second = support.period_result_snapshot(revision=2)
    other_standard = "urn:njsls:ela:RL.CI.11-12.2"
    other = support.period_result_snapshot(
        revision=1,
        standard_id=other_standard,
    )
    another_student = support.period_result_snapshot(
        revision=1,
        student_id="student_2",
    )

    support.seed_result_revision(workspace, first)
    support.seed_result_revision(workspace, second)
    support.seed_result_revision(workspace, other)
    support.seed_result_revision(workspace, another_student)

    assert list_academic_period_proficiency_result_standard_ids(
        workspace,
        support.CLASS_ID,
        support.SCHOOL_YEAR,
        support.PERIOD_ID,
        support.STUDENT_ID,
    ) == tuple(sorted((support.STANDARD_ID, other_standard)))

    assert (
        list_academic_period_proficiency_result_standard_ids(
            workspace,
            support.CLASS_ID,
            support.SCHOOL_YEAR,
            support.PERIOD_ID,
            "student_without_history",
        )
        == ()
    )
