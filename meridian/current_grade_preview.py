"""Coherent read-only current Grade-preview resolution for Meridian v0.3.

Issue #54 composes the existing selected Grade result, family-specific freshness,
teacher override precedence, and explanation projections without recalculating or
persisting academic state.  The service uses optimistic revalidation rather than a
global workspace lock: one exact current-state witness is captured before and
after explanation construction, and any material selector/basis change fails with
a deterministic currentness-conflict error.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias, cast

from meridian.conventional_grade import (
    ConventionalGradeResultReference,
    ConventionalGradeResultSnapshot,
    assess_conventional_grade_result_freshness,
    conventional_grade_calculation_input_sha256,
)
from meridian.conventional_grade_assembly import (
    ConventionalGradeAssemblyError,
    ConventionalGradeWorkEvidenceSpec,
    assemble_conventional_grade_calculation,
)
from meridian.conventional_grade_explanation import (
    ConventionalGradePreviewExplanation,
    explain_conventional_grade_preview,
)
from meridian.conventional_grade_storage import (
    ConventionalGradeStorageError,
    load_current_conventional_grade_result,
)
from meridian.effective_grade import (
    EffectiveGradeError,
    EffectiveGradeResolution,
    resolve_effective_grade,
)
from meridian.grade_policy import (
    GradeCalculationFamily,
    GradePolicyReference,
    GradePolicyRevision,
)
from meridian.grade_policy_activation import (
    GradePolicyActivationDecision,
    GradePolicyActivationReference,
)
from meridian.grade_policy_activation_storage import (
    GradePolicyActivationStorageError,
    load_current_grade_policy_activation,
    load_grade_policy_activation_revision,
)
from meridian.grade_policy_storage import (
    GradePolicyStorageError,
    load_grade_policy_revision,
)
from meridian.grade_preview_explanation import (
    GradePreviewCurrentnessConflictError,
    GradePreviewIntegrityError,
    GradePreviewSourceError,
    GradePreviewTarget,
    GradePreviewTargetError,
    GradePreviewTargetNotFoundError,
)
from meridian.hybrid_grade import hybrid_grade_calculation_input_sha256
from meridian.hybrid_grade_assembly import (
    HybridGradeAssemblyError,
    assemble_hybrid_grade_calculation,
)
from meridian.hybrid_grade_explanation import (
    HybridGradePreviewExplanation,
    explain_hybrid_grade_preview,
)
from meridian.hybrid_grade_result import (
    HybridGradeResultReference,
    HybridGradeResultSnapshot,
    assess_hybrid_grade_result_freshness,
)
from meridian.hybrid_grade_storage import (
    HybridGradeStorageError,
    load_current_hybrid_grade_result,
)
from meridian.standards_grade import standards_grade_calculation_input_sha256
from meridian.standards_grade_assembly import (
    StandardsGradeAssemblyError,
    assemble_standards_grade_calculation,
)
from meridian.standards_grade_explanation import (
    StandardsGradePreviewExplanation,
    explain_standards_grade_preview,
)
from meridian.standards_grade_result import (
    StandardsGradeResultReference,
    StandardsGradeResultSnapshot,
    assess_standards_grade_result_freshness,
)
from meridian.standards_grade_storage import (
    StandardsGradeStorageError,
    load_current_standards_grade_result,
)
from meridian.teacher_grade_override import (
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideReference,
)
from meridian.teacher_grade_override_storage import (
    TeacherGradeOverrideStorageError,
    get_current_teacher_grade_override_reference,
    load_current_teacher_grade_override,
)
from meridian.teacher_grade_override_workflow import (
    TeacherGradeOverrideSelectedSource,
    TeacherGradeOverrideSourceIntegrityError,
    TeacherGradeOverrideSourceResult,
    TeacherGradeOverrideWorkflowError,
    load_teacher_grade_override_source_result,
)

CurrentGradePreviewExplanation: TypeAlias = (
    ConventionalGradePreviewExplanation
    | StandardsGradePreviewExplanation
    | HybridGradePreviewExplanation
)
GradeResultSnapshot: TypeAlias = (
    ConventionalGradeResultSnapshot
    | StandardsGradeResultSnapshot
    | HybridGradeResultSnapshot
)


@dataclass(frozen=True, slots=True)
class _CurrentGradePreviewWitness:
    """Exact optimistic-read token for every material current Grade basis."""

    source_result: GradeOverrideSourceResultReference
    current_basis_sha256: str
    current_activation_reference: GradePolicyActivationReference
    current_policy_reference: GradePolicyReference
    selected_override_reference: TeacherGradeOverrideReference | None
    effective: EffectiveGradeResolution


@dataclass(frozen=True, slots=True)
class _CurrentGradePreviewState:
    snapshot: GradeResultSnapshot
    witness: _CurrentGradePreviewWitness


@dataclass(frozen=True, slots=True)
class _SourceAuthority:
    policy: GradePolicyRevision
    activation: GradePolicyActivationDecision


def explain_current_grade_preview(
    workspace_root: str | Path,
    target: GradePreviewTarget,
    *,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None = None,
) -> CurrentGradePreviewExplanation:
    """Explain one exact current selected Grade with optimistic revalidation.

    Conventional and hybrid previews require an explicit ``work_evidence`` tuple,
    including the empty tuple when no producer work is needed. Standards previews
    do not accept a conventional work-evidence argument.
    """

    if not isinstance(target, GradePreviewTarget):
        raise GradePreviewTargetError("target must be a GradePreviewTarget.")
    _validate_work_evidence(target.calculation_family, work_evidence)
    root = Path(workspace_root)

    initial = _capture_current_state(root, target, work_evidence=work_evidence)
    authority = _load_source_authority(root, target, initial.snapshot)
    explanation = _build_family_explanation(
        root,
        initial.snapshot,
        authority,
        initial.witness.effective,
    )

    try:
        final = _capture_current_state(root, target, work_evidence=work_evidence)
    except GradePreviewSourceError as error:
        raise GradePreviewCurrentnessConflictError(
            "Current Grade preview basis changed during explanation resolution."
        ) from error
    if final.witness != initial.witness:
        raise GradePreviewCurrentnessConflictError(
            "Current Grade preview basis changed during explanation resolution."
        )
    return explanation


def _validate_work_evidence(
    family: GradeCalculationFamily,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None,
) -> None:
    if family in {"conventional", "hybrid"}:
        if work_evidence is None:
            raise GradePreviewTargetError(
                f"{family} current preview requires explicit work_evidence."
            )
        return
    if work_evidence is not None:
        raise GradePreviewTargetError(
            "standards-based current preview does not accept work_evidence."
        )


def _capture_current_state(
    root: Path,
    target: GradePreviewTarget,
    *,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None,
) -> _CurrentGradePreviewState:
    if target.calculation_family == "conventional":
        return _capture_conventional_state(
            root,
            target,
            cast(tuple[ConventionalGradeWorkEvidenceSpec, ...], work_evidence),
        )
    if target.calculation_family == "standards_based":
        return _capture_standards_state(root, target)
    if target.calculation_family == "hybrid":
        return _capture_hybrid_state(
            root,
            target,
            cast(tuple[ConventionalGradeWorkEvidenceSpec, ...], work_evidence),
        )
    raise GradePreviewTargetError("unsupported current Grade preview family.")


def _capture_conventional_state(
    root: Path,
    target: GradePreviewTarget,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...],
) -> _CurrentGradePreviewState:
    try:
        stored = load_current_conventional_grade_result(
            root,
            target.class_id,
            target.student_id,
            target.target_period,
            target.calendar_revision,
        )
    except ConventionalGradeStorageError as error:
        raise GradePreviewIntegrityError(
            f"Selected conventional Grade result is invalid: {error}"
        ) from error
    if stored is None:
        raise GradePreviewTargetNotFoundError(
            "Conventional Grade result has no explicit current selection."
        )
    try:
        assembly = assemble_conventional_grade_calculation(
            root,
            target.class_id,
            target.student_id,
            target.target_period,
            target.calendar_revision,
            work_evidence,
        )
        freshness = assess_conventional_grade_result_freshness(
            stored.snapshot,
            assembly.inputs,
        )
    except ConventionalGradeAssemblyError as error:
        raise GradePreviewSourceError(
            f"Current conventional Grade basis could not be resolved: {error}"
        ) from error
    except ValueError as error:
        raise GradePreviewIntegrityError(
            f"Conventional Grade currentness could not be verified: {error}"
        ) from error
    source = TeacherGradeOverrideSelectedSource(
        source=TeacherGradeOverrideSourceResult(
            source_result=GradeOverrideSourceResultReference(
                "conventional",
                stored.reference,
            ),
            source_status=stored.snapshot.outcome.status,
            base_grade=(
                stored.snapshot.outcome.rounded_grade
                if stored.snapshot.outcome.status == "calculated"
                else None
            ),
        ),
        freshness_status=freshness.status,
        freshness_reasons=tuple(freshness.reasons),
    )
    witness = _finish_current_witness(
        root,
        target,
        source,
        current_basis_sha256=conventional_grade_calculation_input_sha256(
            assembly.inputs
        ),
        current_activation_reference=assembly.activation.reference,
        current_policy_reference=assembly.policy.reference,
    )
    _require_conventional_selection_unchanged(root, target, stored.reference)
    return _CurrentGradePreviewState(stored.snapshot, witness)


def _capture_standards_state(
    root: Path,
    target: GradePreviewTarget,
) -> _CurrentGradePreviewState:
    try:
        stored = load_current_standards_grade_result(
            root,
            target.class_id,
            target.student_id,
            target.target_period,
            target.calendar_revision,
        )
    except StandardsGradeStorageError as error:
        raise GradePreviewIntegrityError(
            f"Selected standards Grade result is invalid: {error}"
        ) from error
    if stored is None:
        raise GradePreviewTargetNotFoundError(
            "Standards Grade result has no explicit current selection."
        )
    try:
        assembly = assemble_standards_grade_calculation(
            root,
            target.class_id,
            target.student_id,
            target.target_period,
            target.calendar_revision,
        )
        freshness = assess_standards_grade_result_freshness(
            stored.snapshot,
            assembly.inputs,
        )
    except StandardsGradeAssemblyError as error:
        raise GradePreviewSourceError(
            f"Current standards Grade basis could not be resolved: {error}"
        ) from error
    except ValueError as error:
        raise GradePreviewIntegrityError(
            f"Standards Grade currentness could not be verified: {error}"
        ) from error
    source = TeacherGradeOverrideSelectedSource(
        source=TeacherGradeOverrideSourceResult(
            source_result=GradeOverrideSourceResultReference(
                "standards_based",
                stored.reference,
            ),
            source_status=stored.snapshot.outcome.status,
            base_grade=(
                stored.snapshot.outcome.rounded_grade
                if stored.snapshot.outcome.status == "calculated"
                else None
            ),
        ),
        freshness_status=freshness.status,
        freshness_reasons=tuple(freshness.reasons),
    )
    witness = _finish_current_witness(
        root,
        target,
        source,
        current_basis_sha256=standards_grade_calculation_input_sha256(
            assembly.inputs
        ),
        current_activation_reference=assembly.activation.reference,
        current_policy_reference=assembly.policy.reference,
    )
    _require_standards_selection_unchanged(root, target, stored.reference)
    return _CurrentGradePreviewState(stored.snapshot, witness)


def _capture_hybrid_state(
    root: Path,
    target: GradePreviewTarget,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...],
) -> _CurrentGradePreviewState:
    try:
        stored = load_current_hybrid_grade_result(
            root,
            target.class_id,
            target.student_id,
            target.target_period,
            target.calendar_revision,
        )
    except HybridGradeStorageError as error:
        raise GradePreviewIntegrityError(
            f"Selected hybrid Grade result is invalid: {error}"
        ) from error
    if stored is None:
        raise GradePreviewTargetNotFoundError(
            "Hybrid Grade result has no explicit current selection."
        )
    try:
        assembly = assemble_hybrid_grade_calculation(
            root,
            target.class_id,
            target.student_id,
            target.target_period,
            target.calendar_revision,
            work_evidence,
        )
        freshness = assess_hybrid_grade_result_freshness(
            stored.snapshot,
            assembly.inputs,
        )
    except HybridGradeAssemblyError as error:
        raise GradePreviewSourceError(
            f"Current hybrid Grade basis could not be resolved: {error}"
        ) from error
    except ValueError as error:
        raise GradePreviewIntegrityError(
            f"Hybrid Grade currentness could not be verified: {error}"
        ) from error
    source = TeacherGradeOverrideSelectedSource(
        source=TeacherGradeOverrideSourceResult(
            source_result=GradeOverrideSourceResultReference(
                "hybrid",
                stored.reference,
            ),
            source_status=stored.snapshot.outcome.status,
            base_grade=(
                stored.snapshot.outcome.rounded_grade
                if stored.snapshot.outcome.status == "calculated"
                else None
            ),
        ),
        freshness_status=freshness.status,
        freshness_reasons=tuple(freshness.reasons),
    )
    witness = _finish_current_witness(
        root,
        target,
        source,
        current_basis_sha256=hybrid_grade_calculation_input_sha256(
            assembly.inputs
        ),
        current_activation_reference=assembly.activation.reference,
        current_policy_reference=assembly.policy.reference,
    )
    _require_hybrid_selection_unchanged(root, target, stored.reference)
    return _CurrentGradePreviewState(stored.snapshot, witness)


def _finish_current_witness(
    root: Path,
    target: GradePreviewTarget,
    selected_source: TeacherGradeOverrideSelectedSource,
    *,
    current_basis_sha256: str,
    current_activation_reference: GradePolicyActivationReference,
    current_policy_reference: GradePolicyReference,
) -> _CurrentGradePreviewWitness:
    _require_current_activation_unchanged(
        root,
        target,
        current_activation_reference,
    )
    selected_override_reference, effective = _resolve_effective(
        root,
        target,
        selected_source,
    )
    return _CurrentGradePreviewWitness(
        source_result=selected_source.source_result,
        current_basis_sha256=current_basis_sha256,
        current_activation_reference=current_activation_reference,
        current_policy_reference=current_policy_reference,
        selected_override_reference=selected_override_reference,
        effective=effective,
    )


def _resolve_effective(
    root: Path,
    target: GradePreviewTarget,
    selected_source: TeacherGradeOverrideSelectedSource,
) -> tuple[TeacherGradeOverrideReference | None, EffectiveGradeResolution]:
    try:
        stored_override = load_current_teacher_grade_override(
            root,
            target.class_id,
            target.student_id,
            target.target_period,
            target.calendar_revision,
            target.calculation_family,
        )
    except TeacherGradeOverrideStorageError as error:
        raise GradePreviewIntegrityError(
            f"Selected teacher Grade override is invalid: {error}"
        ) from error

    if stored_override is None:
        try:
            effective = resolve_effective_grade(selected_source)
        except EffectiveGradeError as error:
            raise GradePreviewIntegrityError(
                f"Effective Grade state is internally inconsistent: {error}"
            ) from error
        _require_override_selection_unchanged(root, target, None)
        return None, effective

    try:
        load_teacher_grade_override_source_result(
            root,
            stored_override.decision.source_result,
        )
    except (
        TeacherGradeOverrideSourceIntegrityError,
        TeacherGradeOverrideWorkflowError,
    ) as error:
        raise GradePreviewIntegrityError(
            "Selected override references unavailable or corrupt historical "
            "Grade-result provenance."
        ) from error
    try:
        effective = resolve_effective_grade(
            selected_source,
            selected_override_reference=stored_override.reference,
            selected_override=stored_override.decision,
        )
    except EffectiveGradeError as error:
        raise GradePreviewIntegrityError(
            f"Effective Grade state is internally inconsistent: {error}"
        ) from error
    _require_override_selection_unchanged(
        root,
        target,
        stored_override.reference,
    )
    return stored_override.reference, effective


def _load_source_authority(
    root: Path,
    target: GradePreviewTarget,
    snapshot: GradeResultSnapshot,
) -> _SourceAuthority:
    activation_reference = snapshot.activation_reference
    policy_reference = snapshot.policy_reference
    try:
        stored_activation = load_grade_policy_activation_revision(
            root,
            activation_reference.class_id,
            target.target_period,
            activation_reference.activation_revision,
        )
        stored_policy = load_grade_policy_revision(
            root,
            policy_reference.class_id,
            policy_reference.policy_id,
            policy_reference.policy_revision,
        )
    except (GradePolicyActivationStorageError, GradePolicyStorageError) as error:
        raise GradePreviewIntegrityError(
            f"Exact Grade policy authority could not be verified: {error}"
        ) from error
    if stored_activation.reference != activation_reference:
        raise GradePreviewIntegrityError(
            "Persisted Grade result activation digest does not match exact history."
        )
    if stored_policy.reference != policy_reference:
        raise GradePreviewIntegrityError(
            "Persisted Grade result policy digest does not match exact history."
        )
    activation = stored_activation.decision
    if (
        activation.decision != "activate"
        or activation.calendar_revision != target.calendar_revision
        or activation.policy_reference != policy_reference
    ):
        raise GradePreviewIntegrityError(
            "Persisted Grade result activation authority is internally inconsistent."
        )
    if stored_policy.policy.calculation_family != target.calculation_family:
        raise GradePreviewIntegrityError(
            "Persisted Grade result policy family does not match preview target."
        )
    return _SourceAuthority(stored_policy.policy, activation)


def _build_family_explanation(
    root: Path,
    snapshot: GradeResultSnapshot,
    authority: _SourceAuthority,
    effective: EffectiveGradeResolution,
) -> CurrentGradePreviewExplanation:
    if isinstance(snapshot, ConventionalGradeResultSnapshot):
        return explain_conventional_grade_preview(
            root,
            snapshot,
            policy=authority.policy,
            activation=authority.activation,
            effective=effective,
        )
    if isinstance(snapshot, StandardsGradeResultSnapshot):
        return explain_standards_grade_preview(
            root,
            snapshot,
            policy=authority.policy,
            activation=authority.activation,
            effective=effective,
        )
    if isinstance(snapshot, HybridGradeResultSnapshot):
        return explain_hybrid_grade_preview(
            root,
            snapshot,
            policy=authority.policy,
            activation=authority.activation,
            effective=effective,
        )
    raise GradePreviewIntegrityError("Selected Grade result family is unsupported.")


def _require_current_activation_unchanged(
    root: Path,
    target: GradePreviewTarget,
    expected: GradePolicyActivationReference,
) -> None:
    try:
        current = load_current_grade_policy_activation(
            root,
            target.class_id,
            target.target_period,
        )
    except GradePolicyActivationStorageError as error:
        raise GradePreviewIntegrityError(
            f"Current Grade-policy activation is invalid: {error}"
        ) from error
    if current is None or current.reference != expected:
        raise GradePreviewCurrentnessConflictError(
            "Current Grade-policy activation changed during preview resolution."
        )


def _require_override_selection_unchanged(
    root: Path,
    target: GradePreviewTarget,
    expected: TeacherGradeOverrideReference | None,
) -> None:
    try:
        current = get_current_teacher_grade_override_reference(
            root,
            target.class_id,
            target.student_id,
            target.target_period,
            target.calendar_revision,
            target.calculation_family,
        )
    except TeacherGradeOverrideStorageError as error:
        raise GradePreviewIntegrityError(
            f"Current teacher Grade override selector is invalid: {error}"
        ) from error
    if current != expected:
        raise GradePreviewCurrentnessConflictError(
            "Current teacher Grade override selection changed during "
            "preview resolution."
        )


def _require_conventional_selection_unchanged(
    root: Path,
    target: GradePreviewTarget,
    expected: ConventionalGradeResultReference,
) -> None:
    try:
        current = load_current_conventional_grade_result(
            root,
            target.class_id,
            target.student_id,
            target.target_period,
            target.calendar_revision,
        )
    except ConventionalGradeStorageError as error:
        raise GradePreviewIntegrityError(
            f"Current conventional Grade selector is invalid: {error}"
        ) from error
    if current is None or current.reference != expected:
        raise GradePreviewCurrentnessConflictError(
            "Current conventional Grade selection changed during preview resolution."
        )


def _require_standards_selection_unchanged(
    root: Path,
    target: GradePreviewTarget,
    expected: StandardsGradeResultReference,
) -> None:
    try:
        current = load_current_standards_grade_result(
            root,
            target.class_id,
            target.student_id,
            target.target_period,
            target.calendar_revision,
        )
    except StandardsGradeStorageError as error:
        raise GradePreviewIntegrityError(
            f"Current standards Grade selector is invalid: {error}"
        ) from error
    if current is None or current.reference != expected:
        raise GradePreviewCurrentnessConflictError(
            "Current standards Grade selection changed during preview resolution."
        )


def _require_hybrid_selection_unchanged(
    root: Path,
    target: GradePreviewTarget,
    expected: HybridGradeResultReference,
) -> None:
    try:
        current = load_current_hybrid_grade_result(
            root,
            target.class_id,
            target.student_id,
            target.target_period,
            target.calendar_revision,
        )
    except HybridGradeStorageError as error:
        raise GradePreviewIntegrityError(
            f"Current hybrid Grade selector is invalid: {error}"
        ) from error
    if current is None or current.reference != expected:
        raise GradePreviewCurrentnessConflictError(
            "Current hybrid Grade selection changed during preview resolution."
        )
