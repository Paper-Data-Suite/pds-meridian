from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.routing_models import ModuleWorkRef

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationInputEntry,
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyMembershipBasis,
    AcademicPeriodProficiencyResultSnapshot,
    AcademicPeriodProficiencyTarget,
    academic_period_proficiency_aggregation_policy_reference,
    academic_period_proficiency_result_reference,
    calculate_academic_period_proficiency,
    create_academic_period_proficiency_result_snapshot,
)
from meridian.grade_items import GradeItemWorkReference
from meridian.grouping_signal_derivation import (
    GROUPING_SIGNAL_DERIVATION_ALGORITHM_VERSION,
    GROUPING_SIGNAL_DERIVATION_RECORD_TYPE,
    GROUPING_SIGNAL_DERIVATION_SCHEMA_VERSION,
    GroupingSignalDerivationBlockedError,
    GroupingSignalDerivationReference,
    GroupingSignalDerivationSerializationError,
    GroupingSignalDerivationSnapshot,
    GroupingSignalDerivationValidationError,
    GroupingSignalResolvedStudentResult,
    GroupingSignalStudentDerivation,
    derive_grouping_signal_snapshot,
    grouping_signal_derivation_calculation_fingerprint,
    grouping_signal_derivation_id,
    grouping_signal_derivation_reference,
    grouping_signal_derivation_reference_from_dict,
    grouping_signal_derivation_reference_to_dict,
    grouping_signal_derivation_sha256,
    grouping_signal_derivation_snapshot_from_dict,
    grouping_signal_derivation_snapshot_from_json_bytes,
    grouping_signal_derivation_snapshot_to_dict,
    grouping_signal_derivation_snapshot_to_json_bytes,
    grouping_signal_roster_basis,
)
from meridian.grouping_signal_policy import (
    GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
    GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
    GroupingSignalAcademicBasis,
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicy,
    GroupingSignalPolicyActor,
    grouping_signal_derivation_policy_reference,
)
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.standards_evidence import GradeItemAggregationBasis
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_ALGORITHM_VERSION,
    StandardProficiencyActor,
    StandardProficiencyInsufficiencyReason,
    StandardProficiencyResultReference,
)

CLASS_ID = "synthetic_class_2026"
STANDARD_ID = "njsls-ela:RL.CR.9-10.1"
NOW = datetime(2026, 8, 30, 21, tzinfo=UTC)
PERIOD = AcademicPeriodProficiencyTarget(
    AcademicPeriodRef("2026-2027", "mp1"),
    2,
)


def scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="teacher_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Teacher scale",
        description="Synthetic criterion-referenced scale.",
        levels=(
            ProficiencyLevel("level_1", 1, "Beginning", "Synthetic level 1."),
            ProficiencyLevel("level_2", 2, "Developing", "Synthetic level 2."),
            ProficiencyLevel("level_3", 3, "Proficient", "Synthetic level 3."),
            ProficiencyLevel("level_4", 4, "Extending", "Synthetic level 4."),
        ),
        proficiency_threshold_level_id="level_3",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def source_policy(
    exact_scale: ProficiencyScale,
    *,
    revision: int = 1,
) -> AcademicPeriodProficiencyAggregationPolicy:
    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="period_proficiency_policy",
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Academic Period proficiency",
        target_scale=proficiency_scale_reference(exact_scale),
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def grouping_policy(
    exact_scale: ProficiencyScale,
    exact_source_policy: AcademicPeriodProficiencyAggregationPolicy,
    *,
    revision: int = 1,
    missing: str = "noncontributing",
    insufficient: str = "noncontributing",
) -> GroupingSignalDerivationPolicy:
    return GroupingSignalDerivationPolicy(
        schema_version=GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="reading_planning_signal",
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Reading planning signal",
        academic_basis=GroupingSignalAcademicBasis(
            basis_kind="academic_period_proficiency",
            target_period=PERIOD,
            standard_id=STANDARD_ID,
            source_policy=academic_period_proficiency_aggregation_policy_reference(
                exact_source_policy
            ),
            target_scale=proficiency_scale_reference(exact_scale),
        ),
        dimension_id="reading_planning",
        band_count=3,
        band_definitions=(
            GroupingSignalBandDefinition(1, 1, 1),
            GroupingSignalBandDefinition(2, 2, 3),
            GroupingSignalBandDefinition(3, 4, 4),
        ),
        tie_handling="same_level_same_band",
        missing_result_handling=missing,  # type: ignore[arg-type]
        insufficient_result_handling=insufficient,  # type: ignore[arg-type]
        actor=GroupingSignalPolicyActor("teacher", "teacher_local"),
        rationale="Temporary planning context.",
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def membership_basis(student_id: str) -> AcademicPeriodProficiencyMembershipBasis:
    suffix = student_id[-1]
    return AcademicPeriodProficiencyMembershipBasis(
        grade_item_id="grade_a",
        grade_item_revision=1,
        grade_item_revision_sha256=(suffix * 64),
        work_reference=GradeItemWorkReference(
            ModuleWorkRef("scoreform", CLASS_ID, f"work_{suffix}"),
            1,
        ),
        membership_revision=1,
        membership_sha256=("f" * 63) + suffix,
        academic_period=PERIOD,
    )


def source_reference(student_id: str) -> StandardProficiencyResultReference:
    suffix = student_id[-1]
    return StandardProficiencyResultReference(
        CLASS_ID,
        "grade_a",
        student_id,
        STANDARD_ID,
        1,
        ("d" * 63) + suffix,
    )


def source_input(
    exact_scale: ProficiencyScale,
    student_id: str,
    level_id: str | None,
) -> AcademicPeriodProficiencyAggregationInputs:
    basis = GradeItemAggregationBasis(
        CLASS_ID,
        "grade_a",
        1,
        membership_basis(student_id).grade_item_revision_sha256,
    )
    if level_id is None:
        entry = AcademicPeriodProficiencyAggregationInputEntry(
            grade_item=basis,
            memberships=(membership_basis(student_id),),
            status="insufficient_evidence",
            period_scope_mismatch_reason=None,
            result_reference=source_reference(student_id),
            result_algorithm_version=STANDARD_PROFICIENCY_ALGORITHM_VERSION,
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
    else:
        entry = AcademicPeriodProficiencyAggregationInputEntry(
            grade_item=basis,
            memberships=(membership_basis(student_id),),
            status="calculated",
            period_scope_mismatch_reason=None,
            result_reference=source_reference(student_id),
            result_algorithm_version=STANDARD_PROFICIENCY_ALGORITHM_VERSION,
            result_calculation_fingerprint="e" * 64,
            result_status="calculated",
            proficiency_level_id=level_id,
            result_insufficiency_reasons=(),
        )
    return AcademicPeriodProficiencyAggregationInputs(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=PERIOD,
        student_id=student_id,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(exact_scale),
        period_membership_scope="direct",
        entries=(entry,),
    )


def period_result(
    exact_scale: ProficiencyScale,
    exact_source_policy: AcademicPeriodProficiencyAggregationPolicy,
    student_id: str,
    level_id: str | None,
    *,
    revision: int = 1,
) -> AcademicPeriodProficiencyResultSnapshot:
    inputs = source_input(exact_scale, student_id, level_id)
    outcome = calculate_academic_period_proficiency(
        inputs,
        exact_source_policy,
        exact_scale,
    )
    return create_academic_period_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=revision,
        calculated_at=NOW + timedelta(minutes=revision - 1),
    )


def derived_snapshot(
    *,
    student_order: tuple[str, ...] = ("student_3", "student_1", "student_2"),
    levels: dict[str, str | None] | None = None,
    missing: str = "noncontributing",
    insufficient: str = "noncontributing",
) -> GroupingSignalDerivationSnapshot:
    exact_scale = scale()
    exact_source_policy = source_policy(exact_scale)
    exact_policy = grouping_policy(
        exact_scale,
        exact_source_policy,
        missing=missing,
        insufficient=insufficient,
    )
    chosen_levels = levels or {
        "student_1": "level_1",
        "student_2": "level_3",
        "student_3": "level_4",
    }
    roster = grouping_signal_roster_basis(CLASS_ID, student_order)
    resolved = tuple(
        GroupingSignalResolvedStudentResult(
            student_id,
            (
                None
                if student_id not in chosen_levels
                else period_result(
                    exact_scale,
                    exact_source_policy,
                    student_id,
                    chosen_levels[student_id],
                )
            ),
        )
        for student_id in student_order
    )
    return derive_grouping_signal_snapshot(
        exact_policy,
        grouping_signal_derivation_policy_reference(exact_policy),
        exact_scale,
        roster,
        resolved,
    )


def test_roster_basis_is_frozen_privacy_minimal_and_order_independent() -> None:
    first = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_3", "student_1", "student_2"),
    )
    second = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_2", "student_3", "student_1"),
    )
    assert first == second
    assert first.student_ids == ("student_1", "student_2", "student_3")
    assert len(first.membership_sha256) == 64
    assert not hasattr(first, "__dict__")
    with pytest.raises(FrozenInstanceError):
        first.class_id = "changed"  # type: ignore[misc]


def test_roster_basis_changes_only_when_membership_changes() -> None:
    first = grouping_signal_roster_basis(CLASS_ID, ("student_1", "student_2"))
    reordered = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_2", "student_1"),
    )
    changed = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_1", "student_3"),
    )
    assert first.membership_sha256 == reordered.membership_sha256
    assert first.membership_sha256 != changed.membership_sha256


@pytest.mark.parametrize("student_ids", [(), ("student_1", "student_1")])
def test_roster_basis_rejects_empty_or_duplicate_membership(
    student_ids: tuple[str, ...],
) -> None:
    with pytest.raises(GroupingSignalDerivationValidationError):
        grouping_signal_roster_basis(CLASS_ID, student_ids)


def test_roster_basis_rejects_forged_membership_digest() -> None:
    basis = grouping_signal_roster_basis(CLASS_ID, ("student_1",))
    with pytest.raises(GroupingSignalDerivationValidationError, match="bind"):
        replace(basis, membership_sha256="0" * 64)


def test_student_derivation_shapes_preserve_missing_and_insufficient() -> None:
    exact_scale = scale()
    exact_source_policy = source_policy(exact_scale)
    calculated = period_result(
        exact_scale,
        exact_source_policy,
        "student_1",
        "level_2",
    )
    reference = academic_period_proficiency_result_reference(calculated)
    assert GroupingSignalStudentDerivation(
        "student_1",
        "calculated",
        "contributing",
        reference,
        "level_2",
        2,
        2,
    ).band == 2
    assert GroupingSignalStudentDerivation(
        "student_2",
        "missing",
        "noncontributing",
        None,
        None,
        None,
        None,
    ).source_result is None
    insufficient_result = period_result(
        exact_scale,
        exact_source_policy,
        "student_3",
        None,
    )
    insufficient_reference = academic_period_proficiency_result_reference(
        insufficient_result
    )
    assert GroupingSignalStudentDerivation(
        "student_3",
        "insufficient_evidence",
        "noncontributing",
        insufficient_reference,
        None,
        None,
        None,
    ).source_state == "insufficient_evidence"


def test_student_derivation_rejects_numeric_missing_or_insufficient_fallback() -> None:
    with pytest.raises(GroupingSignalDerivationValidationError, match="missing"):
        GroupingSignalStudentDerivation(
            "student_1",
            "missing",
            "noncontributing",
            None,
            None,
            None,
            1,
        )


def test_exact_scale_positions_map_to_teacher_defined_contextual_bands() -> None:
    snapshot = derived_snapshot(
        student_order=("student_4", "student_2", "student_1", "student_3"),
        levels={
            "student_1": "level_1",
            "student_2": "level_2",
            "student_3": "level_3",
            "student_4": "level_4",
        },
    )
    assert tuple(
        (item.student_id, item.scale_position, item.band)
        for item in snapshot.student_derivations
    ) == (
        ("student_1", 1, 1),
        ("student_2", 2, 2),
        ("student_3", 3, 2),
        ("student_4", 4, 3),
    )


def test_same_level_always_maps_to_same_band() -> None:
    snapshot = derived_snapshot(
        levels={
            "student_1": "level_3",
            "student_2": "level_3",
            "student_3": "level_3",
        }
    )
    assert {item.band for item in snapshot.student_derivations} == {2}


def test_missing_noncontributing_retains_student_without_band() -> None:
    snapshot = derived_snapshot(
        levels={
            "student_1": "level_1",
            "student_3": "level_4",
        },
    )
    missing = snapshot.student_derivations[1]
    assert missing.student_id == "student_2"
    assert missing.source_state == "missing"
    assert missing.disposition == "noncontributing"
    assert missing.source_result is None
    assert missing.band is None


def test_insufficient_noncontributing_retains_exact_result_reference() -> None:
    snapshot = derived_snapshot(
        levels={
            "student_1": "level_1",
            "student_2": None,
            "student_3": "level_4",
        },
    )
    insufficient = snapshot.student_derivations[1]
    assert insufficient.source_state == "insufficient_evidence"
    assert insufficient.disposition == "noncontributing"
    assert insufficient.source_result is not None
    assert insufficient.band is None


def test_missing_blocking_aborts_pure_derivation_with_structured_student() -> None:
    with pytest.raises(GroupingSignalDerivationBlockedError) as captured:
        derived_snapshot(
            levels={"student_1": "level_1", "student_3": "level_4"},
            missing="blocking",
        )
    assert captured.value.blocking_students == (("student_2", "missing"),)


def test_insufficient_blocking_aborts_pure_derivation_with_structured_student() -> None:
    with pytest.raises(GroupingSignalDerivationBlockedError) as captured:
        derived_snapshot(
            levels={
                "student_1": "level_1",
                "student_2": None,
                "student_3": "level_4",
            },
            insufficient="blocking",
        )
    assert captured.value.blocking_students == (
        ("student_2", "insufficient_evidence"),
    )


def test_zero_contributor_derivation_is_valid_without_fabricated_band() -> None:
    snapshot = derived_snapshot(
        levels={"student_1": None, "student_2": None, "student_3": None}
    )
    assert all(
        item.disposition == "noncontributing"
        for item in snapshot.student_derivations
    )
    assert all(item.band is None for item in snapshot.student_derivations)


def test_input_order_does_not_change_fingerprint_identity_or_bytes() -> None:
    first = derived_snapshot(
        student_order=("student_3", "student_1", "student_2"),
    )
    second = derived_snapshot(
        student_order=("student_2", "student_3", "student_1"),
    )
    assert first.calculation_fingerprint == second.calculation_fingerprint
    assert first.derivation_id == second.derivation_id
    assert grouping_signal_derivation_snapshot_to_json_bytes(first) == (
        grouping_signal_derivation_snapshot_to_json_bytes(second)
    )


def test_roster_membership_change_changes_fingerprint_and_identity() -> None:
    exact_scale = scale()
    exact_source_policy = source_policy(exact_scale)
    exact_policy = grouping_policy(exact_scale, exact_source_policy)
    policy_reference = grouping_signal_derivation_policy_reference(exact_policy)

    first_roster = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_1", "student_2"),
    )
    first = derive_grouping_signal_snapshot(
        exact_policy,
        policy_reference,
        exact_scale,
        first_roster,
        (
            GroupingSignalResolvedStudentResult(
                "student_1",
                period_result(
                    exact_scale,
                    exact_source_policy,
                    "student_1",
                    "level_2",
                ),
            ),
            GroupingSignalResolvedStudentResult(
                "student_2",
                period_result(
                    exact_scale,
                    exact_source_policy,
                    "student_2",
                    "level_3",
                ),
            ),
        ),
    )
    second_roster = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_1", "student_3"),
    )
    second = derive_grouping_signal_snapshot(
        exact_policy,
        policy_reference,
        exact_scale,
        second_roster,
        (
            GroupingSignalResolvedStudentResult(
                "student_1",
                period_result(
                    exact_scale,
                    exact_source_policy,
                    "student_1",
                    "level_2",
                ),
            ),
            GroupingSignalResolvedStudentResult(
                "student_3",
                period_result(
                    exact_scale,
                    exact_source_policy,
                    "student_3",
                    "level_3",
                ),
            ),
        ),
    )
    assert first.calculation_fingerprint != second.calculation_fingerprint
    assert first.derivation_id != second.derivation_id


def test_selected_policy_reference_is_exact_and_changes_identity() -> None:
    exact_scale = scale()
    exact_source_policy = source_policy(exact_scale)
    first_policy = grouping_policy(exact_scale, exact_source_policy, revision=1)
    second_policy = grouping_policy(exact_scale, exact_source_policy, revision=2)
    roster = grouping_signal_roster_basis(CLASS_ID, ("student_1",))
    resolved = (
        GroupingSignalResolvedStudentResult(
            "student_1",
            period_result(
                exact_scale,
                exact_source_policy,
                "student_1",
                "level_2",
            ),
        ),
    )
    first = derive_grouping_signal_snapshot(
        first_policy,
        grouping_signal_derivation_policy_reference(first_policy),
        exact_scale,
        roster,
        resolved,
    )
    second = derive_grouping_signal_snapshot(
        second_policy,
        grouping_signal_derivation_policy_reference(second_policy),
        exact_scale,
        roster,
        resolved,
    )
    assert first.policy_reference != second.policy_reference
    assert first.calculation_fingerprint != second.calculation_fingerprint
    assert first.derivation_id != second.derivation_id


def test_wrong_policy_reference_is_rejected_instead_of_inferred() -> None:
    exact_scale = scale()
    exact_source_policy = source_policy(exact_scale)
    exact_policy = grouping_policy(exact_scale, exact_source_policy)
    reference = grouping_signal_derivation_policy_reference(exact_policy)
    forged = replace(reference, policy_sha256="0" * 64)
    roster = grouping_signal_roster_basis(CLASS_ID, ("student_1",))
    resolved = (
        GroupingSignalResolvedStudentResult(
            "student_1",
            period_result(
                exact_scale,
                exact_source_policy,
                "student_1",
                "level_2",
            ),
        ),
    )
    with pytest.raises(GroupingSignalDerivationValidationError, match="exact selected"):
        derive_grouping_signal_snapshot(
            exact_policy,
            forged,
            exact_scale,
            roster,
            resolved,
        )


def test_selected_result_must_match_exact_policy_academic_basis() -> None:
    exact_scale = scale()
    result_source_policy = source_policy(exact_scale, revision=1)
    selected_source_policy = source_policy(exact_scale, revision=2)
    exact_policy = grouping_policy(exact_scale, selected_source_policy)
    roster = grouping_signal_roster_basis(CLASS_ID, ("student_1",))
    selected_result = period_result(
        exact_scale,
        result_source_policy,
        "student_1",
        "level_2",
    )
    with pytest.raises(GroupingSignalDerivationValidationError, match="academic basis"):
        derive_grouping_signal_snapshot(
            exact_policy,
            grouping_signal_derivation_policy_reference(exact_policy),
            exact_scale,
            roster,
            (GroupingSignalResolvedStudentResult("student_1", selected_result),),
        )


def test_resolved_students_must_cover_exact_roster_once_each() -> None:
    exact_scale = scale()
    exact_source_policy = source_policy(exact_scale)
    exact_policy = grouping_policy(exact_scale, exact_source_policy)
    roster = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_1", "student_2"),
    )
    with pytest.raises(GroupingSignalDerivationValidationError, match="exact roster"):
        derive_grouping_signal_snapshot(
            exact_policy,
            grouping_signal_derivation_policy_reference(exact_policy),
            exact_scale,
            roster,
            (
                GroupingSignalResolvedStudentResult(
                    "student_1",
                    period_result(
                        exact_scale,
                        exact_source_policy,
                        "student_1",
                        "level_2",
                    ),
                ),
            ),
        )


def test_snapshot_contract_is_content_addressed_frozen_and_has_no_timestamp() -> None:
    snapshot = derived_snapshot()
    assert snapshot.schema_version == GROUPING_SIGNAL_DERIVATION_SCHEMA_VERSION
    assert snapshot.record_type == GROUPING_SIGNAL_DERIVATION_RECORD_TYPE
    assert snapshot.algorithm_version == GROUPING_SIGNAL_DERIVATION_ALGORITHM_VERSION
    assert snapshot.derivation_id == grouping_signal_derivation_id(
        snapshot.calculation_fingerprint
    )
    assert not hasattr(snapshot, "generated_at")
    assert not hasattr(snapshot, "created_at")
    assert not hasattr(snapshot, "__dict__")
    with pytest.raises(FrozenInstanceError):
        snapshot.dimension_id = "changed"  # type: ignore[misc]


def test_snapshot_fingerprint_can_be_recomputed_from_semantic_source_state() -> None:
    snapshot = derived_snapshot()
    assert snapshot.calculation_fingerprint == (
        grouping_signal_derivation_calculation_fingerprint(
            snapshot.policy_reference,
            snapshot.roster_basis,
            snapshot.student_derivations,
        )
    )


def test_snapshot_rejects_forged_fingerprint_or_derivation_id() -> None:
    snapshot = derived_snapshot()
    with pytest.raises(GroupingSignalDerivationValidationError, match="fingerprint"):
        replace(snapshot, calculation_fingerprint="0" * 64)
    with pytest.raises(
        GroupingSignalDerivationValidationError,
        match="content-addressed",
    ):
        replace(snapshot, derivation_id="gsd_" + ("0" * 64))


def test_snapshot_round_trip_digest_and_reference_are_exact() -> None:
    snapshot = derived_snapshot()
    data = grouping_signal_derivation_snapshot_to_dict(snapshot)
    assert grouping_signal_derivation_snapshot_from_dict(data) == snapshot
    payload = grouping_signal_derivation_snapshot_to_json_bytes(snapshot)
    assert payload.endswith(b"\n")
    assert b"\r" not in payload
    assert grouping_signal_derivation_snapshot_from_json_bytes(payload) == snapshot

    digest = grouping_signal_derivation_sha256(snapshot)
    reference = grouping_signal_derivation_reference(snapshot)
    assert reference == GroupingSignalDerivationReference(
        CLASS_ID,
        snapshot.derivation_id,
        digest,
    )
    reference_data = grouping_signal_derivation_reference_to_dict(reference)
    assert grouping_signal_derivation_reference_from_dict(reference_data) == reference


def test_snapshot_json_rejects_noncanonical_duplicate_and_unknown_data() -> None:
    snapshot = derived_snapshot()
    payload = grouping_signal_derivation_snapshot_to_json_bytes(snapshot)
    with pytest.raises(GroupingSignalDerivationSerializationError, match="canonical"):
        grouping_signal_derivation_snapshot_from_json_bytes(payload.rstrip(b"\n"))

    duplicate = payload.replace(
        b'{\n  "algorithm_version"',
        b'{\n  "algorithm_version": "academic_period_proficiency_band_v1",\n'
        b'  "algorithm_version"',
        1,
    )
    with pytest.raises(GroupingSignalDerivationSerializationError, match="duplicate"):
        grouping_signal_derivation_snapshot_from_json_bytes(duplicate)

    data = grouping_signal_derivation_snapshot_to_dict(snapshot)
    data["unexpected"] = "value"
    with pytest.raises(GroupingSignalDerivationValidationError, match="unknown"):
        grouping_signal_derivation_snapshot_from_dict(data)


def test_snapshot_student_derivations_are_canonical_and_cover_roster() -> None:
    snapshot = derived_snapshot()
    reversed_derivations = tuple(reversed(snapshot.student_derivations))
    canonical = replace(snapshot, student_derivations=reversed_derivations)
    assert canonical.student_derivations == snapshot.student_derivations

    with pytest.raises(GroupingSignalDerivationValidationError, match="exact roster"):
        replace(snapshot, student_derivations=snapshot.student_derivations[:-1])


def test_snapshot_rejects_band_outside_declared_band_count() -> None:
    snapshot = derived_snapshot()
    first = snapshot.student_derivations[0]
    assert first.band is not None
    invalid = replace(first, band=4)
    with pytest.raises(GroupingSignalDerivationValidationError, match="band_count"):
        replace(
            snapshot,
            student_derivations=(invalid,) + snapshot.student_derivations[1:],
        )


def test_derivation_reference_requires_exact_digest_and_content_addressed_id() -> None:
    snapshot = derived_snapshot()
    reference = grouping_signal_derivation_reference(snapshot)
    with pytest.raises(GroupingSignalDerivationValidationError, match="SHA-256"):
        replace(reference, derivation_sha256="not-a-digest")
    with pytest.raises(GroupingSignalDerivationValidationError, match="gsd_"):
        replace(reference, derivation_id="derivation_1")
