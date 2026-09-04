from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

import meridian.calculation_preview_workflow as workflow
from meridian.standards_evidence import StandardAggregationInputs
from meridian.standards_proficiency import (
    StandardProficiencyCalculationPolicyReference,
)

POLICY_REF = StandardProficiencyCalculationPolicyReference(
    class_id="class_2026",
    policy_id="default_four_level",
    policy_revision=2,
    policy_sha256="a" * 64,
)


def inputs() -> StandardAggregationInputs:
    return cast(
        StandardAggregationInputs,
        SimpleNamespace(
            grade_item=SimpleNamespace(
                class_id="class_2026",
                grade_item_id="unit1_assessment",
            ),
            student_id="student_001",
            standard_id="NJSLSA.R1",
            target_scale=SimpleNamespace(
                class_id="class_2026",
                scale_id="four_level",
                scale_revision=3,
                scale_sha256="b" * 64,
            ),
            entries=(
                SimpleNamespace(
                    status="performance",
                    exclusion_reason=None,
                ),
                SimpleNamespace(
                    status="excluded",
                    exclusion_reason="attempt_not_selected",
                ),
                SimpleNamespace(
                    status="excluded",
                    exclusion_reason="mapping_unmapped",
                ),
                SimpleNamespace(
                    status="excluded",
                    exclusion_reason="mapping_unmapped",
                ),
            ),
            sha256="c" * 64,
        ),
    )


def policy() -> object:
    return SimpleNamespace(
        title="Teacher four-level proficiency",
        target_scale=inputs().target_scale,
        strategy="median",
        minimum_performance_observations=2,
        mode_tie_rule=None,
        median_even_rule="higher",
        blocking_exclusion_reasons=(
            "mapping_unmapped",
            "source_unverifiable",
        ),
        native_state_handling="blocking",
    )


def outcome() -> object:
    return SimpleNamespace(
        status="insufficient_evidence",
        proficiency_level_id=None,
        calculation_fingerprint="d" * 64,
        performance_observation_count=1,
        native_state_count=0,
        excluded_count=3,
        level_counts=(),
        insufficiency_reasons=(
            SimpleNamespace(
                kind="blocking_exclusion",
                source_keys=("e" * 64,),
                required_observations=None,
                actual_observations=None,
            ),
            SimpleNamespace(
                kind="below_minimum_performance_observations",
                source_keys=(),
                required_observations=2,
                actual_observations=1,
            ),
        ),
        tie_resolution=None,
        explanation_entries=(),
    )


def install_runtime_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "StandardAggregationInputs",
        SimpleNamespace,
    )


def install_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    install_runtime_types(monkeypatch)
    stored_policy = SimpleNamespace(
        policy=policy(),
        policy_sha256=POLICY_REF.policy_sha256,
        reference=POLICY_REF,
    )
    monkeypatch.setattr(
        workflow,
        "load_standard_proficiency_policy_revision",
        lambda *args, **kwargs: stored_policy,
    )
    stored_scale = SimpleNamespace(
        scale=SimpleNamespace(),
        scale_sha256="b" * 64,
    )
    monkeypatch.setattr(
        workflow,
        "load_proficiency_scale_revision",
        lambda *args, **kwargs: stored_scale,
    )
    monkeypatch.setattr(
        workflow,
        "calculate_standard_proficiency",
        lambda *args, **kwargs: outcome(),
    )
    monkeypatch.setattr(
        workflow,
        "list_standard_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_standard_proficiency_result_revision",
        lambda *args, **kwargs: 1,
    )


def test_preview_projects_exact_policy_counts_and_result_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_dependencies(monkeypatch)

    projection = workflow.build_calculation_preview_projection(
        "workspace",
        inputs(),
        POLICY_REF,
    )

    assert projection.class_id == "class_2026"
    assert projection.grade_item_id == "unit1_assessment"
    assert projection.student_id == "student_001"
    assert projection.standard_id == "NJSLSA.R1"
    assert projection.policy_reference == POLICY_REF
    assert projection.policy_title == "Teacher four-level proficiency"
    assert projection.strategy == "median"
    assert projection.minimum_performance_observations == 2
    assert projection.median_even_rule == "higher"
    assert projection.mode_tie_rule is None
    assert projection.blocking_exclusion_reasons == (
        "mapping_unmapped",
        "source_unverifiable",
    )
    assert projection.native_state_handling == "blocking"
    assert projection.input_entry_count == 4
    assert projection.exclusion_reason_counts == (
        ("attempt_not_selected", 1),
        ("mapping_unmapped", 2),
    )
    assert projection.status == "insufficient_evidence"
    assert projection.proficiency_level_id is None
    assert projection.calculation_fingerprint == "d" * 64
    assert projection.result_history == (1, 2)
    assert projection.next_result_revision == 3
    assert projection.current_result_revision == 1
    assert projection.result_write_performed is False
    assert projection.result_selection_performed is False


def test_preview_runs_pure_calculation_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_dependencies(monkeypatch)
    observed: list[tuple[object, object, object]] = []

    def calculate(
        exact_inputs: object,
        exact_policy: object,
        exact_scale: object,
    ) -> object:
        observed.append((exact_inputs, exact_policy, exact_scale))
        return outcome()

    monkeypatch.setattr(
        workflow,
        "calculate_standard_proficiency",
        calculate,
    )

    exact_inputs = inputs()
    projection = workflow.build_calculation_preview_projection(
        "workspace",
        exact_inputs,
        POLICY_REF,
    )

    assert observed == [
        (
            exact_inputs,
            policy(),
            SimpleNamespace(),
        )
    ]
    assert projection.result_write_performed is False
    assert projection.result_selection_performed is False


def test_preview_rejects_policy_digest_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_runtime_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_standard_proficiency_policy_revision",
        lambda *args, **kwargs: SimpleNamespace(
            policy=policy(),
            policy_sha256="f" * 64,
        ),
    )

    with pytest.raises(
        workflow.CalculationPreviewWorkflowDependencyError,
        match="policy SHA-256",
    ):
        workflow.build_calculation_preview_projection(
            "workspace",
            inputs(),
            POLICY_REF,
        )


def test_preview_rejects_target_scale_digest_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_runtime_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_standard_proficiency_policy_revision",
        lambda *args, **kwargs: SimpleNamespace(
            policy=policy(),
            policy_sha256=POLICY_REF.policy_sha256,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "load_proficiency_scale_revision",
        lambda *args, **kwargs: SimpleNamespace(
            scale=SimpleNamespace(),
            scale_sha256="f" * 64,
        ),
    )

    with pytest.raises(
        workflow.CalculationPreviewWorkflowDependencyError,
        match="target-scale SHA-256",
    ):
        workflow.build_calculation_preview_projection(
            "workspace",
            inputs(),
            POLICY_REF,
        )


def test_preview_rejects_policy_target_scale_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_runtime_types(monkeypatch)
    different = policy()
    different.target_scale = SimpleNamespace(
        class_id="class_2026",
        scale_id="other_scale",
        scale_revision=1,
        scale_sha256="9" * 64,
    )
    monkeypatch.setattr(
        workflow,
        "load_standard_proficiency_policy_revision",
        lambda *args, **kwargs: SimpleNamespace(
            policy=different,
            policy_sha256=POLICY_REF.policy_sha256,
        ),
    )

    with pytest.raises(
        workflow.CalculationPreviewWorkflowDependencyError,
        match="target scale does not match",
    ):
        workflow.build_calculation_preview_projection(
            "workspace",
            inputs(),
            POLICY_REF,
        )
