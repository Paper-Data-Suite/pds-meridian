"""Bounded exact #35 input assembly for Academic Period Calculation Preview."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.academic_period_storage import (
    AcademicPeriodCalendarStorageError,
    load_academic_period_calendar_revision,
)
from pds_core.routing_models import ModuleWorkRef

from meridian.academic_period_calculation_preview_workflow import (
    AcademicPeriodCalculationPreviewProjection,
    build_academic_period_calculation_preview_projection,
)
from meridian.academic_period_proficiency import (
    MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_CANDIDATES,
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyAggregationPolicyReference,
    AcademicPeriodProficiencyTarget,
    AcademicPeriodProficiencyValidationError,
    ResolvedAcademicPeriodProficiencyCandidate,
    academic_period_proficiency_membership_basis_from_decision,
    build_academic_period_proficiency_aggregation_inputs,
)
from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    load_academic_period_proficiency_policy_revision,
)
from meridian.grade_item_membership_storage import (
    GradeItemMembershipStorageError,
    load_grade_item_membership_revision,
)
from meridian.grade_item_storage import GradeItemStorageError, load_grade_item_revision
from meridian.standards_evidence import GradeItemAggregationBasis
from meridian.standards_proficiency_storage import (
    StandardProficiencyStorageError,
    load_standard_proficiency_result_revision,
)


class AcademicPeriodCalculationAssemblyError(RuntimeError):
    """Base failure while assembling exact bounded #35 calculation inputs."""

    code = "teacher_workflow.calculation_preview.academic_period_assembly_error"


class AcademicPeriodCalculationAssemblyScopeError(
    AcademicPeriodCalculationAssemblyError,
    ValueError,
):
    """Raised when caller-supplied exact #35 scope is invalid."""

    code = "teacher_workflow.calculation_preview.academic_period_assembly_invalid"


class AcademicPeriodCalculationAssemblyDependencyError(
    AcademicPeriodCalculationAssemblyError
):
    """Raised when an exact persisted #28/#34/#35 dependency cannot be verified."""

    code = (
        "teacher_workflow.calculation_preview."
        "academic_period_assembly_dependency_invalid"
    )


@dataclass(frozen=True, slots=True)
class AcademicPeriodMembershipSpec:
    """One exact persisted selected-membership basis supplied by the caller."""

    work: ModuleWorkRef
    membership_revision: int
    membership_sha256: str


@dataclass(frozen=True, slots=True)
class AcademicPeriodCalculationCandidateSpec:
    """One explicit Grade Item candidate plus optional exact #34 result."""

    grade_item_id: str
    grade_item_revision: int
    grade_item_revision_sha256: str
    memberships: tuple[AcademicPeriodMembershipSpec, ...]
    result_revision: int | None = None
    result_sha256: str | None = None

    @property
    def has_result(self) -> bool:
        return self.result_revision is not None


@dataclass(frozen=True, slots=True)
class BoundedAcademicPeriodCalculationPreview:
    """Exact caller-bounded #35 inputs plus the read-only pure calculation."""

    target_period: AcademicPeriodProficiencyTarget
    candidate_specs: tuple[AcademicPeriodCalculationCandidateSpec, ...]
    inputs: AcademicPeriodProficiencyAggregationInputs
    calculation: AcademicPeriodCalculationPreviewProjection

    @property
    def candidate_count(self) -> int:
        return len(self.candidate_specs)

    @property
    def grade_item_ids(self) -> tuple[str, ...]:
        return tuple(spec.grade_item_id for spec in self.candidate_specs)

    @property
    def result_write_performed(self) -> bool:
        return self.calculation.result_write_performed

    @property
    def result_selection_performed(self) -> bool:
        return self.calculation.result_selection_performed


def build_bounded_academic_period_calculation_preview(
    workspace_root: str | Path,
    target_period: AcademicPeriodProficiencyTarget,
    student_id: str,
    standard_id: str,
    candidate_specs: tuple[AcademicPeriodCalculationCandidateSpec, ...],
    policy_reference: AcademicPeriodProficiencyAggregationPolicyReference,
) -> BoundedAcademicPeriodCalculationPreview:
    """Resolve only exact caller-supplied #28/#34 candidate provenance."""
    _validate_request(
        target_period,
        student_id,
        standard_id,
        candidate_specs,
        policy_reference,
    )

    try:
        stored_policy = load_academic_period_proficiency_policy_revision(
            workspace_root,
            policy_reference.class_id,
            policy_reference.policy_id,
            policy_reference.policy_revision,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise AcademicPeriodCalculationAssemblyDependencyError(
            f"Exact Academic Period proficiency policy could not be loaded: {error}"
        ) from error
    if stored_policy.policy_sha256 != policy_reference.policy_sha256:
        raise AcademicPeriodCalculationAssemblyDependencyError(
            "Exact Academic Period policy SHA-256 does not match stored revision."
        )
    policy = stored_policy.policy

    try:
        calendar = load_academic_period_calendar_revision(
            workspace_root,
            target_period.period.school_year,
            target_period.calendar_revision,
        )
    except AcademicPeriodCalendarStorageError as error:
        raise AcademicPeriodCalculationAssemblyDependencyError(
            f"Exact Core Academic Period calendar could not be loaded: {error}"
        ) from error

    resolved: list[ResolvedAcademicPeriodProficiencyCandidate] = []
    for spec in sorted(candidate_specs, key=lambda value: value.grade_item_id):
        try:
            stored_grade_item = load_grade_item_revision(
                workspace_root,
                policy_reference.class_id,
                spec.grade_item_id,
                spec.grade_item_revision,
            )
        except GradeItemStorageError as error:
            raise AcademicPeriodCalculationAssemblyDependencyError(
                f"Exact Grade Item revision could not be loaded: {error}"
            ) from error
        if stored_grade_item.revision_sha256 != spec.grade_item_revision_sha256:
            raise AcademicPeriodCalculationAssemblyDependencyError(
                f"Grade Item {spec.grade_item_id!r} revision SHA-256 "
                "does not match the supplied exact basis."
            )
        grade_item_basis = GradeItemAggregationBasis(
            class_id=policy_reference.class_id,
            grade_item_id=spec.grade_item_id,
            grade_item_revision=spec.grade_item_revision,
            grade_item_revision_sha256=spec.grade_item_revision_sha256,
        )

        memberships = []
        seen_work: set[tuple[str, str]] = set()
        for membership_spec in sorted(
            spec.memberships,
            key=lambda value: (value.work.module_id, value.work.work_id),
        ):
            work_key = (
                membership_spec.work.module_id,
                membership_spec.work.work_id,
            )
            if work_key in seen_work:
                raise AcademicPeriodCalculationAssemblyScopeError(
                    f"Grade Item {spec.grade_item_id!r} memberships must not "
                    "duplicate a logical work relationship."
                )
            seen_work.add(work_key)
            try:
                stored_membership = load_grade_item_membership_revision(
                    workspace_root,
                    policy_reference.class_id,
                    spec.grade_item_id,
                    membership_spec.work,
                    membership_spec.membership_revision,
                )
            except GradeItemMembershipStorageError as error:
                raise AcademicPeriodCalculationAssemblyDependencyError(
                    f"Exact Grade Item membership could not be loaded: {error}"
                ) from error
            if stored_membership.decision_sha256 != membership_spec.membership_sha256:
                raise AcademicPeriodCalculationAssemblyDependencyError(
                    "Exact membership SHA-256 does not match the supplied basis."
                )
            decision = stored_membership.decision
            if (
                decision.grade_item_revision != spec.grade_item_revision
                or decision.grade_item_revision_sha256
                != spec.grade_item_revision_sha256
            ):
                raise AcademicPeriodCalculationAssemblyDependencyError(
                    "Exact membership Grade Item basis does not match the "
                    "candidate Grade Item basis."
                )
            try:
                memberships.append(
                    academic_period_proficiency_membership_basis_from_decision(
                        decision,
                        stored_membership.decision_sha256,
                    )
                )
            except AcademicPeriodProficiencyValidationError as error:
                raise AcademicPeriodCalculationAssemblyDependencyError(
                    str(error)
                ) from error

        result_snapshot = None
        if spec.result_revision is not None:
            try:
                stored_result = load_standard_proficiency_result_revision(
                    workspace_root,
                    policy_reference.class_id,
                    spec.grade_item_id,
                    student_id,
                    standard_id,
                    spec.result_revision,
                )
            except StandardProficiencyStorageError as error:
                raise AcademicPeriodCalculationAssemblyDependencyError(
                    "Exact #34 Grade Item proficiency result could not be "
                    f"loaded: {error}"
                ) from error
            if stored_result.result_sha256 != spec.result_sha256:
                raise AcademicPeriodCalculationAssemblyDependencyError(
                    "Exact #34 result SHA-256 does not match the supplied result."
                )
            result_snapshot = stored_result.snapshot

        try:
            resolved.append(
                ResolvedAcademicPeriodProficiencyCandidate(
                    grade_item=grade_item_basis,
                    memberships=tuple(memberships),
                    result=result_snapshot,
                )
            )
        except AcademicPeriodProficiencyValidationError as error:
            raise AcademicPeriodCalculationAssemblyDependencyError(
                str(error)
            ) from error

    try:
        exact_inputs = build_academic_period_proficiency_aggregation_inputs(
            target_period=target_period,
            calendar=calendar,
            student_id=student_id,
            standard_id=standard_id,
            target_scale=policy.target_scale,
            period_membership_scope=policy.period_membership_scope,
            candidates=tuple(resolved),
        )
    except AcademicPeriodProficiencyValidationError as error:
        raise AcademicPeriodCalculationAssemblyDependencyError(
            str(error)
        ) from error

    calculation = build_academic_period_calculation_preview_projection(
        workspace_root,
        exact_inputs,
        policy_reference,
    )
    ordered_specs = tuple(
        sorted(candidate_specs, key=lambda value: value.grade_item_id)
    )
    return BoundedAcademicPeriodCalculationPreview(
        target_period=target_period,
        candidate_specs=ordered_specs,
        inputs=exact_inputs,
        calculation=calculation,
    )


def _validate_request(
    target_period: AcademicPeriodProficiencyTarget,
    student_id: str,
    standard_id: str,
    candidate_specs: tuple[AcademicPeriodCalculationCandidateSpec, ...],
    policy_reference: AcademicPeriodProficiencyAggregationPolicyReference,
) -> None:
    if not isinstance(target_period, AcademicPeriodProficiencyTarget):
        raise AcademicPeriodCalculationAssemblyScopeError(
            "target_period must be an exact AcademicPeriodProficiencyTarget."
        )
    for field_name, value in (
        ("student_id", student_id),
        ("standard_id", standard_id),
    ):
        if not isinstance(value, str) or not value:
            raise AcademicPeriodCalculationAssemblyScopeError(
                f"{field_name} must be a nonempty string."
            )
    if not isinstance(
        policy_reference,
        AcademicPeriodProficiencyAggregationPolicyReference,
    ):
        raise AcademicPeriodCalculationAssemblyScopeError(
            "policy_reference must be an exact Academic Period policy reference."
        )
    if not isinstance(candidate_specs, tuple) or any(
        not isinstance(spec, AcademicPeriodCalculationCandidateSpec)
        for spec in candidate_specs
    ):
        raise AcademicPeriodCalculationAssemblyScopeError(
            "candidate_specs must be a tuple of exact "
            "AcademicPeriodCalculationCandidateSpec values."
        )
    if len(candidate_specs) > MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_CANDIDATES:
        raise AcademicPeriodCalculationAssemblyScopeError(
            "Academic Period candidate count exceeds the finite #35 maximum."
        )
    grade_item_ids = tuple(spec.grade_item_id for spec in candidate_specs)
    if len(set(grade_item_ids)) != len(grade_item_ids):
        raise AcademicPeriodCalculationAssemblyScopeError(
            "Academic Period candidates must not duplicate a logical Grade Item."
        )
    for spec in candidate_specs:
        _validate_candidate_spec(spec, policy_reference.class_id)


def _validate_candidate_spec(
    spec: AcademicPeriodCalculationCandidateSpec,
    class_id: str,
) -> None:
    if not isinstance(spec.grade_item_id, str) or not spec.grade_item_id:
        raise AcademicPeriodCalculationAssemblyScopeError(
            "candidate grade_item_id must be a nonempty string."
        )
    if (
        not isinstance(spec.grade_item_revision, int)
        or isinstance(spec.grade_item_revision, bool)
        or spec.grade_item_revision <= 0
    ):
        raise AcademicPeriodCalculationAssemblyScopeError(
            "candidate grade_item_revision must be a positive integer."
        )
    _validate_sha(spec.grade_item_revision_sha256, "grade_item_revision_sha256")
    if not isinstance(spec.memberships, tuple) or any(
        not isinstance(item, AcademicPeriodMembershipSpec)
        for item in spec.memberships
    ):
        raise AcademicPeriodCalculationAssemblyScopeError(
            "candidate memberships must be a tuple of exact "
            "AcademicPeriodMembershipSpec values."
        )
    for membership in spec.memberships:
        if not isinstance(membership.work, ModuleWorkRef):
            raise AcademicPeriodCalculationAssemblyScopeError(
                "membership work must be an exact ModuleWorkRef."
            )
        if membership.work.class_id != class_id:
            raise AcademicPeriodCalculationAssemblyScopeError(
                "membership work class must match the Academic Period policy class."
            )
        if (
            not isinstance(membership.membership_revision, int)
            or isinstance(membership.membership_revision, bool)
            or membership.membership_revision <= 0
        ):
            raise AcademicPeriodCalculationAssemblyScopeError(
                "membership_revision must be a positive integer."
            )
        _validate_sha(membership.membership_sha256, "membership_sha256")

    if (spec.result_revision is None) != (spec.result_sha256 is None):
        raise AcademicPeriodCalculationAssemblyScopeError(
            "result_revision and result_sha256 must either both be "
            "supplied or both be absent."
        )
    if spec.result_revision is not None:
        if (
            not isinstance(spec.result_revision, int)
            or isinstance(spec.result_revision, bool)
            or spec.result_revision <= 0
        ):
            raise AcademicPeriodCalculationAssemblyScopeError(
                "result_revision must be a positive integer."
            )
        assert spec.result_sha256 is not None
        _validate_sha(spec.result_sha256, "result_sha256")


def _validate_sha(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AcademicPeriodCalculationAssemblyScopeError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
