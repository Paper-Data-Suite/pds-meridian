from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.routing_models import ModuleWorkRef

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION,
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    ACADEMIC_PERIOD_PROFICIENCY_RESULT_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_RESULT_SCHEMA_VERSION,
    MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULTS,
    AcademicPeriodProficiencyAggregationInputEntry,
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyCalculationOutcome,
    AcademicPeriodProficiencyInsufficiencyReason,
    AcademicPeriodProficiencyMembershipBasis,
    AcademicPeriodProficiencyResultFreshness,
    AcademicPeriodProficiencyResultSnapshot,
    AcademicPeriodProficiencyScopeResolution,
    AcademicPeriodProficiencySerializationError,
    AcademicPeriodProficiencyTarget,
    AcademicPeriodProficiencyValidationError,
    ResolvedAcademicPeriodProficiencyCandidate,
    academic_period_proficiency_aggregation_input_entry_from_dict,
    academic_period_proficiency_aggregation_input_entry_to_dict,
    academic_period_proficiency_aggregation_inputs_from_dict,
    academic_period_proficiency_aggregation_inputs_from_json_bytes,
    academic_period_proficiency_aggregation_inputs_sha256,
    academic_period_proficiency_aggregation_inputs_to_dict,
    academic_period_proficiency_aggregation_inputs_to_json_bytes,
    academic_period_proficiency_aggregation_policy_from_dict,
    academic_period_proficiency_aggregation_policy_from_json_bytes,
    academic_period_proficiency_aggregation_policy_reference,
    academic_period_proficiency_aggregation_policy_reference_from_dict,
    academic_period_proficiency_aggregation_policy_reference_to_dict,
    academic_period_proficiency_aggregation_policy_sha256,
    academic_period_proficiency_aggregation_policy_to_dict,
    academic_period_proficiency_aggregation_policy_to_json_bytes,
    academic_period_proficiency_calculation_fingerprint,
    academic_period_proficiency_calculation_outcome_from_json_bytes,
    academic_period_proficiency_calculation_outcome_to_json_bytes,
    academic_period_proficiency_membership_basis_from_decision,
    academic_period_proficiency_membership_basis_from_dict,
    academic_period_proficiency_membership_basis_to_dict,
    academic_period_proficiency_result_reference,
    academic_period_proficiency_result_reference_from_dict,
    academic_period_proficiency_result_reference_to_dict,
    academic_period_proficiency_result_snapshot_from_json_bytes,
    academic_period_proficiency_result_snapshot_to_json_bytes,
    academic_period_proficiency_target_from_dict,
    academic_period_proficiency_target_to_dict,
    assess_academic_period_proficiency_result_freshness,
    build_academic_period_proficiency_aggregation_inputs,
    calculate_academic_period_proficiency,
    create_academic_period_proficiency_result_snapshot,
    is_academic_period_membership_scope,
    is_period_result_handling,
    resolve_academic_period_proficiency_scope,
    validate_academic_period_proficiency_aggregation_policy_transition,
    validate_academic_period_proficiency_result_transition,
)
from meridian.evidence_eligibility import (
    EvidenceSourceReference,
    evidence_source_key,
)
from meridian.grade_item_memberships import (
    GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
    GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
    grade_item_membership_decision_to_json_bytes,
)
from meridian.grade_items import GradeItemWorkReference
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
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
    StandardAggregationInputEntry,
    StandardAggregationInputs,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_ALGORITHM_VERSION,
    STANDARD_PROFICIENCY_RESULT_RECORD_TYPE,
    STANDARD_PROFICIENCY_RESULT_SCHEMA_VERSION,
    StandardProficiencyActor,
    StandardProficiencyCalculationOutcome,
    StandardProficiencyCalculationPolicyReference,
    StandardProficiencyEntryExplanation,
    StandardProficiencyInsufficiencyReason,
    StandardProficiencyResultReference,
    StandardProficiencyResultSnapshot,
    standard_proficiency_result_reference,
)

CLASS_ID = "synthetic_class_2026"
NOW = datetime(2026, 8, 28, 15, tzinfo=UTC)
SHA = "a" * 64


def scale_ref(*, class_id: str = CLASS_ID) -> ProficiencyScaleReference:
    return ProficiencyScaleReference(
        class_id,
        "teacher_scale",
        1,
        SHA,
    )


def actor() -> StandardProficiencyActor:
    return StandardProficiencyActor("teacher", "teacher_local")


def policy(
    *,
    revision: int = 1,
    strategy: str = "highest",
    scope: str = "direct",
    mode_tie_rule: str | None = None,
    median_even_rule: str | None = None,
    missing: str = "noncontributing",
    insufficient: str = "noncontributing",
    minimum: int = 1,
    target_scale: ProficiencyScaleReference | None = None,
    revised_at: datetime | None = None,
) -> AcademicPeriodProficiencyAggregationPolicy:
    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="teacher_period_policy",
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Teacher Academic Period proficiency",
        target_scale=target_scale or scale_ref(),
        strategy=strategy,  # type: ignore[arg-type]
        period_membership_scope=scope,  # type: ignore[arg-type]
        minimum_calculated_results=minimum,
        mode_tie_rule=mode_tie_rule,  # type: ignore[arg-type]
        median_even_rule=median_even_rule,  # type: ignore[arg-type]
        missing_result_handling=missing,  # type: ignore[arg-type]
        insufficient_result_handling=insufficient,  # type: ignore[arg-type]
        actor=actor(),
        rationale=None,
        revised_at=revised_at or NOW + timedelta(minutes=revision - 1),
    )


def test_policy_model_is_frozen_slotted_and_uses_exact_v1_identity() -> None:
    value = policy()
    assert value.schema_version == "1"
    assert value.record_type == (
        "meridian_academic_period_proficiency_aggregation_policy"
    )
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
def test_supported_v1_strategy_shapes_match_grade_item_semantics(
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


def test_strategy_rejects_missing_or_irrelevant_tie_rules() -> None:
    with pytest.raises(AcademicPeriodProficiencyValidationError, match="requires"):
        policy(strategy="mode")
    with pytest.raises(AcademicPeriodProficiencyValidationError, match="requires"):
        policy(strategy="median")
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="must not define",
    ):
        policy(strategy="highest", mode_tie_rule="lower")


@pytest.mark.parametrize("scope", ["direct", "descendants"])
def test_period_membership_scope_is_exact_and_closed(scope: str) -> None:
    assert is_academic_period_membership_scope(scope)
    assert policy(scope=scope).period_membership_scope == scope

    assert not is_academic_period_membership_scope(scope.upper())
    assert not is_academic_period_membership_scope(f" {scope}")


@pytest.mark.parametrize("handling", ["noncontributing", "blocking"])
def test_missing_and_insufficient_handling_are_independent(
    handling: str,
) -> None:
    assert is_period_result_handling(handling)
    value = policy(missing=handling, insufficient=handling)
    assert value.missing_result_handling == handling
    assert value.insufficient_result_handling == handling


def test_scope_and_result_handling_reject_unknown_values() -> None:
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="period_membership_scope",
    ):
        policy(scope="siblings")
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="missing_result_handling",
    ):
        policy(missing="lowest")


@pytest.mark.parametrize("minimum", [0, -1, True])
def test_minimum_calculated_results_requires_positive_nonboolean_integer(
    minimum: int,
) -> None:
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="positive integer",
    ):
        policy(minimum=minimum)


def test_minimum_calculated_results_is_bounded() -> None:
    value = policy(minimum=MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULTS)
    assert (
        value.minimum_calculated_results
        == MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULTS
    )
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="bounded maximum",
    ):
        policy(minimum=MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULTS + 1)


def test_policy_target_scale_must_match_class_scope() -> None:
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="target_scale class_id",
    ):
        policy(target_scale=scale_ref(class_id="other_class"))


def test_policy_revised_at_is_canonicalized_to_utc() -> None:
    local = datetime(
        2026,
        8,
        28,
        11,
        tzinfo=timezone(timedelta(hours=-4)),
    )
    value = policy(revised_at=local)
    assert value.revised_at == NOW
    assert value.revised_at.tzinfo is UTC


def test_revision_shape_and_transition_are_contiguous_and_explicit() -> None:
    first = policy()
    second = policy(revision=2)
    assert (
        validate_academic_period_proficiency_aggregation_policy_transition(
            first,
            second,
        )
        == second
    )

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="contiguous",
    ):
        validate_academic_period_proficiency_aggregation_policy_transition(
            first,
            policy(revision=3),
        )

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="logical identity",
    ):
        validate_academic_period_proficiency_aggregation_policy_transition(
            first,
            replace(second, policy_id="another_policy"),
        )


def test_transition_rejects_backward_revision_time() -> None:
    first = policy()
    second = policy(
        revision=2,
        revised_at=NOW - timedelta(seconds=1),
    )
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="nondecreasing",
    ):
        validate_academic_period_proficiency_aggregation_policy_transition(
            first,
            second,
        )


def test_policy_mapping_and_json_round_trip_are_exact_and_stable() -> None:
    original = policy(
        strategy="median",
        scope="descendants",
        median_even_rule="higher",
        missing="blocking",
        insufficient="noncontributing",
        minimum=2,
    )

    data = academic_period_proficiency_aggregation_policy_to_dict(original)
    assert set(data) == {
        "schema_version",
        "record_type",
        "class_id",
        "policy_id",
        "policy_revision",
        "supersedes_revision",
        "title",
        "target_scale",
        "strategy",
        "period_membership_scope",
        "minimum_calculated_results",
        "mode_tie_rule",
        "median_even_rule",
        "missing_result_handling",
        "insufficient_result_handling",
        "actor",
        "rationale",
        "revised_at",
    }
    assert academic_period_proficiency_aggregation_policy_from_dict(data) == original

    payload = academic_period_proficiency_aggregation_policy_to_json_bytes(
        original
    )
    assert payload.endswith(b"\n")
    assert (
        academic_period_proficiency_aggregation_policy_from_json_bytes(payload)
        == original
    )
    assert payload == (
        academic_period_proficiency_aggregation_policy_to_json_bytes(original)
    )


def test_policy_reference_binds_exact_canonical_policy_bytes() -> None:
    value = policy()
    reference = academic_period_proficiency_aggregation_policy_reference(value)
    assert reference.class_id == CLASS_ID
    assert reference.policy_id == value.policy_id
    assert reference.policy_revision == 1
    assert reference.policy_sha256 == (
        academic_period_proficiency_aggregation_policy_sha256(value)
    )

    data = academic_period_proficiency_aggregation_policy_reference_to_dict(
        reference
    )
    assert (
        academic_period_proficiency_aggregation_policy_reference_from_dict(data)
        == reference
    )

    changed = replace(value, missing_result_handling="blocking")
    assert (
        academic_period_proficiency_aggregation_policy_sha256(changed)
        != reference.policy_sha256
    )


def test_policy_mapping_rejects_missing_unknown_and_nonstring_keys() -> None:
    data = academic_period_proficiency_aggregation_policy_to_dict(policy())

    missing = dict(data)
    missing.pop("strategy")
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="missing",
    ):
        academic_period_proficiency_aggregation_policy_from_dict(missing)

    unknown = dict(data)
    unknown["unexpected"] = "value"
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="unknown",
    ):
        academic_period_proficiency_aggregation_policy_from_dict(unknown)

    nonstring: dict[object, object] = dict(data)
    nonstring[1] = "value"
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="keys must be strings",
    ):
        academic_period_proficiency_aggregation_policy_from_dict(nonstring)


def test_policy_json_rejects_duplicate_keys_and_nonstandard_constants() -> None:
    payload = (
        b'{"schema_version":"1","schema_version":"1","record_type":"x"}'
    )
    with pytest.raises(
        AcademicPeriodProficiencySerializationError,
        match="duplicate JSON object key",
    ):
        academic_period_proficiency_aggregation_policy_from_json_bytes(payload)

    with pytest.raises(
        AcademicPeriodProficiencySerializationError,
        match="non-standard JSON numeric constant",
    ):
        academic_period_proficiency_aggregation_policy_from_json_bytes(
            b'{"value":NaN}'
        )


def test_policy_json_rejects_invalid_utf8_and_nonobject_top_level() -> None:
    with pytest.raises(
        AcademicPeriodProficiencySerializationError,
        match="UTF-8",
    ):
        academic_period_proficiency_aggregation_policy_from_json_bytes(
            b"\xff"
        )

    with pytest.raises(
        AcademicPeriodProficiencySerializationError,
        match="JSON object",
    ):
        academic_period_proficiency_aggregation_policy_from_json_bytes(
            b"[]"
        )



def period_target(
    period_id: str = "mp1",
    *,
    school_year: str = "2026-2027",
    calendar_revision: int = 1,
) -> AcademicPeriodProficiencyTarget:
    return AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(school_year, period_id),
        calendar_revision,
    )


def grade_item_basis(
    grade_item_id: str = "grade_a",
    *,
    revision: int = 1,
    digest: str = "b" * 64,
) -> GradeItemAggregationBasis:
    return GradeItemAggregationBasis(
        CLASS_ID,
        grade_item_id,
        revision,
        digest,
    )


def membership_basis(
    grade_item_id: str = "grade_a",
    *,
    module_id: str = "scoreform",
    work_id: str = "work_a",
    period_id: str = "mp1",
    school_year: str = "2026-2027",
    calendar_revision: int = 1,
    grade_item_revision: int = 1,
    grade_item_digest: str = "b" * 64,
    membership_revision: int = 1,
    membership_digest: str = "c" * 64,
) -> AcademicPeriodProficiencyMembershipBasis:
    return AcademicPeriodProficiencyMembershipBasis(
        grade_item_id=grade_item_id,
        grade_item_revision=grade_item_revision,
        grade_item_revision_sha256=grade_item_digest,
        work_reference=GradeItemWorkReference(
            ModuleWorkRef(module_id, CLASS_ID, work_id),
            1,
        ),
        membership_revision=membership_revision,
        membership_sha256=membership_digest,
        academic_period=period_target(
            period_id,
            school_year=school_year,
            calendar_revision=calendar_revision,
        ),
    )


def membership_decision(
    grade_item_id: str = "grade_a",
    *,
    decision: str = "included",
    period_id: str = "mp1",
    module_id: str = "scoreform",
    work_id: str = "work_a",
    grade_item_revision: int = 1,
    grade_item_digest: str = "b" * 64,
) -> GradeItemMembershipDecision:
    assignment = (
        GradeItemAcademicPeriodAssignment(
            AcademicPeriodRef("2026-2027", period_id),
            1,
        )
        if decision == "included"
        else None
    )
    return GradeItemMembershipDecision(
        schema_version=GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
        record_type=GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=grade_item_id,
        grade_item_revision=grade_item_revision,
        grade_item_revision_sha256=grade_item_digest,
        work_reference=GradeItemWorkReference(
            ModuleWorkRef(module_id, CLASS_ID, work_id),
            1,
        ),
        membership_revision=1,
        supersedes_revision=None,
        decision=decision,  # type: ignore[arg-type]
        academic_period=assignment,
        actor_id="teacher_local",
        rationale=None,
        decided_at=NOW,
    )


def exact_membership_basis_from_decision(
    decision: GradeItemMembershipDecision,
) -> AcademicPeriodProficiencyMembershipBasis:
    digest = hashlib.sha256(
        grade_item_membership_decision_to_json_bytes(decision)
    ).hexdigest()
    return academic_period_proficiency_membership_basis_from_decision(
        decision,
        digest,
    )


def grade_item_result_snapshot(
    grade_item_id: str = "grade_a",
    *,
    student_id: str = "student_1",
    standard_id: str = "urn:standard:period",
    status: str = "calculated",
    level_id: str | None = "proficient",
    target_scale: ProficiencyScaleReference | None = None,
    grade_item_revision: int = 1,
    grade_item_digest: str = "b" * 64,
) -> StandardProficiencyResultSnapshot:
    scale = target_scale or scale_ref()
    basis = grade_item_basis(
        grade_item_id,
        revision=grade_item_revision,
        digest=grade_item_digest,
    )
    standard_inputs = StandardAggregationInputs(
        schema_version=STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        record_type=STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item=basis,
        student_id=student_id,
        standard_id=standard_id,
        target_scale=scale,
        entries=(),
    )
    policy_reference = StandardProficiencyCalculationPolicyReference(
        CLASS_ID,
        "grade_item_policy",
        1,
        "7" * 64,
    )
    if status == "calculated":
        reasons: tuple[StandardProficiencyInsufficiencyReason, ...] = ()
        outcome_level = level_id
    else:
        reasons = (
            StandardProficiencyInsufficiencyReason(
                "no_performance_evidence",
                actual_observations=0,
            ),
        )
        outcome_level = None
    outcome = StandardProficiencyCalculationOutcome(
        algorithm_version=STANDARD_PROFICIENCY_ALGORITHM_VERSION,
        status=status,  # type: ignore[arg-type]
        proficiency_level_id=outcome_level,
        aggregation_inputs_sha256=standard_inputs.sha256,
        calculation_fingerprint="8" * 64,
        policy_reference=policy_reference,
        target_scale=scale,
        performance_observation_count=0,
        native_state_count=0,
        excluded_count=0,
        level_counts=(),
        insufficiency_reasons=reasons,
        tie_resolution=None,
        explanation_entries=(),
    )
    return StandardProficiencyResultSnapshot(
        schema_version=STANDARD_PROFICIENCY_RESULT_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_RESULT_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=grade_item_id,
        student_id=student_id,
        standard_id=standard_id,
        result_revision=1,
        supersedes_revision=None,
        algorithm_version=STANDARD_PROFICIENCY_ALGORITHM_VERSION,
        calculation_fingerprint=outcome.calculation_fingerprint,
        inputs=standard_inputs,
        inputs_sha256=standard_inputs.sha256,
        policy_reference=policy_reference,
        target_scale=scale,
        outcome=outcome,
        calculated_at=NOW,
    )


def grade_item_result_with_membership_provenance(
    membership: AcademicPeriodProficiencyMembershipBasis,
) -> StandardProficiencyResultSnapshot:
    """Build a synthetic #34 result carrying one exact membership reference."""

    basis = grade_item_basis(
        membership.grade_item_id,
        revision=membership.grade_item_revision,
        digest=membership.grade_item_revision_sha256,
    )
    target_scale = scale_ref()
    source = EvidenceSourceReference(
        membership.work_reference.work,
        "pub_" + "a" * 32,
        "1" * 64,
        "2" * 64,
        "item_a",
    )
    entry = StandardAggregationInputEntry(
        source=source,
        result_kind="synthetic",
        target_kind="question",
        status="excluded",
        exclusion_reason="eligibility_not_included",
        membership_reference=AggregationDecisionReference(
            "membership",
            membership.membership_revision,
            membership.membership_sha256,
        ),
        eligibility_reference=None,
        attempt_selection_reference=None,
        reassessment_reference=None,
        association_reference=None,
        mapping_profile_reference=None,
        mapping_status=None,
        proficiency_level_id=None,
        native_state=None,
    )
    inputs = StandardAggregationInputs(
        schema_version=STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        record_type=STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item=basis,
        student_id="student_1",
        standard_id="urn:standard:period",
        target_scale=target_scale,
        entries=(entry,),
    )
    policy_reference = StandardProficiencyCalculationPolicyReference(
        CLASS_ID,
        "grade_item_policy",
        1,
        "7" * 64,
    )
    outcome = StandardProficiencyCalculationOutcome(
        algorithm_version=STANDARD_PROFICIENCY_ALGORITHM_VERSION,
        status="insufficient_evidence",
        proficiency_level_id=None,
        aggregation_inputs_sha256=inputs.sha256,
        calculation_fingerprint="8" * 64,
        policy_reference=policy_reference,
        target_scale=target_scale,
        performance_observation_count=0,
        native_state_count=0,
        excluded_count=1,
        level_counts=(),
        insufficiency_reasons=(
            StandardProficiencyInsufficiencyReason(
                "no_performance_evidence",
                actual_observations=0,
            ),
        ),
        tie_resolution=None,
        explanation_entries=(
            StandardProficiencyEntryExplanation(
                evidence_source_key(source),
                "excluded",
                None,
                None,
                "eligibility_not_included",
            ),
        ),
    )
    return StandardProficiencyResultSnapshot(
        schema_version=STANDARD_PROFICIENCY_RESULT_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_RESULT_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=membership.grade_item_id,
        student_id="student_1",
        standard_id="urn:standard:period",
        result_revision=1,
        supersedes_revision=None,
        algorithm_version=STANDARD_PROFICIENCY_ALGORITHM_VERSION,
        calculation_fingerprint=outcome.calculation_fingerprint,
        inputs=inputs,
        inputs_sha256=inputs.sha256,
        policy_reference=policy_reference,
        target_scale=target_scale,
        outcome=outcome,
        calculated_at=NOW,
    )


def resolved_candidate(
    grade_item_id: str = "grade_a",
    *,
    memberships: tuple[AcademicPeriodProficiencyMembershipBasis, ...] | None = None,
    result: StandardProficiencyResultSnapshot | None = None,
) -> ResolvedAcademicPeriodProficiencyCandidate:
    return ResolvedAcademicPeriodProficiencyCandidate(
        grade_item=grade_item_basis(grade_item_id),
        memberships=memberships or (membership_basis(grade_item_id),),
        result=result,
    )


def test_resolved_candidate_accepts_matching_result_membership_provenance() -> None:
    membership = membership_basis()
    result = grade_item_result_with_membership_provenance(membership)

    candidate = resolved_candidate(
        memberships=(membership,),
        result=result,
    )

    assert candidate.memberships == (membership,)
    assert candidate.result == result


@pytest.mark.parametrize(
    ("membership_revision", "membership_digest"),
    (
        (2, "d" * 64),
        (1, "d" * 64),
    ),
)
def test_resolved_candidate_rejects_stale_result_membership_provenance(
    membership_revision: int,
    membership_digest: str,
) -> None:
    recorded = membership_basis()
    result = grade_item_result_with_membership_provenance(recorded)
    supplied = membership_basis(
        membership_revision=membership_revision,
        membership_digest=membership_digest,
    )

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="membership revision and digest",
    ):
        resolved_candidate(
            memberships=(supplied,),
            result=result,
        )


def test_resolved_candidate_rejects_result_membership_work_absent_from_basis() -> None:
    recorded = membership_basis()
    result = grade_item_result_with_membership_provenance(recorded)
    supplied = membership_basis(work_id="work_b")

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="work absent",
    ):
        resolved_candidate(
            memberships=(supplied,),
            result=result,
        )


def result_reference(
    grade_item_id: str = "grade_a",
    *,
    student_id: str = "student_1",
    standard_id: str = "urn:standard:period",
    digest: str = "d" * 64,
) -> StandardProficiencyResultReference:
    return StandardProficiencyResultReference(
        CLASS_ID,
        grade_item_id,
        student_id,
        standard_id,
        1,
        digest,
    )


def calculated_input_entry(
    grade_item_id: str = "grade_a",
    *,
    level_id: str = "proficient",
) -> AcademicPeriodProficiencyAggregationInputEntry:
    return AcademicPeriodProficiencyAggregationInputEntry(
        grade_item=grade_item_basis(grade_item_id),
        memberships=(membership_basis(grade_item_id),),
        status="calculated",
        period_scope_mismatch_reason=None,
        result_reference=result_reference(grade_item_id),
        result_algorithm_version="1",
        result_calculation_fingerprint="e" * 64,
        result_status="calculated",
        proficiency_level_id=level_id,
        result_insufficiency_reasons=(),
    )


def insufficient_input_entry(
    grade_item_id: str = "grade_a",
) -> AcademicPeriodProficiencyAggregationInputEntry:
    return AcademicPeriodProficiencyAggregationInputEntry(
        grade_item=grade_item_basis(grade_item_id),
        memberships=(membership_basis(grade_item_id),),
        status="insufficient_evidence",
        period_scope_mismatch_reason=None,
        result_reference=result_reference(grade_item_id),
        result_algorithm_version="1",
        result_calculation_fingerprint="e" * 64,
        result_status="insufficient_evidence",
        proficiency_level_id=None,
        result_insufficiency_reasons=(
            StandardProficiencyInsufficiencyReason(
                "no_performance_evidence",
                actual_observations=0,
            ),
        ),
    )


def missing_input_entry(
    grade_item_id: str = "grade_a",
) -> AcademicPeriodProficiencyAggregationInputEntry:
    return AcademicPeriodProficiencyAggregationInputEntry(
        grade_item=grade_item_basis(grade_item_id),
        memberships=(membership_basis(grade_item_id),),
        status="missing_result",
        period_scope_mismatch_reason=None,
        result_reference=None,
        result_algorithm_version=None,
        result_calculation_fingerprint=None,
        result_status=None,
        proficiency_level_id=None,
        result_insufficiency_reasons=(),
    )


def mismatch_input_entry(
    grade_item_id: str = "grade_a",
) -> AcademicPeriodProficiencyAggregationInputEntry:
    return AcademicPeriodProficiencyAggregationInputEntry(
        grade_item=grade_item_basis(grade_item_id),
        memberships=(
            membership_basis(
                grade_item_id,
                module_id="quillan",
                work_id="work_b",
                period_id="mp2",
                membership_digest="f" * 64,
            ),
            membership_basis(grade_item_id, work_id="work_a", period_id="mp1"),
        ),
        status="period_scope_mismatch",
        period_scope_mismatch_reason="mixed_sibling_periods",
        result_reference=result_reference(grade_item_id),
        result_algorithm_version="1",
        result_calculation_fingerprint="e" * 64,
        result_status="calculated",
        proficiency_level_id="proficient",
        result_insufficiency_reasons=(),
    )


def period_inputs(
    *entries: AcademicPeriodProficiencyAggregationInputEntry,
) -> AcademicPeriodProficiencyAggregationInputs:
    return AcademicPeriodProficiencyAggregationInputs(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=period_target(),
        student_id="student_1",
        standard_id="urn:standard:period",
        target_scale=scale_ref(),
        period_membership_scope="direct",
        entries=entries,
    )


def test_target_and_membership_basis_are_frozen_exact_snapshots() -> None:
    target = period_target()
    membership = membership_basis()

    assert target.period.period_id == "mp1"
    assert target.calendar_revision == 1
    assert membership.grade_item_id == "grade_a"
    assert membership.academic_period == target
    assert not hasattr(target, "__dict__")
    assert not hasattr(membership, "__dict__")

    with pytest.raises(FrozenInstanceError):
        target.calendar_revision = 2  # type: ignore[misc]


def test_membership_basis_round_trip_preserves_exact_period_provenance() -> None:
    original = membership_basis(calendar_revision=3, period_id="semester_1")
    data = academic_period_proficiency_membership_basis_to_dict(original)
    assert (
        academic_period_proficiency_membership_basis_from_dict(data)
        == original
    )
    assert (
        academic_period_proficiency_target_from_dict(
            academic_period_proficiency_target_to_dict(original.academic_period)
        )
        == original.academic_period
    )


@pytest.mark.parametrize(
    "entry_factory",
    [
        calculated_input_entry,
        insufficient_input_entry,
        missing_input_entry,
        mismatch_input_entry,
    ],
)
def test_all_four_canonical_input_states_round_trip(
    entry_factory: object,
) -> None:
    entry = entry_factory()  # type: ignore[operator]
    data = academic_period_proficiency_aggregation_input_entry_to_dict(entry)
    assert academic_period_proficiency_aggregation_input_entry_from_dict(data) == entry


def test_entry_requires_complete_membership_basis_for_exact_grade_item() -> None:
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="at least one included membership",
    ):
        replace(calculated_input_entry(), memberships=())

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="exact Grade Item basis",
    ):
        replace(
            calculated_input_entry(),
            memberships=(membership_basis(grade_item_id="grade_b"),),
        )


def test_membership_basis_requires_deterministic_unique_work_ordering() -> None:
    first = membership_basis(
        module_id="quillan",
        work_id="work_b",
        membership_digest="f" * 64,
    )
    second = membership_basis(work_id="work_a")

    value = replace(calculated_input_entry(), memberships=(first, second))
    assert len(value.memberships) == 2

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="deterministic module/work ordering",
    ):
        replace(calculated_input_entry(), memberships=(second, first))

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="must not duplicate",
    ):
        replace(calculated_input_entry(), memberships=(first, first))


def test_result_shape_is_exact_for_calculated_and_insufficient_states() -> None:
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="requires one level",
    ):
        replace(calculated_input_entry(), proficiency_level_id=None)

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="requires no level",
    ):
        replace(
            insufficient_input_entry(),
            proficiency_level_id="emerging",
        )


def test_missing_result_must_not_carry_fabricated_result_metadata() -> None:
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="must not carry normalized result fields",
    ):
        replace(
            missing_input_entry(),
            result_algorithm_version="1",
        )


def test_period_scope_mismatch_is_explicit_and_can_preserve_result_provenance() -> None:
    entry = mismatch_input_entry()
    assert entry.period_scope_mismatch_reason == "mixed_sibling_periods"
    assert entry.result_reference is not None
    assert entry.result_status == "calculated"

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="requires an explicit mismatch reason",
    ):
        replace(entry, period_scope_mismatch_reason=None)


def test_inputs_require_unique_deterministically_ordered_grade_items() -> None:
    first = calculated_input_entry("grade_a")
    second = missing_input_entry("grade_b")
    value = period_inputs(first, second)
    assert tuple(item.grade_item.grade_item_id for item in value.entries) == (
        "grade_a",
        "grade_b",
    )

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="deterministic Grade Item ID ordering",
    ):
        period_inputs(second, first)

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="must not duplicate",
    ):
        period_inputs(first, first)


def test_inputs_validate_exact_result_class_student_and_standard_scope() -> None:
    wrong_student = replace(
        calculated_input_entry(),
        result_reference=result_reference(student_id="student_2"),
    )
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="class/student/standard scope",
    ):
        period_inputs(wrong_student)


def test_inputs_normalize_durable_standard_id_and_bind_target_scale() -> None:
    value = replace(
        period_inputs(calculated_input_entry()),
        standard_id="  urn:standard:period  ",
    )
    assert value.standard_id == "urn:standard:period"

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="target_scale class_id",
    ):
        replace(
            value,
            target_scale=scale_ref(class_id="other_class"),
        )


def test_inputs_round_trip_and_sha_are_stable() -> None:
    original = period_inputs(
        calculated_input_entry("grade_a"),
        insufficient_input_entry("grade_b"),
        missing_input_entry("grade_c"),
        mismatch_input_entry("grade_d"),
    )
    data = academic_period_proficiency_aggregation_inputs_to_dict(original)
    assert academic_period_proficiency_aggregation_inputs_from_dict(data) == original

    payload = academic_period_proficiency_aggregation_inputs_to_json_bytes(original)
    assert payload.endswith(b"\n")
    assert (
        academic_period_proficiency_aggregation_inputs_from_json_bytes(payload)
        == original
    )
    assert original.sha256 == academic_period_proficiency_aggregation_inputs_sha256(
        original
    )


def test_inputs_json_rejects_noncanonical_equivalent_payload() -> None:
    original = period_inputs(calculated_input_entry())
    payload = academic_period_proficiency_aggregation_inputs_to_json_bytes(original)
    noncanonical = payload.replace(b'  "class_id"', b'    "class_id"', 1)
    assert noncanonical != payload

    with pytest.raises(
        AcademicPeriodProficiencySerializationError,
        match="not canonical JSON",
    ):
        academic_period_proficiency_aggregation_inputs_from_json_bytes(
            noncanonical
        )


def test_policy_json_also_rejects_noncanonical_equivalent_payload() -> None:
    original = policy()
    payload = academic_period_proficiency_aggregation_policy_to_json_bytes(original)
    noncanonical = payload.replace(b'  "actor"', b'    "actor"', 1)
    assert noncanonical != payload

    with pytest.raises(
        AcademicPeriodProficiencySerializationError,
        match="not canonical JSON",
    ):
        academic_period_proficiency_aggregation_policy_from_json_bytes(
            noncanonical
        )


def academic_period_calendar(
    *,
    revision: int = 1,
) -> AcademicPeriodCalendar:
    return AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year="2026-2027",
        calendar_revision=revision,
        created_at=NOW,
        updated_at=NOW,
        periods=(
            AcademicPeriod(
                "semester_1",
                "semester",
                "Semester 1",
                date(2026, 9, 1),
                date(2027, 1, 31),
                None,
                1,
                "active",
            ),
            AcademicPeriod(
                "mp1",
                "marking_period",
                "Marking Period 1",
                date(2026, 9, 1),
                date(2026, 11, 15),
                "semester_1",
                1,
                "active",
            ),
            AcademicPeriod(
                "mp2",
                "marking_period",
                "Marking Period 2",
                date(2026, 11, 16),
                date(2027, 1, 31),
                "semester_1",
                2,
                "planned",
            ),
            AcademicPeriod(
                "parallel_window",
                "custom",
                "Parallel Window",
                date(2026, 9, 1),
                date(2027, 1, 31),
                None,
                2,
                "active",
            ),
        ),
    )


def test_scope_resolution_value_is_frozen_and_exact() -> None:
    eligible = AcademicPeriodProficiencyScopeResolution("eligible", None)
    mismatch = AcademicPeriodProficiencyScopeResolution(
        "period_scope_mismatch",
        "mixed_sibling_periods",
    )
    assert eligible.mismatch_reason is None
    assert mismatch.mismatch_reason == "mixed_sibling_periods"
    assert not hasattr(eligible, "__dict__")

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="must not carry",
    ):
        AcademicPeriodProficiencyScopeResolution(
            "eligible",
            "outside_target_period",
        )


def test_direct_scope_requires_every_membership_on_exact_target() -> None:
    result = resolve_academic_period_proficiency_scope(
        period_target("mp1"),
        academic_period_calendar(),
        (
            membership_basis(
                module_id="quillan",
                work_id="writing",
                period_id="mp1",
                membership_digest="f" * 64,
            ),
            membership_basis(work_id="quiz", period_id="mp1"),
        ),
        "direct",
    )
    assert result == AcademicPeriodProficiencyScopeResolution("eligible", None)


def test_direct_scope_blocks_mixed_mp1_mp2_as_explicit_sibling_mismatch() -> None:
    result = resolve_academic_period_proficiency_scope(
        period_target("mp1"),
        academic_period_calendar(),
        (
            membership_basis(work_id="quiz", period_id="mp1"),
            membership_basis(
                module_id="quillan",
                work_id="writing",
                period_id="mp2",
                membership_digest="f" * 64,
            ),
        ),
        "direct",
    )
    assert result == AcademicPeriodProficiencyScopeResolution(
        "period_scope_mismatch",
        "mixed_sibling_periods",
    )


def test_descendants_scope_allows_mp1_and_mp2_under_semester_1() -> None:
    result = resolve_academic_period_proficiency_scope(
        period_target("semester_1"),
        academic_period_calendar(),
        (
            membership_basis(work_id="quiz", period_id="mp1"),
            membership_basis(
                module_id="quillan",
                work_id="writing",
                period_id="mp2",
                membership_digest="f" * 64,
            ),
        ),
        "descendants",
    )
    assert result.status == "eligible"
    assert result.mismatch_reason is None


def test_direct_parent_scope_does_not_inherit_child_membership() -> None:
    result = resolve_academic_period_proficiency_scope(
        period_target("semester_1"),
        academic_period_calendar(),
        (
            membership_basis(work_id="quiz", period_id="mp1"),
            membership_basis(
                module_id="quillan",
                work_id="writing",
                period_id="mp2",
                membership_digest="f" * 64,
            ),
        ),
        "direct",
    )
    assert result.mismatch_reason == "mixed_sibling_periods"


def test_single_outside_period_uses_outside_target_period() -> None:
    result = resolve_academic_period_proficiency_scope(
        period_target("mp1"),
        academic_period_calendar(),
        (membership_basis(period_id="mp2"),),
        "descendants",
    )
    assert result == AcademicPeriodProficiencyScopeResolution(
        "period_scope_mismatch",
        "outside_target_period",
    )


def test_overlapping_parallel_period_dates_do_not_create_scope_membership() -> None:
    result = resolve_academic_period_proficiency_scope(
        period_target("semester_1"),
        academic_period_calendar(),
        (membership_basis(period_id="parallel_window"),),
        "descendants",
    )
    assert result.mismatch_reason == "outside_target_period"


def test_membership_school_year_mismatch_is_explicit_before_hierarchy() -> None:
    result = resolve_academic_period_proficiency_scope(
        period_target("mp1"),
        academic_period_calendar(),
        (membership_basis(school_year="2027-2028"),),
        "direct",
    )
    assert result.mismatch_reason == "school_year_mismatch"


def test_membership_calendar_revision_mismatch_is_explicit() -> None:
    result = resolve_academic_period_proficiency_scope(
        period_target("mp1"),
        academic_period_calendar(),
        (membership_basis(calendar_revision=2),),
        "direct",
    )
    assert result.mismatch_reason == "calendar_revision_mismatch"


def test_target_must_match_and_exist_in_exact_calendar_revision() -> None:
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="calendar_revision must match",
    ):
        resolve_academic_period_proficiency_scope(
            period_target("mp1", calendar_revision=2),
            academic_period_calendar(),
            (membership_basis(),),
            "direct",
        )

    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="target period must exist",
    ):
        resolve_academic_period_proficiency_scope(
            period_target("missing_period"),
            academic_period_calendar(),
            (membership_basis(),),
            "direct",
        )


def test_matching_revision_membership_period_must_exist_in_calendar() -> None:
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="period missing from the exact calendar",
    ):
        resolve_academic_period_proficiency_scope(
            period_target("mp1"),
            academic_period_calendar(),
            (membership_basis(period_id="not_in_calendar"),),
            "direct",
        )


def calculation_scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="teacher_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Teacher scale",
        description="Synthetic ordered scale for Academic Period tests.",
        levels=(
            ProficiencyLevel("emerging", 1, "Emerging", "Synthetic level 1."),
            ProficiencyLevel("developing", 2, "Developing", "Synthetic level 2."),
            ProficiencyLevel("proficient", 3, "Proficient", "Synthetic level 3."),
            ProficiencyLevel("advanced", 4, "Advanced", "Synthetic level 4."),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def calculation_policy(
    scale: ProficiencyScale,
    *,
    strategy: str = "highest",
    scope: str = "direct",
    mode_tie_rule: str | None = None,
    median_even_rule: str | None = None,
    missing: str = "noncontributing",
    insufficient: str = "noncontributing",
    minimum: int = 1,
) -> AcademicPeriodProficiencyAggregationPolicy:
    return policy(
        strategy=strategy,
        scope=scope,
        mode_tie_rule=mode_tie_rule,
        median_even_rule=median_even_rule,
        missing=missing,
        insufficient=insufficient,
        minimum=minimum,
        target_scale=proficiency_scale_reference(scale),
    )


def calculation_inputs(
    scale: ProficiencyScale,
    *entries: AcademicPeriodProficiencyAggregationInputEntry,
) -> AcademicPeriodProficiencyAggregationInputs:
    return replace(
        period_inputs(*entries),
        target_scale=proficiency_scale_reference(scale),
    )



def test_membership_basis_from_exact_included_decision_binds_canonical_digest() -> None:
    decision = membership_decision()
    basis = exact_membership_basis_from_decision(decision)
    assert basis.grade_item_id == decision.grade_item_id
    assert basis.membership_revision == decision.membership_revision
    assert basis.work_reference == decision.work_reference
    assert basis.academic_period == period_target()
    assert basis.membership_sha256 == hashlib.sha256(
        grade_item_membership_decision_to_json_bytes(decision)
    ).hexdigest()


def test_membership_basis_from_decision_rejects_wrong_digest_and_excluded() -> None:
    included = membership_decision()
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="decision_sha256",
    ):
        academic_period_proficiency_membership_basis_from_decision(
            included,
            "0" * 64,
        )

    excluded = membership_decision(decision="excluded")
    digest = hashlib.sha256(
        grade_item_membership_decision_to_json_bytes(excluded)
    ).hexdigest()
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="included",
    ):
        academic_period_proficiency_membership_basis_from_decision(
            excluded,
            digest,
        )


def test_resolved_candidate_requires_exact_result_grade_item_basis() -> None:
    result = grade_item_result_snapshot(grade_item_digest="9" * 64)
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="exact candidate Grade Item basis",
    ):
        resolved_candidate(result=result)


def test_builder_normalizes_calculated_insufficient_and_missing_results() -> None:
    scale = scale_ref()
    built = build_academic_period_proficiency_aggregation_inputs(
        target_period=period_target(),
        calendar=academic_period_calendar(),
        student_id="student_1",
        standard_id="urn:standard:period",
        target_scale=scale,
        period_membership_scope="direct",
        candidates=(
            resolved_candidate(
                "grade_c",
                result=grade_item_result_snapshot("grade_c"),
            ),
            resolved_candidate(
                "grade_b",
                result=grade_item_result_snapshot(
                    "grade_b",
                    status="insufficient_evidence",
                    level_id=None,
                ),
            ),
            resolved_candidate("grade_a", result=None),
        ),
    )

    assert built.period_membership_scope == "direct"
    assert [entry.grade_item.grade_item_id for entry in built.entries] == [
        "grade_a",
        "grade_b",
        "grade_c",
    ]
    assert [entry.status for entry in built.entries] == [
        "missing_result",
        "insufficient_evidence",
        "calculated",
    ]
    calculated = built.entries[-1]
    assert calculated.result_reference == standard_proficiency_result_reference(
        grade_item_result_snapshot("grade_c")
    )
    assert calculated.proficiency_level_id == "proficient"


def test_builder_classifies_scope_mismatch_before_missing_result() -> None:
    mixed_memberships = (
        membership_basis(
            "grade_a",
            module_id="quillan",
            work_id="work_b",
            period_id="mp2",
            membership_digest="f" * 64,
        ),
        membership_basis("grade_a", work_id="work_a", period_id="mp1"),
    )
    built = build_academic_period_proficiency_aggregation_inputs(
        target_period=period_target(),
        calendar=academic_period_calendar(),
        student_id="student_1",
        standard_id="urn:standard:period",
        target_scale=scale_ref(),
        period_membership_scope="direct",
        candidates=(
            resolved_candidate(
                memberships=mixed_memberships,
                result=None,
            ),
        ),
    )
    entry = built.entries[0]
    assert entry.status == "period_scope_mismatch"
    assert entry.period_scope_mismatch_reason == "mixed_sibling_periods"
    assert entry.result_reference is None


def test_builder_descendants_scope_accepts_child_memberships() -> None:
    memberships = (
        membership_basis(
            "grade_a",
            module_id="quillan",
            work_id="work_b",
            period_id="mp2",
            membership_digest="f" * 64,
        ),
        membership_basis("grade_a", work_id="work_a", period_id="mp1"),
    )
    built = build_academic_period_proficiency_aggregation_inputs(
        target_period=period_target("semester_1"),
        calendar=academic_period_calendar(),
        student_id="student_1",
        standard_id="urn:standard:period",
        target_scale=scale_ref(),
        period_membership_scope="descendants",
        candidates=(
            resolved_candidate(
                memberships=memberships,
                result=grade_item_result_snapshot(),
            ),
        ),
    )
    assert built.period_membership_scope == "descendants"
    assert built.entries[0].status == "calculated"


@pytest.mark.parametrize(
    ("result_kwargs", "match"),
    [
        ({"student_id": "student_2"}, "student_id"),
        ({"standard_id": "urn:standard:other"}, "standard_id"),
        (
            {
                "target_scale": ProficiencyScaleReference(
                    CLASS_ID,
                    "other_scale",
                    1,
                    "a" * 64,
                )
            },
            "target_scale",
        ),
    ],
)
def test_builder_rejects_wrong_result_scope(
    result_kwargs: dict[str, object],
    match: str,
) -> None:
    result = grade_item_result_snapshot(**result_kwargs)  # type: ignore[arg-type]
    with pytest.raises(AcademicPeriodProficiencyValidationError, match=match):
        build_academic_period_proficiency_aggregation_inputs(
            target_period=period_target(),
            calendar=academic_period_calendar(),
            student_id="student_1",
            standard_id="urn:standard:period",
            target_scale=scale_ref(),
            period_membership_scope="direct",
            candidates=(resolved_candidate(result=result),),
        )


def test_builder_rejects_duplicate_grade_item_candidates() -> None:
    candidate = resolved_candidate(result=None)
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="duplicate",
    ):
        build_academic_period_proficiency_aggregation_inputs(
            target_period=period_target(),
            calendar=academic_period_calendar(),
            student_id="student_1",
            standard_id="urn:standard:period",
            target_scale=scale_ref(),
            period_membership_scope="direct",
            candidates=(candidate, candidate),
        )


def test_inputs_bind_scope_and_reject_policy_scope_mismatch() -> None:
    scale = calculation_scale()
    inputs = replace(
        calculation_inputs(scale, calculated_input_entry()),
        period_membership_scope="descendants",
    )
    assert (
        academic_period_proficiency_aggregation_inputs_from_json_bytes(
            academic_period_proficiency_aggregation_inputs_to_json_bytes(inputs)
        ).period_membership_scope
        == "descendants"
    )
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="period_membership_scope",
    ):
        calculate_academic_period_proficiency(
            inputs,
            calculation_policy(scale, scope="direct"),
            scale,
        )



def test_academic_period_algorithm_version_is_explicit() -> None:
    assert ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION == "1"


def test_highest_and_lowest_use_exact_scale_order() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="developing"),
        calculated_input_entry("grade_b", level_id="advanced"),
        calculated_input_entry("grade_c", level_id="proficient"),
    )
    highest = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale, strategy="highest"),
        scale,
    )
    lowest = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale, strategy="lowest"),
        scale,
    )
    assert highest.status == "calculated"
    assert highest.proficiency_level_id == "advanced"
    assert lowest.status == "calculated"
    assert lowest.proficiency_level_id == "developing"


@pytest.mark.parametrize(
    ("rule", "expected", "status"),
    [
        ("lower", "developing", "calculated"),
        ("higher", "proficient", "calculated"),
        ("insufficient", None, "insufficient_evidence"),
    ],
)
def test_even_median_uses_explicit_policy_rule(
    rule: str,
    expected: str | None,
    status: str,
) -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="developing"),
        calculated_input_entry("grade_b", level_id="proficient"),
    )
    outcome = calculate_academic_period_proficiency(
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
        assert tuple(reason.kind for reason in outcome.insufficiency_reasons) == (
            "unresolved_even_median",
        )


def test_odd_median_selects_middle_without_tie_metadata() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="emerging"),
        calculated_input_entry("grade_b", level_id="proficient"),
        calculated_input_entry("grade_c", level_id="advanced"),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(
            scale,
            strategy="median",
            median_even_rule="higher",
        ),
        scale,
    )
    assert outcome.proficiency_level_id == "proficient"
    assert outcome.tie_resolution is None


@pytest.mark.parametrize(
    ("rule", "expected", "status"),
    [
        ("lower", "developing", "calculated"),
        ("higher", "proficient", "calculated"),
        ("insufficient", None, "insufficient_evidence"),
    ],
)
def test_mode_tie_uses_explicit_policy_rule(
    rule: str,
    expected: str | None,
    status: str,
) -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="developing"),
        calculated_input_entry("grade_b", level_id="developing"),
        calculated_input_entry("grade_c", level_id="proficient"),
        calculated_input_entry("grade_d", level_id="proficient"),
    )
    outcome = calculate_academic_period_proficiency(
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
        assert tuple(reason.kind for reason in outcome.insufficiency_reasons) == (
            "unresolved_mode_tie",
        )


def test_unique_mode_selects_the_unique_most_common_level() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="developing"),
        calculated_input_entry("grade_b", level_id="developing"),
        calculated_input_entry("grade_c", level_id="advanced"),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale, strategy="mode", mode_tie_rule="higher"),
        scale,
    )
    assert outcome.proficiency_level_id == "developing"
    assert outcome.tie_resolution is None


def test_missing_result_can_be_noncontributing_or_blocking() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="proficient"),
        missing_input_entry("grade_b"),
    )
    nonblocking = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale, missing="noncontributing"),
        scale,
    )
    blocking = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale, missing="blocking"),
        scale,
    )
    assert nonblocking.status == "calculated"
    assert nonblocking.proficiency_level_id == "proficient"
    assert blocking.status == "insufficient_evidence"
    assert tuple(reason.kind for reason in blocking.insufficiency_reasons) == (
        "blocking_missing_result",
    )


def test_insufficient_result_can_be_noncontributing_or_blocking() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="proficient"),
        insufficient_input_entry("grade_b"),
    )
    nonblocking = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale, insufficient="noncontributing"),
        scale,
    )
    blocking = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale, insufficient="blocking"),
        scale,
    )
    assert nonblocking.status == "calculated"
    assert blocking.status == "insufficient_evidence"
    assert tuple(reason.kind for reason in blocking.insufficiency_reasons) == (
        "blocking_insufficient_result",
    )


def test_period_scope_mismatch_is_always_blocking() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="advanced"),
        mismatch_input_entry("grade_b"),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(
            scale,
            missing="noncontributing",
            insufficient="noncontributing",
        ),
        scale,
    )
    assert outcome.status == "insufficient_evidence"
    assert outcome.proficiency_level_id is None
    assert outcome.period_scope_mismatch_count == 1
    assert outcome.insufficiency_reasons[0] == (
        AcademicPeriodProficiencyInsufficiencyReason(
            "period_scope_mismatch",
            ("grade_b",),
        )
    )


def test_zero_calculated_results_never_becomes_lowest_proficiency() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(scale, missing_input_entry("grade_a"))
    outcome = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale, missing="noncontributing"),
        scale,
    )
    assert outcome.status == "insufficient_evidence"
    assert outcome.proficiency_level_id is None
    assert outcome.insufficiency_reasons == (
        AcademicPeriodProficiencyInsufficiencyReason(
            "no_calculated_results",
            actual_results=0,
        ),
    )


def test_lowest_scale_level_remains_a_valid_calculated_result() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="emerging"),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale),
        scale,
    )
    assert outcome.status == "calculated"
    assert outcome.proficiency_level_id == "emerging"


def test_minimum_calculated_results_is_enforced_after_noncontributing_entries() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="proficient"),
        missing_input_entry("grade_b"),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale, minimum=2),
        scale,
    )
    assert outcome.status == "insufficient_evidence"
    assert outcome.insufficiency_reasons == (
        AcademicPeriodProficiencyInsufficiencyReason(
            "below_minimum_calculated_results",
            required_results=2,
            actual_results=1,
        ),
    )


def test_outcome_counts_and_explanations_preserve_candidate_dispositions() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="proficient"),
        insufficient_input_entry("grade_b"),
        missing_input_entry("grade_c"),
        mismatch_input_entry("grade_d"),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale),
        scale,
    )
    assert outcome.candidate_count == 4
    assert outcome.calculated_result_count == 1
    assert outcome.insufficient_result_count == 1
    assert outcome.missing_result_count == 1
    assert outcome.period_scope_mismatch_count == 1
    assert tuple(item.grade_item_id for item in outcome.explanation_entries) == (
        "grade_a",
        "grade_b",
        "grade_c",
        "grade_d",
    )
    assert tuple(item.contributed for item in outcome.explanation_entries) == (
        True,
        False,
        False,
        False,
    )


def test_calculation_fingerprint_is_deterministic_and_policy_bound() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="proficient"),
    )
    first_policy = calculation_policy(scale)
    first = academic_period_proficiency_calculation_fingerprint(
        inputs,
        first_policy,
        scale,
    )
    second = academic_period_proficiency_calculation_fingerprint(
        inputs,
        first_policy,
        scale,
    )
    changed = academic_period_proficiency_calculation_fingerprint(
        inputs,
        replace(first_policy, missing_result_handling="blocking"),
        scale,
    )
    assert first == second
    assert first != changed


def test_calculation_rejects_wrong_exact_scale_revision() -> None:
    scale = calculation_scale()
    inputs = period_inputs(calculated_input_entry("grade_a"))
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="do not bind this exact proficiency-scale revision",
    ):
        calculate_academic_period_proficiency(
            inputs,
            calculation_policy(scale),
            scale,
        )


def test_outcome_json_round_trip_is_canonical_and_exact() -> None:
    scale = calculation_scale()
    inputs = calculation_inputs(
        scale,
        calculated_input_entry("grade_a", level_id="proficient"),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        calculation_policy(scale),
        scale,
    )
    assert isinstance(outcome, AcademicPeriodProficiencyCalculationOutcome)
    payload = academic_period_proficiency_calculation_outcome_to_json_bytes(
        outcome
    )
    assert payload.endswith(b"\n")
    assert (
        academic_period_proficiency_calculation_outcome_from_json_bytes(payload)
        == outcome
    )
    with pytest.raises(
        AcademicPeriodProficiencySerializationError,
        match="not canonical JSON",
    ):
        academic_period_proficiency_calculation_outcome_from_json_bytes(
            payload.replace(b"\n", b"", 1)
        )




def period_result_snapshot(
    *,
    revision: int = 1,
    calculated_at: datetime = NOW,
    target_period: AcademicPeriodProficiencyTarget | None = None,
) -> AcademicPeriodProficiencyResultSnapshot:
    scale = calculation_scale()
    chosen_target = target_period or period_target("mp1")
    first = replace(
        calculated_input_entry("grade_a", level_id="developing"),
        memberships=(
            membership_basis(
                "grade_a",
                period_id=chosen_target.period.period_id,
                school_year=chosen_target.period.school_year,
                calendar_revision=chosen_target.calendar_revision,
            ),
        ),
        result_reference=result_reference(
            "grade_a",
            digest="a" * 64,
        ),
    )
    second = replace(
        calculated_input_entry("grade_b", level_id="proficient"),
        memberships=(
            membership_basis(
                "grade_b",
                work_id="work_b",
                period_id=chosen_target.period.period_id,
                school_year=chosen_target.period.school_year,
                calendar_revision=chosen_target.calendar_revision,
                membership_digest="d" * 64,
            ),
        ),
        result_reference=result_reference(
            "grade_b",
            digest="b" * 64,
        ),
    )
    exact_inputs = replace(
        calculation_inputs(scale, first, second),
        target_period=chosen_target,
    )
    exact_policy = calculation_policy(scale, strategy="highest")
    outcome = calculate_academic_period_proficiency(
        exact_inputs,
        exact_policy,
        scale,
    )
    return create_academic_period_proficiency_result_snapshot(
        exact_inputs,
        outcome,
        result_revision=revision,
        calculated_at=calculated_at,
    )


def test_period_result_snapshot_is_frozen_slotted_and_preserves_exact_inputs() -> None:
    value = period_result_snapshot()
    assert value.schema_version == ACADEMIC_PERIOD_PROFICIENCY_RESULT_SCHEMA_VERSION
    assert value.record_type == ACADEMIC_PERIOD_PROFICIENCY_RESULT_RECORD_TYPE
    assert value.inputs_sha256 == value.inputs.sha256
    assert value.target_period == period_target("mp1")
    assert value.outcome.status == "calculated"
    assert value.outcome.proficiency_level_id == "proficient"
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.student_id = "changed"  # type: ignore[misc]


def test_period_result_scope_must_match_embedded_inputs() -> None:
    value = period_result_snapshot()
    for changed in (
        {"class_id": "other_class"},
        {"student_id": "student_2"},
        {"standard_id": "urn:standard:other"},
        {"target_period": period_target("mp2")},
    ):
        with pytest.raises(
            AcademicPeriodProficiencyValidationError,
            match="scope",
        ):
            replace(value, **changed)


def test_period_result_metadata_must_match_exact_inputs_and_outcome() -> None:
    value = period_result_snapshot()
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="inputs_sha256",
    ):
        replace(value, inputs_sha256="0" * 64)
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="metadata",
    ):
        replace(value, calculation_fingerprint="0" * 64)
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="target_scale",
    ):
        replace(
            value,
            target_scale=replace(value.target_scale, scale_sha256="0" * 64),
        )


def test_period_result_transition_uses_durable_period_not_calendar_revision() -> None:
    first = period_result_snapshot()
    second = period_result_snapshot(
        revision=2,
        calculated_at=NOW + timedelta(minutes=1),
        target_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef("2026-2027", "mp1"),
            2,
        ),
    )
    assert second.supersedes_revision == 1
    assert (
        validate_academic_period_proficiency_result_transition(first, second)
        == second
    )

    different_period_family = period_result_snapshot(
        revision=2,
        calculated_at=NOW + timedelta(minutes=1),
        target_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef("2026-2027", "mp2"),
            1,
        ),
    )
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="logical identity",
    ):
        validate_academic_period_proficiency_result_transition(
            first,
            different_period_family,
        )


def test_period_result_json_round_trip_is_canonical_and_preserves_inputs() -> None:
    value = period_result_snapshot()
    encoded = academic_period_proficiency_result_snapshot_to_json_bytes(value)
    assert encoded.endswith(b"\n")
    assert b"\r" not in encoded
    assert b'"period_membership_scope": "direct"' in encoded
    assert b'"calendar_revision": 1' in encoded
    assert (
        academic_period_proficiency_result_snapshot_from_json_bytes(encoded)
        == value
    )


def test_period_result_json_rejects_duplicate_unknown_and_noncanonical() -> None:
    encoded = academic_period_proficiency_result_snapshot_to_json_bytes(
        period_result_snapshot()
    )
    duplicate = encoded.replace(
        b'{\n  "algorithm_version":',
        b'{\n  "class_id": "duplicate",\n  "algorithm_version":',
        1,
    )
    with pytest.raises(
        AcademicPeriodProficiencySerializationError,
        match="duplicate",
    ):
        academic_period_proficiency_result_snapshot_from_json_bytes(duplicate)

    unknown = encoded.replace(
        b"{\n",
        b'{\n  "unexpected": true,\n',
        1,
    )
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="unknown",
    ):
        academic_period_proficiency_result_snapshot_from_json_bytes(unknown)

    with pytest.raises(
        AcademicPeriodProficiencySerializationError,
        match="canonical",
    ):
        academic_period_proficiency_result_snapshot_from_json_bytes(
            encoded.replace(b"\n", b"\r\n")
        )


def test_period_result_reference_binds_durable_family_and_snapshot_bytes() -> None:
    value = period_result_snapshot()
    reference = academic_period_proficiency_result_reference(value)
    assert reference.class_id == CLASS_ID
    assert reference.school_year == "2026-2027"
    assert reference.period_id == "mp1"
    assert reference.student_id == "student_1"
    assert reference.standard_id == "urn:standard:period"
    assert reference.result_revision == 1
    assert len(reference.result_sha256) == 64
    assert academic_period_proficiency_result_reference_from_dict(
        academic_period_proficiency_result_reference_to_dict(reference)
    ) == reference


def test_period_result_calculated_at_is_audit_metadata_only() -> None:
    first = period_result_snapshot(calculated_at=NOW)
    second = period_result_snapshot(calculated_at=NOW + timedelta(hours=1))
    assert first.outcome == second.outcome
    assert first.calculation_fingerprint == second.calculation_fingerprint
    assert first.inputs_sha256 == second.inputs_sha256
    assert academic_period_proficiency_result_reference(first) != (
        academic_period_proficiency_result_reference(second)
    )


def test_period_result_calculated_at_requires_timezone_and_canonicalizes() -> None:
    value = period_result_snapshot()
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="timezone-aware",
    ):
        replace(value, calculated_at=datetime(2026, 8, 28, 12, 0))

    offset = NOW.astimezone(timezone(timedelta(hours=-4)))
    assert replace(value, calculated_at=offset).calculated_at == NOW

def test_period_result_freshness_is_current_for_exact_same_basis() -> None:
    result = period_result_snapshot()
    freshness = assess_academic_period_proficiency_result_freshness(
        result,
        result.inputs,
        result.policy_reference,
        result.target_scale,
        result.target_period.calendar_revision,
        result.algorithm_version,
    )
    assert freshness == AcademicPeriodProficiencyResultFreshness("current", ())


def test_period_result_freshness_reports_each_reason_independently() -> None:
    result = period_result_snapshot()
    changed_entry = replace(
        result.inputs.entries[0],
        proficiency_level_id="advanced",
    )
    changed_inputs = replace(
        result.inputs,
        entries=(changed_entry, *result.inputs.entries[1:]),
    )
    changed_policy = replace(
        result.policy_reference,
        policy_revision=2,
        policy_sha256="b" * 64,
    )
    changed_scale = replace(
        result.target_scale,
        scale_revision=2,
        scale_sha256="b" * 64,
    )

    cases = (
        (
            changed_inputs,
            result.policy_reference,
            result.target_scale,
            1,
            "1",
            "inputs_changed",
        ),
        (
            result.inputs,
            changed_policy,
            result.target_scale,
            1,
            "1",
            "policy_changed",
        ),
        (
            result.inputs,
            result.policy_reference,
            changed_scale,
            1,
            "1",
            "scale_changed",
        ),
        (
            result.inputs,
            result.policy_reference,
            result.target_scale,
            2,
            "1",
            "calendar_changed",
        ),
        (
            result.inputs,
            result.policy_reference,
            result.target_scale,
            1,
            "2",
            "algorithm_changed",
        ),
    )
    for (
        inputs,
        policy_ref,
        scale_reference,
        calendar_revision,
        algorithm,
        reason,
    ) in cases:
        freshness = assess_academic_period_proficiency_result_freshness(
            result,
            inputs,
            policy_ref,
            scale_reference,
            calendar_revision,
            algorithm,
        )
        assert freshness.status == "stale"
        assert freshness.reasons == (reason,)


def test_period_result_freshness_orders_multiple_reasons_deterministically() -> None:
    result = period_result_snapshot()
    changed_entry = replace(
        result.inputs.entries[0],
        proficiency_level_id="advanced",
    )
    changed_inputs = replace(
        result.inputs,
        entries=(changed_entry, *result.inputs.entries[1:]),
    )
    freshness = assess_academic_period_proficiency_result_freshness(
        result,
        changed_inputs,
        replace(
            result.policy_reference,
            policy_revision=2,
            policy_sha256="b" * 64,
        ),
        replace(
            result.target_scale,
            scale_revision=2,
            scale_sha256="b" * 64,
        ),
        2,
        "2",
    )
    assert freshness.status == "stale"
    assert freshness.reasons == (
        "inputs_changed",
        "policy_changed",
        "scale_changed",
        "calendar_changed",
        "algorithm_changed",
    )


def test_period_result_freshness_rejects_mixed_result_family() -> None:
    result = period_result_snapshot()
    other_period_inputs = replace(
        result.inputs,
        target_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef("2026-2027", "mp2"),
            1,
        ),
    )
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="logical identity",
    ):
        assess_academic_period_proficiency_result_freshness(
            result,
            other_period_inputs,
            result.policy_reference,
            result.target_scale,
            1,
            result.algorithm_version,
        )


def test_period_result_freshness_value_rejects_invalid_status_reason_pairs() -> None:
    with pytest.raises(AcademicPeriodProficiencyValidationError):
        AcademicPeriodProficiencyResultFreshness("current", ("inputs_changed",))
    with pytest.raises(AcademicPeriodProficiencyValidationError):
        AcademicPeriodProficiencyResultFreshness("stale", ())

