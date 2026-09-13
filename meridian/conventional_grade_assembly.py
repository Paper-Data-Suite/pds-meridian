"""Storage-aware assembly for one exact conventional Academic Period Grade.

This module is deliberately downstream from Meridian's canonical v0.2 decision
chain. It resolves exact #28 membership plus #29/#30/#31 current-use state from
caller-supplied authorized projection snapshots, then constructs the immutable
pure input consumed by :mod:`meridian.conventional_grade`.

It does not discover producer-private files, authorize evidence access, select
attempts, change reassessment state, mutate source state, persist a result, or
infer an official Grade.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routing_models import (
    ModuleWorkRef,
    RoutingModelError,
    validate_module_work_ref,
)

from meridian.attempt_selection import AttemptCandidate, AttemptObservationReference
from meridian.attempt_selection_storage import StoredAttemptSelectionDecision
from meridian.conventional_grade import (
    ConventionalGradeCalculationInput,
    ConventionalGradeCalculationOutcome,
    ConventionalGradeItemInput,
    ConventionalGradeItemState,
    ConventionalGradeProvenanceReference,
    ConventionalGradeValidationError,
    calculate_conventional_grade,
    conventional_grade_calculation_fingerprint,
    create_conventional_grade_calculation_input,
    resolve_conventional_grade_item_input,
)
from meridian.evidence import (
    EvidenceItem,
    NativePointValue,
    NativeStateValue,
)
from meridian.evidence_eligibility import (
    EvidenceSourceReference,
    evidence_source_key,
)
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityResolution,
    EvidenceEligibilityStorageError,
    resolve_current_evidence_eligibility,
)
from meridian.grade_item_membership_storage import (
    GradeItemMembershipStorageError,
    StoredGradeItemMembershipDecision,
    list_grade_item_membership_work_refs,
    load_current_grade_item_membership_decision,
)
from meridian.grade_item_storage import GradeItemStorageError, load_grade_item_revision
from meridian.grade_policy import (
    ConventionalGradeConfiguration,
    GradePolicyItemParticipation,
)
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
from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.reassessment_storage import (
    ReassessmentResolution,
    ReassessmentStorageError,
    StoredReassessmentDecision,
    resolve_current_reassessment,
)

ConventionalGradeWorkEvidenceStatus: TypeAlias = Literal[
    "available",
    "missing",
    "unavailable",
]

CONVENTIONAL_GRADE_STATE_PRECEDENCE: Final[tuple[ConventionalGradeItemState, ...]] = (
    "unresolved",
    "invalid",
    "unavailable",
    "withdrawn",
    "pending",
    "incomplete",
    "insufficient_evidence",
    "excluded",
    "excused",
    "not_applicable",
    "missing",
)

_BLOCKS_NUMERIC: Final[frozenset[ConventionalGradeItemState]] = frozenset(
    {
        "unresolved",
        "invalid",
        "unavailable",
        "withdrawn",
        "pending",
        "incomplete",
    }
)
_GENERIC_NATIVE_STATES: Final[frozenset[str]] = frozenset(
    {
        "missing",
        "pending",
        "incomplete",
        "excused",
        "excluded",
        "not_applicable",
        "insufficient_evidence",
        "unavailable",
        "withdrawn",
        "invalid",
        "unresolved",
    }
)


class ConventionalGradeAssemblyError(RuntimeError):
    """Base error while assembling exact conventional Grade inputs."""

    code = "conventional_grade.assembly_error"


class ConventionalGradeAssemblyScopeError(ConventionalGradeAssemblyError, ValueError):
    """Raised when caller-supplied calculation scope is inconsistent."""

    code = "conventional_grade.assembly_invalid"


class ConventionalGradeAssemblyDependencyError(ConventionalGradeAssemblyError):
    """Raised when canonical policy/v0.2 dependencies cannot be verified."""

    code = "conventional_grade.assembly_dependency_invalid"


@dataclass(frozen=True, slots=True)
class ConventionalGradeWorkEvidenceSpec:
    """Caller-bounded evidence observation for one exact Grade Item/work relation.

    ``available`` means the supplied authorized snapshots are the exact bounded
    projection set the caller is asking #50 to resolve for this work/student
    observation. ``missing`` means the caller established that no student-bearing
    source/projection is present. ``unavailable`` means the logical relationship
    exists but required authorized/source material cannot presently be supplied.
    """

    grade_item_id: str
    work: ModuleWorkRef
    status: ConventionalGradeWorkEvidenceStatus
    authorized_snapshots: tuple[AuthorizedProjectionSnapshot, ...] = field(
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        object.__setattr__(self, "work", _work(self.work))
        if self.status not in {"available", "missing", "unavailable"}:
            raise ConventionalGradeAssemblyScopeError(
                "work evidence status must be available, missing, or unavailable."
            )
        try:
            snapshots = tuple(self.authorized_snapshots)
        except TypeError as error:
            raise ConventionalGradeAssemblyScopeError(
                "authorized_snapshots must be an iterable."
            ) from error
        if any(
            not isinstance(value, AuthorizedProjectionSnapshot)
            for value in snapshots
        ):
            raise ConventionalGradeAssemblyScopeError(
                "authorized_snapshots must contain only "
                "AuthorizedProjectionSnapshot values."
            )
        typed = snapshots
        if self.status == "available" and not typed:
            raise ConventionalGradeAssemblyScopeError(
                "available work evidence requires at least one authorized snapshot."
            )
        if self.status != "available" and typed:
            raise ConventionalGradeAssemblyScopeError(
                "missing/unavailable work evidence must not carry snapshots."
            )
        identities: set[tuple[str, str, str]] = set()
        for snapshot in typed:
            if _snapshot_work(snapshot) != self.work:
                raise ConventionalGradeAssemblyScopeError(
                    "authorized snapshot work must match the work evidence spec."
                )
            identity = _snapshot_identity(snapshot)
            if identity in identities:
                raise ConventionalGradeAssemblyScopeError(
                    "work evidence must not duplicate an exact authorized snapshot."
                )
            identities.add(identity)
        object.__setattr__(
            self,
            "authorized_snapshots",
            tuple(sorted(typed, key=_snapshot_identity)),
        )


@dataclass(frozen=True, slots=True)
class ConventionalGradeAssembly:
    """Exact verified authority, pure calculation basis, and advisory outcome."""

    activation: StoredGradePolicyActivationDecision
    policy: StoredGradePolicyRevision
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] = field(repr=False)
    inputs: ConventionalGradeCalculationInput
    outcome: ConventionalGradeCalculationOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.activation, StoredGradePolicyActivationDecision):
            raise ConventionalGradeAssemblyScopeError(
                "activation must be StoredGradePolicyActivationDecision."
            )
        if not isinstance(self.policy, StoredGradePolicyRevision):
            raise ConventionalGradeAssemblyScopeError(
                "policy must be StoredGradePolicyRevision."
            )
        if not isinstance(self.inputs, ConventionalGradeCalculationInput):
            raise ConventionalGradeAssemblyScopeError(
                "inputs must be ConventionalGradeCalculationInput."
            )
        if not isinstance(self.outcome, ConventionalGradeCalculationOutcome):
            raise ConventionalGradeAssemblyScopeError(
                "outcome must be ConventionalGradeCalculationOutcome."
            )
        if self.outcome.calculation_fingerprint != self.inputs_fingerprint:
            raise ConventionalGradeAssemblyScopeError(
                "outcome fingerprint must match the exact assembled input basis."
            )

    @property
    def inputs_fingerprint(self) -> str:
        """Return the deterministic fingerprint of the exact assembled basis."""

        return conventional_grade_calculation_fingerprint(self.inputs)


@dataclass(frozen=True, slots=True)
class _StateSignal:
    state: ConventionalGradeItemState
    reason_code: str
    provenance: tuple[ConventionalGradeProvenanceReference, ...]
    blocks_numeric: bool


@dataclass(frozen=True, slots=True)
class _PointObservation:
    value: NativePointValue
    provenance: tuple[ConventionalGradeProvenanceReference, ...]


@dataclass(frozen=True, slots=True)
class _SnapshotResolution:
    snapshot: AuthorizedProjectionSnapshot = field(repr=False)
    reassessment: ReassessmentResolution
    allowed_sources: frozenset[EvidenceSourceReference]
    provenance: tuple[ConventionalGradeProvenanceReference, ...]


def assemble_conventional_grade_calculation(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...],
) -> ConventionalGradeAssembly:
    """Assemble and calculate from exact selected #49/#28/#29/#30/#31 state.

    The function is read-only. Caller-provided authorized snapshots are the sole
    producer-evidence surface opened by this layer.
    """

    root = Path(workspace_root)
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    specs = _validate_work_evidence(work_evidence, class_value)

    try:
        activation_resolution = resolve_grade_policy_activation(
            root,
            class_value,
            period,
        )
    except GradePolicyActivationStorageError as error:
        raise ConventionalGradeAssemblyDependencyError(
            f"Exact Grade-policy activation could not be resolved: {error}"
        ) from error
    if (
        activation_resolution.status != "activated"
        or activation_resolution.activation is None
        or activation_resolution.policy_reference is None
    ):
        raise ConventionalGradeAssemblyDependencyError(
            "Conventional calculation requires an explicitly activated Grade policy."
        )
    activation = activation_resolution.activation
    if activation.decision.calendar_revision != calendar:
        raise ConventionalGradeAssemblyScopeError(
            "Requested calendar_revision does not match the exact selected activation."
        )

    policy_ref = activation_resolution.policy_reference
    try:
        stored_policy = load_grade_policy_revision(
            root,
            policy_ref.class_id,
            policy_ref.policy_id,
            policy_ref.policy_revision,
        )
    except GradePolicyStorageError as error:
        raise ConventionalGradeAssemblyDependencyError(
            f"Exact activated Grade-policy revision could not be loaded: {error}"
        ) from error
    if stored_policy.policy_sha256 != policy_ref.policy_sha256:
        raise ConventionalGradeAssemblyDependencyError(
            "Activated Grade-policy SHA-256 does not match the stored revision."
        )
    policy = stored_policy.policy
    if policy.calculation_family != "conventional" or not isinstance(
        policy.configuration,
        ConventionalGradeConfiguration,
    ):
        raise ConventionalGradeAssemblyDependencyError(
            "Activated Grade policy is not a conventional Grade policy."
        )

    policy_grade_item_ids = {
        participation.grade_item.grade_item_id
        for participation in policy.configuration.items
    }
    extras = tuple(
        spec
        for spec in specs
        if spec.grade_item_id not in policy_grade_item_ids
    )
    if extras:
        raise ConventionalGradeAssemblyScopeError(
            "work_evidence contains a Grade Item that does not participate in the "
            "activated policy."
        )

    by_grade_item: dict[str, tuple[ConventionalGradeWorkEvidenceSpec, ...]] = {}
    for grade_item_id in policy_grade_item_ids:
        by_grade_item[grade_item_id] = tuple(
            spec for spec in specs if spec.grade_item_id == grade_item_id
        )

    assembled_items: list[ConventionalGradeItemInput] = []
    for participation in policy.configuration.items:
        _verify_policy_grade_item(root, participation)
        assembled_items.append(
            _assemble_policy_item(
                root=root,
                class_id=class_value,
                student_id=student,
                target_period=period,
                calendar_revision=calendar,
                participation=participation,
                work_evidence=by_grade_item[participation.grade_item.grade_item_id],
            )
        )

    try:
        inputs = create_conventional_grade_calculation_input(
            policy=policy,
            activation=activation.decision,
            student_id=student,
            target_period=period,
            calendar_revision=calendar,
            items=tuple(assembled_items),
        )
        outcome = calculate_conventional_grade(inputs)
    except ConventionalGradeValidationError as error:
        raise ConventionalGradeAssemblyDependencyError(
            f"Assembled conventional calculation basis is invalid: {error}"
        ) from error

    return ConventionalGradeAssembly(
        activation=activation,
        policy=stored_policy,
        work_evidence=specs,
        inputs=inputs,
        outcome=outcome,
    )


def _assemble_policy_item(
    *,
    root: Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    participation: GradePolicyItemParticipation,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...],
) -> ConventionalGradeItemInput:
    grade_item_id = participation.grade_item.grade_item_id
    try:
        work_refs = list_grade_item_membership_work_refs(
            root,
            class_id,
            grade_item_id,
        )
    except GradeItemMembershipStorageError as error:
        raise ConventionalGradeAssemblyDependencyError(
            f"Grade Item {grade_item_id!r} membership collection could not be "
            f"verified: {error}"
        ) from error

    period_memberships: list[StoredGradeItemMembershipDecision] = []
    matching_memberships: list[StoredGradeItemMembershipDecision] = []
    membership_provenance: list[ConventionalGradeProvenanceReference] = []
    membership_reasons: list[str] = []
    membership_blockers: list[_StateSignal] = []

    for work in work_refs:
        try:
            stored = load_current_grade_item_membership_decision(
                root,
                class_id,
                grade_item_id,
                work,
            )
        except GradeItemMembershipStorageError as error:
            raise ConventionalGradeAssemblyDependencyError(
                f"Current Grade Item membership could not be loaded: {error}"
            ) from error
        if stored is None:
            membership_reasons.append("membership_unselected")
            continue
        membership_reference = _membership_provenance(stored)
        membership_provenance.append(membership_reference)
        decision = stored.decision
        if decision.decision != "included":
            membership_reasons.append("membership_excluded")
            continue
        assignment = decision.academic_period
        if assignment is None:  # model validation forbids this; fail closed
            membership_blockers.append(
                _StateSignal(
                    state="invalid",
                    reason_code="membership_assignment_missing",
                    provenance=(membership_reference,),
                    blocks_numeric=True,
                )
            )
            continue
        if assignment.period != target_period:
            membership_reasons.append("membership_period_mismatch")
            continue
        if assignment.calendar_revision != calendar_revision:
            membership_reasons.append("membership_calendar_mismatch")
            continue
        period_memberships.append(stored)
        if (
            decision.grade_item_revision
            != participation.grade_item.grade_item_revision
            or decision.grade_item_revision_sha256
            != participation.grade_item.grade_item_revision_sha256
        ):
            membership_blockers.append(
                _StateSignal(
                    state="unresolved",
                    reason_code="membership_grade_item_basis_mismatch",
                    provenance=(membership_reference,),
                    blocks_numeric=True,
                )
            )
            continue
        matching_memberships.append(stored)

    scoped_work_keys = {
        _work_key(stored.decision.work_reference.work) for stored in period_memberships
    }
    for spec in work_evidence:
        if _work_key(spec.work) not in scoped_work_keys:
            raise ConventionalGradeAssemblyScopeError(
                f"work_evidence for Grade Item {grade_item_id!r} is not assigned "
                "to the exact target period/calendar revision."
            )

    if not period_memberships:
        if work_evidence:
            raise ConventionalGradeAssemblyScopeError(
                f"Grade Item {grade_item_id!r} has no exact target-period membership."
            )
        reasons = tuple(membership_reasons) or ("no_exact_period_membership",)
        return _no_points(
            participation=participation,
            student_id=student_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
            state="not_applicable",
            reasons=reasons,
            provenance=tuple(membership_provenance),
        )

    signals = list(membership_blockers)
    points: list[_PointObservation] = []
    all_provenance = list(membership_provenance)
    matched_spec_keys: set[tuple[str, str]] = set()

    for stored_membership in matching_memberships:
        work = stored_membership.decision.work_reference.work
        work_key = _work_key(work)
        work_spec = next(
            (
                candidate
                for candidate in work_evidence
                if _work_key(candidate.work) == work_key
            ),
            None,
        )
        if work_spec is None:
            signals.append(
                _StateSignal(
                    state="unavailable",
                    reason_code="work_evidence_not_supplied",
                    provenance=(_membership_provenance(stored_membership),),
                    blocks_numeric=True,
                )
            )
            continue
        matched_spec_keys.add(work_key)
        if work_spec.status == "missing":
            signals.append(
                _StateSignal(
                    state="missing",
                    reason_code="work_has_no_student_evidence",
                    provenance=(_membership_provenance(stored_membership),),
                    blocks_numeric=False,
                )
            )
            continue
        if work_spec.status == "unavailable":
            signals.append(
                _StateSignal(
                    state="unavailable",
                    reason_code="authorized_projection_unavailable",
                    provenance=(_membership_provenance(stored_membership),),
                    blocks_numeric=True,
                )
            )
            continue

        work_points, work_signals, work_provenance = _assemble_available_work(
            root=root,
            class_id=class_id,
            grade_item_id=grade_item_id,
            student_id=student_id,
            work=work,
            membership=stored_membership,
            snapshots=work_spec.authorized_snapshots,
        )
        points.extend(work_points)
        signals.extend(work_signals)
        all_provenance.extend(work_provenance)

    unmatched_specs = tuple(
        spec for spec in work_evidence if _work_key(spec.work) not in matched_spec_keys
    )
    if unmatched_specs and not membership_blockers:
        raise ConventionalGradeAssemblyScopeError(
            f"work_evidence for Grade Item {grade_item_id!r} does not match an "
            "exact policy-compatible membership."
        )

    blocking_signals = tuple(signal for signal in signals if signal.blocks_numeric)
    item_provenance = _merge_provenance(
        tuple(all_provenance),
        tuple(reference for point in points for reference in point.provenance),
        tuple(
            reference
            for signal in signals
            for reference in signal.provenance
        ),
    )

    if len(points) > 1:
        return resolve_conventional_grade_item_input(
            participation=participation,
            student_id=student_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
            point_observations=tuple(point.value for point in points),
            no_point_state="missing",
            reason_codes=tuple(signal.reason_code for signal in blocking_signals),
            provenance=item_provenance,
        )
    if len(points) == 1 and not blocking_signals:
        return resolve_conventional_grade_item_input(
            participation=participation,
            student_id=student_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
            point_observations=(points[0].value,),
            no_point_state="missing",
            reason_codes=(),
            provenance=item_provenance,
        )

    selected_state = _strongest_state(signals, default="missing")
    reasons = tuple(
        signal.reason_code for signal in signals if signal.state == selected_state
    )
    if not reasons:
        reasons = ("no_grade_bearing_point_observation",)
    return _no_points(
        participation=participation,
        student_id=student_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        state=selected_state,
        reasons=reasons,
        provenance=item_provenance,
    )


def _assemble_available_work(
    *,
    root: Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    work: ModuleWorkRef,
    membership: StoredGradeItemMembershipDecision,
    snapshots: tuple[AuthorizedProjectionSnapshot, ...],
) -> tuple[
    tuple[_PointObservation, ...],
    tuple[_StateSignal, ...],
    tuple[ConventionalGradeProvenanceReference, ...],
]:
    membership_ref = _membership_provenance(membership)
    source_items: dict[EvidenceSourceReference, EvidenceItem] = {}
    source_provenance: dict[
        EvidenceSourceReference,
        tuple[ConventionalGradeProvenanceReference, ...],
    ] = {}
    eligibility: dict[EvidenceSourceReference, EvidenceEligibilityResolution] = {}
    signals: list[_StateSignal] = []
    nonstudent_seen = False

    for snapshot in snapshots:
        inventory = snapshot.stored.snapshot.inventory
        if any(item.subject is None for item in inventory.items):
            nonstudent_seen = True
        for item in inventory.for_student(student_id):
            source = _evidence_source(snapshot, item)
            if source in source_items:
                raise ConventionalGradeAssemblyDependencyError(
                    "Exact authorized evidence source appeared more than once."
                )
            source_items[source] = item
            source_ref = _source_provenance(source)
            try:
                resolution = resolve_current_evidence_eligibility(
                    root,
                    class_id,
                    grade_item_id,
                    source,
                    authorized_snapshot=snapshot,
                )
            except EvidenceEligibilityStorageError as error:
                raise ConventionalGradeAssemblyDependencyError(
                    f"Canonical evidence eligibility could not be resolved: {error}"
                ) from error
            eligibility[source] = resolution
            source_refs = [membership_ref, source_ref]
            if resolution.selected is not None:
                source_refs.append(_eligibility_provenance(source, resolution))
            source_provenance[source] = _merge_provenance(tuple(source_refs))
            signal = _eligibility_signal(item, resolution, source_provenance[source])
            if signal is not None:
                signals.append(signal)

    snapshot_resolutions = tuple(
        _resolve_snapshot_reassessment(
            root=root,
            class_id=class_id,
            grade_item_id=grade_item_id,
            work=work,
            student_id=student_id,
            snapshot=snapshot,
        )
        for snapshot in snapshots
    )
    attempt_allowed, attempt_signal, decision_provenance = _resolve_work_attempt_scope(
        snapshot_resolutions
    )
    if attempt_signal is not None:
        signals.append(attempt_signal)

    operative_sources = {
        source
        for source, resolution in eligibility.items()
        if resolution.operative_included
    }
    allowed_sources = operative_sources
    if attempt_allowed is not None:
        allowed_sources = operative_sources.intersection(attempt_allowed)

    points: list[_PointObservation] = []
    fallback_signals: list[_StateSignal] = []
    for source in sorted(allowed_sources, key=_source_sort_key):
        item = source_items[source]
        point_provenance = _merge_provenance(
            source_provenance[source],
            decision_provenance,
        )
        if isinstance(item.value, NativePointValue):
            points.append(_PointObservation(item.value, point_provenance))
        else:
            fallback_signals.append(
                _nonpoint_value_signal(item, point_provenance)
            )

    if not source_items:
        state = "insufficient_evidence" if nonstudent_seen else "missing"
        reason = (
            "nonstudent_evidence_not_individualized"
            if nonstudent_seen
            else "no_student_evidence"
        )
        fallback_signals.append(
            _StateSignal(
                state=cast(ConventionalGradeItemState, state),
                reason_code=reason,
                provenance=(membership_ref,),
                blocks_numeric=False,
            )
        )

    # Non-point evidence must never eclipse a valid point observation merely
    # because the producer also projects response/rubric/correctness detail.
    # It remains classification evidence only when no point observation survives.
    if not points:
        signals.extend(fallback_signals)

    return (
        tuple(points),
        tuple(signals),
        _merge_provenance(
            (membership_ref,),
            tuple(
                reference
                for refs in source_provenance.values()
                for reference in refs
            ),
            decision_provenance,
        ),
    )


def _resolve_snapshot_reassessment(
    *,
    root: Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    snapshot: AuthorizedProjectionSnapshot,
) -> _SnapshotResolution:
    try:
        resolution = resolve_current_reassessment(
            root,
            class_id,
            grade_item_id,
            work,
            student_id,
            authorized_snapshot=snapshot,
        )
    except ReassessmentStorageError as error:
        raise ConventionalGradeAssemblyDependencyError(
            f"Canonical attempt/reassessment state could not be resolved: {error}"
        ) from error

    allowed: set[EvidenceSourceReference] = set()
    provenance: list[ConventionalGradeProvenanceReference] = []
    upstream = resolution.attempt_selection
    if upstream.selected is not None:
        provenance.append(_attempt_selection_provenance(upstream.selected))
    if resolution.selected is not None:
        provenance.append(_reassessment_provenance(resolution.selected))

    if resolution.status in {"single_selected", "resolved"}:
        candidate_by_attempt: dict[AttemptObservationReference, AttemptCandidate] = {
            candidate.attempt: candidate for candidate in upstream.current_candidates
        }
        for attempt in resolution.contributing_attempts:
            candidate = candidate_by_attempt.get(attempt)
            if candidate is None:
                raise ConventionalGradeAssemblyDependencyError(
                    "Reassessment contributor is absent from current #30 candidates."
                )
            allowed.update(basis.source for basis in candidate.eligible_evidence)

    return _SnapshotResolution(
        snapshot=snapshot,
        reassessment=resolution,
        allowed_sources=frozenset(allowed),
        provenance=_merge_provenance(tuple(provenance)),
    )


def _resolve_work_attempt_scope(
    resolutions: tuple[_SnapshotResolution, ...],
) -> tuple[
    frozenset[EvidenceSourceReference] | None,
    _StateSignal | None,
    tuple[ConventionalGradeProvenanceReference, ...],
]:
    operative = tuple(
        value
        for value in resolutions
        if value.reassessment.status in {"single_selected", "resolved"}
        and value.reassessment.operative_reassessment
    )
    if len(operative) > 1:
        provenance = _merge_provenance(
            *(value.provenance for value in operative)
        )
        return (
            frozenset(),
            _StateSignal(
                state="unresolved",
                reason_code="multiple_operative_reassessment_snapshots",
                provenance=provenance,
                blocks_numeric=True,
            ),
            provenance,
        )
    if len(operative) == 1:
        value = operative[0]
        return value.allowed_sources, None, value.provenance

    if resolutions and all(
        value.reassessment.status == "not_applicable" for value in resolutions
    ):
        return None, None, ()

    selected_none = tuple(
        value for value in resolutions if value.reassessment.status == "selected_none"
    )
    if selected_none and all(
        value.reassessment.status in {"selected_none", "not_applicable"}
        for value in resolutions
    ):
        provenance = _merge_provenance(
            *(value.provenance for value in selected_none)
        )
        return (
            frozenset(),
            _StateSignal(
                state="insufficient_evidence",
                reason_code="attempt_selection_selected_none",
                provenance=provenance,
                blocks_numeric=False,
            ),
            provenance,
        )

    problematic = tuple(
        value for value in resolutions if value.reassessment.status != "not_applicable"
    )
    provenance = _merge_provenance(*(value.provenance for value in problematic))
    reason = "reassessment_unresolved"
    if problematic:
        reason = f"reassessment_{problematic[0].reassessment.status}"
    return (
        frozenset(),
        _StateSignal(
            state="unresolved",
            reason_code=reason,
            provenance=provenance,
            blocks_numeric=True,
        ),
        provenance,
    )


def _eligibility_signal(
    item: EvidenceItem,
    resolution: EvidenceEligibilityResolution,
    provenance: tuple[ConventionalGradeProvenanceReference, ...],
) -> _StateSignal | None:
    if resolution.operative_included:
        return None
    status = resolution.status
    if status == "no_decision":
        state: ConventionalGradeItemState = "pending"
        reason = "eligibility_no_decision"
    elif status == "pending":
        state = "pending"
        reason = "eligibility_pending"
    elif status in {"excluded", "superseded"}:
        state = "excluded"
        reason = f"eligibility_{status}"
    elif status in {"withdrawn", "included_source_withdrawn"}:
        state = "withdrawn"
        reason = "eligibility_withdrawn"
    elif status == "unsupported":
        state = "insufficient_evidence"
        reason = "eligibility_unsupported"
    elif status == "source_unverifiable":
        state = "unavailable"
        reason = "eligibility_source_unverifiable"
    elif status == "membership_stale":
        state = "unresolved"
        reason = "eligibility_membership_stale"
    else:
        state = "unresolved"
        reason = "eligibility_unresolved"
    return _StateSignal(
        state=state,
        reason_code=reason,
        provenance=provenance,
        blocks_numeric=(
            isinstance(item.value, NativePointValue) and state in _BLOCKS_NUMERIC
        ),
    )


def _nonpoint_value_signal(
    item: EvidenceItem,
    provenance: tuple[ConventionalGradeProvenanceReference, ...],
) -> _StateSignal:
    if (
        isinstance(item.value, NativeStateValue)
        and item.value.code in _GENERIC_NATIVE_STATES
    ):
        state = cast(ConventionalGradeItemState, item.value.code)
        return _StateSignal(
            state=state,
            reason_code=f"native_state_{item.value.code}",
            provenance=provenance,
            blocks_numeric=False,
        )
    return _StateSignal(
        state="insufficient_evidence",
        reason_code=(
            "native_state_not_points"
            if isinstance(item.value, NativeStateValue)
            else "native_value_not_points"
        ),
        provenance=provenance,
        blocks_numeric=False,
    )


def _strongest_state(
    signals: list[_StateSignal] | tuple[_StateSignal, ...],
    *,
    default: ConventionalGradeItemState,
) -> ConventionalGradeItemState:
    present = {signal.state for signal in signals}
    for state in CONVENTIONAL_GRADE_STATE_PRECEDENCE:
        if state in present:
            return state
    return default


def _no_points(
    *,
    participation: GradePolicyItemParticipation,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    state: ConventionalGradeItemState,
    reasons: tuple[str, ...],
    provenance: tuple[ConventionalGradeProvenanceReference, ...],
) -> ConventionalGradeItemInput:
    try:
        return resolve_conventional_grade_item_input(
            participation=participation,
            student_id=student_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
            point_observations=(),
            no_point_state=state,
            reason_codes=tuple(sorted(set(reasons))),
            provenance=_merge_provenance(provenance),
        )
    except ConventionalGradeValidationError as error:
        raise ConventionalGradeAssemblyDependencyError(str(error)) from error


def _verify_policy_grade_item(
    root: Path,
    participation: GradePolicyItemParticipation,
) -> None:
    ref = participation.grade_item
    try:
        stored = load_grade_item_revision(
            root,
            ref.class_id,
            ref.grade_item_id,
            ref.grade_item_revision,
        )
    except GradeItemStorageError as error:
        raise ConventionalGradeAssemblyDependencyError(
            f"Exact Grade Item revision could not be loaded: {error}"
        ) from error
    if stored.revision_sha256 != ref.grade_item_revision_sha256:
        raise ConventionalGradeAssemblyDependencyError(
            f"Grade Item {ref.grade_item_id!r} SHA-256 does not match policy "
            "participation."
        )


def _validate_work_evidence(
    value: object,
    class_id: str,
) -> tuple[ConventionalGradeWorkEvidenceSpec, ...]:
    if isinstance(value, (str, bytes)):
        raise ConventionalGradeAssemblyScopeError(
            "work_evidence must be an iterable."
        )
    try:
        specs = tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise ConventionalGradeAssemblyScopeError(
            "work_evidence must be an iterable."
        ) from error
    if any(not isinstance(spec, ConventionalGradeWorkEvidenceSpec) for spec in specs):
        raise ConventionalGradeAssemblyScopeError(
            "work_evidence must contain ConventionalGradeWorkEvidenceSpec values."
        )
    typed = tuple(cast(ConventionalGradeWorkEvidenceSpec, spec) for spec in specs)
    seen: set[tuple[str, str, str]] = set()
    for spec in typed:
        if spec.work.class_id != class_id:
            raise ConventionalGradeAssemblyScopeError(
                "work evidence class must match calculation class_id."
            )
        key = (spec.grade_item_id, spec.work.module_id, spec.work.work_id)
        if key in seen:
            raise ConventionalGradeAssemblyScopeError(
                "work_evidence must not duplicate a Grade Item/work relation."
            )
        seen.add(key)
    return tuple(
        sorted(
            typed,
            key=lambda spec: (
                spec.grade_item_id,
                spec.work.module_id,
                spec.work.work_id,
            ),
        )
    )


def _evidence_source(
    snapshot: AuthorizedProjectionSnapshot,
    item: EvidenceItem,
) -> EvidenceSourceReference:
    stored = snapshot.stored
    publication = stored.snapshot.source.publication
    if item.provenance.work != publication.work:
        raise ConventionalGradeAssemblyDependencyError(
            "Projected EvidenceItem work does not match its authorized snapshot."
        )
    if item.provenance.publication_id != publication.publication_id:
        raise ConventionalGradeAssemblyDependencyError(
            "Projected EvidenceItem publication does not match authorized snapshot."
        )
    return EvidenceSourceReference(
        work=publication.work,
        publication_id=publication.publication_id,
        cache_key=stored.cache_key,
        snapshot_digest=stored.snapshot_digest,
        item_id=item.item_id,
    )


def _membership_provenance(
    stored: StoredGradeItemMembershipDecision,
) -> ConventionalGradeProvenanceReference:
    decision = stored.decision
    work = decision.work_reference.work
    key = (
        f"{decision.grade_item_id}:{work.module_id}:{work.work_id}:"
        f"membership:{decision.membership_revision}"
    )
    return ConventionalGradeProvenanceReference(
        kind="membership",
        reference_key=key,
        reference_sha256=stored.decision_sha256,
    )


def _source_provenance(
    source: EvidenceSourceReference,
) -> ConventionalGradeProvenanceReference:
    return ConventionalGradeProvenanceReference(
        kind="source",
        reference_key=(
            f"{source.publication_id}:{source.cache_key}:{source.item_id}"
        ),
        reference_sha256=source.snapshot_digest,
    )


def _eligibility_provenance(
    source: EvidenceSourceReference,
    resolution: EvidenceEligibilityResolution,
) -> ConventionalGradeProvenanceReference:
    selected = resolution.selected
    if selected is None:
        raise ConventionalGradeAssemblyDependencyError(
            "eligibility provenance requires a selected decision."
        )
    return ConventionalGradeProvenanceReference(
        kind="eligibility",
        reference_key=(
            f"{evidence_source_key(source)}:eligibility:"
            f"{selected.decision.eligibility_revision}"
        ),
        reference_sha256=selected.decision_sha256,
    )


def _attempt_selection_provenance(
    stored: StoredAttemptSelectionDecision,
) -> ConventionalGradeProvenanceReference:
    decision = stored.decision
    work = decision.work
    return ConventionalGradeProvenanceReference(
        kind="attempt_selection",
        reference_key=(
            f"{decision.class_id}:{decision.grade_item_id}:{work.module_id}:"
            f"{work.work_id}:{decision.student_id}:attempt_selection:"
            f"{decision.decision_revision}"
        ),
        reference_sha256=stored.decision_sha256,
    )


def _reassessment_provenance(
    stored: StoredReassessmentDecision,
) -> ConventionalGradeProvenanceReference:
    decision = stored.decision
    work = decision.work
    return ConventionalGradeProvenanceReference(
        kind="reassessment",
        reference_key=(
            f"{decision.class_id}:{decision.grade_item_id}:{work.module_id}:"
            f"{work.work_id}:{decision.student_id}:reassessment:"
            f"{decision.decision_revision}"
        ),
        reference_sha256=stored.decision_sha256,
    )


def _merge_provenance(
    *groups: tuple[ConventionalGradeProvenanceReference, ...],
) -> tuple[ConventionalGradeProvenanceReference, ...]:
    by_key: dict[
        tuple[str, str, str],
        ConventionalGradeProvenanceReference,
    ] = {}
    for group in groups:
        for reference in group:
            key = (
                reference.kind,
                reference.reference_key,
                reference.reference_sha256,
            )
            by_key[key] = reference
    return tuple(by_key[key] for key in sorted(by_key))


def _snapshot_work(snapshot: AuthorizedProjectionSnapshot) -> ModuleWorkRef:
    return snapshot.stored.snapshot.source.publication.work


def _snapshot_identity(snapshot: AuthorizedProjectionSnapshot) -> tuple[str, str, str]:
    stored = snapshot.stored
    return (
        stored.snapshot.source.publication.publication_id,
        stored.cache_key,
        stored.snapshot_digest,
    )


def _work_key(work: ModuleWorkRef) -> tuple[str, str]:
    return work.module_id, work.work_id


def _source_sort_key(source: EvidenceSourceReference) -> tuple[str, str, str, str]:
    return (
        source.publication_id,
        source.cache_key,
        source.snapshot_digest,
        source.item_id,
    )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConventionalGradeAssemblyScopeError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ConventionalGradeAssemblyScopeError(str(error)) from error


def _work(value: object) -> ModuleWorkRef:
    if not isinstance(value, ModuleWorkRef):
        raise ConventionalGradeAssemblyScopeError("work must be ModuleWorkRef.")
    try:
        return validate_module_work_ref(value)
    except RoutingModelError as error:
        raise ConventionalGradeAssemblyScopeError(str(error)) from error


def _period(value: object) -> AcademicPeriodRef:
    if not isinstance(value, AcademicPeriodRef):
        raise ConventionalGradeAssemblyScopeError(
            "target_period must be AcademicPeriodRef."
        )
    try:
        return validate_academic_period_ref(value)
    except AcademicPeriodValidationError as error:
        raise ConventionalGradeAssemblyScopeError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConventionalGradeAssemblyScopeError(
            f"{field_name} must be a positive integer."
        )
    return value
