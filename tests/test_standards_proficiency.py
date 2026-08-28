from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.evidence import NativeStateValue
from meridian.evidence_eligibility import (
    EvidenceSourceReference,
    evidence_source_key,
)
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    NativeValueMappingProfileReference,
    ProficiencyLevel,
    ProficiencyScale,
    ProficiencyScaleReference,
    proficiency_scale_reference,
)
from meridian.standards_evidence import (
    STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
    STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
    AggregationDecisionReference,
    GradeItemAggregationBasis,
    StandardAggregationExclusionReason,
    StandardAggregationInputEntry,
    StandardAggregationInputs,
    StandardEvidenceAssociationReference,
)
from meridian.standards_proficiency import (
    MAXIMUM_STANDARD_PROFICIENCY_OBSERVATIONS,
    STANDARD_PROFICIENCY_ALGORITHM_VERSION,
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    NativeStateHandling,
    StandardProficiencyActor,
    StandardProficiencyActorKind,
    StandardProficiencyCalculationOutcome,
    StandardProficiencyCalculationPolicy,
    StandardProficiencySerializationError,
    StandardProficiencyValidationError,
    calculate_standard_proficiency,
    is_blockable_standard_aggregation_exclusion_reason,
    standard_proficiency_calculation_fingerprint,
    standard_proficiency_calculation_policy_from_json_bytes,
    standard_proficiency_calculation_policy_reference,
    standard_proficiency_calculation_policy_to_json_bytes,
    validate_standard_proficiency_calculation_policy_transition,
)

CLASS_ID = "synthetic_class_2026"
NOW = datetime(2026, 8, 27, 23, tzinfo=UTC)
SHA = "a" * 64
WORK = ModuleWorkRef("scoreform", CLASS_ID, "calculation_quiz")
STANDARD_ID = "urn:standard:calculation"
GRADE_ITEM_ID = "calculation_grade_item"


def scale_ref(*, digest: str = SHA) -> ProficiencyScaleReference:
    return ProficiencyScaleReference(
        CLASS_ID,
        "teacher_scale",
        1,
        digest,
    )


def actor(
    kind: StandardProficiencyActorKind = "teacher",
) -> StandardProficiencyActor:
    return StandardProficiencyActor(
        kind,
        f"{kind}_local",
    )


def policy(
    *,
    revision: int = 1,
    strategy: str = "highest",
    mode_tie_rule: str | None = None,
    median_even_rule: str | None = None,
    blocking: tuple[str, ...] = (
        "standard_unresolved",
        "mapping_not_supplied",
    ),
    native_state_handling: NativeStateHandling = "noncontributing",
    minimum: int = 1,
) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="teacher_standard_policy",
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Teacher standard proficiency",
        target_scale=scale_ref(),
        strategy=strategy,  # type: ignore[arg-type]
        minimum_performance_observations=minimum,
        mode_tie_rule=mode_tie_rule,  # type: ignore[arg-type]
        median_even_rule=median_even_rule,  # type: ignore[arg-type]
        blocking_exclusion_reasons=blocking,  # type: ignore[arg-type]
        native_state_handling=native_state_handling,
        actor=actor(),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )




def calculation_scale(
    level_ids: tuple[str, ...] = (
        "emerging",
        "developing",
        "proficient",
        "advanced",
    ),
) -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="calculation_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Calculation scale",
        description="Synthetic ordered scale for pure calculation tests.",
        levels=tuple(
            ProficiencyLevel(
                level_id,
                position,
                f"Level {position}",
                f"Synthetic level {position}.",
            )
            for position, level_id in enumerate(level_ids, start=1)
        ),
        proficiency_threshold_level_id=level_ids[-2],
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def calculation_policy(
    scale: ProficiencyScale,
    *,
    strategy: str = "highest",
    mode_tie_rule: str | None = None,
    median_even_rule: str | None = None,
    blocking: tuple[str, ...] = (),
    native_state_handling: NativeStateHandling = "noncontributing",
    minimum: int = 1,
) -> StandardProficiencyCalculationPolicy:
    return replace(
        policy(
            strategy=strategy,
            mode_tie_rule=mode_tie_rule,
            median_even_rule=median_even_rule,
            blocking=blocking,
            native_state_handling=native_state_handling,
            minimum=minimum,
        ),
        target_scale=proficiency_scale_reference(scale),
    )


def evidence_source(number: int) -> EvidenceSourceReference:
    return EvidenceSourceReference(
        WORK,
        "pub_" + "1" * 32,
        "2" * 64,
        "3" * 64,
        f"item_{number}",
    )


def association_reference(
    source: EvidenceSourceReference,
) -> StandardEvidenceAssociationReference:
    return StandardEvidenceAssociationReference(
        CLASS_ID,
        GRADE_ITEM_ID,
        source,
        STANDARD_ID,
        1,
        "4" * 64,
    )


def mapping_profile_reference(
    scale: ProficiencyScale,
) -> NativeValueMappingProfileReference:
    return NativeValueMappingProfileReference(
        CLASS_ID,
        scale.scale_id,
        "calculation_profile",
        1,
        "5" * 64,
    )


def performance_entry(
    number: int,
    level_id: str,
    scale: ProficiencyScale,
) -> StandardAggregationInputEntry:
    source = evidence_source(number)
    return StandardAggregationInputEntry(
        source=source,
        result_kind="question_correctness",
        target_kind="question",
        status="performance",
        exclusion_reason=None,
        membership_reference=AggregationDecisionReference(
            "membership",
            1,
            "6" * 64,
        ),
        eligibility_reference=AggregationDecisionReference(
            "eligibility",
            1,
            "7" * 64,
        ),
        attempt_selection_reference=None,
        reassessment_reference=None,
        association_reference=association_reference(source),
        mapping_profile_reference=mapping_profile_reference(scale),
        mapping_status="mapped",
        proficiency_level_id=level_id,
        native_state=None,
    )


def native_state_entry(
    number: int,
    code: str,
    scale: ProficiencyScale,
) -> StandardAggregationInputEntry:
    source = evidence_source(number)
    return StandardAggregationInputEntry(
        source=source,
        result_kind="selected_response_state",
        target_kind="question",
        status="native_state",
        exclusion_reason=None,
        membership_reference=AggregationDecisionReference(
            "membership",
            1,
            "6" * 64,
        ),
        eligibility_reference=AggregationDecisionReference(
            "eligibility",
            1,
            "7" * 64,
        ),
        attempt_selection_reference=None,
        reassessment_reference=None,
        association_reference=association_reference(source),
        mapping_profile_reference=mapping_profile_reference(scale),
        mapping_status="native_state",
        proficiency_level_id=None,
        native_state=NativeStateValue(code),
    )


def excluded_entry(
    number: int,
    reason: StandardAggregationExclusionReason,
) -> StandardAggregationInputEntry:
    return StandardAggregationInputEntry(
        source=evidence_source(number),
        result_kind="question_correctness",
        target_kind="question",
        status="excluded",
        exclusion_reason=reason,
        membership_reference=None,
        eligibility_reference=None,
        attempt_selection_reference=None,
        reassessment_reference=None,
        association_reference=None,
        mapping_profile_reference=None,
        mapping_status=None,
        proficiency_level_id=None,
        native_state=None,
    )


def calculation_inputs(
    scale: ProficiencyScale,
    *entries: StandardAggregationInputEntry,
) -> StandardAggregationInputs:
    ordered = tuple(
        sorted(
            entries,
            key=lambda entry: evidence_source_key(entry.source),
        )
    )
    return StandardAggregationInputs(
        STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        GradeItemAggregationBasis(
            CLASS_ID,
            GRADE_ITEM_ID,
            1,
            "8" * 64,
        ),
        "student_1",
        STANDARD_ID,
        proficiency_scale_reference(scale),
        ordered,
    )


def test_policy_model_is_frozen_slotted_and_algorithm_is_explicit() -> None:
    value = policy()
    assert STANDARD_PROFICIENCY_ALGORITHM_VERSION == "1"
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.title = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("strategy", "mode_rule", "median_rule"),
    [
        ("highest", None, None),
        ("lowest", None, None),
        ("median", None, "lower"),
        ("median", None, "higher"),
        ("median", None, "insufficient"),
        ("mode", "lower", None),
        ("mode", "higher", None),
        ("mode", "insufficient", None),
    ],
)
def test_supported_v1_strategy_shapes_are_explicit(
    strategy: str,
    mode_rule: str | None,
    median_rule: str | None,
) -> None:
    value = policy(
        strategy=strategy,
        mode_tie_rule=mode_rule,
        median_even_rule=median_rule,
    )
    assert value.strategy == strategy
    assert value.mode_tie_rule == mode_rule
    assert value.median_even_rule == median_rule


def test_strategy_rejects_irrelevant_or_missing_tie_rules() -> None:
    with pytest.raises(StandardProficiencyValidationError, match="requires"):
        policy(strategy="mode")
    with pytest.raises(StandardProficiencyValidationError, match="requires"):
        policy(strategy="median")
    with pytest.raises(StandardProficiencyValidationError, match="must not"):
        policy(strategy="highest", mode_tie_rule="lower")
    with pytest.raises(StandardProficiencyValidationError, match="must not"):
        policy(
            strategy="mode",
            mode_tie_rule="lower",
            median_even_rule="higher",
        )


def test_minimum_performance_observations_is_positive_and_bounded() -> None:
    assert policy(minimum=1).minimum_performance_observations == 1
    assert (
        policy(minimum=MAXIMUM_STANDARD_PROFICIENCY_OBSERVATIONS)
        .minimum_performance_observations
        == MAXIMUM_STANDARD_PROFICIENCY_OBSERVATIONS
    )
    with pytest.raises(StandardProficiencyValidationError, match="positive"):
        policy(minimum=0)
    with pytest.raises(StandardProficiencyValidationError, match="bounded"):
        policy(minimum=MAXIMUM_STANDARD_PROFICIENCY_OBSERVATIONS + 1)


def test_blocking_reasons_are_closed_to_unresolved_problem_states() -> None:
    value = policy(
        blocking=(
            "standard_unresolved",
            "association_unresolved",
            "mapping_unmapped",
        )
    )
    assert value.blocking_exclusion_reasons == (
        "association_unresolved",
        "mapping_unmapped",
        "standard_unresolved",
    )
    for allowed in value.blocking_exclusion_reasons:
        assert is_blockable_standard_aggregation_exclusion_reason(allowed)
    for deliberate in (
        "not_associated",
        "eligibility_not_included",
        "attempt_not_selected",
        "reassessment_noncontributing",
        "nonstudent_target",
        "student_mismatch",
    ):
        assert not is_blockable_standard_aggregation_exclusion_reason(
            deliberate
        )
        with pytest.raises(
            StandardProficiencyValidationError,
            match="nonblocking",
        ):
            policy(blocking=(deliberate,))


def test_blocking_reasons_reject_duplicates() -> None:
    with pytest.raises(StandardProficiencyValidationError, match="duplicates"):
        policy(
            blocking=(
                "mapping_not_supplied",
                "mapping_not_supplied",
            )
        )


@pytest.mark.parametrize("handling", ["noncontributing", "blocking"])
def test_native_state_handling_is_explicit(
    handling: NativeStateHandling,
) -> None:
    assert (
        policy(native_state_handling=handling).native_state_handling
        == handling
    )


def test_target_scale_must_match_policy_class() -> None:
    with pytest.raises(StandardProficiencyValidationError, match="class_id"):
        replace(
            policy(),
            target_scale=ProficiencyScaleReference(
                "other_class",
                "teacher_scale",
                1,
                SHA,
            ),
        )


def test_actor_is_teacher_or_policy_and_never_producer() -> None:
    assert actor("teacher").kind == "teacher"
    assert actor("policy").kind == "policy"
    with pytest.raises(StandardProficiencyValidationError, match="actor kind"):
        StandardProficiencyActor("producer", "producer_local")  # type: ignore[arg-type]


def test_policy_revision_pair_is_contiguous_by_construction() -> None:
    with pytest.raises(StandardProficiencyValidationError, match="revision 1"):
        replace(policy(), supersedes_revision=1)
    with pytest.raises(
        StandardProficiencyValidationError,
        match="immediately prior",
    ):
        replace(
            policy(revision=2),
            supersedes_revision=None,
        )


def test_policy_transition_preserves_identity_and_time_order() -> None:
    first = policy()
    second = policy(revision=2, minimum=2)
    assert (
        validate_standard_proficiency_calculation_policy_transition(
            first,
            second,
        )
        == second
    )
    with pytest.raises(
        StandardProficiencyValidationError,
        match="logical identity",
    ):
        validate_standard_proficiency_calculation_policy_transition(
            first,
            replace(second, policy_id="another_policy"),
        )
    with pytest.raises(
        StandardProficiencyValidationError,
        match="contiguous",
    ):
        validate_standard_proficiency_calculation_policy_transition(
            first,
            replace(
                second,
                policy_revision=3,
                supersedes_revision=2,
            ),
        )
    with pytest.raises(
        StandardProficiencyValidationError,
        match="nondecreasing",
    ):
        validate_standard_proficiency_calculation_policy_transition(
            first,
            replace(second, revised_at=NOW - timedelta(seconds=1)),
        )


def test_timestamp_is_timezone_aware_and_canonicalized_to_utc() -> None:
    with pytest.raises(
        StandardProficiencyValidationError,
        match="timezone-aware",
    ):
        replace(policy(), revised_at=datetime(2026, 8, 27, 23))
    offset = NOW.astimezone(timezone(timedelta(hours=-4)))
    assert replace(policy(), revised_at=offset).revised_at == NOW


def test_policy_json_round_trip_is_canonical_and_exact() -> None:
    value = policy(
        strategy="mode",
        mode_tie_rule="higher",
        blocking=("mapping_unmapped", "association_unresolved"),
        native_state_handling="blocking",
        minimum=2,
    )
    encoded = standard_proficiency_calculation_policy_to_json_bytes(value)
    assert encoded.endswith(b"\n")
    assert b"\r" not in encoded
    assert b'"strategy": "mode"' in encoded
    assert (
        standard_proficiency_calculation_policy_from_json_bytes(encoded)
        == value
    )
    assert b"2026-08-27T23:00:00.000000Z" in encoded


def test_json_rejects_duplicate_unknown_missing_and_noncanonical_bytes() -> None:
    encoded = standard_proficiency_calculation_policy_to_json_bytes(policy())
    duplicate = encoded.replace(
        b'{\n  "actor":',
        b'{\n  "policy_id": "duplicate",\n  "actor":',
        1,
    )
    with pytest.raises(
        StandardProficiencySerializationError,
        match="duplicate",
    ):
        standard_proficiency_calculation_policy_from_json_bytes(duplicate)

    unknown = encoded.replace(
        b"{\n",
        b'{\n  "unexpected": true,\n',
        1,
    )
    with pytest.raises(
        StandardProficiencySerializationError,
        match="unknown",
    ):
        standard_proficiency_calculation_policy_from_json_bytes(unknown)

    missing = encoded.replace(
        b'  "strategy": "highest",\n',
        b"",
        1,
    )
    with pytest.raises(
        StandardProficiencySerializationError,
        match="missing",
    ):
        standard_proficiency_calculation_policy_from_json_bytes(missing)

    with pytest.raises(
        StandardProficiencySerializationError,
        match="canonical",
    ):
        standard_proficiency_calculation_policy_from_json_bytes(
            encoded.replace(b"\n", b"\r\n")
        )


def test_policy_reference_binds_exact_revision_and_canonical_digest() -> None:
    first = policy()
    first_ref = standard_proficiency_calculation_policy_reference(first)
    assert first_ref.class_id == CLASS_ID
    assert first_ref.policy_id == first.policy_id
    assert first_ref.policy_revision == 1
    assert len(first_ref.policy_sha256) == 64

    changed = replace(first, title="Changed policy title")
    changed_ref = standard_proficiency_calculation_policy_reference(changed)
    assert changed_ref.policy_sha256 != first_ref.policy_sha256



def test_calculation_highest_and_lowest_use_scale_positions_only() -> None:
    scale = calculation_scale(("alpha", "omega", "middle"))
    inputs = calculation_inputs(
        scale,
        performance_entry(1, "omega", scale),
        performance_entry(2, "alpha", scale),
        performance_entry(3, "middle", scale),
    )

    highest = calculate_standard_proficiency(
        inputs,
        calculation_policy(scale, strategy="highest"),
        scale,
    )
    lowest = calculate_standard_proficiency(
        inputs,
        calculation_policy(scale, strategy="lowest"),
        scale,
    )

    assert highest.status == "calculated"
    assert highest.proficiency_level_id == "middle"
    assert lowest.proficiency_level_id == "alpha"
    assert tuple(
        (item.proficiency_level_id, item.count)
        for item in highest.level_counts
    ) == (
        ("alpha", 1),
        ("omega", 1),
        ("middle", 1),
    )


def test_median_odd_selects_the_ordered_middle_level() -> None:
    scale = calculation_scale(("low", "middle", "high"))
    inputs = calculation_inputs(
        scale,
        performance_entry(1, "high", scale),
        performance_entry(2, "low", scale),
        performance_entry(3, "middle", scale),
    )
    outcome = calculate_standard_proficiency(
        inputs,
        calculation_policy(
            scale,
            strategy="median",
            median_even_rule="insufficient",
        ),
        scale,
    )
    assert outcome.proficiency_level_id == "middle"
    assert outcome.tie_resolution is None


@pytest.mark.parametrize(
    ("rule", "expected", "status"),
    [
        ("lower", "low", "calculated"),
        ("higher", "high", "calculated"),
        ("insufficient", None, "insufficient_evidence"),
    ],
)
def test_median_even_uses_explicit_policy(
    rule: str,
    expected: str | None,
    status: str,
) -> None:
    scale = calculation_scale(("low", "middle", "high"))
    inputs = calculation_inputs(
        scale,
        performance_entry(1, "low", scale),
        performance_entry(2, "high", scale),
    )
    outcome = calculate_standard_proficiency(
        inputs,
        calculation_policy(
            scale,
            strategy="median",
            median_even_rule=rule,
        ),
        scale,
    )
    assert outcome.status == status
    assert outcome.proficiency_level_id == expected
    assert outcome.tie_resolution is not None
    assert outcome.tie_resolution.kind == "median_even"
    assert outcome.tie_resolution.rule == rule
    if rule == "insufficient":
        assert tuple(
            reason.kind for reason in outcome.insufficiency_reasons
        ) == ("unresolved_even_median",)


def test_mode_unique_winner_uses_counts_not_input_order() -> None:
    scale = calculation_scale(("low", "middle", "high"))
    inputs = calculation_inputs(
        scale,
        performance_entry(1, "high", scale),
        performance_entry(2, "middle", scale),
        performance_entry(3, "middle", scale),
        performance_entry(4, "low", scale),
    )
    outcome = calculate_standard_proficiency(
        inputs,
        calculation_policy(
            scale,
            strategy="mode",
            mode_tie_rule="insufficient",
        ),
        scale,
    )
    assert outcome.proficiency_level_id == "middle"
    assert outcome.tie_resolution is None


@pytest.mark.parametrize(
    ("rule", "expected", "status"),
    [
        ("lower", "low", "calculated"),
        ("higher", "high", "calculated"),
        ("insufficient", None, "insufficient_evidence"),
    ],
)
def test_mode_tie_uses_explicit_policy(
    rule: str,
    expected: str | None,
    status: str,
) -> None:
    scale = calculation_scale(("low", "middle", "high"))
    inputs = calculation_inputs(
        scale,
        performance_entry(1, "high", scale),
        performance_entry(2, "low", scale),
    )
    outcome = calculate_standard_proficiency(
        inputs,
        calculation_policy(
            scale,
            strategy="mode",
            mode_tie_rule=rule,
        ),
        scale,
    )
    assert outcome.status == status
    assert outcome.proficiency_level_id == expected
    assert outcome.tie_resolution is not None
    assert outcome.tie_resolution.kind == "mode_tie"
    if rule == "insufficient":
        assert tuple(
            reason.kind for reason in outcome.insufficiency_reasons
        ) == ("unresolved_mode_tie",)


def test_no_performance_is_insufficient_not_lowest_proficiency() -> None:
    scale = calculation_scale(("low", "high"))
    inputs = calculation_inputs(
        scale,
        native_state_entry(1, "unrated", scale),
        excluded_entry(2, "not_associated"),
    )
    outcome = calculate_standard_proficiency(
        inputs,
        calculation_policy(scale, strategy="highest"),
        scale,
    )
    assert outcome.status == "insufficient_evidence"
    assert outcome.proficiency_level_id is None
    assert tuple(
        reason.kind for reason in outcome.insufficiency_reasons
    ) == ("no_performance_evidence",)


def test_minimum_performance_count_is_checked_before_strategy() -> None:
    scale = calculation_scale(("low", "high"))
    inputs = calculation_inputs(
        scale,
        performance_entry(1, "high", scale),
    )
    outcome = calculate_standard_proficiency(
        inputs,
        calculation_policy(
            scale,
            strategy="highest",
            minimum=2,
        ),
        scale,
    )
    reason = outcome.insufficiency_reasons[0]
    assert reason.kind == "below_minimum_performance_observations"
    assert reason.required_observations == 2
    assert reason.actual_observations == 1


def test_blocking_exclusion_fails_closed_but_deliberate_exclusion_does_not() -> None:
    scale = calculation_scale(("low", "high"))
    blocked_inputs = calculation_inputs(
        scale,
        performance_entry(1, "high", scale),
        excluded_entry(2, "standard_unresolved"),
    )
    blocked = calculate_standard_proficiency(
        blocked_inputs,
        calculation_policy(
            scale,
            blocking=("standard_unresolved",),
        ),
        scale,
    )
    assert blocked.status == "insufficient_evidence"
    assert blocked.insufficiency_reasons[0].kind == "blocking_exclusion"
    assert len(blocked.insufficiency_reasons[0].source_keys) == 1

    deliberate_inputs = calculation_inputs(
        scale,
        performance_entry(1, "high", scale),
        excluded_entry(2, "not_associated"),
    )
    deliberate = calculate_standard_proficiency(
        deliberate_inputs,
        calculation_policy(
            scale,
            blocking=("standard_unresolved",),
        ),
        scale,
    )
    assert deliberate.status == "calculated"
    assert deliberate.proficiency_level_id == "high"


def test_native_state_handling_is_policy_controlled_without_zero_fabrication() -> None:
    scale = calculation_scale(("low", "high"))
    inputs = calculation_inputs(
        scale,
        performance_entry(1, "high", scale),
        native_state_entry(2, "unrated", scale),
    )
    noncontributing = calculate_standard_proficiency(
        inputs,
        calculation_policy(
            scale,
            native_state_handling="noncontributing",
        ),
        scale,
    )
    blocked = calculate_standard_proficiency(
        inputs,
        calculation_policy(
            scale,
            native_state_handling="blocking",
        ),
        scale,
    )
    assert noncontributing.proficiency_level_id == "high"
    assert noncontributing.native_state_count == 1
    assert blocked.status == "insufficient_evidence"
    assert blocked.proficiency_level_id is None
    assert blocked.insufficiency_reasons[0].kind == "blocking_native_state"


def test_calculation_rejects_level_outside_exact_target_scale() -> None:
    scale = calculation_scale(("low", "high"))
    inputs = calculation_inputs(
        scale,
        performance_entry(1, "outside", scale),
    )
    with pytest.raises(
        StandardProficiencyValidationError,
        match="outside the exact target scale",
    ):
        calculate_standard_proficiency(
            inputs,
            calculation_policy(scale),
            scale,
        )


def test_calculation_rejects_scale_or_policy_basis_mismatch() -> None:
    scale = calculation_scale(("low", "high"))
    inputs = calculation_inputs(
        scale,
        performance_entry(1, "high", scale),
    )
    changed_scale = replace(scale, title="Changed exact scale revision")
    with pytest.raises(
        StandardProficiencyValidationError,
        match="aggregation inputs",
    ):
        calculate_standard_proficiency(
            inputs,
            calculation_policy(changed_scale),
            changed_scale,
        )
    with pytest.raises(
        StandardProficiencyValidationError,
        match="calculation policy",
    ):
        calculate_standard_proficiency(
            inputs,
            replace(
                calculation_policy(scale),
                target_scale=ProficiencyScaleReference(
                    CLASS_ID,
                    scale.scale_id,
                    1,
                    "f" * 64,
                ),
            ),
            scale,
        )


def test_outcome_explanation_and_fingerprint_are_deterministic() -> None:
    scale = calculation_scale(("low", "middle", "high"))
    inputs = calculation_inputs(
        scale,
        performance_entry(1, "middle", scale),
        native_state_entry(2, "unrated", scale),
        excluded_entry(3, "not_associated"),
    )
    policy_value = calculation_policy(scale)
    first = calculate_standard_proficiency(
        inputs,
        policy_value,
        scale,
    )
    second = calculate_standard_proficiency(
        inputs,
        policy_value,
        scale,
    )
    assert isinstance(first, StandardProficiencyCalculationOutcome)
    assert first == second
    assert first.calculation_fingerprint == (
        standard_proficiency_calculation_fingerprint(
            inputs,
            policy_value,
            scale,
        )
    )
    assert first.aggregation_inputs_sha256 == inputs.sha256
    assert first.performance_observation_count == 1
    assert first.native_state_count == 1
    assert first.excluded_count == 1
    assert tuple(item.status for item in first.explanation_entries) == (
        tuple(
            entry.status
            for entry in inputs.entries
        )
    )
    assert {
        item.source_key for item in first.explanation_entries
    } == {
        evidence_source_key(entry.source) for entry in inputs.entries
    }
