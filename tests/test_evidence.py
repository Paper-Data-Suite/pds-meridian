from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from pds_core.academic_work_registrations import (
    AcademicWorkRegistration,
    academic_work_registration_from_dict,
)
from pds_core.publication_records import (
    PublicationRecord,
    PublicationWithdrawal,
    publication_record_from_dict,
    publication_withdrawal_from_dict,
)
from pds_core.routing_models import ModuleWorkRef

from meridian.evidence import (
    UNEVALUATED_ELIGIBILITY,
    EvidenceEligibility,
    EvidenceInventory,
    EvidenceItem,
    EvidenceProvenance,
    EvidenceTarget,
    EvidenceTargetIdentity,
    EvidenceValidationError,
    NativeArtifact,
    NativePointValue,
    NativeProvenance,
    NativeReference,
    NativeScalarValue,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    NativeStateValue,
    NativeTimestamp,
    ProjectionIdentity,
    StudentSubject,
)

CoreContext: TypeAlias = tuple[
    AcademicWorkRegistration,
    PublicationRecord,
    PublicationWithdrawal,
]

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
SUBJECT = StudentSubject("00001")
PROJECTION = ProjectionIdentity(
    projection_id="synthetic_projection",
    projection_contract_version="1",
    producer_reader_distribution="synthetic-producer",
    producer_reader_version="1.0.0",
)


@pytest.fixture
def core_context(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> CoreContext:
    registration = academic_work_registration_from_dict(
        fixture_loader("core_v0_6/baseline_registration.json")
    )
    publication = publication_record_from_dict(
        fixture_loader("core_v0_6/baseline_publication.json")
    )
    withdrawal = publication_withdrawal_from_dict(
        fixture_loader("core_v0_6/baseline_withdrawal.json")
    )
    return registration, publication, withdrawal


def native_provenance(attempt_id: str = "attempt_1") -> NativeProvenance:
    return NativeProvenance(
        references=(
            NativeReference("attempt", attempt_id, sequence=1),
            NativeReference("issuance", "issuance_1"),
            NativeReference("page", "page_1", sequence=1),
            NativeReference("route", "route_1"),
            NativeReference("scan", "scan_1"),
            NativeReference("source_page", sequence=1),
        ),
        artifacts=(
            NativeArtifact(
                kind="retained_scan",
                path="scans/source/2026-02-01/synthetic_scan.pdf",
                digest_algorithm="sha256",
                digest="b" * 64,
            ),
        ),
        timestamps=(NativeTimestamp("scored_at", NOW),),
    )


def provenance(
    core_context: CoreContext,
    *,
    native: NativeProvenance | None = None,
    withdrawal: PublicationWithdrawal | None = None,
) -> EvidenceProvenance:
    registration, publication, _ = core_context
    return EvidenceProvenance(
        publication=publication,
        registration=registration,
        withdrawal=withdrawal,
        projection=PROJECTION,
        native=native or native_provenance(),
    )


def evidence_item(
    core_context: CoreContext,
    *,
    item_id: str = "evidence_1",
    target: EvidenceTarget | None = None,
    result_kind: str = "attempt_points",
    value: object | None = None,
    native: NativeProvenance | None = None,
    eligibility: EvidenceEligibility = UNEVALUATED_ELIGIBILITY,
) -> EvidenceItem:
    typed_value = NativePointValue(earned=8, possible=10) if value is None else value
    return EvidenceItem(
        item_id=item_id,
        subject=SUBJECT,
        target=target or EvidenceTarget("attempt", "attempt_1", sequence=1),
        result_kind=result_kind,
        value=cast(Any, typed_value),
        provenance=provenance(core_context, native=native),
        eligibility=eligibility,
    )


def four_level_scale(
    *,
    scale_id: str = "standards_4_level",
    contract_version: str = "2",
) -> NativeScale:
    return NativeScale(
        scale_id=scale_id,
        contract_version=contract_version,
        levels=(
            NativeScaleLevel(
                value=1,
                label="Developing",
                description="Emerging evidence of the standard.",
            ),
            NativeScaleLevel(
                value=2,
                label="Approaching",
                description="Partial evidence of the standard.",
            ),
            NativeScaleLevel(
                value=3,
                label="Meeting",
                description="Clear evidence of the standard.",
            ),
            NativeScaleLevel(
                value=4,
                label="Exceeding",
                description="Especially strong evidence of the standard.",
            ),
        ),
    )


def test_core_provenance_retains_exact_contract_identity(
    core_context: CoreContext,
) -> None:
    registration, publication, withdrawal = core_context
    result = provenance(core_context, withdrawal=withdrawal)

    assert result.publication == publication
    assert result.registration == registration
    assert result.withdrawal == withdrawal
    assert result.producer_module_id == "synthetic_producer"
    assert result.work == publication.work
    assert result.publication_kind == "academic_result_set"
    assert result.publication_id == publication.publication_id
    assert result.core_publication_schema_version == "1"
    assert result.record_set_id == "synthetic_record_set"
    assert result.record_set_revision == 1
    assert result.manifest_contract_version == "fixture_manifest_1"
    assert result.manifest_digest_algorithm == "sha256"
    assert result.manifest_digest == "a" * 64
    assert result.source_record == publication.source_record
    assert result.producer_contract_version == "fixture_contract_1"


def test_academic_provenance_requires_exact_registration(
    core_context: CoreContext,
) -> None:
    registration, publication, _ = core_context

    with pytest.raises(EvidenceValidationError, match="requires"):
        EvidenceProvenance(
            publication=publication,
            registration=None,
            withdrawal=None,
            projection=PROJECTION,
            native=native_provenance(),
        )

    mismatched = replace(registration, registration_revision=2)
    with pytest.raises(EvidenceValidationError, match="revision"):
        EvidenceProvenance(
            publication=publication,
            registration=mismatched,
            withdrawal=None,
            projection=PROJECTION,
            native=native_provenance(),
        )


def test_withdrawal_must_identify_same_publication(
    core_context: CoreContext,
) -> None:
    registration, publication, withdrawal = core_context
    mismatched = replace(
        withdrawal,
        publication_id="pub_22222222222222222222222222222222",
    )
    with pytest.raises(EvidenceValidationError, match="withdrawal"):
        EvidenceProvenance(
            publication=publication,
            registration=registration,
            withdrawal=mismatched,
            projection=PROJECTION,
            native=native_provenance(),
        )


def test_intervention_provenance_rejects_registration(
    core_context: CoreContext,
) -> None:
    registration, publication, _ = core_context
    intervention_work = ModuleWorkRef(
        module_id="synthetic_intervention",
        class_id="synthetic_class_2026",
        work_id="support_plan_alpha",
    )
    intervention = PublicationRecord(
        schema_version="1",
        record_type="publication_record",
        publication_id="pub_33333333333333333333333333333333",
        work=intervention_work,
        source_record=None,
        publication_kind="intervention_record_set",
        capabilities=("intervention_status",),
        record_set_id="support_record_set",
        record_set_revision=1,
        manifest_contract_version="support_manifest_1",
        manifest_path=(
            "classes/synthetic_class_2026/modules/synthetic_intervention/"
            "work/support_plan_alpha/publications/support_record_set/1.json"
        ),
        manifest_digest_algorithm="sha256",
        manifest_digest="c" * 64,
        published_at=NOW,
        academic_work_registration_revision=None,
        supersedes_publication_id=None,
    )

    with pytest.raises(EvidenceValidationError, match="must not carry"):
        EvidenceProvenance(
            publication=intervention,
            registration=registration,
            withdrawal=None,
            projection=PROJECTION,
            native=NativeProvenance(
                references=(NativeReference("intervention", "support_1"),)
            ),
        )

    result = EvidenceProvenance(
        publication=intervention,
        registration=None,
        withdrawal=None,
        projection=PROJECTION,
        native=NativeProvenance(
            references=(NativeReference("intervention", "support_1"),)
        ),
    )
    assert result.publication_kind == "intervention_record_set"
    assert result.producer_contract_version is None


def test_scoreform_shaped_attempts_remain_separate(
    core_context: CoreContext,
) -> None:
    first = evidence_item(
        core_context,
        item_id="attempt_1_points",
        native=native_provenance("attempt_1"),
    )
    second = evidence_item(
        core_context,
        item_id="attempt_2_points",
        target=EvidenceTarget("attempt", "attempt_2", sequence=2),
        value=NativePointValue(earned=9, possible=10),
        native=NativeProvenance(
            references=(NativeReference("attempt", "attempt_2", sequence=2),),
            timestamps=(NativeTimestamp("scored_at", NOW),),
        ),
    )
    inventory = EvidenceInventory((first, second))

    assert inventory.items == (first, second)
    assert first.value == NativePointValue(8, 10)
    assert second.value == NativePointValue(9, 10)
    assert not hasattr(first, "selected")
    assert not hasattr(first.value, "percentage")


def test_scoreform_shaped_question_meanings_do_not_collapse(
    core_context: CoreContext,
) -> None:
    question = EvidenceTarget(
        target_kind="question",
        target_id="question_1",
        parent_target=EvidenceTargetIdentity("attempt", "attempt_1"),
        standard_ids=("njsls-ela:RL.CR.9-10.1",),
        sequence=1,
    )
    selected = evidence_item(
        core_context,
        item_id="question_1_response",
        target=question,
        result_kind="selected_response",
        value=NativeScalarValue("A"),
    )
    correctness = evidence_item(
        core_context,
        item_id="question_1_correctness",
        target=question,
        result_kind="question_correctness",
        value=NativeScalarValue(True),
    )
    blank = evidence_item(
        core_context,
        item_id="question_2_blank",
        target=replace(question, target_id="question_2", sequence=2),
        result_kind="selected_response_state",
        value=NativeStateValue("blank"),
    )
    ambiguous = evidence_item(
        core_context,
        item_id="question_3_ambiguous",
        target=replace(question, target_id="question_3", sequence=3),
        result_kind="selected_response_state",
        value=NativeStateValue("ambiguous"),
    )

    assert selected.result_kind != correctness.result_kind
    assert blank.value != ambiguous.value
    assert blank.value != NativeScalarValue(0)
    assert ambiguous.value != NativeScalarValue(0)


def test_scoreform_shaped_routed_and_manual_provenance_remain_distinct(
    core_context: CoreContext,
) -> None:
    routed = evidence_item(core_context, item_id="routed", result_kind="result_origin")
    manual = evidence_item(
        core_context,
        item_id="manual",
        result_kind="result_origin",
        value=NativeScalarValue("plain_paper_manual"),
        native=NativeProvenance(
            references=(NativeReference("attempt", "manual_attempt_1"),)
        ),
    )

    assert routed.provenance.native.artifacts
    assert manual.provenance.native.artifacts == ()
    assert routed.provenance.native != manual.provenance.native


def test_quillan_shaped_observation_states_remain_distinct(
    core_context: CoreContext,
) -> None:
    target = EvidenceTarget(
        target_kind="review_unit",
        target_id="paragraph_1",
        parent_target=EvidenceTargetIdentity("submission", "submission_1"),
        standard_ids=("njsls-ela:W.AW.9-10.1",),
        sequence=1,
    )
    not_applicable = evidence_item(
        core_context,
        item_id="observation_not_applicable",
        target=target,
        result_kind="standard_applicability",
        value=NativeScalarValue(False),
    )
    evidence_absent = evidence_item(
        core_context,
        item_id="observation_evidence_absent",
        target=target,
        result_kind="standard_evidence_presence",
        value=NativeScalarValue(False),
    )
    unrated = evidence_item(
        core_context,
        item_id="observation_unrated",
        target=target,
        result_kind="standard_observation_rating",
        value=NativeStateValue("unrated"),
    )

    assert not_applicable.result_kind != evidence_absent.result_kind
    assert evidence_absent.value == NativeScalarValue(False)
    assert unrated.value == NativeStateValue("unrated")
    assert unrated.value != NativeScalarValue(0)


def test_quillan_native_ratings_preserve_scale_and_result_kind(
    core_context: CoreContext,
) -> None:
    scale = four_level_scale()
    observation = evidence_item(
        core_context,
        item_id="observation_rating",
        target=EvidenceTarget(
            "review_unit",
            "paragraph_1",
            standard_ids=("njsls-ela:W.AW.9-10.1",),
            sequence=1,
        ),
        result_kind="standard_observation_rating",
        value=NativeScaledValue(2, scale),
    )
    overall = evidence_item(
        core_context,
        item_id="overall_rating",
        target=EvidenceTarget(
            "standard",
            "njsls-ela:W.AW.9-10.1",
            standard_ids=("njsls-ela:W.AW.9-10.1",),
        ),
        result_kind="overall_standard_rating",
        value=NativeScaledValue(3, scale),
    )

    assert observation.result_kind != overall.result_kind
    assert cast(NativeScaledValue, observation.value).scale == scale
    assert cast(NativeScaledValue, overall.value).scale.levels[2].label == "Meeting"


def test_quillan_minimum_requirement_dispositions_are_not_scores(
    core_context: CoreContext,
) -> None:
    not_checked = evidence_item(
        core_context,
        item_id="requirements_not_checked",
        result_kind="minimum_requirement_status",
        value=NativeStateValue("not_checked"),
    )
    returned = evidence_item(
        core_context,
        item_id="returned_without_review",
        result_kind="review_disposition",
        value=NativeStateValue("returned_without_full_review"),
    )

    assert not_checked.value != returned.value
    assert not_checked.value != NativeScalarValue(0)
    assert returned.value != NativeScalarValue(0)


def test_scale_values_compare_by_exact_scalar_type() -> None:
    integer_scale = NativeScale(
        "integer_scale",
        (NativeScaleLevel(1), NativeScaleLevel(2)),
        contract_version="1",
    )
    string_scale = NativeScale(
        "string_scale",
        (NativeScaleLevel("1"), NativeScaleLevel("2")),
        contract_version="1",
    )
    float_scale = NativeScale(
        "float_scale",
        (NativeScaleLevel(1.0), NativeScaleLevel(2.0)),
        contract_version="1",
    )

    assert NativeScalarValue(1) != NativeScalarValue("1")
    assert NativeScalarValue(1) != NativeScalarValue(1.0)
    assert NativeScaledValue(1, integer_scale) != NativeScaledValue("1", string_scale)
    assert integer_scale != float_scale
    with pytest.raises(EvidenceValidationError, match="exactly match"):
        NativeScaledValue("1", integer_scale)


def test_scale_identity_includes_version_and_ordered_levels() -> None:
    baseline = four_level_scale()
    other_id = four_level_scale(scale_id="district_4_level")
    other_version = four_level_scale(contract_version="3")
    reversed_levels = replace(baseline, levels=tuple(reversed(baseline.levels)))

    assert baseline != other_id
    assert baseline != other_version
    assert baseline != reversed_levels


def test_scale_rejects_duplicate_exact_values() -> None:
    with pytest.raises(EvidenceValidationError, match="unique"):
        NativeScale(
            "duplicate_scale",
            (NativeScaleLevel(1), NativeScaleLevel(1)),
        )

    typed = NativeScale(
        "typed_scale",
        (NativeScaleLevel(1), NativeScaleLevel(True)),
    )
    assert typed.levels[0] != typed.levels[1]


def test_eligibility_preserves_policy_and_does_not_change_value(
    core_context: CoreContext,
) -> None:
    eligible = EvidenceEligibility.eligible(
        policy_id="evidence_policy",
        policy_version="1",
    )
    ineligible = EvidenceEligibility.ineligible(
        policy_id="evidence_policy",
        policy_version="1",
        reason_codes=("policy.not_grade_bearing", "policy.reporting_only"),
    )
    first = evidence_item(
        core_context,
        item_id="eligible_item",
        eligibility=eligible,
    )
    second = evidence_item(
        core_context,
        item_id="ineligible_item",
        eligibility=ineligible,
    )
    inventory = EvidenceInventory((first, second))

    assert inventory.for_eligibility("eligible") == (first,)
    assert inventory.for_eligibility("ineligible") == (second,)
    assert second.eligibility.reason_codes == (
        "policy.not_grade_bearing",
        "policy.reporting_only",
    )
    assert second.value == NativePointValue(8, 10)
    assert not hasattr(second.eligibility, "selected")


def test_invalid_eligibility_combinations_fail() -> None:
    with pytest.raises(EvidenceValidationError, match="must not claim"):
        EvidenceEligibility(
            status="unevaluated",
            policy_id="evidence_policy",
            policy_version="1",
        )
    with pytest.raises(EvidenceValidationError, match="requires policy"):
        EvidenceEligibility(status="eligible")
    with pytest.raises(EvidenceValidationError, match="at least one"):
        EvidenceEligibility(
            status="ineligible",
            policy_id="evidence_policy",
            policy_version="1",
        )


def test_inventory_filters_preserve_relative_order(
    core_context: CoreContext,
) -> None:
    standard = "njsls-ela:RL.CR.9-10.1"
    first = evidence_item(
        core_context,
        item_id="first_item",
        target=EvidenceTarget(
            "question",
            "question_1",
            standard_ids=(standard,),
            sequence=1,
        ),
    )
    second = evidence_item(
        core_context,
        item_id="second_item",
        target=EvidenceTarget(
            "question",
            "question_2",
            standard_ids=(standard,),
            sequence=2,
        ),
    )
    inventory = EvidenceInventory((first, second))

    assert inventory.for_student("00001") == (first, second)
    assert inventory.for_work(first.provenance.work) == (first, second)
    assert inventory.for_publication(first.provenance.publication_id) == (
        first,
        second,
    )
    assert inventory.for_target_kind("question") == (first, second)
    assert inventory.for_standard(standard) == (first, second)


def test_producer_native_identity_and_display_text_are_preserved_exactly(
    core_context: CoreContext,
) -> None:
    reference_id = "Observation / A"
    parent_id = " Submission / A "
    target_id = "Body / 1"
    standard_id = " Standard / A "
    scale_id = " synthetic / scale "
    label = "Emerging / Developing \\ Δ"
    description = "First line\nSecond line\twith formatting"
    reference = NativeReference("observation", reference_id)
    parent = EvidenceTargetIdentity("submission", parent_id)
    target = EvidenceTarget(
        "review_unit",
        target_id,
        parent_target=parent,
        standard_ids=(standard_id,),
        sequence=1,
    )
    scale = NativeScale(
        scale_id,
        (NativeScaleLevel(0, label, description),),
    )
    item = evidence_item(
        core_context,
        target=target,
        result_kind="native_rating",
        value=NativeScaledValue(0, scale),
        native=NativeProvenance((reference,)),
    )
    inventory = EvidenceInventory((item,))

    assert reference.identifier == reference_id
    assert parent.target_id == parent_id
    assert target.target_id == target_id
    assert target.standard_ids == (standard_id,)
    assert scale.scale_id == scale_id
    assert scale.levels[0].label == label
    assert scale.levels[0].description == description
    assert inventory.for_standard(standard_id) == (item,)
    assert inventory.for_standard(standard_id.strip()) == ()


@pytest.mark.parametrize("invalid", [1, "", " \t\n", "native\x00identity"])
def test_producer_native_text_rejects_nontext_empty_whitespace_and_nul(
    core_context: CoreContext, invalid: object
) -> None:
    value = cast(Any, invalid)
    constructors = (
        lambda: NativeReference("observation", value),
        lambda: EvidenceTargetIdentity("submission", value),
        lambda: EvidenceTarget("review_unit", value),
        lambda: EvidenceTarget("review_unit", standard_ids=(value,)),
        lambda: NativeScale(value, (NativeScaleLevel(0),)),
        lambda: NativeScaleLevel(0, value),
        lambda: NativeScaleLevel(0, description=value),
    )
    for construct in constructors:
        with pytest.raises(EvidenceValidationError):
            construct()

    inventory = EvidenceInventory((evidence_item(core_context),))
    with pytest.raises(EvidenceValidationError):
        inventory.for_standard(value)


def test_inventory_rejects_duplicate_item_ids(
    core_context: CoreContext,
) -> None:
    first = evidence_item(core_context)
    duplicate = replace(first, value=NativePointValue(9, 10))
    with pytest.raises(EvidenceValidationError, match="unique"):
        EvidenceInventory((first, duplicate))


def test_target_rejects_duplicate_standard_ids() -> None:
    with pytest.raises(EvidenceValidationError, match="duplicates"):
        EvidenceTarget(
            "question",
            "question_1",
            standard_ids=("standard:a", "standard:a"),
        )


def test_native_provenance_preserves_supplied_order() -> None:
    first = NativeReference("attempt", "attempt_1", sequence=1)
    second = NativeReference("question", "question_2", sequence=2)
    result = NativeProvenance(references=(first, second))
    assert result.references == (first, second)


def test_artifact_paths_are_privacy_safe_and_workspace_relative() -> None:
    valid = NativeArtifact(
        "manifest",
        "classes/synthetic/modules/producer/work/alpha/manifest.json",
    )
    assert isinstance(valid.path, str)

    for path in (
        "C:/Users/example/private.json",
        "/home/example/private.json",
        "classes/../private.json",
        "classes\\private.json",
        "classes//private.json",
    ):
        with pytest.raises(EvidenceValidationError):
            NativeArtifact("manifest", path)


def test_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(EvidenceValidationError, match="timezone-aware"):
        NativeTimestamp("reviewed_at", datetime(2026, 2, 1, 12, 0))


def test_arbitrary_payloads_and_nonfinite_numbers_fail(
    core_context: CoreContext,
) -> None:
    with pytest.raises(EvidenceValidationError):
        NativeScalarValue(cast(Any, None))
    with pytest.raises(EvidenceValidationError):
        NativeScalarValue(float("nan"))
    with pytest.raises(EvidenceValidationError):
        NativePointValue(earned=1, possible=float("inf"))
    with pytest.raises(EvidenceValidationError):
        NativePointValue(earned=1, possible=0)
    with pytest.raises(EvidenceValidationError, match="typed evidence-value"):
        evidence_item(core_context, value={"score": 1})


def test_models_are_frozen(core_context: CoreContext) -> None:
    item = evidence_item(core_context)
    with pytest.raises(FrozenInstanceError):
        item.item_id = "replacement"  # type: ignore[misc]


def test_model_construction_is_read_only(
    core_context: CoreContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    before = tuple(tmp_path.iterdir())
    EvidenceInventory((evidence_item(core_context),))
    assert tuple(tmp_path.iterdir()) == before
