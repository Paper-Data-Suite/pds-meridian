"""Bounded #33 input assembly for teacher Calculation Preview."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.calculation_preview_workflow import (
    CalculationPreviewProjection,
    build_calculation_preview_projection,
)
from meridian.evidence_eligibility import evidence_source_key
from meridian.grade_item_storage import (
    GradeItemStorageError,
    load_current_grade_item_revision,
)
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_evidence import (
    MAXIMUM_STANDARD_AGGREGATION_CANDIDATES,
    GradeItemAggregationBasis,
    StandardAggregationInputs,
)
from meridian.standards_evidence_storage import (
    StandardAggregationCandidateBinding,
    StandardsEvidenceStorageError,
    resolve_standard_aggregation_inputs,
)
from meridian.standards_proficiency import (
    StandardProficiencyCalculationPolicyReference,
)


class CalculationPreviewAssemblyError(RuntimeError):
    """Base failure while assembling exact bounded Calculation Preview inputs."""

    code = "teacher_workflow.calculation_preview.assembly_error"


class CalculationPreviewAssemblyScopeError(
    CalculationPreviewAssemblyError,
    ValueError,
):
    """Raised when the teacher-supplied bounded calculation scope is invalid."""

    code = "teacher_workflow.calculation_preview.assembly_invalid"


class CalculationPreviewAssemblyDependencyError(
    CalculationPreviewAssemblyError
):
    """Raised when exact selected Grade Item/#33 dependencies cannot resolve."""

    code = "teacher_workflow.calculation_preview.assembly_dependency_invalid"


@dataclass(frozen=True, slots=True)
class BoundedCalculationPreview:
    """Exact caller-bounded #33 inputs plus the read-only #34 projection."""

    grade_item_basis: GradeItemAggregationBasis
    bindings: tuple[StandardAggregationCandidateBinding, ...]
    inputs: StandardAggregationInputs
    calculation: CalculationPreviewProjection
    source_keys: tuple[str, ...]

    @property
    def binding_count(self) -> int:
        return len(self.bindings)

    @property
    def class_id(self) -> str:
        return self.grade_item_basis.class_id

    @property
    def grade_item_id(self) -> str:
        return self.grade_item_basis.grade_item_id

    @property
    def student_id(self) -> str:
        return self.inputs.student_id

    @property
    def standard_id(self) -> str:
        return self.inputs.standard_id

    @property
    def result_write_performed(self) -> bool:
        return self.calculation.result_write_performed

    @property
    def result_selection_performed(self) -> bool:
        return self.calculation.result_selection_performed


def build_bounded_calculation_preview(
    workspace_root: str | Path,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    target_scale: ProficiencyScaleReference,
    bindings: tuple[StandardAggregationCandidateBinding, ...],
    policy_reference: StandardProficiencyCalculationPolicyReference,
) -> BoundedCalculationPreview:
    """Resolve only caller-supplied bindings, then run the pure #34 preview."""
    _validate_request(
        grade_item_id,
        student_id,
        standard_id,
        target_scale,
        bindings,
        policy_reference,
    )

    source_keys = tuple(
        evidence_source_key(binding.source) for binding in bindings
    )
    if len(set(source_keys)) != len(source_keys):
        raise CalculationPreviewAssemblyScopeError(
            "Calculation Preview bindings must not duplicate an evidence source."
        )

    try:
        stored_grade_item = load_current_grade_item_revision(
            workspace_root,
            target_scale.class_id,
            grade_item_id,
        )
    except GradeItemStorageError as error:
        raise CalculationPreviewAssemblyDependencyError(
            f"Selected Grade Item could not be loaded: {error}"
        ) from error
    if stored_grade_item is None:
        raise CalculationPreviewAssemblyDependencyError(
            "Calculation Preview requires an explicitly selected Grade Item revision."
        )

    basis = GradeItemAggregationBasis(
        class_id=target_scale.class_id,
        grade_item_id=grade_item_id,
        grade_item_revision=(
            stored_grade_item.revision.grade_item_revision
        ),
        grade_item_revision_sha256=stored_grade_item.revision_sha256,
    )

    try:
        exact_inputs = resolve_standard_aggregation_inputs(
            workspace_root,
            basis,
            student_id,
            standard_id,
            target_scale,
            bindings,
        )
    except StandardsEvidenceStorageError as error:
        raise CalculationPreviewAssemblyDependencyError(str(error)) from error

    calculation = build_calculation_preview_projection(
        workspace_root,
        exact_inputs,
        policy_reference,
    )
    return BoundedCalculationPreview(
        grade_item_basis=basis,
        bindings=bindings,
        inputs=exact_inputs,
        calculation=calculation,
        source_keys=source_keys,
    )


def _validate_request(
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    target_scale: ProficiencyScaleReference,
    bindings: tuple[StandardAggregationCandidateBinding, ...],
    policy_reference: StandardProficiencyCalculationPolicyReference,
) -> None:
    for field_name, value in (
        ("grade_item_id", grade_item_id),
        ("student_id", student_id),
        ("standard_id", standard_id),
    ):
        if not isinstance(value, str) or not value:
            raise CalculationPreviewAssemblyScopeError(
                f"{field_name} must be a nonempty string."
            )
    if not isinstance(target_scale, ProficiencyScaleReference):
        raise CalculationPreviewAssemblyScopeError(
            "target_scale must be an exact ProficiencyScaleReference."
        )
    if not isinstance(bindings, tuple) or any(
        not isinstance(binding, StandardAggregationCandidateBinding)
        for binding in bindings
    ):
        raise CalculationPreviewAssemblyScopeError(
            "bindings must be a tuple of exact StandardAggregationCandidateBinding "
            "values."
        )
    if len(bindings) > MAXIMUM_STANDARD_AGGREGATION_CANDIDATES:
        raise CalculationPreviewAssemblyScopeError(
            "Calculation Preview binding count exceeds the finite #33 maximum."
        )
    if not isinstance(
        policy_reference,
        StandardProficiencyCalculationPolicyReference,
    ):
        raise CalculationPreviewAssemblyScopeError(
            "policy_reference must be an exact calculation-policy reference."
        )
    if policy_reference.class_id != target_scale.class_id:
        raise CalculationPreviewAssemblyScopeError(
            "Calculation policy class must match the target-scale class."
        )
    for binding in bindings:
        if binding.source.work.class_id != target_scale.class_id:
            raise CalculationPreviewAssemblyScopeError(
                "Every explicit evidence binding must belong to the target class."
            )
