"""Storage-aware assembly for one exact standards-based Academic Period Grade.

The assembler consumes canonical Meridian/Core state only. It resolves the
explicit Grade-policy activation, reloads the exact activated policy and target
proficiency scale, and consumes only the explicitly selected Academic Period
proficiency result for each policy-participating standard. It does not reopen
producer evidence, recalculate proficiency, mutate selection state, persist a
Grade result, apply overrides, or create ReportingSnapshots.
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

from meridian.academic_period_attention import (
    AcademicPeriodAttentionReadError,
    assess_selected_academic_period_proficiency_result_freshness,
)
from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    StoredAcademicPeriodProficiencyResult,
    load_current_academic_period_proficiency_result,
)
from meridian.grade_policy import (
    GradePolicyReference,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
)
from meridian.grade_policy_activation_storage import (
    GradePolicyActivationResolution,
    GradePolicyActivationStorageError,
    StoredGradePolicyActivationDecision,
    resolve_grade_policy_activation,
)
from meridian.grade_policy_storage import (
    GradePolicyStorageError,
    StoredGradePolicyRevision,
    load_grade_policy_revision,
    validate_grade_policy_dependencies,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    StoredProficiencyScale,
    load_proficiency_scale_revision,
)
from meridian.standards_grade import (
    StandardsGradeCalculationInput,
    StandardsGradeCalculationOutcome,
    StandardsGradeSourceState,
    StandardsGradeStandardInput,
    calculate_standards_grade,
    create_standards_grade_calculation_input,
    standards_grade_calculation_fingerprint,
)


class StandardsGradeAssemblyError(RuntimeError):
    """Base failure while assembling one exact standards Grade basis."""

    code = "standards_grade.assembly_error"


class StandardsGradeAssemblyScopeError(StandardsGradeAssemblyError, ValueError):
    """Raised when the requested standards Grade scope is invalid."""

    code = "standards_grade.assembly_scope_invalid"


class StandardsGradeAssemblyAuthorityError(StandardsGradeAssemblyError):
    """Raised when no exact activated standards-based authority exists."""

    code = "standards_grade.assembly_authority_invalid"


class StandardsGradeAssemblyDependencyError(StandardsGradeAssemblyError):
    """Raised when exact canonical dependencies cannot be loaded safely."""

    code = "standards_grade.assembly_dependency_invalid"


@dataclass(frozen=True, slots=True)
class StandardsGradeAssembly:
    """Exact read-only basis and pure outcome for one standards Grade."""

    activation: StoredGradePolicyActivationDecision
    policy: StoredGradePolicyRevision
    target_scale: StoredProficiencyScale
    standards: tuple[StandardsGradeStandardInput, ...]
    inputs: StandardsGradeCalculationInput
    outcome: StandardsGradeCalculationOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.activation, StoredGradePolicyActivationDecision):
            raise StandardsGradeAssemblyScopeError(
                "activation must be StoredGradePolicyActivationDecision."
            )
        if not isinstance(self.policy, StoredGradePolicyRevision):
            raise StandardsGradeAssemblyScopeError(
                "policy must be StoredGradePolicyRevision."
            )
        if not isinstance(self.target_scale, StoredProficiencyScale):
            raise StandardsGradeAssemblyScopeError(
                "target_scale must be StoredProficiencyScale."
            )
        standards = tuple(self.standards)
        if any(
            not isinstance(item, StandardsGradeStandardInput)
            for item in standards
        ):
            raise StandardsGradeAssemblyScopeError(
                "standards must contain StandardsGradeStandardInput values."
            )
        if not isinstance(self.inputs, StandardsGradeCalculationInput):
            raise StandardsGradeAssemblyScopeError(
                "inputs must be StandardsGradeCalculationInput."
            )
        if not isinstance(self.outcome, StandardsGradeCalculationOutcome):
            raise StandardsGradeAssemblyScopeError(
                "outcome must be StandardsGradeCalculationOutcome."
            )
        if standards != self.inputs.standards:
            raise StandardsGradeAssemblyScopeError(
                "standards must exactly equal the canonical calculation inputs."
            )
        if self.policy.reference != self.inputs.policy_reference:
            raise StandardsGradeAssemblyScopeError(
                "stored policy must match the exact calculation policy reference."
            )
        if self.activation.reference != self.inputs.activation_reference:
            raise StandardsGradeAssemblyScopeError(
                "stored activation must match the calculation activation reference."
            )
        if self.target_scale.reference != self.inputs.configuration.target_scale:
            raise StandardsGradeAssemblyScopeError(
                "stored target scale must match exact standards policy authority."
            )
        if calculate_standards_grade(self.inputs) != self.outcome:
            raise StandardsGradeAssemblyScopeError(
                "outcome must exactly reproduce from the assembled inputs."
            )
        object.__setattr__(self, "standards", standards)

    @property
    def inputs_fingerprint(self) -> str:
        """Return the deterministic pure-calculation fingerprint."""

        return standards_grade_calculation_fingerprint(self.inputs)


def assemble_standards_grade_calculation(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> StandardsGradeAssembly:
    """Assemble and purely calculate one exact standards Academic Period Grade."""

    root = Path(workspace_root).resolve()
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")

    resolution = _resolve_activation(root, class_value, period)
    activation = resolution.activation
    policy_reference = resolution.policy_reference
    if (
        resolution.status != "activated"
        or activation is None
        or policy_reference is None
    ):
        raise StandardsGradeAssemblyAuthorityError(
            "Standards Grade calculation requires one explicitly activated "
            "Grade policy for the exact Academic Period."
        )
    if activation.decision.calendar_revision != calendar:
        raise StandardsGradeAssemblyAuthorityError(
            "Selected Grade-policy activation belongs to a different calendar "
            "revision than the requested calculation scope."
        )

    stored_policy = _load_exact_policy(root, policy_reference)
    policy = stored_policy.policy
    if policy.calculation_family != "standards_based" or not isinstance(
        policy.configuration,
        StandardsBasedGradeConfiguration,
    ):
        raise StandardsGradeAssemblyAuthorityError(
            "Exact activated Grade policy must use calculation_family="
            "standards_based for issue #51."
        )
    if activation.decision.policy_reference != stored_policy.reference:
        raise StandardsGradeAssemblyAuthorityError(
            "Activated Grade-policy reference does not match exact stored policy."
        )

    try:
        dependencies = validate_grade_policy_dependencies(root, policy)
    except GradePolicyStorageError as error:
        raise StandardsGradeAssemblyDependencyError(
            "Activated standards Grade-policy dependencies are not verifiable."
        ) from error
    target_scale = dependencies.target_scale
    if target_scale is None:
        target_scale = _load_exact_scale(root, policy.configuration)
    if target_scale.reference != policy.configuration.target_scale:
        raise StandardsGradeAssemblyDependencyError(
            "Exact standards Grade policy target-scale dependency does not match."
        )

    standard_inputs = tuple(
        _assemble_standard_input(
            root,
            class_value,
            student,
            period,
            calendar,
            participation,
            policy.configuration,
        )
        for participation in policy.configuration.standards
    )

    try:
        inputs = create_standards_grade_calculation_input(
            policy=policy,
            activation=activation.decision,
            student_id=student,
            target_period=period,
            calendar_revision=calendar,
            standards=standard_inputs,
        )
        outcome = calculate_standards_grade(inputs)
    except ValueError as error:
        raise StandardsGradeAssemblyDependencyError(str(error)) from error

    return StandardsGradeAssembly(
        activation=activation,
        policy=stored_policy,
        target_scale=target_scale,
        standards=standard_inputs,
        inputs=inputs,
        outcome=outcome,
    )


def _assemble_standard_input(
    workspace_root: Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    participation: StandardGradeParticipation,
    configuration: StandardsBasedGradeConfiguration,
) -> StandardsGradeStandardInput:
    standard_id = participation.standard_id
    try:
        stored = load_current_academic_period_proficiency_result(
            workspace_root,
            class_id,
            target_period.school_year,
            target_period.period_id,
            student_id,
            standard_id,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise StandardsGradeAssemblyDependencyError(
            "Selected Academic Period proficiency result could not be read safely."
        ) from error

    if stored is None:
        return StandardsGradeStandardInput(
            participation=participation,
            student_id=student_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
            status="missing",
            result_reference=None,
            result_calculation_fingerprint=None,
            result_algorithm_version=None,
            proficiency_level_id=None,
            target_scale=None,
            freshness_status=None,
            reason_codes=("missing_selected_proficiency_result",),
        )

    return _input_from_selected_result(
        workspace_root,
        stored,
        student_id,
        target_period,
        calendar_revision,
        participation,
        configuration,
    )


def _input_from_selected_result(
    workspace_root: Path,
    stored: StoredAcademicPeriodProficiencyResult,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    participation: StandardGradeParticipation,
    configuration: StandardsBasedGradeConfiguration,
) -> StandardsGradeStandardInput:
    snapshot = stored.snapshot
    standard_id = participation.standard_id
    if (
        snapshot.class_id != configuration.target_scale.class_id
        or snapshot.student_id != student_id
        or snapshot.standard_id != standard_id
        or snapshot.target_period.period != target_period
    ):
        raise StandardsGradeAssemblyDependencyError(
            "Selected Academic Period proficiency result crosses the exact "
            "standards Grade logical scope."
        )

    try:
        freshness = assess_selected_academic_period_proficiency_result_freshness(
            workspace_root,
            stored,
        )
    except AcademicPeriodAttentionReadError as error:
        raise StandardsGradeAssemblyDependencyError(
            "Selected Academic Period proficiency result currentness could not "
            "be established safely."
        ) from error

    reason_codes: list[str] = []
    status: StandardsGradeSourceState
    level_id: str | None = None

    if snapshot.target_period.calendar_revision != calendar_revision:
        status = "unresolved"
        reason_codes.append("calendar_scope_mismatch")
    elif snapshot.target_scale != configuration.target_scale:
        status = "unresolved"
        reason_codes.append("proficiency_scale_mismatch")
    elif freshness.status == "stale":
        status = "unresolved"
        reason_codes.append("upstream_result_stale")
        reason_codes.extend(f"upstream_{reason}" for reason in freshness.reasons)
    elif snapshot.outcome.status == "calculated":
        level_id = snapshot.outcome.proficiency_level_id
        if level_id is None:
            status = "invalid"
            reason_codes.append("calculated_result_missing_level")
        else:
            status = "calculated"
    elif snapshot.outcome.status == "insufficient_evidence":
        status = "insufficient_evidence"
        reason_codes.append("upstream_insufficient_evidence")
    else:  # defensive: the v0.2 domain currently closes this union.
        status = "invalid"
        reason_codes.append("unsupported_upstream_result_status")

    return StandardsGradeStandardInput(
        participation=participation,
        student_id=student_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        status=status,
        result_reference=stored.reference,
        result_calculation_fingerprint=snapshot.calculation_fingerprint,
        result_algorithm_version=snapshot.algorithm_version,
        proficiency_level_id=level_id,
        target_scale=snapshot.target_scale,
        freshness_status=freshness.status,
        freshness_reasons=tuple(freshness.reasons),
        reason_codes=tuple(reason_codes),
    )


def _resolve_activation(
    workspace_root: Path,
    class_id: str,
    target_period: AcademicPeriodRef,
) -> GradePolicyActivationResolution:
    try:
        return resolve_grade_policy_activation(
            workspace_root,
            class_id,
            target_period,
        )
    except GradePolicyActivationStorageError as error:
        raise StandardsGradeAssemblyDependencyError(
            "Grade-policy activation could not be resolved safely."
        ) from error


def _load_exact_policy(
    workspace_root: Path,
    reference: GradePolicyReference,
) -> StoredGradePolicyRevision:
    try:
        stored = load_grade_policy_revision(
            workspace_root,
            reference.class_id,
            reference.policy_id,
            reference.policy_revision,
        )
    except GradePolicyStorageError as error:
        raise StandardsGradeAssemblyDependencyError(
            "Exact activated Grade-policy revision is unavailable."
        ) from error
    if stored.policy_sha256 != reference.policy_sha256:
        raise StandardsGradeAssemblyDependencyError(
            "Exact activated Grade-policy digest does not match provenance."
        )
    return stored


def _load_exact_scale(
    workspace_root: Path,
    configuration: StandardsBasedGradeConfiguration,
) -> StoredProficiencyScale:
    reference = configuration.target_scale
    try:
        stored = load_proficiency_scale_revision(
            workspace_root,
            reference.class_id,
            reference.scale_id,
            reference.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise StandardsGradeAssemblyDependencyError(
            "Exact standards Grade target proficiency scale is unavailable."
        ) from error
    if stored.reference != reference:
        raise StandardsGradeAssemblyDependencyError(
            "Exact standards Grade target proficiency-scale digest does not match."
        )
    return stored


def _period(value: object) -> AcademicPeriodRef:
    if not isinstance(value, AcademicPeriodRef):
        raise StandardsGradeAssemblyScopeError(
            "target_period must be an AcademicPeriodRef."
        )
    try:
        return validate_academic_period_ref(value)
    except AcademicPeriodValidationError as error:
        raise StandardsGradeAssemblyScopeError(str(error)) from error


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise StandardsGradeAssemblyScopeError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise StandardsGradeAssemblyScopeError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StandardsGradeAssemblyScopeError(
            f"{field_name} must be a positive integer."
        )
    return value


__all__ = [
    "StandardsGradeAssembly",
    "StandardsGradeAssemblyAuthorityError",
    "StandardsGradeAssemblyDependencyError",
    "StandardsGradeAssemblyError",
    "StandardsGradeAssemblyScopeError",
    "assemble_standards_grade_calculation",
]
