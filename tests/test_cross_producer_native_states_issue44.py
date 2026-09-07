from __future__ import annotations

from pathlib import Path

import meridian.attempt_selection_storage as attempt_storage
import meridian.reassessment_storage as reassessment_storage
from meridian.evidence import (
    EvidenceItem,
    NativeScalarValue,
    NativeScaledValue,
    NativeStateValue,
)
from meridian.proficiency_mapping import (
    NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
    NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
    MappingActor,
    NativeValueMappingProfile,
    ScaledLevelMappingRule,
    map_evidence_item,
    native_value_source_signature_from_item,
    proficiency_scale_reference,
)
from tests.cross_producer_attempts_support import (
    Issue44AttemptWorkspace,
    derive_scoreform_attempts,
    prepare_attempt_workspace,
)
from tests.cross_producer_native_states_support import (
    project_quillan_with_rating,
    select_scoreform_attempt_sequences,
)
from tests.cross_producer_proficiency_support import (
    ACTOR_ID,
    GRADE_ITEM_ID,
    NOW,
    cross_producer_scale,
    representative_items,
    representative_mapping_profiles,
)
from tests.cross_producer_test_support import (
    SECONDARY_STUDENT_ID,
    SHARED_STUDENT_ID,
)


def _prepare_named_workspace(
    tmp_path: Path,
    name: str,
) -> Issue44AttemptWorkspace:
    root = tmp_path / name
    root.mkdir()
    return prepare_attempt_workspace(root)


def _native_sequence(item: EvidenceItem, kind: str) -> int | None:
    values = tuple(
        reference.sequence
        for reference in item.provenance.native.references
        if reference.kind == kind
    )
    if len(values) != 1:
        raise AssertionError(f"Expected exactly one {kind} native reference.")
    return values[0]


def _reference_ids(item: EvidenceItem, kind: str) -> tuple[str, ...]:
    return tuple(
        reference.identifier
        for reference in item.provenance.native.references
        if reference.kind == kind and reference.identifier is not None
    )


def _quillan_scaled_profile(
    item: EvidenceItem,
    *,
    profile_id: str,
) -> NativeValueMappingProfile:
    value = item.value
    if not isinstance(value, NativeScaledValue):
        raise AssertionError("Quillan mapping profile requires a scaled value.")
    target = cross_producer_scale()
    return NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=target.class_id,
        scale_id=target.scale_id,
        profile_id=profile_id,
        profile_revision=1,
        supersedes_revision=None,
        target_scale=proficiency_scale_reference(target),
        source_signature=native_value_source_signature_from_item(item),
        mapping_kind="exact_native_scale",
        native_scale=value.scale,
        points_possible=None,
        mapping_rules=(
            ScaledLevelMappingRule(0, "beginning"),
            ScaledLevelMappingRule(2, "developing"),
            ScaledLevelMappingRule(4, "advanced"),
        ),
        actor=MappingActor("teacher", ACTOR_ID),
        rationale="Issue #44 exact Quillan semantic-family mapping.",
        revised_at=NOW,
    )


def test_scoreform_attempt_state_matrix_is_explicit(tmp_path: Path) -> None:
    unresolved = _prepare_named_workspace(tmp_path, "unresolved")
    derivation = derive_scoreform_attempts(unresolved)
    assert derivation.status == "applicable"
    work = unresolved.mixed.publications["scoreform"].work

    initial = attempt_storage.resolve_current_attempt_selection(
        unresolved.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        authorized_snapshot=unresolved.authorized["scoreform"],
    )
    assert initial.status == "no_decision"
    assert not initial.operative_selection
    assert initial.selected is None
    assert tuple(
        candidate.attempt.native.sequence for candidate in initial.current_candidates
    ) == (1, 2)

    initial_reassessment = reassessment_storage.resolve_current_reassessment(
        unresolved.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        authorized_snapshot=unresolved.authorized["scoreform"],
    )
    assert initial_reassessment.status == "attempt_selection_unresolved"
    assert initial_reassessment.contributing_attempts == ()

    none = _prepare_named_workspace(tmp_path, "none")
    none_selection = select_scoreform_attempt_sequences(
        none,
        derive_scoreform_attempts(none),
        (),
    )
    assert none_selection.status == "selected_none"
    assert none_selection.operative_selection
    assert none_selection.selected is not None
    assert none_selection.selected.decision.selected_attempts == ()
    none_reassessment = reassessment_storage.resolve_current_reassessment(
        none.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        none.mixed.publications["scoreform"].work,
        SHARED_STUDENT_ID,
        authorized_snapshot=none.authorized["scoreform"],
    )
    assert none_reassessment.status == "selected_none"
    assert none_reassessment.contributing_attempts == ()

    for sequence in (1, 2):
        scenario = _prepare_named_workspace(tmp_path, f"selected_{sequence}")
        selection = select_scoreform_attempt_sequences(
            scenario,
            derive_scoreform_attempts(scenario),
            (sequence,),
        )
        assert selection.status == "selected"
        assert selection.operative_selection
        assert selection.selected is not None
        assert tuple(
            attempt.native.sequence
            for attempt in selection.selected.decision.selected_attempts
        ) == (sequence,)
        reassessment = reassessment_storage.resolve_current_reassessment(
            scenario.mixed.root,
            scenario.mixed.publications["scoreform"].work.class_id,
            GRADE_ITEM_ID,
            scenario.mixed.publications["scoreform"].work,
            SHARED_STUDENT_ID,
            authorized_snapshot=scenario.authorized["scoreform"],
        )
        assert reassessment.status == "single_selected"
        assert tuple(
            attempt.native.sequence for attempt in reassessment.contributing_attempts
        ) == (sequence,)


def test_scoreform_blank_ambiguous_and_correctness_remain_separate(
    tmp_path: Path,
) -> None:
    scenario = prepare_attempt_workspace(tmp_path)
    items = tuple(
        item
        for item in scenario.projected["scoreform"].inventory.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
    )
    states = tuple(
        item for item in items if item.result_kind == "selected_response_state"
    )
    observed = {
        (
            _native_sequence(item, "attempt"),
            _native_sequence(item, "question"),
            item.value.code,
        )
        for item in states
        if isinstance(item.value, NativeStateValue)
    }
    assert observed == {(1, 3, "blank"), (2, 1, "ambiguous")}

    for state in states:
        attempt = _native_sequence(state, "attempt")
        question = _native_sequence(state, "question")
        correctness = next(
            item
            for item in items
            if item.result_kind == "question_correctness"
            and _native_sequence(item, "attempt") == attempt
            and _native_sequence(item, "question") == question
        )
        assert correctness.item_id != state.item_id
        assert isinstance(correctness.value, NativeScalarValue)
        assert correctness.value.value is False
        assert isinstance(state.value, NativeStateValue)


def test_quillan_missingness_and_rating_families_do_not_collapse() -> None:
    inventory = project_quillan_with_rating(0)
    primary = tuple(
        item
        for item in inventory.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
    )
    secondary = tuple(
        item
        for item in inventory.items
        if item.subject is not None
        and item.subject.student_id == SECONDARY_STUDENT_ID
    )

    rated_observation = next(
        item
        for item in primary
        if item.result_kind == "standard_observation_rating"
        and item.target.target_id == "body_4"
    )
    overall = next(
        item for item in primary if item.result_kind == "overall_standard_rating"
    )
    assert isinstance(rated_observation.value, NativeScaledValue)
    assert isinstance(overall.value, NativeScaledValue)
    assert rated_observation.value.value == 0
    assert overall.value.value == 0
    assert rated_observation.value.scale == overall.value.scale

    not_applicable = next(
        item
        for item in primary
        if item.result_kind == "standard_applicability"
        and item.target.target_id == "body_1"
    )
    evidence_absent = next(
        item
        for item in primary
        if item.result_kind == "standard_evidence_presence"
        and item.target.target_id == "body_2"
    )
    assert not_applicable.value == NativeScalarValue(False)
    assert evidence_absent.value == NativeScalarValue(False)

    unrated_by_target = {
        item.target.target_id: item.value
        for item in primary
        if item.result_kind == "standard_observation_rating"
        and isinstance(item.value, NativeStateValue)
    }
    assert unrated_by_target == {
        "body_1": NativeStateValue("unrated"),
        "body_2": NativeStateValue("unrated"),
        "body_3": NativeStateValue("unrated"),
    }
    assert all(
        not isinstance(value, NativeScaledValue)
        for value in unrated_by_target.values()
    )

    assert any(
        item.result_kind == "review_state"
        and item.value == NativeStateValue("returned_without_full_review")
        for item in secondary
    )
    assert any(
        item.result_kind == "minimum_requirement_status"
        and item.value == NativeStateValue("returned_without_full_review")
        for item in secondary
    )
    assert not any(
        item.result_kind in {
            "overall_standard_rating",
            "standard_observation_rating",
        }
        for item in secondary
    )

    target = cross_producer_scale()
    overall_profile = _quillan_scaled_profile(
        overall,
        profile_id="issue44_quillan_overall_zero",
    )
    overall_outcome = map_evidence_item(overall, overall_profile, target)
    assert (overall_outcome.status, overall_outcome.proficiency_level_id) == (
        "mapped",
        "beginning",
    )
    assert overall_profile.native_scale == overall.value.scale

    for other in (
        rated_observation,
        not_applicable,
        evidence_absent,
        secondary[0],
        secondary[-1],
    ):
        outcome = map_evidence_item(other, overall_profile, target)
        assert outcome.status == "unsupported"
        assert outcome.unsupported_reason == "source_signature_mismatch"

    observation_profile = _quillan_scaled_profile(
        rated_observation,
        profile_id="issue44_quillan_observation_zero",
    )
    unrated = next(
        item
        for item in primary
        if item.result_kind == "standard_observation_rating"
        and item.target.target_id == "body_3"
    )
    unrated_outcome = map_evidence_item(unrated, observation_profile, target)
    assert unrated_outcome.status == "native_state"
    assert unrated_outcome.native_state == NativeStateValue("unrated")


def test_concord_absent_and_native_score_currentness_remain_distinct(
    tmp_path: Path,
) -> None:
    scenario = prepare_attempt_workspace(tmp_path)
    inventory = scenario.projected["concord"].inventory
    representative = representative_items(scenario.projected)
    target = cross_producer_scale()
    profiles = representative_mapping_profiles(representative, target)

    absent = next(
        item
        for item in inventory.items
        if item.subject is not None
        and item.subject.student_id == SECONDARY_STUDENT_ID
        and item.result_kind == "standard_backed_score"
    )
    assert absent.target.target_kind == "core_student"
    assert absent.value == NativeStateValue("absent")
    mapped_absent = map_evidence_item(absent, profiles.concord_student, target)
    assert mapped_absent.status == "native_state"
    assert mapped_absent.proficiency_level_id is None
    assert mapped_absent.native_state == NativeStateValue("absent")

    group_scores = tuple(
        item
        for item in inventory.items
        if item.subject is None and item.result_kind == "local_score"
    )
    predecessor = next(
        item
        for item in group_scores
        if _reference_ids(item, "score_current_state") == ("superseded",)
    )
    current = next(
        item
        for item in group_scores
        if _reference_ids(item, "score_current_state") == ("current",)
    )
    assert representative.concord_group_current == current
    assert isinstance(predecessor.value, NativeScaledValue)
    assert isinstance(current.value, NativeScaledValue)
    assert predecessor.value.value == 0
    assert current.value.value == 4
    assert predecessor.target == current.target
    assert _reference_ids(current, "score_supersedes") == ("score_001",)
    assert _reference_ids(current, "moderation_status") == (
        "accepted_with_qualification",
    )
    assert _reference_ids(current, "moderation_permitted_use") == (
        "support_group_score",
    )
    assert SHARED_STUDENT_ID in _reference_ids(current, "moderation_subject_id")
    assert current.subject is None
