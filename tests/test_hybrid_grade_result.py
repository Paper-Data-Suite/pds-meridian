from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.hybrid_grade_result import (
    HybridGradeResultFreshness,
    HybridGradeResultSerializationError,
    HybridGradeResultValidationError,
    assess_hybrid_grade_result_freshness,
    create_hybrid_grade_result_snapshot,
    hybrid_grade_result_snapshot_from_json_bytes,
    hybrid_grade_result_snapshot_to_json_bytes,
    validate_hybrid_grade_result_transition,
)
from tests.issue52_hybrid_test_support import (
    NOW,
    PERIOD,
    activation,
    conventional_input,
    hybrid_input,
    policy,
    standards_input,
)


def _basis():
    value = policy()
    decision = activation(value)
    inputs = hybrid_input(
        value,
        decision,
        conventional_input(value, decision, earned="92"),
        standards_input(value, decision),
    )
    return inputs, calculate_hybrid_grade(inputs)


def _snapshot(revision: int = 1):
    inputs, outcome = _basis()
    return create_hybrid_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=revision,
        calculated_at=NOW + timedelta(seconds=revision - 1),
    )


def test_snapshot_round_trip_is_canonical_and_reproduces_outcome() -> None:
    snapshot = _snapshot()
    encoded = hybrid_grade_result_snapshot_to_json_bytes(snapshot)
    decoded = hybrid_grade_result_snapshot_from_json_bytes(encoded)

    assert encoded.endswith(b"\n")
    assert decoded == snapshot
    assert calculate_hybrid_grade(decoded.inputs) == decoded.outcome
    assert hybrid_grade_result_snapshot_to_json_bytes(decoded) == encoded


def test_tampered_persisted_outcome_is_rejected() -> None:
    encoded = hybrid_grade_result_snapshot_to_json_bytes(_snapshot())
    decoded = json.loads(encoded.decode("utf-8"))
    decoded["outcome"]["rounded_grade"] = "99.99"
    tampered = (
        json.dumps(
            decoded,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")

    with pytest.raises(
        HybridGradeResultSerializationError,
        match="does not exactly reproduce",
    ):
        hybrid_grade_result_snapshot_from_json_bytes(tampered)


def test_freshness_is_current_for_exact_same_basis() -> None:
    snapshot = _snapshot()
    freshness = assess_hybrid_grade_result_freshness(snapshot, snapshot.inputs)

    assert freshness == HybridGradeResultFreshness("current", ())


def test_conventional_drift_is_distinct_from_proficiency_drift() -> None:
    snapshot = _snapshot()
    conventional = snapshot.inputs.conventional
    item = conventional.items[0]
    changed_conventional = replace(
        conventional,
        items=(replace(item, earned=Decimal("91")),),
    )
    conventional_inputs = replace(
        snapshot.inputs,
        conventional=changed_conventional,
    )

    conventional_freshness = assess_hybrid_grade_result_freshness(
        snapshot,
        conventional_inputs,
    )
    assert conventional_freshness.reasons == ("conventional_inputs_changed",)

    standards = snapshot.inputs.standards_based
    standard = standards.standards[0]
    assert standard.result_reference is not None
    changed_reference = replace(
        standard.result_reference,
        result_revision=2,
        result_sha256="e" * 64,
    )
    changed_standard = replace(
        standard,
        result_reference=changed_reference,
        result_calculation_fingerprint="f" * 64,
    )
    changed_standards = replace(standards, standards=(changed_standard,))
    proficiency_inputs = replace(
        snapshot.inputs,
        standards_based=changed_standards,
    )

    proficiency_freshness = assess_hybrid_grade_result_freshness(
        snapshot,
        proficiency_inputs,
    )
    assert proficiency_freshness.reasons == ("proficiency_results_changed",)


def test_authority_drift_is_not_double_labeled_as_source_drift() -> None:
    snapshot = _snapshot()
    new_policy = replace(
        snapshot.inputs.policy_reference,
        policy_sha256="e" * 64,
    )
    new_activation = replace(
        snapshot.inputs.activation_reference,
        activation_sha256="f" * 64,
    )
    conventional = replace(
        snapshot.inputs.conventional,
        policy_reference=new_policy,
        activation_reference=new_activation,
        items=(
            replace(
                snapshot.inputs.conventional.items[0],
                earned=Decimal("80"),
            ),
        ),
    )
    standards = replace(
        snapshot.inputs.standards_based,
        policy_reference=new_policy,
        activation_reference=new_activation,
    )
    changed = replace(
        snapshot.inputs,
        policy_reference=new_policy,
        activation_reference=new_activation,
        conventional=conventional,
        standards_based=standards,
    )

    freshness = assess_hybrid_grade_result_freshness(snapshot, changed)
    assert freshness.reasons == ("activation_changed", "policy_changed")


def test_calendar_scope_and_algorithm_reasons_use_canonical_order() -> None:
    snapshot = _snapshot()
    other_period = AcademicPeriodRef(PERIOD.school_year, "mp2")
    activation_reference = replace(
        snapshot.inputs.activation_reference,
        period_id=other_period.period_id,
    )
    conventional = snapshot.inputs.conventional
    conventional = replace(
        conventional,
        target_period=other_period,
        activation_reference=activation_reference,
        items=tuple(
            replace(item, target_period=other_period)
            for item in conventional.items
        ),
    )
    standards = snapshot.inputs.standards_based
    standards = replace(
        standards,
        target_period=other_period,
        activation_reference=activation_reference,
        standards=tuple(
            replace(
                item,
                target_period=other_period,
                result_reference=replace(
                    item.result_reference,
                    period_id=other_period.period_id,
                ),
            )
            for item in standards.standards
        ),
    )
    changed = replace(
        snapshot.inputs,
        target_period=other_period,
        activation_reference=activation_reference,
        conventional=conventional,
        standards_based=standards,
    )

    freshness = assess_hybrid_grade_result_freshness(
        snapshot,
        changed,
        hybrid_algorithm_version="2",
    )
    assert freshness.reasons == (
        "calendar_scope_changed",
        "activation_changed",
        "algorithm_changed",
    )


def test_component_algorithm_drift_is_algorithm_changed() -> None:
    snapshot = _snapshot()

    assert assess_hybrid_grade_result_freshness(
        snapshot,
        snapshot.inputs,
        conventional_algorithm_version="2",
    ).reasons == ("algorithm_changed",)
    assert assess_hybrid_grade_result_freshness(
        snapshot,
        snapshot.inputs,
        standards_algorithm_version="2",
    ).reasons == ("algorithm_changed",)


def test_freshness_contract_rejects_duplicate_reasons_and_bad_algorithm() -> None:
    with pytest.raises(HybridGradeResultValidationError, match="duplicates"):
        HybridGradeResultFreshness(
            "stale",
            ("policy_changed", "policy_changed"),
        )

    snapshot = _snapshot()
    with pytest.raises(HybridGradeResultValidationError):
        assess_hybrid_grade_result_freshness(
            snapshot,
            snapshot.inputs,
            hybrid_algorithm_version="",
        )


def test_result_history_transition_is_contiguous_and_scope_bound() -> None:
    first = _snapshot(1)
    second = _snapshot(2)
    assert validate_hybrid_grade_result_transition(first, second) == second

    with pytest.raises(HybridGradeResultValidationError, match="contiguous"):
        validate_hybrid_grade_result_transition(first, _snapshot(3))
