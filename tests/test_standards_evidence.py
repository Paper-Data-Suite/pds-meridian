from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.evidence import NativeStateValue
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.proficiency_mapping import (
    NativeValueMappingOutcome,
    NativeValueMappingProfileReference,
    ProficiencyScaleReference,
)
from meridian.standards_evidence import (
    MAXIMUM_STANDARD_AGGREGATION_CANDIDATES,
    STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
    STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
    STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
    STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
    AggregationDecisionReference,
    GradeItemAggregationBasis,
    ResolvedStandardAggregationCandidate,
    StandardEvidenceActor,
    StandardEvidenceAssociationDecision,
    StandardEvidenceAssociationReference,
    StandardsEvidenceSerializationError,
    StandardsEvidenceValidationError,
    build_standard_aggregation_inputs,
    standard_aggregation_inputs_from_json_bytes,
    standard_aggregation_inputs_sha256,
    standard_aggregation_inputs_to_json_bytes,
    standard_evidence_association_from_json_bytes,
    standard_evidence_association_key,
    standard_evidence_association_to_json_bytes,
    validate_standard_evidence_association_transition,
)

NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)
WORK = ModuleWorkRef("scoreform", "synthetic_class_2026", "quiz_1")
STANDARD = "https://standards.example/RL:9-10.1?edition=2026"
SHA = "a" * 64


def source(item_id: str = "item_1") -> EvidenceSourceReference:
    return EvidenceSourceReference(
        WORK,
        "pub_" + "1" * 32,
        "2" * 64,
        "3" * 64,
        item_id,
    )


def decision(revision: int = 1) -> StandardEvidenceAssociationDecision:
    return StandardEvidenceAssociationDecision(
        STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
        STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
        WORK.class_id,
        "grade_item_1",
        source(),
        STANDARD,
        revision,
        None if revision == 1 else revision - 1,
        "associated",
        "producer_declared",
        StandardEvidenceActor("teacher", "teacher_local"),
        None,
        NOW,
    )


def scale_ref(digest: str = "4" * 64) -> ProficiencyScaleReference:
    return ProficiencyScaleReference(WORK.class_id, "scale_1", 1, digest)


def profile_ref() -> NativeValueMappingProfileReference:
    return NativeValueMappingProfileReference(
        WORK.class_id, "scale_1", "profile_1", 1, "5" * 64
    )


def association_ref(
    *, source_value: EvidenceSourceReference | None = None, standard_id: str = STANDARD
) -> StandardEvidenceAssociationReference:
    return StandardEvidenceAssociationReference(
        WORK.class_id,
        "grade_item_1",
        source_value or source(),
        standard_id,
        1,
        "8" * 64,
    )


def candidate(
    *,
    association: str = "associated",
    eligibility: str = "included",
    attempt: str = "not_applicable",
    reassessment: str = "not_applicable",
    subject_kind: str = "student",
    student_id: str | None = "student_1",
    outcome: NativeValueMappingOutcome | None = None,
) -> ResolvedStandardAggregationCandidate:
    if outcome is None:
        outcome = NativeValueMappingOutcome(
            "mapped", profile_ref(), scale_ref(), proficiency_level_id="ready"
        )
    return ResolvedStandardAggregationCandidate(
        source(),
        STANDARD,
        "question_correctness",
        "question",
        subject_kind,  # type: ignore[arg-type]
        student_id,
        association,  # type: ignore[arg-type]
        eligibility,  # type: ignore[arg-type]
        attempt,  # type: ignore[arg-type]
        reassessment,  # type: ignore[arg-type]
        AggregationDecisionReference("membership", 1, SHA),
        AggregationDecisionReference("eligibility", 1, SHA),
        (
            AggregationDecisionReference("attempt_selection", 1, SHA)
            if attempt in {"selected", "not_selected"}
            else None
        ),
        (
            AggregationDecisionReference("reassessment", 1, SHA)
            if reassessment in {"contributing", "noncontributing"}
            else None
        ),
        None if association == "no_decision" else association_ref(),
        outcome,
    )


def build(*candidates: ResolvedStandardAggregationCandidate):
    return build_standard_aggregation_inputs(
        GradeItemAggregationBasis(WORK.class_id, "grade_item_1", 2, "6" * 64),
        "student_1",
        STANDARD,
        scale_ref(),
        candidates,
    )


def test_association_model_is_frozen_slotted_and_canonical() -> None:
    value = decision()
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.standard_id = "changed"  # type: ignore[misc]
    encoded = standard_evidence_association_to_json_bytes(value)
    assert encoded.endswith(b"\n") and b"\r" not in encoded
    assert standard_evidence_association_from_json_bytes(encoded) == value
    with pytest.raises(StandardsEvidenceSerializationError):
        standard_evidence_association_from_json_bytes(encoded.replace(b"\n", b"\r\n"))


def test_association_json_rejects_duplicate_unknown_and_missing_keys() -> None:
    encoded = standard_evidence_association_to_json_bytes(decision())
    with pytest.raises(StandardsEvidenceSerializationError, match="duplicate"):
        standard_evidence_association_from_json_bytes(
            encoded.replace(b'{\n  "actor"', b'{\n  "actor": null,\n  "actor"')
        )
    with pytest.raises(StandardsEvidenceSerializationError, match="unknown"):
        standard_evidence_association_from_json_bytes(
            encoded.replace(b"{\n", b'{\n  "unknown": true,\n', 1)
        )
    with pytest.raises(StandardsEvidenceSerializationError, match="missing"):
        standard_evidence_association_from_json_bytes(
            encoded.replace(b'  "basis": "producer_declared",\n', b"")
        )


def test_transition_preserves_identity_and_is_contiguous() -> None:
    assert validate_standard_evidence_association_transition(
        decision(), decision(2)
    ) == decision(2)
    with pytest.raises(StandardsEvidenceValidationError, match="logical identity"):
        validate_standard_evidence_association_transition(
            decision(), replace(decision(2), standard_id="another:standard")
        )
    with pytest.raises(StandardsEvidenceValidationError, match="must not precede"):
        validate_standard_evidence_association_transition(
            decision(), replace(decision(2), decided_at=NOW.replace(hour=11))
        )


def test_association_key_hashes_windows_hostile_standard_id() -> None:
    key = standard_evidence_association_key(
        WORK.class_id, "grade_item_1", source(), STANDARD
    )
    assert len(key) == 64
    assert STANDARD not in key
    assert key == standard_evidence_association_key(
        WORK.class_id, "grade_item_1", source(), STANDARD
    )


def test_standard_id_matches_core_required_text_semantics() -> None:
    durable = "  https://standards.example/" + "x" * 1200 + "?a=1:b.2  "
    value = replace(decision(), standard_id=durable)
    assert value.standard_id == durable.strip()
    assert standard_evidence_association_from_json_bytes(
        standard_evidence_association_to_json_bytes(value)
    ) == value
    padded_key = standard_evidence_association_key(
        value.class_id, value.grade_item_id, value.source, durable
    )
    assert durable.strip() not in padded_key
    assert padded_key == standard_evidence_association_key(
        value.class_id, value.grade_item_id, value.source, durable.strip()
    )
    with pytest.raises(StandardsEvidenceValidationError, match="blank"):
        replace(decision(), standard_id=" \t\r\n ")


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"association": "no_decision"}, "association_unresolved"),
        ({"association": "not_associated"}, "not_associated"),
        ({"association": "source_unverifiable"}, "source_unverifiable"),
        ({"association": "standard_unresolved"}, "standard_unresolved"),
        ({"eligibility": "unresolved"}, "eligibility_unresolved"),
        ({"eligibility": "not_included"}, "eligibility_not_included"),
        ({"attempt": "unresolved"}, "attempt_selection_unresolved"),
        ({"attempt": "not_selected"}, "attempt_not_selected"),
        ({"reassessment": "unresolved"}, "reassessment_unresolved"),
        ({"reassessment": "noncontributing"}, "reassessment_noncontributing"),
        (
            {"subject_kind": "nonstudent", "student_id": None},
            "nonstudent_target",
        ),
        ({"student_id": "student_2"}, "student_mismatch"),
    ],
)
def test_pure_builder_preserves_closed_upstream_exclusions(
    changes: dict[str, object], reason: str
) -> None:
    inputs = build(candidate(**changes))  # type: ignore[arg-type]
    assert inputs.entries[0].status == "excluded"
    assert inputs.entries[0].exclusion_reason == reason


def test_mapping_states_and_scale_binding_remain_exact() -> None:
    performance = build(candidate()).entries[0]
    assert performance.status == "performance"
    assert performance.proficiency_level_id == "ready"

    native = NativeValueMappingOutcome(
        "native_state",
        profile_ref(),
        scale_ref(),
        native_state=NativeStateValue("unrated"),
    )
    native_entry = build(candidate(outcome=native)).entries[0]
    assert native_entry.status == "native_state"
    assert native_entry.native_state == NativeStateValue("unrated")

    unmapped = NativeValueMappingOutcome("unmapped", profile_ref(), scale_ref())
    assert (
        build(candidate(outcome=unmapped)).entries[0].exclusion_reason
        == "mapping_unmapped"
    )
    unsupported = NativeValueMappingOutcome(
        "unsupported",
        profile_ref(),
        scale_ref(),
        unsupported_reason="value_kind_mismatch",
    )
    assert (
        build(candidate(outcome=unsupported)).entries[0].exclusion_reason
        == "mapping_unsupported"
    )
    mismatch = NativeValueMappingOutcome(
        "mapped",
        profile_ref(),
        scale_ref("7" * 64),
        proficiency_level_id="ready",
    )
    assert (
        build(candidate(outcome=mismatch)).entries[0].exclusion_reason
        == "scale_mismatch"
    )


def test_missing_mapping_is_not_selected_automatically() -> None:
    value = candidate()
    inputs = build(replace(value, mapping_outcome=None))
    assert inputs.entries[0].exclusion_reason == "mapping_not_supplied"


def test_builder_orders_deterministically_and_calculates_nothing() -> None:
    first = candidate()
    second = replace(
        candidate(),
        source=source("item_2"),
        association_reference=association_ref(source_value=source("item_2")),
    )
    inputs = build(second, first)
    assert inputs.schema_version == STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION
    assert inputs.record_type == STANDARD_AGGREGATION_INPUTS_RECORD_TYPE
    assert len(inputs.sha256) == 64
    assert inputs.sha256 == standard_aggregation_inputs_sha256(inputs)
    assert standard_aggregation_inputs_to_json_bytes(inputs).endswith(b"\n")
    assert (
        standard_aggregation_inputs_from_json_bytes(
            standard_aggregation_inputs_to_json_bytes(inputs)
        )
        == inputs
    )
    assert not hasattr(inputs, "proficiency")
    assert not hasattr(inputs, "__dict__")
    with pytest.raises(FrozenInstanceError):
        inputs.student_id = "changed"  # type: ignore[misc]
    with pytest.raises(StandardsEvidenceValidationError, match="duplicate"):
        build(first, first)


def test_builder_rejects_an_over_limit_explicit_candidate_set() -> None:
    with pytest.raises(StandardsEvidenceValidationError, match="finite maximum"):
        build(
            *(
                candidate()
                for _ in range(MAXIMUM_STANDARD_AGGREGATION_CANDIDATES + 1)
            )
        )


def test_many_to_many_keys_are_separate_and_do_not_roll_up() -> None:
    child = standard_evidence_association_key(
        WORK.class_id, "grade_item_1", source(), "urn:standard:child"
    )
    parent = standard_evidence_association_key(
        WORK.class_id, "grade_item_1", source(), "urn:standard:parent"
    )
    another_source = standard_evidence_association_key(
        WORK.class_id, "grade_item_1", source("item_2"), "urn:standard:child"
    )
    assert len({child, parent, another_source}) == 3


def test_resolved_candidate_rejects_incoherent_provenance() -> None:
    value = candidate()
    with pytest.raises(StandardsEvidenceValidationError, match="membership reference"):
        replace(
            value,
            membership_reference=AggregationDecisionReference(
                "eligibility", 1, SHA
            ),
        )
    with pytest.raises(StandardsEvidenceValidationError, match="association reference"):
        replace(value, association_reference=None)
    with pytest.raises(StandardsEvidenceValidationError, match="must not carry"):
        replace(value, association_state="no_decision")
    with pytest.raises(StandardsEvidenceValidationError, match="eligibility reference"):
        replace(value, eligibility_reference=None)
    with pytest.raises(StandardsEvidenceValidationError, match="attempt-selection"):
        replace(value, attempt_state="selected")
    with pytest.raises(
        StandardsEvidenceValidationError, match="reassessment reference"
    ):
        replace(value, reassessment_state="contributing")


def test_entry_and_canonical_decoder_reject_impossible_provenance() -> None:
    inputs = build(candidate())
    entry = inputs.entries[0]
    with pytest.raises(StandardsEvidenceValidationError, match="mapping_status"):
        replace(
            entry,
            status="excluded",
            exclusion_reason="student_mismatch",
            mapping_status="bogus",  # type: ignore[arg-type]
        )
    with pytest.raises(StandardsEvidenceValidationError, match="membership reference"):
        replace(
            entry,
            membership_reference=AggregationDecisionReference(
                "eligibility", 1, SHA
            ),
        )
    with pytest.raises(StandardsEvidenceValidationError, match="requires exact"):
        replace(entry, association_reference=None)
    with pytest.raises(StandardsEvidenceValidationError, match="membership"):
        replace(entry, membership_reference=None)
    with pytest.raises(StandardsEvidenceValidationError, match="eligibility"):
        replace(entry, eligibility_reference=None)
    with pytest.raises(StandardsEvidenceValidationError, match="mapping_not_supplied"):
        replace(
            entry,
            status="excluded",
            exclusion_reason="mapping_not_supplied",
            proficiency_level_id=None,
        )

    encoded = standard_aggregation_inputs_to_json_bytes(inputs)
    tampered = encoded.replace(
        b'"mapping_status": "mapped"', b'"mapping_status": "bogus"'
    )
    with pytest.raises(StandardsEvidenceValidationError, match="mapping_status"):
        standard_aggregation_inputs_from_json_bytes(tampered)

    wrong_reference_kind = encoded.replace(
        b'"decision_kind": "membership"',
        b'"decision_kind": "eligibility"',
        1,
    )
    with pytest.raises(StandardsEvidenceValidationError, match="membership reference"):
        standard_aggregation_inputs_from_json_bytes(wrong_reference_kind)


def test_aggregation_decoder_rejects_cross_scope_entry_tampering() -> None:
    inputs = build(candidate())
    encoded = standard_aggregation_inputs_to_json_bytes(inputs)
    wrong_standard = encoded.replace(
        STANDARD.encode(), b"https://standards.example/another", 1
    )
    with pytest.raises(StandardsEvidenceValidationError, match="association reference"):
        standard_aggregation_inputs_from_json_bytes(wrong_standard)

    wrong_reference = replace(
        candidate(),
        source=source("item_2"),
        association_reference=association_ref(source_value=source("item_2")),
    )
    other_class = standard_aggregation_inputs_to_json_bytes(
        build(wrong_reference)
    ).replace(
        b'"class_id": "synthetic_class_2026"', b'"class_id": "other_class"', 1
    )
    with pytest.raises(StandardsEvidenceValidationError, match="source class"):
        standard_aggregation_inputs_from_json_bytes(other_class)
