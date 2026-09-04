from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.standards_review_workflow as workflow
from meridian.proficiency_mapping import (
    NativeValueMappingProfileReference,
    ProficiencyScaleReference,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="test_1",
)
TARGET_SCALE = ProficiencyScaleReference(
    class_id=CLASS_ID,
    scale_id="four_level",
    scale_revision=2,
    scale_sha256="a" * 64,
)
PROFILE = NativeValueMappingProfileReference(
    class_id=CLASS_ID,
    scale_id="four_level",
    profile_id="scoreform_points",
    profile_revision=3,
    profile_sha256="b" * 64,
)


def authorized() -> AuthorizedProjectionSnapshot:
    publication = SimpleNamespace(
        work=WORK,
        publication_id=PUBLICATION_ID,
    )
    value = SimpleNamespace(
        stored=SimpleNamespace(
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
            snapshot=SimpleNamespace(
                source=SimpleNamespace(publication=publication),
            ),
        )
    )
    return cast(AuthorizedProjectionSnapshot, value)


def install_runtime_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "AuthorizedProjectionSnapshot",
        SimpleNamespace,
    )


def evidence_item() -> object:
    return SimpleNamespace(
        target=SimpleNamespace(
            standard_ids=(STANDARD_ID, "NJSLSA.R2"),
        )
    )


def current_grade_item() -> object:
    return SimpleNamespace(
        revision=SimpleNamespace(grade_item_revision=4),
        revision_sha256="c" * 64,
    )


def association() -> object:
    decision = SimpleNamespace(
        association_revision=2,
        disposition="associated",
        basis="explicit",
        actor=SimpleNamespace(
            kind="teacher",
            actor_id="teacher_42",
        ),
        rationale="This item demonstrates the target standard.",
    )
    selected = SimpleNamespace(
        decision=decision,
        decision_sha256="d" * 64,
    )
    standard_resolution = SimpleNamespace(
        resolved=True,
        active=True,
        standard=SimpleNamespace(standard_id=STANDARD_ID),
        frameworks=(),
    )
    return SimpleNamespace(
        status="associated",
        selected=selected,
        standard_resolution=standard_resolution,
        operative_associated=True,
    )


def candidate(
    *,
    mapping_status: str = "mapped",
    subject_kind: str = "student",
    subject_student_id: str | None = STUDENT_ID,
) -> object:
    mapping = SimpleNamespace(
        profile=PROFILE,
        status=mapping_status,
        proficiency_level_id=(
            "meets" if mapping_status == "mapped" else None
        ),
        native_state=None,
        unsupported_reason=(
            "source_signature_mismatch"
            if mapping_status == "unsupported"
            else None
        ),
    )
    return SimpleNamespace(
        mapping_outcome=mapping,
        result_kind="score",
        target_kind="standard",
        subject_kind=subject_kind,
        subject_student_id=subject_student_id,
        eligibility_state="included",
        attempt_state="selected",
        reassessment_state="contributing",
    )


def aggregation_entry(
    *,
    status: str = "performance",
    exclusion_reason: str | None = None,
) -> object:
    return SimpleNamespace(
        source=None,
        status=status,
        exclusion_reason=exclusion_reason,
        membership_reference=SimpleNamespace(revision=5),
        eligibility_reference=SimpleNamespace(revision=6),
        attempt_selection_reference=SimpleNamespace(revision=7),
        reassessment_reference=SimpleNamespace(revision=8),
    )


def install_common(
    monkeypatch: pytest.MonkeyPatch,
    *,
    resolved_candidate: object | None = None,
    entry: object | None = None,
) -> None:
    install_runtime_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "validate_authorized_evidence_source",
        lambda *args, **kwargs: evidence_item(),
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_revision",
        lambda *args, **kwargs: current_grade_item(),
    )
    monkeypatch.setattr(
        workflow,
        "StandardAggregationCandidateBinding",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        workflow,
        "resolve_current_standard_evidence_association",
        lambda *args, **kwargs: association(),
    )
    monkeypatch.setattr(
        workflow,
        "resolve_standard_aggregation_candidate",
        lambda *args, **kwargs: (
            candidate()
            if resolved_candidate is None
            else resolved_candidate
        ),
    )

    def aggregate(*args: object, **kwargs: object) -> object:
        del kwargs
        actual = aggregation_entry() if entry is None else entry
        actual.source = args[5][0].source
        return SimpleNamespace(
            student_id=STUDENT_ID,
            standard_id=STANDARD_ID,
            target_scale=TARGET_SCALE,
            entries=(actual,),
        )

    monkeypatch.setattr(
        workflow,
        "resolve_standard_aggregation_inputs",
        aggregate,
    )


def test_projection_preserves_distinct_interpretation_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_common(monkeypatch)

    projection = workflow.build_standards_review_projection(
        "workspace",
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        "scoreform_item_1",
        TARGET_SCALE,
        authorized_snapshot=authorized(),
        mapping_profile=PROFILE,
    )

    assert projection.class_id == CLASS_ID
    assert projection.item_id == "scoreform_item_1"
    assert projection.producer_declared_standard_ids == (
        STANDARD_ID,
        "NJSLSA.R2",
    )
    assert projection.producer_declares_standard is True
    assert projection.standard_resolution.resolved is True
    assert projection.association_status == "associated"
    assert projection.association_revision == 2
    assert projection.association_basis == "explicit"
    assert projection.association_actor_kind == "teacher"
    assert projection.operative_associated is True
    assert projection.mapping_profile == PROFILE
    assert projection.mapping_status == "mapped"
    assert projection.mapped_proficiency_level_id == "meets"
    assert projection.eligibility_state == "included"
    assert projection.attempt_state == "selected"
    assert projection.reassessment_state == "contributing"
    assert projection.aggregation_status == "performance"
    assert projection.aggregation_exclusion_reason is None
    assert projection.membership_revision == 5
    assert projection.eligibility_revision == 6
    assert projection.attempt_selection_revision == 7
    assert projection.reassessment_revision == 8
    assert projection.contributes_performance is True
    assert projection.calculation_performed is False


def test_projection_surfaces_mapping_not_supplied_without_auto_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = candidate()
    resolved.mapping_outcome = None
    entry = aggregation_entry(
        status="excluded",
        exclusion_reason="mapping_not_supplied",
    )
    install_common(
        monkeypatch,
        resolved_candidate=resolved,
        entry=entry,
    )

    projection = workflow.build_standards_review_projection(
        "workspace",
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        "scoreform_item_1",
        TARGET_SCALE,
        authorized_snapshot=authorized(),
        mapping_profile=None,
    )

    assert projection.mapping_profile is None
    assert projection.mapping_profile_supplied is False
    assert projection.mapping_status is None
    assert projection.aggregation_status == "excluded"
    assert projection.aggregation_exclusion_reason == "mapping_not_supplied"
    assert projection.calculation_performed is False


@pytest.mark.parametrize(
    ("reason", "subject_kind", "subject_student_id"),
    (
        ("eligibility_not_included", "student", STUDENT_ID),
        ("attempt_not_selected", "student", STUDENT_ID),
        ("reassessment_noncontributing", "student", STUDENT_ID),
        ("nonstudent_target", "nonstudent", None),
        ("student_mismatch", "student", "student_002"),
        ("scale_mismatch", "student", STUDENT_ID),
    ),
)
def test_projection_surfaces_canonical_aggregation_exclusions(
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    subject_kind: str,
    subject_student_id: str | None,
) -> None:
    resolved = candidate(
        subject_kind=subject_kind,
        subject_student_id=subject_student_id,
    )
    entry = aggregation_entry(
        status="excluded",
        exclusion_reason=reason,
    )
    install_common(
        monkeypatch,
        resolved_candidate=resolved,
        entry=entry,
    )

    projection = workflow.build_standards_review_projection(
        "workspace",
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        "scoreform_item_1",
        TARGET_SCALE,
        authorized_snapshot=authorized(),
        mapping_profile=PROFILE,
    )

    assert projection.aggregation_status == "excluded"
    assert projection.aggregation_exclusion_reason == reason
    assert projection.subject_kind == subject_kind
    assert projection.subject_student_id == subject_student_id
    assert projection.calculation_performed is False


def test_projection_surfaces_unsupported_mapping_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = candidate(mapping_status="unsupported")
    entry = aggregation_entry(
        status="excluded",
        exclusion_reason="mapping_unsupported",
    )
    install_common(
        monkeypatch,
        resolved_candidate=resolved,
        entry=entry,
    )

    projection = workflow.build_standards_review_projection(
        "workspace",
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        "scoreform_item_1",
        TARGET_SCALE,
        authorized_snapshot=authorized(),
        mapping_profile=PROFILE,
    )

    assert projection.mapping_status == "unsupported"
    assert (
        projection.mapping_unsupported_reason
        == "source_signature_mismatch"
    )
    assert projection.aggregation_exclusion_reason == "mapping_unsupported"


def test_projection_does_not_infer_producer_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = evidence_item()
    item.target.standard_ids = ("NJSLSA.R2",)
    install_common(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "validate_authorized_evidence_source",
        lambda *args, **kwargs: item,
    )

    projection = workflow.build_standards_review_projection(
        "workspace",
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        "scoreform_item_1",
        TARGET_SCALE,
        authorized_snapshot=authorized(),
        mapping_profile=PROFILE,
    )

    assert projection.producer_declares_standard is False
    assert projection.association_status == "associated"
    assert projection.association_basis == "explicit"


def test_projection_requires_explicit_selected_grade_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_runtime_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "validate_authorized_evidence_source",
        lambda *args, **kwargs: evidence_item(),
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_revision",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(
        workflow.StandardsReviewWorkflowDependencyError,
        match="selected Grade Item revision",
    ):
        workflow.build_standards_review_projection(
            "workspace",
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            "scoreform_item_1",
            TARGET_SCALE,
            authorized_snapshot=authorized(),
            mapping_profile=PROFILE,
        )
