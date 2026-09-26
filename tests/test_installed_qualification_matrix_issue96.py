from __future__ import annotations

import pytest

from scripts.installed_qualification_matrix import (
    DEPENDENCY_MATRICES,
    MATRIX_BY_ID,
    PRE_ISSUE96_ENVIRONMENT_SETUP_COUNT,
    SMOKE_ASSIGNMENTS,
    TARGET_SHARED_ENVIRONMENT_COUNT,
    DependencyMatrixId,
    assignments_for,
    matrix_for,
    validate_matrix_inventory,
)


def test_issue96_matrix_inventory_is_valid_and_unique() -> None:
    validate_matrix_inventory()

    matrix_ids = [matrix.matrix_id for matrix in DEPENDENCY_MATRICES]
    assert len(matrix_ids) == len(set(matrix_ids)) == 6
    assert len(MATRIX_BY_ID) == 6


def test_issue96_preoptimization_environment_count_is_recorded() -> None:
    assert PRE_ISSUE96_ENVIRONMENT_SETUP_COUNT == 24
    assert len(SMOKE_ASSIGNMENTS) == 24
    assert TARGET_SHARED_ENVIRONMENT_COUNT == 6


@pytest.mark.parametrize(
    ("matrix_id", "present", "absent"),
    (
        (DependencyMatrixId.CORE, (), ("scoreform", "quillan", "concord")),
        (
            DependencyMatrixId.SCOREFORM,
            ("scoreform",),
            ("quillan", "concord"),
        ),
        (
            DependencyMatrixId.QUILLAN,
            ("quillan",),
            ("scoreform", "concord"),
        ),
        (
            DependencyMatrixId.CONCORD,
            ("concord",),
            ("scoreform", "quillan"),
        ),
        (
            DependencyMatrixId.SCOREFORM_QUILLAN,
            ("scoreform", "quillan"),
            ("concord",),
        ),
        (
            DependencyMatrixId.ALL_ADAPTERS,
            ("scoreform", "quillan", "concord"),
            (),
        ),
    ),
)
def test_issue96_dependency_presence_and_absence_are_explicit(
    matrix_id: DependencyMatrixId,
    present: tuple[str, ...],
    absent: tuple[str, ...],
) -> None:
    matrix = matrix_for(matrix_id)

    assert matrix.producers == present
    assert matrix.excluded_producers == absent


def test_issue96_scoreform_quillan_acceptance_keeps_concord_absent() -> None:
    assignment_names = {
        assignment.name
        for assignment in assignments_for(DependencyMatrixId.SCOREFORM_QUILLAN)
    }

    assert assignment_names == {
        "proficiency-signal-export",
        "standards-grade",
        "hybrid-grade",
    }
    assert "concord" in matrix_for(
        DependencyMatrixId.SCOREFORM_QUILLAN
    ).excluded_producers


def test_issue96_producer_specific_adapter_boundaries_remain_distinct() -> None:
    assert {a.name for a in assignments_for(DependencyMatrixId.SCOREFORM)} == {
        "scoreform-adapter",
        "conventional-grade",
        "teacher-grade-override",
    }
    assert {a.name for a in assignments_for(DependencyMatrixId.QUILLAN)} == {
        "quillan-adapter",
    }
    assert {a.name for a in assignments_for(DependencyMatrixId.CONCORD)} == {
        "concord-adapter",
    }


def test_issue96_all_historical_environment_setups_map_once() -> None:
    names = [assignment.name for assignment in SMOKE_ASSIGNMENTS]

    assert len(names) == len(set(names))
    assert all(assignment.matrix_id in MATRIX_BY_ID for assignment in SMOKE_ASSIGNMENTS)


def test_issue96_smoke_mapping_is_deterministic() -> None:
    first = assignments_for(DependencyMatrixId.CORE)
    second = assignments_for("core")

    assert first == second
    assert tuple(assignment.name for assignment in first) == (
        "wheel-foundation",
        "grade-items",
        "academic-period-proficiency",
        "grouping-signal-contract",
        "grouping-signal-policy",
        "grouping-signal-generation",
        "grouping-signal-preview-review",
        "grouping-signal-export",
        "explanation-traces",
        "teacher-workflows",
        "attention",
    )


def test_issue96_unknown_matrix_reference_fails_closed() -> None:
    with pytest.raises(KeyError, match="Unknown installed qualification matrix"):
        matrix_for("not-a-matrix")
