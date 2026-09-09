from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from meridian.academic_period_proficiency import (
    calculate_academic_period_proficiency,
)
from meridian.academic_period_proficiency_storage import (
    get_current_academic_period_proficiency_result_revision,
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_result_revision,
)
from meridian.evidence import NativeScalarValue, NativeStateValue
from meridian.proficiency_mapping import map_native_value
from meridian.standards_proficiency import calculate_standard_proficiency
from meridian.standards_proficiency_storage import (
    get_current_standard_proficiency_result_revision,
    select_standard_proficiency_result_revision,
    write_standard_proficiency_result_revision,
)
from tests.test_academic_period_proficiency import (
    calculated_input_entry,
    missing_input_entry,
)
from tests.test_academic_period_proficiency import (
    calculation_inputs as period_inputs,
)
from tests.test_academic_period_proficiency import (
    calculation_policy as period_policy,
)
from tests.test_academic_period_proficiency import (
    calculation_scale as period_scale,
)
from tests.test_academic_period_proficiency_storage import (
    CLASS_ID as PERIOD_CLASS_ID,
)
from tests.test_academic_period_proficiency_storage import (
    PERIOD_ID,
    SCHOOL_YEAR,
    period_result_snapshot,
    persist_result_top_level_dependencies,
)
from tests.test_academic_period_proficiency_storage import (
    STANDARD_ID as PERIOD_STANDARD_ID,
)
from tests.test_academic_period_proficiency_storage import (
    STUDENT_ID as PERIOD_STUDENT_ID,
)
from tests.test_academic_period_proficiency_storage import (
    root as period_workspace,
)
from tests.test_proficiency_mapping import (
    scalar_profile,
    signature,
)
from tests.test_proficiency_mapping import (
    scale as mapping_scale,
)
from tests.test_standards_proficiency import (
    calculation_inputs as grade_item_inputs,
)
from tests.test_standards_proficiency import (
    calculation_policy as grade_item_policy,
)
from tests.test_standards_proficiency import (
    calculation_scale as grade_item_scale,
)
from tests.test_standards_proficiency import (
    excluded_entry,
    native_state_entry,
    performance_entry,
)
from tests.test_standards_proficiency_result_storage import (
    CLASS_ID as GRADE_CLASS_ID,
)
from tests.test_standards_proficiency_result_storage import (
    GRADE_ITEM_ID,
)
from tests.test_standards_proficiency_result_storage import (
    STANDARD_ID as GRADE_STANDARD_ID,
)
from tests.test_standards_proficiency_result_storage import (
    STUDENT_ID as GRADE_STUDENT_ID,
)
from tests.test_standards_proficiency_result_storage import (
    snapshot as grade_item_snapshot,
)
from tests.test_standards_proficiency_result_storage import (
    workspace as grade_item_workspace,
)


def test_same_native_scalar_from_other_producer_does_not_cross_apply() -> None:
    target = mapping_scale()
    profile = scalar_profile(target_scale=target)

    matching = map_native_value(
        NativeScalarValue(True),
        signature(),
        profile,
        target,
    )
    cross_producer = map_native_value(
        NativeScalarValue(True),
        signature(producer="quillan"),
        profile,
        target,
    )

    assert matching.status == "mapped"
    assert matching.proficiency_level_id == "proficient"
    assert cross_producer.status == "unsupported"
    assert cross_producer.unsupported_reason == "source_signature_mismatch"


def test_native_non_score_state_does_not_become_low_proficiency() -> None:
    target = mapping_scale()
    profile = scalar_profile(target_scale=target)

    result = map_native_value(
        NativeStateValue("unrated"),
        signature(),
        profile,
        target,
    )

    assert result.status == "native_state"
    assert result.proficiency_level_id is None
    assert result.native_state == NativeStateValue("unrated")


def test_grade_item_aggregation_uses_scale_position_and_preserves_no_evidence() -> None:
    target = grade_item_scale(("alpha", "omega", "middle"))
    calculated = calculate_standard_proficiency(
        grade_item_inputs(
            target,
            performance_entry(1, "omega", target),
            performance_entry(2, "middle", target),
        ),
        grade_item_policy(target, strategy="highest"),
        target,
    )
    insufficient = calculate_standard_proficiency(
        grade_item_inputs(
            target,
            native_state_entry(1, "unrated", target),
            excluded_entry(2, "not_associated"),
        ),
        grade_item_policy(target, strategy="highest"),
        target,
    )

    assert calculated.status == "calculated"
    assert calculated.proficiency_level_id == "middle"
    assert insufficient.status == "insufficient_evidence"
    assert insufficient.proficiency_level_id is None


def test_academic_period_missing_result_is_policy_state_not_lowest_level() -> None:
    target = period_scale()
    mixed = calculate_academic_period_proficiency(
        period_inputs(
            target,
            calculated_input_entry("grade_a", level_id="proficient"),
            missing_input_entry("grade_b"),
        ),
        period_policy(target, missing="noncontributing"),
        target,
    )
    missing_only = calculate_academic_period_proficiency(
        period_inputs(target, missing_input_entry("grade_a")),
        period_policy(target, missing="noncontributing"),
        target,
    )

    assert mixed.status == "calculated"
    assert mixed.proficiency_level_id == "proficient"
    assert missing_only.status == "insufficient_evidence"
    assert missing_only.proficiency_level_id is None


def test_grade_item_result_write_does_not_select_and_history_can_be_reselected(
    tmp_path: Path,
) -> None:
    workspace = grade_item_workspace(tmp_path)
    first = grade_item_snapshot(workspace)
    second = grade_item_snapshot(
        workspace,
        revision=2,
        calculated_at=first.calculated_at + timedelta(minutes=1),
    )

    write_standard_proficiency_result_revision(workspace, first)
    write_standard_proficiency_result_revision(workspace, second)

    assert (
        get_current_standard_proficiency_result_revision(
            workspace,
            GRADE_CLASS_ID,
            GRADE_ITEM_ID,
            GRADE_STUDENT_ID,
            GRADE_STANDARD_ID,
        )
        is None
    )

    select_standard_proficiency_result_revision(
        workspace,
        GRADE_CLASS_ID,
        GRADE_ITEM_ID,
        GRADE_STUDENT_ID,
        GRADE_STANDARD_ID,
        2,
        expected_current_result_revision=None,
    )
    select_standard_proficiency_result_revision(
        workspace,
        GRADE_CLASS_ID,
        GRADE_ITEM_ID,
        GRADE_STUDENT_ID,
        GRADE_STANDARD_ID,
        1,
        expected_current_result_revision=2,
    )

    assert (
        get_current_standard_proficiency_result_revision(
            workspace,
            GRADE_CLASS_ID,
            GRADE_ITEM_ID,
            GRADE_STUDENT_ID,
            GRADE_STANDARD_ID,
        )
        == 1
    )


def test_academic_period_result_write_does_not_select_and_history_can_be_reselected(
    tmp_path: Path,
) -> None:
    workspace = period_workspace(tmp_path)
    persist_result_top_level_dependencies(workspace)

    write_academic_period_proficiency_result_revision(
        workspace,
        period_result_snapshot(revision=1),
    )
    write_academic_period_proficiency_result_revision(
        workspace,
        period_result_snapshot(revision=2),
    )

    assert (
        get_current_academic_period_proficiency_result_revision(
            workspace,
            PERIOD_CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            PERIOD_STUDENT_ID,
            PERIOD_STANDARD_ID,
        )
        is None
    )

    select_academic_period_proficiency_result_revision(
        workspace,
        PERIOD_CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        PERIOD_STUDENT_ID,
        PERIOD_STANDARD_ID,
        2,
        expected_current_result_revision=None,
    )
    select_academic_period_proficiency_result_revision(
        workspace,
        PERIOD_CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        PERIOD_STUDENT_ID,
        PERIOD_STANDARD_ID,
        1,
        expected_current_result_revision=2,
    )

    assert (
        get_current_academic_period_proficiency_result_revision(
            workspace,
            PERIOD_CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            PERIOD_STUDENT_ID,
            PERIOD_STANDARD_ID,
        )
        == 1
    )
