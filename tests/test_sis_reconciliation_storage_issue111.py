from __future__ import annotations

from meridian.academic_period_proficiency_storage import (
    list_current_academic_period_proficiency_results,
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_result_revision,
)
from tests import test_academic_period_proficiency_storage as support


def test_list_current_results_returns_only_explicit_selected_period_results(
    tmp_path,
) -> None:
    workspace = support.root(tmp_path)
    support.persist_result_top_level_dependencies(workspace)
    stored = write_academic_period_proficiency_result_revision(
        workspace,
        support.period_result_snapshot(),
    ).stored
    select_academic_period_proficiency_result_revision(
        workspace,
        support.CLASS_ID,
        support.SCHOOL_YEAR,
        support.PERIOD_ID,
        support.STUDENT_ID,
        support.STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )

    assert list_current_academic_period_proficiency_results(
        workspace,
        support.CLASS_ID,
        support.SCHOOL_YEAR,
        support.PERIOD_ID,
    ) == (stored,)

    assert (
        list_current_academic_period_proficiency_results(
            workspace,
            support.CLASS_ID,
            support.SCHOOL_YEAR,
            "q2",
        )
        == ()
    )
