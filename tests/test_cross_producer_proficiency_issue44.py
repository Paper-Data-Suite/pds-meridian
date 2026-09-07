from __future__ import annotations

from pathlib import Path

from meridian.evidence import NativePointValue, NativeScaledValue
from meridian.proficiency_mapping import (
    map_native_value,
    native_value_source_signature_from_item,
    proficiency_scale_reference,
)
from meridian.standards_evidence import (
    GradeItemAggregationBasis,
    ResolvedStandardAggregationCandidate,
    build_standard_aggregation_inputs,
)
from tests.cross_producer_proficiency_support import (
    GRADE_ITEM_ID,
    PERIOD_ID,
    SCHOOL_YEAR,
    associated_standard,
    association_reference,
    cross_producer_grade_item,
    cross_producer_memberships,
    cross_producer_scale,
    eligibility_reference,
    grade_item_sha256,
    included_eligibility,
    membership_for_module,
    membership_reference,
    representative_items,
    representative_mapping_profiles,
    source_reference,
)
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)
from tests.cross_producer_workspace_support import (
    build_mixed_workspace,
    prepare_all,
    project_and_cache_all,
)


def _reference_ids(item: object, kind: str) -> tuple[str, ...]:
    provenance = getattr(item, "provenance")
    return tuple(
        reference.identifier
        for reference in provenance.native.references
        if reference.kind == kind and reference.identifier is not None
    )


def test_one_grade_item_explicitly_includes_all_three_registered_works() -> None:
    item = cross_producer_grade_item()
    memberships = cross_producer_memberships(item)

    assert item.grade_item_id == GRADE_ITEM_ID
    assert item.purpose == "standards_proficiency"
    assert tuple(
        membership.work_reference.work.module_id for membership in memberships
    ) == ("scoreform", "quillan", "concord")
    assert all(membership.decision == "included" for membership in memberships)
    assert all(
        membership.grade_item_revision_sha256 == grade_item_sha256(item)
        for membership in memberships
    )
    assert all(membership.academic_period is not None for membership in memberships)
    assert {
        (
            membership.academic_period.period.school_year,
            membership.academic_period.period.period_id,
            membership.academic_period.calendar_revision,
        )
        for membership in memberships
        if membership.academic_period is not None
    } == {(SCHOOL_YEAR, PERIOD_ID, 1)}


def test_equal_looking_values_require_exact_source_scale_and_denominator(
    tmp_path: Path,
) -> None:
    mixed = build_mixed_workspace(tmp_path)
    projected = project_and_cache_all(mixed, prepare_all(mixed))
    items = representative_items(projected)
    scale = cross_producer_scale()
    profiles = representative_mapping_profiles(items, scale)

    scoreform_value = items.scoreform_points.value
    quillan_value = items.quillan_overall.value
    concord_value = items.concord_student.value
    assert isinstance(scoreform_value, NativePointValue)
    assert isinstance(quillan_value, NativeScaledValue)
    assert isinstance(concord_value, NativeScaledValue)

    assert scoreform_value.earned == 2
    assert quillan_value.value == 2
    assert concord_value.value == 2
    assert quillan_value.scale != concord_value.scale

    scoreform = map_native_value(
        scoreform_value,
        native_value_source_signature_from_item(items.scoreform_points),
        profiles.scoreform_points,
        scale,
    )
    quillan = map_native_value(
        quillan_value,
        native_value_source_signature_from_item(items.quillan_overall),
        profiles.quillan_overall,
        scale,
    )
    concord = map_native_value(
        concord_value,
        native_value_source_signature_from_item(items.concord_student),
        profiles.concord_student,
        scale,
    )
    assert (scoreform.status, scoreform.proficiency_level_id) == (
        "mapped",
        "proficient",
    )
    assert (quillan.status, quillan.proficiency_level_id) == (
        "mapped",
        "developing",
    )
    assert (concord.status, concord.proficiency_level_id) == (
        "mapped",
        "proficient",
    )

    wrong_source = map_native_value(
        quillan_value,
        native_value_source_signature_from_item(items.quillan_overall),
        profiles.concord_student,
        scale,
    )
    assert wrong_source.status == "unsupported"
    assert wrong_source.unsupported_reason == "source_signature_mismatch"

    wrong_native_scale = map_native_value(
        concord_value,
        native_value_source_signature_from_item(items.quillan_overall),
        profiles.quillan_overall,
        scale,
    )
    assert wrong_native_scale.status == "unsupported"
    assert wrong_native_scale.unsupported_reason == "native_scale_mismatch"

    wrong_denominator = map_native_value(
        NativePointValue(
            earned=scoreform_value.earned,
            possible=scoreform_value.possible + 1,
        ),
        native_value_source_signature_from_item(items.scoreform_points),
        profiles.scoreform_points,
        scale,
    )
    assert wrong_denominator.status == "unsupported"
    assert wrong_denominator.unsupported_reason == "points_possible_mismatch"


def test_concord_group_target_stays_nonstudent_after_successful_decisions_and_mapping(
    tmp_path: Path,
) -> None:
    mixed = build_mixed_workspace(tmp_path)
    projected = project_and_cache_all(mixed, prepare_all(mixed))
    items = representative_items(projected)
    scale = cross_producer_scale()
    profiles = representative_mapping_profiles(items, scale)
    memberships = cross_producer_memberships()

    group = items.concord_group_current
    assert group.subject is None
    assert group.target.target_kind == "concord_group"
    assert SHARED_STUDENT_ID in _reference_ids(group, "score_link_subject_id")
    assert SHARED_STUDENT_ID in _reference_ids(group, "moderation_subject_id")

    source = source_reference(projected["concord"], group)
    membership = membership_for_module(memberships, "concord")
    eligibility = included_eligibility(source, membership)
    association = associated_standard(source, basis="explicit")
    mapped = map_native_value(
        group.value,
        native_value_source_signature_from_item(group),
        profiles.concord_group_current,
        scale,
    )
    assert mapped.status == "mapped"
    assert mapped.proficiency_level_id == "advanced"

    candidate = ResolvedStandardAggregationCandidate(
        source=source,
        standard_id=SHARED_STANDARD_ID,
        result_kind=group.result_kind,
        target_kind=group.target.target_kind,
        subject_kind="nonstudent",
        subject_student_id=None,
        association_state="associated",
        eligibility_state="included",
        attempt_state="not_applicable",
        reassessment_state="not_applicable",
        membership_reference=membership_reference(membership),
        eligibility_reference=eligibility_reference(eligibility),
        attempt_selection_reference=None,
        reassessment_reference=None,
        association_reference=association_reference(association),
        mapping_outcome=mapped,
    )
    inputs = build_standard_aggregation_inputs(
        GradeItemAggregationBasis(
            class_id=mixed.publications["concord"].work.class_id,
            grade_item_id=GRADE_ITEM_ID,
            grade_item_revision=1,
            grade_item_revision_sha256=grade_item_sha256(),
        ),
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        proficiency_scale_reference(scale),
        (candidate,),
    )

    assert len(inputs.entries) == 1
    entry = inputs.entries[0]
    assert entry.status == "excluded"
    assert entry.exclusion_reason == "nonstudent_target"
    assert entry.mapping_status == "mapped"
    assert entry.mapping_profile_reference == mapped.profile
    assert entry.membership_reference == membership_reference(membership)
    assert entry.eligibility_reference == eligibility_reference(eligibility)
    assert entry.association_reference == association_reference(association)
