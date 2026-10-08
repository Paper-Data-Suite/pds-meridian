from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from pds_core.routing_models import ModuleWorkRef

from meridian.guided_proficiency import (
    GuidedProficiencyDependencies,
    load_guided_proficiency_context,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.guided_standards import GuidedScaleChoice
from meridian.proficiency_mapping import (
    NativeValueSourceSignature,
    ProficiencyScaleReference,
)
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem

WORK = ModuleWorkRef("scoreform", "english_12_pd2", "memory_snapshot")
SCALE_REF = ProficiencyScaleReference(
    "english_12_pd2",
    "scale_hidden",
    2,
    "a" * 64,
)


def _evidence() -> TeacherEvidenceReviewItem:
    return TeacherEvidenceReviewItem(
        item_id="item_hidden",
        student_id="00001",
        evidence_label="Attempt 1",
        value_label="8 / 10",
        result_kind_label="Submitted result",
        standard_ids=("durable:RL.TS.11-12.4",),
    )


def _prepared() -> GuidedProjectionResult:
    signature_fields = dict(
        producer_module_id="scoreform",
        publication_kind="academic_result_set",
        manifest_contract_version="scoreform_manifest_v1",
        producer_contract_version="scoreform_result_v1",
        projection_id="scoreform.academic_result",
        projection_contract_version="1",
        producer_reader_distribution="scoreform",
        producer_reader_version="0.12.1",
        result_kind="submitted_result",
        target_kind="attempt",
    )
    item = SimpleNamespace(
        item_id="item_hidden",
        subject=SimpleNamespace(student_id="00001"),
        provenance=SimpleNamespace(
            producer_module_id=signature_fields["producer_module_id"],
            publication_kind=signature_fields["publication_kind"],
            manifest_contract_version=signature_fields[
                "manifest_contract_version"
            ],
            producer_contract_version=signature_fields[
                "producer_contract_version"
            ],
            projection=SimpleNamespace(
                projection_id=signature_fields["projection_id"],
                projection_contract_version=signature_fields[
                    "projection_contract_version"
                ],
                producer_reader_distribution=signature_fields[
                    "producer_reader_distribution"
                ],
                producer_reader_version=signature_fields[
                    "producer_reader_version"
                ],
            ),
        ),
        result_kind="submitted_result",
        target=SimpleNamespace(target_kind="attempt"),
    )
    return cast(
        GuidedProjectionResult,
        SimpleNamespace(
            authorized=SimpleNamespace(
                current_context=SimpleNamespace(
                    publication=SimpleNamespace(
                        work=WORK,
                        publication_id="pub_11111111111111111111111111111111",
                    )
                ),
                stored=SimpleNamespace(
                    cache_key="c" * 64,
                    snapshot_digest="b" * 64,
                    snapshot=SimpleNamespace(
                        inventory=SimpleNamespace(items=(item,))
                    ),
                ),
            )
        ),
    )


def test_context_filters_current_policy_and_mapping_by_exact_scale(
    monkeypatch,
) -> None:
    import meridian.guided_proficiency as guided

    signature = NativeValueSourceSignature(
        "scoreform",
        "academic_result_set",
        "scoreform_manifest_v1",
        "scoreform_result_v1",
        "scoreform.academic_result",
        "1",
        "scoreform",
        "0.12.1",
        "submitted_result",
        "attempt",
    )
    matching_policy = SimpleNamespace(
        policy=SimpleNamespace(
            title="Current standards policy",
            strategy="highest",
            minimum_performance_observations=1,
            target_scale=SCALE_REF,
        ),
        reference=SimpleNamespace(),
    )
    other_policy = SimpleNamespace(
        policy=SimpleNamespace(
            title="Other scale policy",
            strategy="highest",
            minimum_performance_observations=1,
            target_scale=ProficiencyScaleReference(
                "english_12_pd2",
                "other_scale",
                1,
                "c" * 64,
            ),
        ),
        reference=SimpleNamespace(),
    )
    matching_profile = SimpleNamespace(
        profile=SimpleNamespace(
            target_scale=SCALE_REF,
            source_signature=signature,
            mapping_kind="raw_points",
            mapping_rules=(1, 2, 3, 4),
            points_possible=10,
            native_scale=None,
        ),
        reference=SimpleNamespace(),
    )
    other_profile = SimpleNamespace(
        profile=SimpleNamespace(
            target_scale=SCALE_REF,
            source_signature=SimpleNamespace(),
            mapping_kind="raw_points",
            mapping_rules=(1,),
            points_possible=10,
            native_scale=None,
        ),
        reference=SimpleNamespace(),
    )
    monkeypatch.setattr(
        guided,
        "native_value_source_signature_from_item",
        lambda _item: signature,
    )
    deps = GuidedProficiencyDependencies(
        policy_ids_loader=lambda *_args: ("p1", "p2"),
        policy_loader=lambda *_args: (
            matching_policy if _args[-1] == "p1" else other_policy
        ),
        profile_ids_loader=lambda *_args: ("m1", "m2"),
        profile_loader=lambda *_args: (
            matching_profile if _args[-1] == "m1" else other_profile
        ),
        scale_loader=lambda *_args: SimpleNamespace(
            reference=SCALE_REF,
            scale=SimpleNamespace(levels=()),
        ),
    )
    scale = GuidedScaleChoice(
        title="English 4-Level Scale",
        context="Developing → Approaching → Meeting → Exceeding",
        display_label="English 4-Level Scale",
        reference=SCALE_REF,
    )

    context = load_guided_proficiency_context(
        Path("workspace"),
        _prepared(),
        _evidence(),
        scale,
        dependencies=deps,
    )

    assert len(context.policies) == 1
    assert context.policies[0].title == "Current standards policy"
    assert len(context.mappings) == 1
    assert context.mappings[0].display_label.startswith("Raw points")
