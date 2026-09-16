"""Storage-aware assembly for one exact bounded hybrid Academic Period Grade.

The assembler resolves one exact selected hybrid Grade-policy activation and
reuses the accepted #50 conventional and #51 standards component assembly
paths under that single hybrid policy. It does not consume standalone Grade
results, mutate upstream state, apply overrides, create previews or
ReportingSnapshots, or write an official Grade.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.conventional_grade_assembly import (
    ConventionalGradeAssemblyError,
    ConventionalGradeAssemblyScopeError,
    ConventionalGradeComponentAssembly,
    ConventionalGradeWorkEvidenceSpec,
    assemble_conventional_grade_component,
)
from meridian.grade_policy import HybridGradeConfiguration
from meridian.grade_policy_activation_storage import (
    GradePolicyActivationStorageError,
    StoredGradePolicyActivationDecision,
    resolve_grade_policy_activation,
)
from meridian.grade_policy_storage import (
    GradePolicyStorageError,
    StoredGradePolicyRevision,
    load_grade_policy_revision,
)
from meridian.hybrid_grade import (
    HybridGradeCalculationInput,
    HybridGradeCalculationOutcome,
    HybridGradeValidationError,
    calculate_hybrid_grade,
    create_hybrid_grade_calculation_input,
    hybrid_grade_calculation_fingerprint,
)
from meridian.standards_grade_assembly import (
    StandardsGradeAssemblyError,
    StandardsGradeAssemblyScopeError,
    StandardsGradeComponentAssembly,
    assemble_standards_grade_component,
)


class HybridGradeAssemblyError(RuntimeError):
    """Base failure while assembling one exact hybrid Grade basis."""

    code = "hybrid_grade.assembly_error"


class HybridGradeAssemblyScopeError(HybridGradeAssemblyError, ValueError):
    """Raised when caller-supplied hybrid calculation scope is inconsistent."""

    code = "hybrid_grade.assembly_scope_invalid"


class HybridGradeAssemblyAuthorityError(HybridGradeAssemblyError):
    """Raised when no exact activated hybrid Grade-policy authority exists."""

    code = "hybrid_grade.assembly_authority_invalid"


class HybridGradeAssemblyDependencyError(HybridGradeAssemblyError):
    """Raised when exact hybrid dependencies cannot be verified safely."""

    code = "hybrid_grade.assembly_dependency_invalid"


@dataclass(frozen=True, slots=True)
class HybridGradeAssembly:
    """Exact read-only hybrid authority, component bases, and pure outcome."""

    activation: StoredGradePolicyActivationDecision
    policy: StoredGradePolicyRevision
    conventional: ConventionalGradeComponentAssembly
    standards_based: StandardsGradeComponentAssembly
    inputs: HybridGradeCalculationInput
    outcome: HybridGradeCalculationOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.activation, StoredGradePolicyActivationDecision):
            raise HybridGradeAssemblyScopeError(
                "activation must be StoredGradePolicyActivationDecision."
            )
        if not isinstance(self.policy, StoredGradePolicyRevision):
            raise HybridGradeAssemblyScopeError(
                "policy must be StoredGradePolicyRevision."
            )
        if not isinstance(self.conventional, ConventionalGradeComponentAssembly):
            raise HybridGradeAssemblyScopeError(
                "conventional must be ConventionalGradeComponentAssembly."
            )
        if not isinstance(self.standards_based, StandardsGradeComponentAssembly):
            raise HybridGradeAssemblyScopeError(
                "standards_based must be StandardsGradeComponentAssembly."
            )
        if not isinstance(self.inputs, HybridGradeCalculationInput):
            raise HybridGradeAssemblyScopeError(
                "inputs must be HybridGradeCalculationInput."
            )
        if not isinstance(self.outcome, HybridGradeCalculationOutcome):
            raise HybridGradeAssemblyScopeError(
                "outcome must be HybridGradeCalculationOutcome."
            )
        if self.activation.reference != self.inputs.activation_reference:
            raise HybridGradeAssemblyScopeError(
                "stored activation must match exact hybrid calculation authority."
            )
        if self.policy.reference != self.inputs.policy_reference:
            raise HybridGradeAssemblyScopeError(
                "stored policy must match exact hybrid calculation authority."
            )
        if self.conventional.inputs != self.inputs.conventional:
            raise HybridGradeAssemblyScopeError(
                "conventional component must equal the embedded hybrid basis."
            )
        if self.standards_based.inputs != self.inputs.standards_based:
            raise HybridGradeAssemblyScopeError(
                "standards component must equal the embedded hybrid basis."
            )
        if calculate_hybrid_grade(self.inputs) != self.outcome:
            raise HybridGradeAssemblyScopeError(
                "outcome must exactly reproduce from the assembled hybrid inputs."
            )

    @property
    def inputs_fingerprint(self) -> str:
        """Return the deterministic fingerprint of the exact hybrid basis."""

        return hybrid_grade_calculation_fingerprint(self.inputs)


def assemble_hybrid_grade_calculation(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...],
) -> HybridGradeAssembly:
    """Assemble and purely calculate one exact bounded hybrid Grade."""

    root = Path(workspace_root).resolve()
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")

    try:
        resolution = resolve_grade_policy_activation(root, class_value, period)
    except GradePolicyActivationStorageError as error:
        raise HybridGradeAssemblyDependencyError(
            f"Exact Grade-policy activation could not be resolved: {error}"
        ) from error
    activation = resolution.activation
    policy_reference = resolution.policy_reference
    if (
        resolution.status != "activated"
        or activation is None
        or policy_reference is None
    ):
        raise HybridGradeAssemblyAuthorityError(
            "Hybrid calculation requires one explicitly activated Grade policy "
            "for the exact Academic Period."
        )
    if activation.decision.calendar_revision != calendar:
        raise HybridGradeAssemblyAuthorityError(
            "Selected Grade-policy activation belongs to a different calendar "
            "revision than the requested hybrid scope."
        )

    try:
        stored_policy = load_grade_policy_revision(
            root,
            policy_reference.class_id,
            policy_reference.policy_id,
            policy_reference.policy_revision,
        )
    except GradePolicyStorageError as error:
        raise HybridGradeAssemblyDependencyError(
            f"Exact activated Grade-policy revision could not be loaded: {error}"
        ) from error
    if stored_policy.policy_sha256 != policy_reference.policy_sha256:
        raise HybridGradeAssemblyDependencyError(
            "Activated Grade-policy SHA-256 does not match the stored revision."
        )
    policy = stored_policy.policy
    if policy.calculation_family != "hybrid" or not isinstance(
        policy.configuration,
        HybridGradeConfiguration,
    ):
        raise HybridGradeAssemblyAuthorityError(
            "Exact activated Grade policy must use calculation_family=hybrid."
        )
    if activation.decision.policy_reference != stored_policy.reference:
        raise HybridGradeAssemblyAuthorityError(
            "Activated Grade-policy reference does not match exact stored policy."
        )

    try:
        conventional = assemble_conventional_grade_component(
            root,
            activation=activation,
            policy=stored_policy,
            configuration=policy.configuration.conventional,
            class_id=class_value,
            student_id=student,
            target_period=period,
            calendar_revision=calendar,
            work_evidence=work_evidence,
        )
    except ConventionalGradeAssemblyScopeError as error:
        raise HybridGradeAssemblyScopeError(str(error)) from error
    except ConventionalGradeAssemblyError as error:
        raise HybridGradeAssemblyDependencyError(
            f"Hybrid conventional component could not be assembled: {error}"
        ) from error

    try:
        standards = assemble_standards_grade_component(
            root,
            activation=activation,
            policy=stored_policy,
            configuration=policy.configuration.standards_based,
            class_id=class_value,
            student_id=student,
            target_period=period,
            calendar_revision=calendar,
        )
    except StandardsGradeAssemblyScopeError as error:
        raise HybridGradeAssemblyScopeError(str(error)) from error
    except StandardsGradeAssemblyError as error:
        raise HybridGradeAssemblyDependencyError(
            f"Hybrid standards component could not be assembled: {error}"
        ) from error

    try:
        inputs = create_hybrid_grade_calculation_input(
            policy=policy,
            activation=activation.decision,
            student_id=student,
            target_period=period,
            calendar_revision=calendar,
            conventional=conventional.inputs,
            standards_based=standards.inputs,
        )
        outcome = calculate_hybrid_grade(inputs)
    except HybridGradeValidationError as error:
        raise HybridGradeAssemblyDependencyError(
            f"Assembled hybrid calculation basis is invalid: {error}"
        ) from error

    return HybridGradeAssembly(
        activation=activation,
        policy=stored_policy,
        conventional=conventional,
        standards_based=standards,
        inputs=inputs,
        outcome=outcome,
    )


def _period(value: AcademicPeriodRef) -> AcademicPeriodRef:
    if not isinstance(value, AcademicPeriodRef):
        raise HybridGradeAssemblyScopeError(
            "target_period must be AcademicPeriodRef."
        )
    try:
        return validate_academic_period_ref(value)
    except AcademicPeriodValidationError as error:
        raise HybridGradeAssemblyScopeError(str(error)) from error


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise HybridGradeAssemblyScopeError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise HybridGradeAssemblyScopeError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HybridGradeAssemblyScopeError(
            f"{field_name} must be a positive integer."
        )
    return value
