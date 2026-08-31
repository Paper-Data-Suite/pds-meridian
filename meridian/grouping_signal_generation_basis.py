"""Resolve exact current #35 aggregation-input bases for #38 generation.

This module rebuilds the current Academic Period proficiency input basis from
explicit current Grade Item selections, selected included membership decisions,
and explicitly selected #34 standards-proficiency results.  It does not calculate
#35 proficiency, select #35 results, generate #38 derivations, preview signals,
or write Core grouping-signal exchange state.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pds_core.academic_period_storage import (
    AcademicPeriodCalendarStorageError,
    load_academic_period_calendar_revision,
)
from pds_core.academic_periods import AcademicPeriodCalendar
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.academic_period_proficiency import (
    AcademicPeriodMembershipScope,
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyMembershipBasis,
    AcademicPeriodProficiencyValidationError,
    ResolvedAcademicPeriodProficiencyCandidate,
    academic_period_proficiency_membership_basis_from_decision,
    build_academic_period_proficiency_aggregation_inputs,
    resolve_academic_period_proficiency_scope,
)
from meridian.grade_item_membership_storage import (
    GradeItemMembershipStorageError,
    StoredGradeItemMembershipDecision,
    list_selected_included_grade_item_memberships,
)
from meridian.grade_item_storage import (
    GradeItemStorageError,
    StoredGradeItemRevision,
    list_grade_item_ids,
    load_current_grade_item_revision,
)
from meridian.grouping_signal_policy import (
    GroupingSignalDerivationPolicy,
    GroupingSignalPolicyValidationError,
    validate_grouping_signal_derivation_policy,
)
from meridian.grouping_signal_policy_storage import (
    GroupingSignalPolicyDependencies,
    GroupingSignalPolicyStorageError,
    validate_grouping_signal_policy_dependencies,
)
from meridian.standards_evidence import GradeItemAggregationBasis
from meridian.standards_proficiency_storage import (
    StandardProficiencyStorageError,
    StoredStandardProficiencyResult,
    load_current_standard_proficiency_result,
)


class GroupingSignalCurrentBasisError(RuntimeError):
    """Base error for exact current #35 basis reconstruction."""


class GroupingSignalCurrentBasisValidationError(
    GroupingSignalCurrentBasisError,
    ValueError,
):
    """Raised for invalid current-basis resolver arguments."""


class GroupingSignalCurrentBasisReadError(GroupingSignalCurrentBasisError):
    """Raised when exact current Core/Meridian basis state cannot be read safely."""


@dataclass(frozen=True, slots=True)
class CurrentGroupingSignalAcademicBasis:
    """Verified reusable current basis shared across roster-student rebuilds."""

    policy: GroupingSignalDerivationPolicy
    dependencies: GroupingSignalPolicyDependencies
    calendar: AcademicPeriodCalendar
    candidates: tuple[
        tuple[
            GradeItemAggregationBasis,
            tuple[AcademicPeriodProficiencyMembershipBasis, ...],
        ],
        ...,
    ]


def resolve_current_grouping_signal_academic_basis(
    workspace_root: str | Path,
    policy: GroupingSignalDerivationPolicy,
) -> CurrentGroupingSignalAcademicBasis:
    """Resolve exact current Grade Item/membership candidates for one #37 policy."""

    root = _root(workspace_root)
    try:
        exact_policy = validate_grouping_signal_derivation_policy(policy)
    except GroupingSignalPolicyValidationError as error:
        raise GroupingSignalCurrentBasisValidationError(str(error)) from error

    try:
        dependencies = validate_grouping_signal_policy_dependencies(root, exact_policy)
    except GroupingSignalPolicyStorageError as error:
        raise GroupingSignalCurrentBasisReadError(
            "Selected #37 policy dependencies could not be verified for current basis."
        ) from error

    target = exact_policy.academic_basis.target_period
    try:
        calendar = load_academic_period_calendar_revision(
            root,
            target.period.school_year,
            target.calendar_revision,
        )
    except AcademicPeriodCalendarStorageError as error:
        raise GroupingSignalCurrentBasisReadError(
            "Exact Core Academic Period Calendar revision is unavailable."
        ) from error

    scope = dependencies.source_policy.policy.period_membership_scope
    candidates = _current_candidate_bases(
        root,
        exact_policy,
        calendar,
        scope,
    )
    return CurrentGroupingSignalAcademicBasis(
        policy=exact_policy,
        dependencies=dependencies,
        calendar=calendar,
        candidates=candidates,
    )


def build_current_academic_period_proficiency_inputs(
    workspace_root: str | Path,
    current_basis: CurrentGroupingSignalAcademicBasis,
    student_id: str,
) -> AcademicPeriodProficiencyAggregationInputs:
    """Build exact current #35 aggregation inputs for one roster student."""

    root = _root(workspace_root)
    if not isinstance(current_basis, CurrentGroupingSignalAcademicBasis):
        raise GroupingSignalCurrentBasisValidationError(
            "current_basis must be a CurrentGroupingSignalAcademicBasis."
        )
    student = _identifier(student_id, "student_id")
    policy = current_basis.policy
    basis = policy.academic_basis
    scope = current_basis.dependencies.source_policy.policy.period_membership_scope

    resolved: list[ResolvedAcademicPeriodProficiencyCandidate] = []
    for grade_item, memberships in current_basis.candidates:
        selected_result = _load_current_grade_item_result(
            root,
            policy.class_id,
            grade_item.grade_item_id,
            student,
            basis.standard_id,
        )
        result_snapshot = None if selected_result is None else selected_result.snapshot
        try:
            candidate = ResolvedAcademicPeriodProficiencyCandidate(
                grade_item,
                memberships,
                result_snapshot,
            )
        except AcademicPeriodProficiencyValidationError:
            # A selected #34 result whose exact Grade Item/membership/standard/scale
            # provenance no longer matches the current basis is not a current result
            # for this rebuilt #35 input set.  Preserve the candidate as missing.
            candidate = ResolvedAcademicPeriodProficiencyCandidate(
                grade_item,
                memberships,
                None,
            )
        resolved.append(candidate)

    try:
        return build_academic_period_proficiency_aggregation_inputs(
            target_period=basis.target_period,
            calendar=current_basis.calendar,
            student_id=student,
            standard_id=basis.standard_id,
            target_scale=basis.target_scale,
            period_membership_scope=scope,
            candidates=tuple(resolved),
        )
    except AcademicPeriodProficiencyValidationError as error:
        raise GroupingSignalCurrentBasisValidationError(
            f"Current #35 aggregation inputs could not be rebuilt: {error}"
        ) from error


def build_current_grouping_signal_inputs_by_student(
    workspace_root: str | Path,
    policy: GroupingSignalDerivationPolicy,
    student_ids: Iterable[str],
) -> dict[str, AcademicPeriodProficiencyAggregationInputs]:
    """Build deterministic exact current #35 inputs for explicit roster students."""

    students = _student_ids(student_ids)
    current_basis = resolve_current_grouping_signal_academic_basis(
        workspace_root,
        policy,
    )
    return {
        student_id: build_current_academic_period_proficiency_inputs(
            workspace_root,
            current_basis,
            student_id,
        )
        for student_id in students
    }


def _current_candidate_bases(
    root: Path,
    policy: GroupingSignalDerivationPolicy,
    calendar: AcademicPeriodCalendar,
    scope: AcademicPeriodMembershipScope,
) -> tuple[
    tuple[
        GradeItemAggregationBasis,
        tuple[AcademicPeriodProficiencyMembershipBasis, ...],
    ],
    ...,
]:
    try:
        grade_item_ids = list_grade_item_ids(root, policy.class_id)
    except GradeItemStorageError as error:
        raise GroupingSignalCurrentBasisReadError(
            "Could not enumerate current Meridian Grade Items."
        ) from error

    result: list[
        tuple[
            GradeItemAggregationBasis,
            tuple[AcademicPeriodProficiencyMembershipBasis, ...],
        ]
    ] = []
    for grade_item_id in grade_item_ids:
        stored_item = _load_current_grade_item(root, policy.class_id, grade_item_id)
        if stored_item is None:
            continue
        revision = stored_item.revision
        if revision.status != "active" or revision.purpose not in {
            "standards_proficiency",
            "standards_and_conventional",
        }:
            continue

        memberships = _current_membership_bases(root, stored_item)
        if not memberships:
            continue
        if not any(
            _membership_is_relevant(
                policy,
                calendar,
                membership,
                scope,
            )
            for membership in memberships
        ):
            continue

        grade_item = GradeItemAggregationBasis(
            policy.class_id,
            revision.grade_item_id,
            revision.grade_item_revision,
            stored_item.revision_sha256,
        )
        result.append((grade_item, memberships))

    return tuple(sorted(result, key=lambda item: item[0].grade_item_id))


def _current_membership_bases(
    root: Path,
    stored_item: StoredGradeItemRevision,
) -> tuple[AcademicPeriodProficiencyMembershipBasis, ...]:
    revision = stored_item.revision
    try:
        selected = list_selected_included_grade_item_memberships(
            root,
            revision.class_id,
            revision.grade_item_id,
        )
    except GradeItemMembershipStorageError as error:
        raise GroupingSignalCurrentBasisReadError(
            "Could not resolve selected included Grade Item memberships."
        ) from error

    bases: list[AcademicPeriodProficiencyMembershipBasis] = []
    for stored_membership in selected:
        if not _membership_matches_current_grade_item(
            stored_membership,
            stored_item,
        ):
            continue
        try:
            bases.append(
                academic_period_proficiency_membership_basis_from_decision(
                    stored_membership.decision,
                    stored_membership.decision_sha256,
                )
            )
        except AcademicPeriodProficiencyValidationError as error:
            raise GroupingSignalCurrentBasisReadError(
                "Selected included membership cannot form an exact #35 basis."
            ) from error

    return tuple(
        sorted(
            bases,
            key=lambda item: (
                item.work_reference.work.module_id,
                item.work_reference.work.work_id,
            ),
        )
    )


def _membership_matches_current_grade_item(
    membership: StoredGradeItemMembershipDecision,
    grade_item: StoredGradeItemRevision,
) -> bool:
    decision = membership.decision
    revision = grade_item.revision
    return (
        decision.class_id == revision.class_id
        and decision.grade_item_id == revision.grade_item_id
        and decision.grade_item_revision == revision.grade_item_revision
        and decision.grade_item_revision_sha256 == grade_item.revision_sha256
    )


def _membership_is_relevant(
    policy: GroupingSignalDerivationPolicy,
    calendar: AcademicPeriodCalendar,
    membership: AcademicPeriodProficiencyMembershipBasis,
    scope: AcademicPeriodMembershipScope,
) -> bool:
    try:
        resolution = resolve_academic_period_proficiency_scope(
            policy.academic_basis.target_period,
            calendar,
            (membership,),
            scope,
        )
    except AcademicPeriodProficiencyValidationError as error:
        raise GroupingSignalCurrentBasisReadError(
            "Current membership cannot be evaluated against the exact #37 period."
        ) from error
    return resolution.status == "eligible"


def _load_current_grade_item(
    root: Path,
    class_id: str,
    grade_item_id: str,
) -> StoredGradeItemRevision | None:
    try:
        return load_current_grade_item_revision(root, class_id, grade_item_id)
    except GradeItemStorageError as error:
        raise GroupingSignalCurrentBasisReadError(
            "Could not load one explicitly selected current Grade Item revision."
        ) from error


def _load_current_grade_item_result(
    root: Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
) -> StoredStandardProficiencyResult | None:
    try:
        return load_current_standard_proficiency_result(
            root,
            class_id,
            grade_item_id,
            student_id,
            standard_id,
        )
    except StandardProficiencyStorageError as error:
        raise GroupingSignalCurrentBasisReadError(
            "Could not load one explicitly selected current #34 result."
        ) from error


def _student_ids(values: Iterable[str]) -> tuple[str, ...]:
    try:
        items = tuple(values)
    except TypeError as error:
        raise GroupingSignalCurrentBasisValidationError(
            "student_ids must be an iterable of student IDs."
        ) from error
    students = tuple(_identifier(item, "student_id") for item in items)
    if len(set(students)) != len(students):
        raise GroupingSignalCurrentBasisValidationError(
            "student_ids must not contain duplicates."
        )
    return tuple(sorted(students))


def _root(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise GroupingSignalCurrentBasisValidationError(
            "workspace_root must be a string or Path."
        )
    path = Path(value)
    return path if path.is_absolute() else path.resolve()


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalCurrentBasisValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GroupingSignalCurrentBasisValidationError(str(error)) from error
