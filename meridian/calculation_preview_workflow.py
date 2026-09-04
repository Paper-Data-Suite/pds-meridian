"""Read-only Grade Item standards-proficiency calculation preview."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    load_proficiency_scale_revision,
)
from meridian.standards_evidence import StandardAggregationInputs
from meridian.standards_proficiency import (
    StandardProficiencyCalculationOutcome,
    StandardProficiencyCalculationPolicyReference,
    calculate_standard_proficiency,
)
from meridian.standards_proficiency_storage import (
    StandardProficiencyStorageError,
    get_current_standard_proficiency_result_revision,
    list_standard_proficiency_result_revisions,
    load_standard_proficiency_policy_revision,
)


class CalculationPreviewWorkflowError(RuntimeError):
    """Base error for Grade Item standards-proficiency calculation preview."""

    code = "teacher_workflow.calculation_preview_error"


class CalculationPreviewWorkflowScopeError(
    CalculationPreviewWorkflowError,
    ValueError,
):
    """Raised when the exact preview scope is invalid."""

    code = "teacher_workflow.calculation_preview_invalid"


class CalculationPreviewWorkflowDependencyError(
    CalculationPreviewWorkflowError
):
    """Raised when exact stored #32/#34 dependencies cannot be verified."""

    code = "teacher_workflow.calculation_preview_dependency_invalid"


@dataclass(frozen=True, slots=True)
class CalculationPreviewProjection:
    """Teacher-facing read-only projection of one exact #34 calculation."""

    inputs: StandardAggregationInputs
    policy_reference: StandardProficiencyCalculationPolicyReference
    policy_title: str
    strategy: str
    minimum_performance_observations: int
    mode_tie_rule: str | None
    median_even_rule: str | None
    blocking_exclusion_reasons: tuple[str, ...]
    native_state_handling: str
    outcome: StandardProficiencyCalculationOutcome
    input_entry_count: int
    exclusion_reason_counts: tuple[tuple[str, int], ...]
    result_history: tuple[int, ...]
    next_result_revision: int
    current_result_revision: int | None
    result_write_performed: bool = False
    result_selection_performed: bool = False

    @property
    def class_id(self) -> str:
        return self.inputs.grade_item.class_id

    @property
    def grade_item_id(self) -> str:
        return self.inputs.grade_item.grade_item_id

    @property
    def student_id(self) -> str:
        return self.inputs.student_id

    @property
    def standard_id(self) -> str:
        return self.inputs.standard_id

    @property
    def inputs_sha256(self) -> str:
        return self.inputs.sha256

    @property
    def status(self) -> str:
        return self.outcome.status

    @property
    def proficiency_level_id(self) -> str | None:
        return self.outcome.proficiency_level_id

    @property
    def calculation_fingerprint(self) -> str:
        return self.outcome.calculation_fingerprint


def build_calculation_preview_projection(
    workspace_root: str | Path,
    inputs: StandardAggregationInputs,
    policy_reference: StandardProficiencyCalculationPolicyReference,
) -> CalculationPreviewProjection:
    """Run pure #34 calculation over one exact #33 input snapshot."""
    _validate_request(inputs, policy_reference)

    try:
        stored_policy = load_standard_proficiency_policy_revision(
            workspace_root,
            policy_reference.class_id,
            policy_reference.policy_id,
            policy_reference.policy_revision,
        )
    except StandardProficiencyStorageError as error:
        raise CalculationPreviewWorkflowDependencyError(
            f"Exact calculation policy could not be loaded: {error}"
        ) from error
    if stored_policy.policy_sha256 != policy_reference.policy_sha256:
        raise CalculationPreviewWorkflowDependencyError(
            "Exact calculation-policy SHA-256 does not match stored revision."
        )
    policy = stored_policy.policy
    if policy.target_scale != inputs.target_scale:
        raise CalculationPreviewWorkflowDependencyError(
            "Calculation policy target scale does not match exact #33 inputs."
        )

    scale_ref = inputs.target_scale
    try:
        stored_scale = load_proficiency_scale_revision(
            workspace_root,
            scale_ref.class_id,
            scale_ref.scale_id,
            scale_ref.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise CalculationPreviewWorkflowDependencyError(
            f"Exact target proficiency scale could not be loaded: {error}"
        ) from error
    if stored_scale.scale_sha256 != scale_ref.scale_sha256:
        raise CalculationPreviewWorkflowDependencyError(
            "Exact target-scale SHA-256 does not match stored revision."
        )

    try:
        outcome = calculate_standard_proficiency(
            inputs,
            policy,
            stored_scale.scale,
        )
        history = list_standard_proficiency_result_revisions(
            workspace_root,
            inputs.grade_item.class_id,
            inputs.grade_item.grade_item_id,
            inputs.student_id,
            inputs.standard_id,
        )
        current = get_current_standard_proficiency_result_revision(
            workspace_root,
            inputs.grade_item.class_id,
            inputs.grade_item.grade_item_id,
            inputs.student_id,
            inputs.standard_id,
        )
    except (StandardProficiencyStorageError, ValueError) as error:
        raise CalculationPreviewWorkflowDependencyError(str(error)) from error

    exclusions = Counter(
        entry.exclusion_reason
        for entry in inputs.entries
        if entry.status == "excluded" and entry.exclusion_reason is not None
    )
    return CalculationPreviewProjection(
        inputs=inputs,
        policy_reference=stored_policy.reference,
        policy_title=policy.title,
        strategy=policy.strategy,
        minimum_performance_observations=(
            policy.minimum_performance_observations
        ),
        mode_tie_rule=policy.mode_tie_rule,
        median_even_rule=policy.median_even_rule,
        blocking_exclusion_reasons=tuple(
            policy.blocking_exclusion_reasons
        ),
        native_state_handling=policy.native_state_handling,
        outcome=outcome,
        input_entry_count=len(inputs.entries),
        exclusion_reason_counts=tuple(sorted(exclusions.items())),
        result_history=history,
        next_result_revision=1 if not history else history[-1] + 1,
        current_result_revision=current,
    )


def _validate_request(
    inputs: StandardAggregationInputs,
    policy_reference: StandardProficiencyCalculationPolicyReference,
) -> None:
    if not isinstance(inputs, StandardAggregationInputs):
        raise CalculationPreviewWorkflowScopeError(
            "inputs must be exact StandardAggregationInputs."
        )
    if not isinstance(
        policy_reference,
        StandardProficiencyCalculationPolicyReference,
    ):
        raise CalculationPreviewWorkflowScopeError(
            "policy_reference must be an exact calculation-policy reference."
        )
    if policy_reference.class_id != inputs.grade_item.class_id:
        raise CalculationPreviewWorkflowScopeError(
            "Calculation policy class must match the #33 Grade Item class."
        )
