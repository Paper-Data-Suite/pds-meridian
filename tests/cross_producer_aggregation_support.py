"""Real #32/#33 cross-producer acceptance support for Meridian issue #44."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.standards import StandardDefinition, StandardsLibrary

import meridian.evidence_eligibility_storage as eligibility_storage
import meridian.standards_evidence_storage as standards_storage
from meridian.evidence import EvidenceItem, NativeScalarValue, NativeStateValue
from meridian.grade_item_storage import (
    load_current_grade_item_revision,
    select_grade_item_revision,
)
from meridian.proficiency_mapping import (
    NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
    NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
    MappingActor,
    NativeValueMappingProfile,
    ScalarMappingRule,
    native_value_source_signature_from_item,
)
from meridian.proficiency_mapping_storage import (
    StoredNativeValueMappingProfile,
    StoredProficiencyScale,
    write_mapping_profile_revision,
    write_proficiency_scale_revision,
)
from meridian.standards_evidence import GradeItemAggregationBasis
from tests.cross_producer_attempts_support import (
    Issue44AttemptWorkspace,
    derive_scoreform_attempts,
    prepare_attempt_workspace,
    replace_first_with_second_attempt,
    select_both_scoreform_attempts,
)
from tests.cross_producer_proficiency_support import (
    ACTOR_ID,
    GRADE_ITEM_ID,
    NOW,
    associated_standard,
    cross_producer_memberships,
    cross_producer_scale,
    included_eligibility,
    membership_for_module,
    representative_items,
    representative_mapping_profiles,
    source_reference,
)
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)


@dataclass(frozen=True, slots=True)
class Issue44AggregationScenario:
    """Exact persisted basis and real #29-#33 bindings for one student/standard."""

    workspace: Issue44AttemptWorkspace
    grade_item: GradeItemAggregationBasis
    standard_library: StandardsLibrary
    target_scale: StoredProficiencyScale
    scoreform_first_correctness: EvidenceItem
    scoreform_second_ambiguous: EvidenceItem
    quillan_overall: EvidenceItem
    concord_student: EvidenceItem
    concord_group: EvidenceItem
    bindings: tuple[standards_storage.StandardAggregationCandidateBinding, ...]


def _native_sequence(item: EvidenceItem, kind: str) -> int | None:
    values = tuple(
        reference.sequence
        for reference in item.provenance.native.references
        if reference.kind == kind
    )
    if len(values) != 1:
        raise AssertionError(f"Expected exactly one {kind} native reference.")
    return values[0]


def _scoreform_items(
    scenario: Issue44AttemptWorkspace,
) -> tuple[EvidenceItem, EvidenceItem]:
    inventory = scenario.projected["scoreform"].inventory
    first_correctness = next(
        item
        for item in inventory.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "question_correctness"
        and item.target.target_id == "question_1"
        and _native_sequence(item, "attempt") == 1
        and isinstance(item.value, NativeScalarValue)
        and item.value.value is True
    )
    second_ambiguous = next(
        item
        for item in inventory.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "selected_response_state"
        and item.target.target_id == "question_1"
        and _native_sequence(item, "attempt") == 2
        and isinstance(item.value, NativeStateValue)
        and item.value.code == "ambiguous"
    )
    return first_correctness, second_ambiguous


def _standard_library() -> StandardsLibrary:
    return StandardsLibrary(
        (
            StandardDefinition(
                SHARED_STANDARD_ID,
                "ELA.1",
                "issue44_synthetic",
                "Shared issue 44 standard",
                "Synthetic durable Standard used by cross-producer acceptance.",
            ),
        )
    )


def _scalar_profile(
    item: EvidenceItem,
    target_scale: StoredProficiencyScale,
    *,
    profile_id: str,
    rules: tuple[ScalarMappingRule, ...],
) -> NativeValueMappingProfile:
    scale = target_scale.scale
    return NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=scale.class_id,
        scale_id=scale.scale_id,
        profile_id=profile_id,
        profile_revision=1,
        supersedes_revision=None,
        target_scale=target_scale.reference,
        source_signature=native_value_source_signature_from_item(item),
        mapping_kind="exact_scalar",
        native_scale=None,
        points_possible=None,
        mapping_rules=rules,
        actor=MappingActor("teacher", ACTOR_ID),
        rationale="Explicit issue #44 exact source-scoped mapping.",
        revised_at=NOW,
    )


def _persist_eligibility(
    scenario: Issue44AttemptWorkspace,
    item: EvidenceItem,
) -> None:
    memberships = cross_producer_memberships()
    module_id = item.provenance.work.module_id
    membership = membership_for_module(memberships, module_id)
    source = source_reference(scenario.projected[module_id], item)
    decision = included_eligibility(source, membership)
    eligibility_storage.write_evidence_eligibility_revision(
        scenario.mixed.root,
        decision,
        authorized_snapshot=scenario.authorized[module_id],
    )
    eligibility_storage.select_evidence_eligibility_revision(
        scenario.mixed.root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
        decision.eligibility_revision,
        authorized_snapshot=scenario.authorized[module_id],
        expected_current_eligibility_revision=None,
    )


def _persist_association(
    scenario: Issue44AttemptWorkspace,
    item: EvidenceItem,
    library: StandardsLibrary,
    *,
    producer_declared: bool,
) -> None:
    module_id = item.provenance.work.module_id
    source = source_reference(scenario.projected[module_id], item)
    decision = associated_standard(
        source,
        basis="producer_declared" if producer_declared else "explicit",
    )
    standards_storage.write_standard_evidence_association_revision(
        scenario.mixed.root,
        decision,
        authorized_snapshot=scenario.authorized[module_id],
        standards_library=library,
    )
    standards_storage.select_standard_evidence_association_revision(
        scenario.mixed.root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
        decision.standard_id,
        decision.association_revision,
        expected_current_association_revision=None,
    )


def _write_profile(
    scenario: Issue44AttemptWorkspace,
    profile: NativeValueMappingProfile,
) -> StoredNativeValueMappingProfile:
    return write_mapping_profile_revision(
        scenario.mixed.root,
        profile,
    ).stored


def prepare_aggregation_scenario(tmp_path: Path) -> Issue44AggregationScenario:
    """Prepare one real mixed-producer proficiency calculation basis."""
    scenario = prepare_attempt_workspace(tmp_path)
    select_grade_item_revision(
        scenario.mixed.root,
        scenario.mixed.publications["scoreform"].work.class_id,
        GRADE_ITEM_ID,
        1,
        expected_current_revision=None,
    )
    stored_item = load_current_grade_item_revision(
        scenario.mixed.root,
        scenario.mixed.publications["scoreform"].work.class_id,
        GRADE_ITEM_ID,
    )
    if stored_item is None:
        raise AssertionError("Issue #44 Grade Item must be explicitly selected.")

    derivation = derive_scoreform_attempts(scenario)
    selection = select_both_scoreform_attempts(scenario, derivation)
    reassessment = replace_first_with_second_attempt(scenario, selection)
    if reassessment.status != "resolved":
        raise AssertionError("Issue #44 ScoreForm reassessment must resolve.")

    first_correctness, second_ambiguous = _scoreform_items(scenario)
    representative = representative_items(scenario.projected)
    quillan_overall = representative.quillan_overall
    concord_student = representative.concord_student
    concord_group = representative.concord_group_current

    for item in (quillan_overall, concord_student, concord_group):
        _persist_eligibility(scenario, item)

    library = _standard_library()
    for item in (
        first_correctness,
        second_ambiguous,
        quillan_overall,
        concord_student,
    ):
        _persist_association(
            scenario,
            item,
            library,
            producer_declared=True,
        )
    _persist_association(
        scenario,
        concord_group,
        library,
        producer_declared=False,
    )

    target_scale = write_proficiency_scale_revision(
        scenario.mixed.root,
        cross_producer_scale(),
    ).stored
    representative_profiles = representative_mapping_profiles(
        representative,
        target_scale.scale,
    )
    first_profile = _write_profile(
        scenario,
        _scalar_profile(
            first_correctness,
            target_scale,
            profile_id="scoreform_q1_correctness",
            rules=(
                ScalarMappingRule(False, "beginning"),
                ScalarMappingRule(True, "proficient"),
            ),
        ),
    )
    ambiguous_profile = _write_profile(
        scenario,
        _scalar_profile(
            second_ambiguous,
            target_scale,
            profile_id="scoreform_q1_response_state",
            rules=(ScalarMappingRule("ambiguous", "beginning"),),
        ),
    )
    quillan_profile = _write_profile(
        scenario,
        representative_profiles.quillan_overall,
    )
    concord_student_profile = _write_profile(
        scenario,
        representative_profiles.concord_student,
    )
    concord_group_profile = _write_profile(
        scenario,
        representative_profiles.concord_group_current,
    )

    items_and_profiles = (
        ("scoreform", first_correctness, first_profile),
        ("scoreform", second_ambiguous, ambiguous_profile),
        ("quillan", quillan_overall, quillan_profile),
        ("concord", concord_student, concord_student_profile),
        ("concord", concord_group, concord_group_profile),
    )
    bindings = tuple(
        standards_storage.StandardAggregationCandidateBinding(
            source_reference(scenario.projected[module_id], item),
            scenario.authorized[module_id],
            profile.reference,
        )
        for module_id, item, profile in items_and_profiles
    )
    grade_item = GradeItemAggregationBasis(
        stored_item.revision.class_id,
        stored_item.revision.grade_item_id,
        stored_item.revision.grade_item_revision,
        stored_item.revision_sha256,
    )
    return Issue44AggregationScenario(
        workspace=scenario,
        grade_item=grade_item,
        standard_library=library,
        target_scale=target_scale,
        scoreform_first_correctness=first_correctness,
        scoreform_second_ambiguous=second_ambiguous,
        quillan_overall=quillan_overall,
        concord_student=concord_student,
        concord_group=concord_group,
        bindings=bindings,
    )
