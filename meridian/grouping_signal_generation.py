"""Workspace orchestration core for deterministic #38 grouping-signal generation.

This module resolves explicit #37 policy selection, the exact Core roster, and
explicit #35 result selections.  The workspace-level entry point rebuilds exact
current #35 aggregation inputs before freshness comparison; embedded historical
result inputs are never assumed to be current.  Successful generation persists
only a Meridian #38 derivation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeAlias

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.rosters import RosterError, load_roster
from pds_core.routes import class_roster_path

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION,
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyResultReference,
    AcademicPeriodProficiencyStalenessReason,
    academic_period_proficiency_result_reference,
    assess_academic_period_proficiency_result_freshness,
)
from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    StoredAcademicPeriodProficiencyResult,
    load_current_academic_period_proficiency_result,
)
from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationBlockedError,
    GroupingSignalDerivationSnapshot,
    GroupingSignalResolvedStudentResult,
    GroupingSignalRosterBasis,
    derive_grouping_signal_snapshot,
    grouping_signal_roster_basis,
)
from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationWriteDisposition,
    StoredGroupingSignalDerivation,
    write_grouping_signal_derivation,
)
from meridian.grouping_signal_generation_basis import (
    GroupingSignalCurrentBasisError,
    build_current_grouping_signal_inputs_by_student,
)
from meridian.grouping_signal_policy import GroupingSignalDerivationPolicy
from meridian.grouping_signal_policy_storage import (
    GroupingSignalPolicyStorageError,
    StoredGroupingSignalDerivationPolicy,
    load_current_grouping_signal_policy,
    validate_grouping_signal_policy_dependencies,
)

GroupingSignalGenerationStatus: TypeAlias = Literal["generated", "blocked"]
GroupingSignalGenerationBlockerCode: TypeAlias = Literal[
    "no_selected_policy",
    "missing_result",
    "insufficient_evidence",
    "stale_result",
    "selected_result_mismatch",
    "current_basis_unavailable",
]

_BLOCKER_CODES: Final[tuple[GroupingSignalGenerationBlockerCode, ...]] = (
    "no_selected_policy",
    "missing_result",
    "insufficient_evidence",
    "stale_result",
    "selected_result_mismatch",
    "current_basis_unavailable",
)


class GroupingSignalGenerationError(RuntimeError):
    """Base error for #38 generation orchestration failures."""


class GroupingSignalGenerationValidationError(
    GroupingSignalGenerationError,
    ValueError,
):
    """Raised for invalid generation request arguments."""


class GroupingSignalGenerationReadError(GroupingSignalGenerationError):
    """Raised when exact Core/Meridian source state cannot be read safely."""


@dataclass(frozen=True, slots=True)
class GroupingSignalGenerationBlocker:
    """One structured teacher/workflow-resolvable reason generation cannot finish."""

    code: GroupingSignalGenerationBlockerCode
    student_id: str | None
    source_result: AcademicPeriodProficiencyResultReference | None
    freshness_reasons: tuple[AcademicPeriodProficiencyStalenessReason, ...] = ()

    def __post_init__(self) -> None:
        if self.code not in _BLOCKER_CODES:
            raise GroupingSignalGenerationValidationError(
                "unsupported grouping-signal generation blocker code."
            )
        student_id = self.student_id
        if student_id is not None:
            student_id = _identifier(student_id, "student_id")
        source_result = self.source_result
        if source_result is not None and not isinstance(
            source_result,
            AcademicPeriodProficiencyResultReference,
        ):
            raise GroupingSignalGenerationValidationError(
                "source_result must be an exact #35 result reference or None."
            )
        if source_result is not None and student_id != source_result.student_id:
            raise GroupingSignalGenerationValidationError(
                "source_result student_id must match blocker student_id."
            )
        reasons = tuple(self.freshness_reasons)
        allowed_reasons = {
            "inputs_changed",
            "policy_changed",
            "scale_changed",
            "calendar_changed",
            "algorithm_changed",
        }
        if any(reason not in allowed_reasons for reason in reasons):
            raise GroupingSignalGenerationValidationError(
                "freshness_reasons contains an unsupported #35 reason."
            )
        if len(set(reasons)) != len(reasons):
            raise GroupingSignalGenerationValidationError(
                "freshness_reasons must not contain duplicates."
            )
        if self.code == "no_selected_policy":
            if student_id is not None or source_result is not None or reasons:
                raise GroupingSignalGenerationValidationError(
                    "no_selected_policy is a class-level blocker only."
                )
        else:
            if student_id is None:
                raise GroupingSignalGenerationValidationError(
                    "student-level blocker requires student_id."
                )
            if self.code == "stale_result":
                if source_result is None or not reasons:
                    raise GroupingSignalGenerationValidationError(
                        "stale_result requires exact result provenance and reasons."
                    )
            elif reasons:
                raise GroupingSignalGenerationValidationError(
                    "freshness_reasons are valid only for stale_result."
                )
            if self.code in {
                "insufficient_evidence",
                "selected_result_mismatch",
                "current_basis_unavailable",
            } and source_result is None:
                raise GroupingSignalGenerationValidationError(
                    f"{self.code} requires exact selected result provenance."
                )
            if self.code == "missing_result" and source_result is not None:
                raise GroupingSignalGenerationValidationError(
                    "missing_result must not fabricate source-result provenance."
                )
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "freshness_reasons", reasons)


@dataclass(frozen=True, slots=True)
class GroupingSignalGenerationCandidate:
    """Read-only deterministic #38 candidate or structured blockers."""

    status: GroupingSignalGenerationStatus
    blockers: tuple[GroupingSignalGenerationBlocker, ...]
    snapshot: GroupingSignalDerivationSnapshot | None

    def __post_init__(self) -> None:
        if self.status not in {"generated", "blocked"}:
            raise GroupingSignalGenerationValidationError(
                "status must be generated or blocked."
            )
        blockers = tuple(self.blockers)
        if any(
            not isinstance(item, GroupingSignalGenerationBlocker)
            for item in blockers
        ):
            raise GroupingSignalGenerationValidationError(
                "blockers contains an invalid generation blocker."
            )
        ordered = tuple(sorted(blockers, key=_blocker_sort_key))
        if blockers != ordered:
            raise GroupingSignalGenerationValidationError(
                "blockers must use deterministic class/student/code ordering."
            )
        if self.status == "generated":
            if blockers or self.snapshot is None:
                raise GroupingSignalGenerationValidationError(
                    "generated candidate requires a snapshot and no blockers."
                )
        elif not blockers or self.snapshot is not None:
            raise GroupingSignalGenerationValidationError(
                "blocked candidate requires blockers and no snapshot."
            )
        object.__setattr__(self, "blockers", blockers)


@dataclass(frozen=True, slots=True)
class GroupingSignalGenerationResult:
    """Generated immutable derivation or deterministic structured blockers."""

    status: GroupingSignalGenerationStatus
    blockers: tuple[GroupingSignalGenerationBlocker, ...]
    stored: StoredGroupingSignalDerivation | None
    write_disposition: GroupingSignalDerivationWriteDisposition | None

    def __post_init__(self) -> None:
        if self.status not in {"generated", "blocked"}:
            raise GroupingSignalGenerationValidationError(
                "status must be generated or blocked."
            )
        blockers = tuple(self.blockers)
        if any(
            not isinstance(item, GroupingSignalGenerationBlocker)
            for item in blockers
        ):
            raise GroupingSignalGenerationValidationError(
                "blockers contains an invalid generation blocker."
            )
        ordered = tuple(sorted(blockers, key=_blocker_sort_key))
        if blockers != ordered:
            raise GroupingSignalGenerationValidationError(
                "blockers must use deterministic class/student/code ordering."
            )
        if self.status == "generated":
            if blockers or self.stored is None or self.write_disposition is None:
                raise GroupingSignalGenerationValidationError(
                    "generated result requires stored derivation and no blockers."
                )
        elif (
            not blockers
            or self.stored is not None
            or self.write_disposition is not None
        ):
            raise GroupingSignalGenerationValidationError(
                "blocked result requires blockers and no persisted derivation."
            )
        object.__setattr__(self, "blockers", blockers)


def resolve_current_grouping_signal_derivation(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> GroupingSignalGenerationCandidate:
    """Resolve the exact current #38 candidate without persisting it."""

    root = _root(workspace_root)
    exact_class_id = _identifier(class_id, "class_id")
    exact_policy_id = _identifier(policy_id, "policy_id")
    selected_policy = _load_selected_policy(
        root,
        exact_class_id,
        exact_policy_id,
    )
    if selected_policy is None:
        return _no_selected_policy_candidate()

    roster_basis = _load_roster_basis(root, exact_class_id)
    try:
        current_inputs = build_current_grouping_signal_inputs_by_student(
            root,
            selected_policy.policy,
            roster_basis.student_ids,
        )
    except GroupingSignalCurrentBasisError as error:
        raise GroupingSignalGenerationReadError(
            "Could not rebuild the exact current #35 aggregation-input basis."
        ) from error

    return _resolve_grouping_signal_derivation_from_resolved_state(
        root,
        exact_class_id,
        selected_policy,
        roster_basis,
        current_inputs,
    )


def generate_grouping_signal_derivation(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> GroupingSignalGenerationResult:
    """Generate #38 from exact selected workspace state.

    This preserves the established generating orchestration seam while the
    read-only resolver uses the same in-memory candidate core without writing.
    """

    root = _root(workspace_root)
    exact_class_id = _identifier(class_id, "class_id")
    exact_policy_id = _identifier(policy_id, "policy_id")
    selected_policy = _load_selected_policy(
        root,
        exact_class_id,
        exact_policy_id,
    )
    if selected_policy is None:
        return _no_selected_policy_result()

    roster_basis = _load_roster_basis(root, exact_class_id)
    try:
        current_inputs = build_current_grouping_signal_inputs_by_student(
            root,
            selected_policy.policy,
            roster_basis.student_ids,
        )
    except GroupingSignalCurrentBasisError as error:
        raise GroupingSignalGenerationReadError(
            "Could not rebuild the exact current #35 aggregation-input basis."
        ) from error

    return _generate_grouping_signal_derivation_from_resolved_state(
        root,
        exact_class_id,
        selected_policy,
        roster_basis,
        current_inputs,
    )

def resolve_grouping_signal_derivation_from_current_inputs(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    current_inputs_by_student: Mapping[
        str, AcademicPeriodProficiencyAggregationInputs
    ],
) -> GroupingSignalGenerationCandidate:
    """Resolve #38 from explicit current #35 inputs without persisting it."""

    root = _root(workspace_root)
    exact_class_id = _identifier(class_id, "class_id")
    exact_policy_id = _identifier(policy_id, "policy_id")
    current_inputs = _current_inputs_mapping(current_inputs_by_student)
    selected_policy = _load_selected_policy(
        root,
        exact_class_id,
        exact_policy_id,
    )
    if selected_policy is None:
        return _no_selected_policy_candidate()
    roster_basis = _load_roster_basis(root, exact_class_id)
    return _resolve_grouping_signal_derivation_from_resolved_state(
        root,
        exact_class_id,
        selected_policy,
        roster_basis,
        current_inputs,
    )


def generate_grouping_signal_derivation_from_current_inputs(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    current_inputs_by_student: Mapping[
        str, AcademicPeriodProficiencyAggregationInputs
    ],
) -> GroupingSignalGenerationResult:
    """Generate #38 from explicit current #35 inputs and persist it."""

    root = _root(workspace_root)
    exact_class_id = _identifier(class_id, "class_id")
    exact_policy_id = _identifier(policy_id, "policy_id")
    current_inputs = _current_inputs_mapping(current_inputs_by_student)
    selected_policy = _load_selected_policy(
        root,
        exact_class_id,
        exact_policy_id,
    )
    if selected_policy is None:
        return _no_selected_policy_result()
    roster_basis = _load_roster_basis(root, exact_class_id)
    return _generate_grouping_signal_derivation_from_resolved_state(
        root,
        exact_class_id,
        selected_policy,
        roster_basis,
        current_inputs,
    )

def _load_selected_policy(
    root: Path,
    class_id: str,
    policy_id: str,
) -> StoredGroupingSignalDerivationPolicy | None:
    try:
        return load_current_grouping_signal_policy(
            root,
            class_id,
            policy_id,
        )
    except GroupingSignalPolicyStorageError as error:
        raise GroupingSignalGenerationReadError(
            "Could not load the explicitly selected #37 grouping policy."
        ) from error


def _no_selected_policy_candidate() -> GroupingSignalGenerationCandidate:
    return _blocked_candidate(
        (
            GroupingSignalGenerationBlocker(
                "no_selected_policy",
                None,
                None,
            ),
        )
    )

def _no_selected_policy_result() -> GroupingSignalGenerationResult:
    return _blocked(
        (
            GroupingSignalGenerationBlocker(
                "no_selected_policy",
                None,
                None,
            ),
        )
    )

def _resolve_grouping_signal_derivation_from_resolved_state(
    root: Path,
    exact_class_id: str,
    selected_policy: StoredGroupingSignalDerivationPolicy,
    roster_basis: GroupingSignalRosterBasis,
    current_inputs: Mapping[str, AcademicPeriodProficiencyAggregationInputs],
) -> GroupingSignalGenerationCandidate:
    try:
        dependencies = validate_grouping_signal_policy_dependencies(
            root,
            selected_policy.policy,
        )
    except GroupingSignalPolicyStorageError as error:
        raise GroupingSignalGenerationReadError(
            "Selected #37 policy dependencies could not be verified."
        ) from error

    unknown_current_inputs = sorted(
        set(current_inputs) - set(roster_basis.student_ids)
    )
    if unknown_current_inputs:
        raise GroupingSignalGenerationValidationError(
            "current_inputs_by_student contains out-of-roster student IDs: "
            + ", ".join(unknown_current_inputs)
            + "."
        )

    resolved: list[GroupingSignalResolvedStudentResult] = []
    blockers: list[GroupingSignalGenerationBlocker] = []
    policy = selected_policy.policy
    period = policy.academic_basis.target_period.period

    for student_id in roster_basis.student_ids:
        try:
            stored_result = load_current_academic_period_proficiency_result(
                root,
                exact_class_id,
                period.school_year,
                period.period_id,
                student_id,
                policy.academic_basis.standard_id,
            )
        except AcademicPeriodProficiencyStorageError as error:
            raise GroupingSignalGenerationReadError(
                "Could not load one explicitly selected #35 result."
            ) from error

        if stored_result is None:
            resolved.append(GroupingSignalResolvedStudentResult(student_id, None))
            if policy.missing_result_handling == "blocking":
                blockers.append(
                    GroupingSignalGenerationBlocker(
                        "missing_result",
                        student_id,
                        None,
                    )
                )
            continue

        if not _selected_result_matches_policy(stored_result, policy):
            blockers.append(
                GroupingSignalGenerationBlocker(
                    "selected_result_mismatch",
                    student_id,
                    stored_result.reference,
                )
            )
            continue

        current_student_inputs = current_inputs.get(student_id)
        if current_student_inputs is None:
            blockers.append(
                GroupingSignalGenerationBlocker(
                    "current_basis_unavailable",
                    student_id,
                    stored_result.reference,
                )
            )
            continue

        try:
            freshness = assess_academic_period_proficiency_result_freshness(
                stored_result.snapshot,
                current_student_inputs,
                policy.academic_basis.source_policy,
                policy.academic_basis.target_scale,
                policy.academic_basis.target_period.calendar_revision,
                ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION,
            )
        except ValueError as error:
            raise GroupingSignalGenerationValidationError(
                "Current #35 freshness basis is incompatible with selected result: "
                f"{error}"
            ) from error
        if freshness.status == "stale":
            blockers.append(
                GroupingSignalGenerationBlocker(
                    "stale_result",
                    student_id,
                    stored_result.reference,
                    freshness.reasons,
                )
            )
            continue

        resolved.append(
            GroupingSignalResolvedStudentResult(
                student_id,
                stored_result.snapshot,
            )
        )
        if (
            stored_result.snapshot.outcome.status == "insufficient_evidence"
            and policy.insufficient_result_handling == "blocking"
        ):
            blockers.append(
                GroupingSignalGenerationBlocker(
                    "insufficient_evidence",
                    student_id,
                    stored_result.reference,
                )
            )

    if blockers:
        return _blocked_candidate(tuple(blockers))

    try:
        snapshot = derive_grouping_signal_snapshot(
            policy,
            selected_policy.reference,
            dependencies.target_scale.scale,
            roster_basis,
            tuple(resolved),
        )
    except GroupingSignalDerivationBlockedError as error:
        # Normally unreachable because orchestration already surfaces the policy
        # blockers; preserve structured output if the pure layer still rejects.
        derived_blockers = tuple(
            GroupingSignalGenerationBlocker(
                "missing_result" if state == "missing" else "insufficient_evidence",
                student_id,
                _reference_for_student(resolved, student_id),
            )
            for student_id, state in error.blocking_students
        )
        return _blocked_candidate(derived_blockers)
    except ValueError as error:
        raise GroupingSignalGenerationValidationError(str(error)) from error

    return GroupingSignalGenerationCandidate(
        status="generated",
        blockers=(),
        snapshot=snapshot,
    )


def _generate_grouping_signal_derivation_from_resolved_state(
    root: Path,
    exact_class_id: str,
    selected_policy: StoredGroupingSignalDerivationPolicy,
    roster_basis: GroupingSignalRosterBasis,
    current_inputs: Mapping[str, AcademicPeriodProficiencyAggregationInputs],
) -> GroupingSignalGenerationResult:
    """Resolve through the shared pure core and persist the resulting #38 state."""

    candidate = _resolve_grouping_signal_derivation_from_resolved_state(
        root,
        exact_class_id,
        selected_policy,
        roster_basis,
        current_inputs,
    )
    return _persist_grouping_signal_generation_candidate(root, candidate)


def _persist_grouping_signal_generation_candidate(
    root: Path,
    candidate: GroupingSignalGenerationCandidate,
) -> GroupingSignalGenerationResult:
    if candidate.status == "blocked":
        return _blocked(candidate.blockers)
    snapshot = candidate.snapshot
    if snapshot is None:
        raise GroupingSignalGenerationValidationError(
            "generated candidate is missing its derivation snapshot."
        )
    write_result = write_grouping_signal_derivation(root, snapshot)
    return GroupingSignalGenerationResult(
        status="generated",
        blockers=(),
        stored=write_result.stored,
        write_disposition=write_result.disposition,
    )


def _load_roster_basis(root: Path, class_id: str) -> GroupingSignalRosterBasis:
    try:
        roster = load_roster(class_roster_path(root, class_id))
    except RosterError as error:
        raise GroupingSignalGenerationReadError(
            "Could not load the exact current Core class roster."
        ) from error
    if roster.class_id != class_id:
        raise GroupingSignalGenerationReadError(
            "Core roster class_id does not match generation class scope."
        )
    return grouping_signal_roster_basis(
        class_id,
        (student.student_id for student in roster.students),
    )


def _selected_result_matches_policy(
    stored: StoredAcademicPeriodProficiencyResult,
    policy: GroupingSignalDerivationPolicy,
) -> bool:
    snapshot = stored.snapshot
    basis = policy.academic_basis
    return (
        snapshot.class_id == policy.class_id
        and snapshot.target_period == basis.target_period
        and snapshot.standard_id == basis.standard_id
        and snapshot.policy_reference == basis.source_policy
        and snapshot.target_scale == basis.target_scale
    )


def _current_inputs_mapping(
    value: Mapping[str, AcademicPeriodProficiencyAggregationInputs],
) -> dict[str, AcademicPeriodProficiencyAggregationInputs]:
    if not isinstance(value, Mapping):
        raise GroupingSignalGenerationValidationError(
            "current_inputs_by_student must be a mapping."
        )
    result: dict[str, AcademicPeriodProficiencyAggregationInputs] = {}
    for raw_student_id, inputs in value.items():
        student_id = _identifier(raw_student_id, "student_id")
        if student_id in result:
            raise GroupingSignalGenerationValidationError(
                "current_inputs_by_student must not duplicate student IDs."
            )
        if not isinstance(inputs, AcademicPeriodProficiencyAggregationInputs):
            raise GroupingSignalGenerationValidationError(
                "current_inputs_by_student values must be exact #35 aggregation inputs."
            )
        inputs.__post_init__()
        if inputs.student_id != student_id:
            raise GroupingSignalGenerationValidationError(
                "current #35 inputs student_id must match mapping key."
            )
        result[student_id] = inputs
    return result


def _reference_for_student(
    resolved: list[GroupingSignalResolvedStudentResult],
    student_id: str,
) -> AcademicPeriodProficiencyResultReference | None:
    for item in resolved:
        if item.student_id == student_id and item.result is not None:
            return academic_period_proficiency_result_reference(item.result)
    return None


def _blocked_candidate(
    blockers: tuple[GroupingSignalGenerationBlocker, ...],
) -> GroupingSignalGenerationCandidate:
    ordered = tuple(sorted(blockers, key=_blocker_sort_key))
    return GroupingSignalGenerationCandidate(
        status="blocked",
        blockers=ordered,
        snapshot=None,
    )


def _blocked(
    blockers: tuple[GroupingSignalGenerationBlocker, ...],
) -> GroupingSignalGenerationResult:
    ordered = tuple(sorted(blockers, key=_blocker_sort_key))
    return GroupingSignalGenerationResult(
        status="blocked",
        blockers=ordered,
        stored=None,
        write_disposition=None,
    )


def _blocker_sort_key(
    blocker: GroupingSignalGenerationBlocker,
) -> tuple[int, str, str]:
    return (
        0 if blocker.student_id is None else 1,
        "" if blocker.student_id is None else blocker.student_id,
        blocker.code,
    )


def _root(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise GroupingSignalGenerationValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(value)
    if not root.is_absolute():
        root = root.resolve()
    return root


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalGenerationValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GroupingSignalGenerationValidationError(str(error)) from error
