"""Auditable selection and withdrawal lifecycle for teacher Grade overrides.

Issue #53 deliberately keeps immutable override authoring separate from explicit
current selection. This workflow is the teacher-facing lifecycle boundary: it
selects only the latest authored decision, and it records withdrawal as a new
immutable decision against the exact selected active override.

The low-level storage selector may reselect historical revisions for repair and
composition. This workflow intentionally does not expose historical reselection
as an undo/restore mechanism. Effective-Grade precedence remains a separate
layer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef

from meridian.grade_policy import (
    GradeCalculationFamily,
    GradePolicyActor,
    GradePolicyValidationError,
)
from meridian.teacher_grade_override import (
    TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
    TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
    TeacherGradeOverrideDecision,
    TeacherGradeOverrideReference,
    TeacherGradeOverrideValidationError,
    teacher_grade_override_decision_to_json_bytes,
    teacher_grade_override_reference,
    validate_teacher_grade_override_transition,
)
from meridian.teacher_grade_override_storage import (
    TeacherGradeOverrideSelectDisposition,
    TeacherGradeOverrideStorageConflictError,
    TeacherGradeOverrideStorageError,
    TeacherGradeOverrideWriteDisposition,
    get_current_teacher_grade_override_reference,
    list_teacher_grade_override_revisions,
    load_current_teacher_grade_override,
    load_teacher_grade_override_revision,
    select_teacher_grade_override_revision,
    write_teacher_grade_override_revision,
)
from meridian.teacher_grade_override_workflow import (
    TeacherGradeOverrideSourceResult,
    TeacherGradeOverrideWorkflowError,
    TeacherGradeOverrideWorkflowScopeError,
    load_teacher_grade_override_source_result,
)


class TeacherGradeOverrideSelectionScopeError(
    TeacherGradeOverrideWorkflowScopeError
):
    """Raised when a teacher-facing override selection request is invalid."""

    code = "teacher_workflow.grade_override.selection_invalid"


class TeacherGradeOverrideSelectionStaleError(TeacherGradeOverrideWorkflowError):
    """Raised when reviewed override selection state changed before commit."""

    code = "teacher_workflow.grade_override.selection_stale"


class TeacherGradeOverrideWithdrawalScopeError(
    TeacherGradeOverrideWorkflowScopeError
):
    """Raised when an override cannot be withdrawn under the v1 lifecycle."""

    code = "teacher_workflow.grade_override.withdrawal_invalid"


class TeacherGradeOverrideWithdrawalStaleError(TeacherGradeOverrideWorkflowError):
    """Raised when selected override authority changed during withdrawal."""

    code = "teacher_workflow.grade_override.withdrawal_stale"


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideSelectionPreview:
    """Exact reviewed basis for selecting one latest authored decision."""

    target_reference: TeacherGradeOverrideReference
    target_decision: TeacherGradeOverrideDecision
    history: tuple[int, ...]
    expected_current: TeacherGradeOverrideReference | None

    def __post_init__(self) -> None:
        if not isinstance(self.target_reference, TeacherGradeOverrideReference):
            raise TeacherGradeOverrideSelectionScopeError(
                "target_reference must be TeacherGradeOverrideReference."
            )
        if not isinstance(self.target_decision, TeacherGradeOverrideDecision):
            raise TeacherGradeOverrideSelectionScopeError(
                "target_decision must be TeacherGradeOverrideDecision."
            )
        expected_target = teacher_grade_override_reference(self.target_decision)
        if self.target_reference != expected_target:
            raise TeacherGradeOverrideSelectionScopeError(
                "target_reference must bind exact target decision bytes."
            )
        history = tuple(self.history)
        if not history or history != tuple(range(1, history[-1] + 1)):
            raise TeacherGradeOverrideSelectionScopeError(
                "selection history must be contiguous from revision 1."
            )
        if self.target_reference.override_revision != history[-1]:
            raise TeacherGradeOverrideSelectionScopeError(
                "teacher workflow may select only the latest authored override "
                "decision; author a new immutable decision instead of restoring "
                "historical authority."
            )
        current = self.expected_current
        if current is not None:
            if not isinstance(current, TeacherGradeOverrideReference):
                raise TeacherGradeOverrideSelectionScopeError(
                    "expected_current must be TeacherGradeOverrideReference or None."
                )
            _require_same_family(self.target_reference, current)
            if current.override_revision not in history:
                raise TeacherGradeOverrideSelectionScopeError(
                    "expected_current must identify reviewed override history."
                )
        object.__setattr__(self, "history", history)


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideSelectionWorkflowResult:
    """Result of one explicit teacher-facing override selection."""

    target_reference: TeacherGradeOverrideReference
    selected_decision: TeacherGradeOverrideDecision
    previous_current: TeacherGradeOverrideReference | None
    selection_disposition: TeacherGradeOverrideSelectDisposition

    def __post_init__(self) -> None:
        if not isinstance(self.target_reference, TeacherGradeOverrideReference):
            raise TeacherGradeOverrideSelectionScopeError(
                "target_reference must be TeacherGradeOverrideReference."
            )
        if not isinstance(self.selected_decision, TeacherGradeOverrideDecision):
            raise TeacherGradeOverrideSelectionScopeError(
                "selected_decision must be TeacherGradeOverrideDecision."
            )
        if teacher_grade_override_reference(self.selected_decision) != (
            self.target_reference
        ):
            raise TeacherGradeOverrideSelectionScopeError(
                "selected_decision must match target_reference exactly."
            )
        if self.previous_current is not None:
            _require_same_family(self.target_reference, self.previous_current)
        if self.selection_disposition not in {"created", "updated", "existing"}:
            raise TeacherGradeOverrideSelectionScopeError(
                "selection_disposition is invalid."
            )


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideWithdrawalPreview:
    """Exact reviewed basis for one immutable withdrawal decision."""

    selected_override_reference: TeacherGradeOverrideReference
    selected_override_decision: TeacherGradeOverrideDecision
    source: TeacherGradeOverrideSourceResult
    history_before: tuple[int, ...]
    latest_override_sha256_before: str
    candidate: TeacherGradeOverrideDecision
    candidate_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(
            self.selected_override_reference,
            TeacherGradeOverrideReference,
        ):
            raise TeacherGradeOverrideWithdrawalScopeError(
                "selected_override_reference must be TeacherGradeOverrideReference."
            )
        if not isinstance(
            self.selected_override_decision,
            TeacherGradeOverrideDecision,
        ):
            raise TeacherGradeOverrideWithdrawalScopeError(
                "selected_override_decision must be TeacherGradeOverrideDecision."
            )
        if self.selected_override_decision.decision != "override":
            raise TeacherGradeOverrideWithdrawalScopeError(
                "withdrawal requires a selected active override decision."
            )
        if teacher_grade_override_reference(self.selected_override_decision) != (
            self.selected_override_reference
        ):
            raise TeacherGradeOverrideWithdrawalScopeError(
                "selected override reference must bind exact selected decision bytes."
            )
        if not isinstance(self.source, TeacherGradeOverrideSourceResult):
            raise TeacherGradeOverrideWithdrawalScopeError(
                "source must be TeacherGradeOverrideSourceResult."
            )
        if self.source.source_result != self.selected_override_decision.source_result:
            raise TeacherGradeOverrideWithdrawalScopeError(
                "withdrawal source must match selected active override source."
            )
        history = tuple(self.history_before)
        if not history or history != tuple(range(1, history[-1] + 1)):
            raise TeacherGradeOverrideWithdrawalScopeError(
                "withdrawal history must be contiguous from revision 1."
            )
        if self.selected_override_reference.override_revision not in history:
            raise TeacherGradeOverrideWithdrawalScopeError(
                "selected active override must exist in reviewed history."
            )
        if not isinstance(self.latest_override_sha256_before, str) or not (
            self.latest_override_sha256_before
        ):
            raise TeacherGradeOverrideWithdrawalScopeError(
                "latest_override_sha256_before must be nonblank."
            )
        if not isinstance(self.candidate, TeacherGradeOverrideDecision):
            raise TeacherGradeOverrideWithdrawalScopeError(
                "candidate must be TeacherGradeOverrideDecision."
            )
        if self.candidate.decision != "withdraw":
            raise TeacherGradeOverrideWithdrawalScopeError(
                "withdrawal preview requires decision=withdraw."
            )
        if self.candidate.override_revision != history[-1] + 1:
            raise TeacherGradeOverrideWithdrawalScopeError(
                "withdrawal candidate must append exactly one immutable revision."
            )
        if self.candidate.supersedes_revision != history[-1]:
            raise TeacherGradeOverrideWithdrawalScopeError(
                "withdrawal candidate must supersede latest immutable revision."
            )
        if self.candidate.withdrawn_override_reference != (
            self.selected_override_reference
        ):
            raise TeacherGradeOverrideWithdrawalScopeError(
                "withdrawal candidate must reference exact selected active override."
            )
        if self.candidate.source_result != self.source.source_result:
            raise TeacherGradeOverrideWithdrawalScopeError(
                "withdrawal candidate must preserve exact withdrawn source result."
            )
        expected_digest = hashlib.sha256(
            teacher_grade_override_decision_to_json_bytes(self.candidate)
        ).hexdigest()
        if self.candidate_sha256 != expected_digest:
            raise TeacherGradeOverrideWithdrawalScopeError(
                "candidate_sha256 must bind exact withdrawal candidate bytes."
            )
        object.__setattr__(self, "history_before", history)


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideWithdrawalResult:
    """Result of writing one exact immutable withdrawal decision."""

    preview: TeacherGradeOverrideWithdrawalPreview
    write_disposition: TeacherGradeOverrideWriteDisposition
    stored_reference: TeacherGradeOverrideReference
    selected_override_after: TeacherGradeOverrideReference | None

    def __post_init__(self) -> None:
        if not isinstance(self.preview, TeacherGradeOverrideWithdrawalPreview):
            raise TeacherGradeOverrideWithdrawalScopeError(
                "preview must be TeacherGradeOverrideWithdrawalPreview."
            )
        if self.write_disposition not in {"created", "existing"}:
            raise TeacherGradeOverrideWithdrawalScopeError(
                "write_disposition must be created or existing."
            )
        expected = teacher_grade_override_reference(self.preview.candidate)
        if self.stored_reference != expected:
            raise TeacherGradeOverrideWithdrawalScopeError(
                "stored_reference must identify exact withdrawal candidate."
            )
        if self.selected_override_after is not None:
            _require_same_family(expected, self.selected_override_after)


def preview_teacher_grade_override_selection(
    workspace_root: str | Path,
    target_reference: TeacherGradeOverrideReference,
) -> TeacherGradeOverrideSelectionPreview:
    """Preview explicit selection of the latest authored override decision.

    Historical reselection is intentionally rejected here. Corrections, undo,
    restore, and reactivation must be represented by a new immutable decision.
    """

    if not isinstance(target_reference, TeacherGradeOverrideReference):
        raise TeacherGradeOverrideSelectionScopeError(
            "target_reference must be TeacherGradeOverrideReference."
        )
    period = AcademicPeriodRef(
        target_reference.school_year,
        target_reference.period_id,
    )
    try:
        history = list_teacher_grade_override_revisions(
            workspace_root,
            target_reference.class_id,
            target_reference.student_id,
            period,
            target_reference.calendar_revision,
            target_reference.calculation_family,
        )
        if not history:
            raise TeacherGradeOverrideSelectionScopeError(
                "override family has no immutable decision history."
            )
        if target_reference.override_revision not in history:
            raise TeacherGradeOverrideSelectionScopeError(
                "selection target is not present in immutable override history."
            )
        if target_reference.override_revision != history[-1]:
            raise TeacherGradeOverrideSelectionScopeError(
                "teacher workflow refuses historical override reselection; "
                "author a new immutable decision instead."
            )
        stored = load_teacher_grade_override_revision(
            workspace_root,
            target_reference.class_id,
            target_reference.student_id,
            period,
            target_reference.calendar_revision,
            target_reference.calculation_family,
            target_reference.override_revision,
        )
        current = get_current_teacher_grade_override_reference(
            workspace_root,
            target_reference.class_id,
            target_reference.student_id,
            period,
            target_reference.calendar_revision,
            target_reference.calculation_family,
        )
    except TeacherGradeOverrideSelectionScopeError:
        raise
    except TeacherGradeOverrideStorageError as error:
        raise TeacherGradeOverrideWorkflowError(
            f"Override selection preview could not verify canonical state: {error}"
        ) from error
    if stored.reference != target_reference:
        raise TeacherGradeOverrideSelectionScopeError(
            "selection target digest does not match stored immutable decision."
        )
    return TeacherGradeOverrideSelectionPreview(
        target_reference=target_reference,
        target_decision=stored.decision,
        history=history,
        expected_current=current,
    )


def commit_teacher_grade_override_selection_preview(
    workspace_root: str | Path,
    preview: TeacherGradeOverrideSelectionPreview,
) -> TeacherGradeOverrideSelectionWorkflowResult:
    """Revalidate and CAS-select the exact latest previewed decision."""

    if not isinstance(preview, TeacherGradeOverrideSelectionPreview):
        raise TeacherGradeOverrideSelectionScopeError(
            "preview must be TeacherGradeOverrideSelectionPreview."
        )
    target = preview.target_reference
    period = AcademicPeriodRef(target.school_year, target.period_id)
    try:
        history = list_teacher_grade_override_revisions(
            workspace_root,
            target.class_id,
            target.student_id,
            period,
            target.calendar_revision,
            target.calculation_family,
        )
        if history != preview.history:
            raise TeacherGradeOverrideSelectionStaleError(
                "Override history changed after selection preview."
            )
        stored = load_teacher_grade_override_revision(
            workspace_root,
            target.class_id,
            target.student_id,
            period,
            target.calendar_revision,
            target.calculation_family,
            target.override_revision,
        )
        if (
            stored.reference != target
            or stored.decision != preview.target_decision
        ):
            raise TeacherGradeOverrideSelectionStaleError(
                "Selection target changed after preview."
            )
        current = get_current_teacher_grade_override_reference(
            workspace_root,
            target.class_id,
            target.student_id,
            period,
            target.calendar_revision,
            target.calculation_family,
        )
        if current != preview.expected_current:
            raise TeacherGradeOverrideSelectionStaleError(
                "Current override selection changed after preview."
            )
        selected = select_teacher_grade_override_revision(
            workspace_root,
            target,
            expected_current=preview.expected_current,
        )
    except TeacherGradeOverrideSelectionStaleError:
        raise
    except TeacherGradeOverrideStorageConflictError as error:
        raise TeacherGradeOverrideSelectionStaleError(
            "Current override selection changed before CAS commit."
        ) from error
    except TeacherGradeOverrideStorageError as error:
        raise TeacherGradeOverrideWorkflowError(
            f"Override selection could not be committed: {error}"
        ) from error
    if selected.stored.reference != target:
        raise TeacherGradeOverrideWorkflowError(
            "Selected override differs from previewed target."
        )
    return TeacherGradeOverrideSelectionWorkflowResult(
        target_reference=target,
        selected_decision=selected.stored.decision,
        previous_current=preview.expected_current,
        selection_disposition=selected.disposition,
    )


def preview_teacher_grade_override_withdrawal(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
    *,
    actor_id: str,
    rationale: str,
    decided_at: datetime,
) -> TeacherGradeOverrideWithdrawalPreview:
    """Preview withdrawal of the exact selected active override decision.

    The withdrawn source result is loaded by exact immutable reference for
    integrity, but it does not have to remain the selected/fresh Grade result.
    """

    try:
        selected = load_current_teacher_grade_override(
            workspace_root,
            class_id,
            student_id,
            target_period,
            calendar_revision,
            calculation_family,
        )
        if selected is None:
            raise TeacherGradeOverrideWithdrawalScopeError(
                "withdrawal requires an explicitly selected active override."
            )
        if selected.decision.decision != "override":
            raise TeacherGradeOverrideWithdrawalScopeError(
                "selected override decision is already a withdrawal; "
                "reactivation requires a new immutable override decision."
            )
        history = list_teacher_grade_override_revisions(
            workspace_root,
            class_id,
            student_id,
            target_period,
            calendar_revision,
            calculation_family,
        )
        if not history or selected.reference.override_revision not in history:
            raise TeacherGradeOverrideWithdrawalScopeError(
                "selected active override is not present in canonical history."
            )
        latest = load_teacher_grade_override_revision(
            workspace_root,
            class_id,
            student_id,
            target_period,
            calendar_revision,
            calculation_family,
            history[-1],
        )
    except TeacherGradeOverrideWithdrawalScopeError:
        raise
    except TeacherGradeOverrideStorageError as error:
        raise TeacherGradeOverrideWorkflowError(
            f"Withdrawal preview could not verify override state: {error}"
        ) from error

    source = load_teacher_grade_override_source_result(
        workspace_root,
        selected.decision.source_result,
    )
    try:
        actor = GradePolicyActor("teacher", actor_id)
        revision = history[-1] + 1
        candidate = TeacherGradeOverrideDecision(
            schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
            record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
            class_id=class_id,
            student_id=student_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
            calculation_family=calculation_family,
            override_revision=revision,
            supersedes_revision=history[-1],
            decision="withdraw",
            source_result=selected.decision.source_result,
            replacement_grade=None,
            withdrawn_override_reference=selected.reference,
            actor=actor,
            rationale=rationale,
            decided_at=decided_at,
        )
        validate_teacher_grade_override_transition(latest.decision, candidate)
    except (GradePolicyValidationError, TeacherGradeOverrideValidationError) as error:
        raise TeacherGradeOverrideWithdrawalScopeError(str(error)) from error

    content = teacher_grade_override_decision_to_json_bytes(candidate)
    return TeacherGradeOverrideWithdrawalPreview(
        selected_override_reference=selected.reference,
        selected_override_decision=selected.decision,
        source=source,
        history_before=history,
        latest_override_sha256_before=latest.override_sha256,
        candidate=candidate,
        candidate_sha256=hashlib.sha256(content).hexdigest(),
    )


def commit_teacher_grade_override_withdrawal_preview(
    workspace_root: str | Path,
    preview: TeacherGradeOverrideWithdrawalPreview,
) -> TeacherGradeOverrideWithdrawalResult:
    """Write the exact reviewed withdrawal without selecting it."""

    if not isinstance(preview, TeacherGradeOverrideWithdrawalPreview):
        raise TeacherGradeOverrideWithdrawalScopeError(
            "preview must be TeacherGradeOverrideWithdrawalPreview."
        )
    candidate = preview.candidate
    try:
        history = list_teacher_grade_override_revisions(
            workspace_root,
            candidate.class_id,
            candidate.student_id,
            candidate.target_period,
            candidate.calendar_revision,
            candidate.calculation_family,
        )
    except TeacherGradeOverrideStorageError as error:
        raise TeacherGradeOverrideWorkflowError(
            f"Withdrawal history could not be revalidated: {error}"
        ) from error

    replay_history = preview.history_before + (candidate.override_revision,)
    exact_replay = history == replay_history
    if history != preview.history_before and not exact_replay:
        raise TeacherGradeOverrideWithdrawalStaleError(
            "Override history changed after withdrawal preview."
        )

    if exact_replay:
        try:
            existing = load_teacher_grade_override_revision(
                workspace_root,
                candidate.class_id,
                candidate.student_id,
                candidate.target_period,
                candidate.calendar_revision,
                candidate.calculation_family,
                candidate.override_revision,
            )
        except TeacherGradeOverrideStorageError as error:
            raise TeacherGradeOverrideWorkflowError(
                f"Withdrawal replay could not be verified: {error}"
            ) from error
        if (
            existing.decision != candidate
            or existing.override_sha256 != preview.candidate_sha256
        ):
            raise TeacherGradeOverrideWithdrawalStaleError(
                "Existing withdrawal revision differs from preview."
            )
    else:
        try:
            latest = load_teacher_grade_override_revision(
                workspace_root,
                candidate.class_id,
                candidate.student_id,
                candidate.target_period,
                candidate.calendar_revision,
                candidate.calculation_family,
                preview.history_before[-1],
            )
        except TeacherGradeOverrideStorageError as error:
            raise TeacherGradeOverrideWorkflowError(
                f"Latest override revision could not be revalidated: {error}"
            ) from error
        if latest.override_sha256 != preview.latest_override_sha256_before:
            raise TeacherGradeOverrideWithdrawalStaleError(
                "Latest override revision changed after withdrawal preview."
            )

    _require_exact_withdrawal_source(workspace_root, preview)
    if not exact_replay:
        _require_selected_active_override(workspace_root, preview)

    def precommit_guard() -> None:
        _require_selected_active_override(workspace_root, preview)
        _require_exact_withdrawal_source(workspace_root, preview)

    try:
        written = write_teacher_grade_override_revision(
            workspace_root,
            candidate,
            precommit_guard=None if exact_replay else precommit_guard,
        )
    except TeacherGradeOverrideWithdrawalStaleError:
        raise
    except TeacherGradeOverrideStorageError as error:
        raise TeacherGradeOverrideWorkflowError(
            f"Withdrawal revision could not be persisted: {error}"
        ) from error

    if written.stored.decision != candidate:
        raise TeacherGradeOverrideWorkflowError(
            "Persisted withdrawal differs from previewed decision."
        )
    if written.stored.override_sha256 != preview.candidate_sha256:
        raise TeacherGradeOverrideWorkflowError(
            "Persisted withdrawal digest differs from preview."
        )

    _require_exact_withdrawal_source(workspace_root, preview)
    try:
        selected_after = get_current_teacher_grade_override_reference(
            workspace_root,
            candidate.class_id,
            candidate.student_id,
            candidate.target_period,
            candidate.calendar_revision,
            candidate.calculation_family,
        )
    except TeacherGradeOverrideStorageError as error:
        raise TeacherGradeOverrideWorkflowError(
            f"Override current selection could not be read: {error}"
        ) from error
    if not exact_replay and selected_after != preview.selected_override_reference:
        raise TeacherGradeOverrideWithdrawalStaleError(
            "Current override selection changed while withdrawal commit completed."
        )
    return TeacherGradeOverrideWithdrawalResult(
        preview=preview,
        write_disposition=written.disposition,
        stored_reference=written.stored.reference,
        selected_override_after=selected_after,
    )


def _require_selected_active_override(
    workspace_root: str | Path,
    preview: TeacherGradeOverrideWithdrawalPreview,
) -> None:
    reference = preview.selected_override_reference
    period = AcademicPeriodRef(reference.school_year, reference.period_id)
    try:
        selected = load_current_teacher_grade_override(
            workspace_root,
            reference.class_id,
            reference.student_id,
            period,
            reference.calendar_revision,
            reference.calculation_family,
        )
    except TeacherGradeOverrideStorageError as error:
        raise TeacherGradeOverrideWithdrawalStaleError(
            "Selected active override could not be revalidated."
        ) from error
    if (
        selected is None
        or selected.reference != reference
        or selected.decision != preview.selected_override_decision
        or selected.decision.decision != "override"
    ):
        raise TeacherGradeOverrideWithdrawalStaleError(
            "Selected active override changed after withdrawal preview."
        )


def _require_exact_withdrawal_source(
    workspace_root: str | Path,
    preview: TeacherGradeOverrideWithdrawalPreview,
) -> None:
    try:
        source = load_teacher_grade_override_source_result(
            workspace_root,
            preview.source.source_result,
        )
    except TeacherGradeOverrideWorkflowError:
        raise
    if source != preview.source:
        raise TeacherGradeOverrideWithdrawalStaleError(
            "Exact source result changed after withdrawal preview."
        )


def _require_same_family(
    left: TeacherGradeOverrideReference,
    right: TeacherGradeOverrideReference,
) -> None:
    left_scope = (
        left.class_id,
        left.student_id,
        left.school_year,
        left.period_id,
        left.calendar_revision,
        left.calculation_family,
    )
    right_scope = (
        right.class_id,
        right.student_id,
        right.school_year,
        right.period_id,
        right.calendar_revision,
        right.calculation_family,
    )
    if left_scope != right_scope:
        raise TeacherGradeOverrideSelectionScopeError(
            "override references must belong to the same logical family."
        )


__all__ = [
    "TeacherGradeOverrideSelectionPreview",
    "TeacherGradeOverrideSelectionScopeError",
    "TeacherGradeOverrideSelectionStaleError",
    "TeacherGradeOverrideSelectionWorkflowResult",
    "TeacherGradeOverrideWithdrawalPreview",
    "TeacherGradeOverrideWithdrawalResult",
    "TeacherGradeOverrideWithdrawalScopeError",
    "TeacherGradeOverrideWithdrawalStaleError",
    "commit_teacher_grade_override_selection_preview",
    "commit_teacher_grade_override_withdrawal_preview",
    "preview_teacher_grade_override_selection",
    "preview_teacher_grade_override_withdrawal",
]
