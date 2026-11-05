"""#124 E2C: persist exact correlations before each existing #122 APPLY.

This is an opt-in, non-menu binder, not a restart writer or a new academic
engine. Every #122 action retains its immutable/CAS/receipt authority.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from meridian.assessment_setup_composite import PreparedAssessmentSetupComposite
from meridian.assessment_setup_correlation import (
    AssessmentSetupCorrelation,
    bind_correlation_action,
    create_assessment_setup_correlation,
    inspect_assessment_setup_correlation,
)
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_live import bind_live_assessment_setup
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_recovery import inspect_assessment_setup_recovery
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.teacher_action_contract import TeacherActionActor, TeacherActionResult
from meridian.teacher_action_guided import PreparedGuidedAction
from meridian.teacher_action_receipts import TeacherActionReceiptStore


class CorrelatedAssessmentSetupError(RuntimeError):
    """The reviewed setup cannot safely start a correlated academic action."""


@dataclass(frozen=True, slots=True)
class _CorrelatedAction(PreparedGuidedAction):
    """#122 prepared action; synchronous durable fence before its own APPLY."""

    before_apply: Callable[[], None] | None = None

    def apply(self, *, confirmed: bool) -> TeacherActionResult:
        if confirmed:
            if self.before_apply is None:
                raise CorrelatedAssessmentSetupError("Missing durable action fence.")
            self.before_apply()
        return PreparedGuidedAction.apply(self, confirmed=confirmed)


def _fenced(
    action: PreparedGuidedAction, before: Callable[[], None]
) -> PreparedGuidedAction:
    if not isinstance(action, PreparedGuidedAction):
        raise CorrelatedAssessmentSetupError("Only #122 prepared actions are allowed.")
    return _CorrelatedAction(
        preview=action.preview,
        port=action.port,
        store=action.store,
        existing_policy_selection=action.existing_policy_selection,
        before_apply=before,
    )


def bind_correlated_live_assessment_setup(
    workspace_root: str | Path,
    preview: AssessmentSetupPreview,
    *,
    actor: TeacherActionActor | None,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> PreparedAssessmentSetupComposite:
    """Bind a one-shot D2 action sequence with E2B *pre-action* durability.

    Cancellation writes no correlation. Once APPLY begins, no fresh binding
    may reuse an existing correlation: crash recovery must inspect that exact
    stored record and the original #122 receipts, never start a second create.
    """
    # Use the same fully normalized workspace as D2 and E2A.
    root = Path(workspace_root).resolve()
    prepared = bind_live_assessment_setup(
        root, preview, actor=actor, dependencies=dependencies
    )
    if preview.kind == "already_ready":
        return prepared
    if actor is None or actor.source != "saved":
        raise CorrelatedAssessmentSetupError(
            "Durable setup requires saved teacher attribution."
        )
    base = create_assessment_setup_correlation(root, preview, actor)
    store = AssessmentSetupCorrelationStore(root, preview.class_id)
    current: AssessmentSetupCorrelation | None = None

    def no_collision() -> None:
        # Look at *all* class correlations, not only this exact review hash.
        # Never select a recent-looking correlation or infer a new Grade Item.
        for record in store.list_records():
            if record.grade_item_id == base.grade_item_id or (
                record.module_id == base.module_id and record.work_id == base.work_id
            ):
                raise CorrelatedAssessmentSetupError(
                    "Related durable setup already exists; inspect recovery."
                )

    def canonical_before_first() -> None:
        observed = inspect_assessment_setup_recovery(root, preview)
        required = (
            "pristine"
            if preview.kind == "create_and_link"
            else "grade_item_selected_link_missing"
        )
        if (
            observed.state != required
            or observed.grade_action_ids
            or observed.membership_action_ids
        ):
            raise CorrelatedAssessmentSetupError(
                "Prior or changed academic state requires recovery review."
            )
        if preview.kind == "use_existing" and (
            observed.grade_selected_revision != preview.selected_grade_item_revision
        ):
            raise CorrelatedAssessmentSetupError(
                "Existing selected Grade Item revision changed."
            )

    def claim_initial() -> AssessmentSetupCorrelation:
        nonlocal current
        if current is not None:
            raise CorrelatedAssessmentSetupError(
                "This composite has already started an academic action."
            )
        no_collision()
        canonical_before_first()
        claimed = store.create_reviewed(base)
        if claimed.disposition != "created" or claimed.record != base:
            raise CorrelatedAssessmentSetupError(
                "An existing reviewed correlation cannot be replayed."
            )
        current = base
        return base

    def before_grade(action: PreparedGuidedAction) -> None:
        nonlocal current
        old = claim_initial()
        updated = bind_correlation_action(old, action, family="grade_item")
        record = store.advance_exact(expected=old, updated=updated)
        if record.record != updated or record.disposition != "advanced":
            raise CorrelatedAssessmentSetupError(
                "Grade action identity was not durably recorded."
            )
        current = updated

    def before_membership(action: PreparedGuidedAction) -> None:
        nonlocal current
        if preview.kind == "use_existing":
            old = claim_initial()
        else:
            grade_bound = current
            if grade_bound is None or grade_bound.stage != "grade_bound":
                raise CorrelatedAssessmentSetupError(
                    "Original Grade Item action was not durably bound."
                )
            old = grade_bound
            persisted = store.load(old.intent_sha256)
            if persisted != old:
                raise CorrelatedAssessmentSetupError(
                    "Grade Item correlation changed or disappeared."
                )
            observed = inspect_assessment_setup_recovery(root, preview)
            if (
                observed.state != "grade_item_selected_link_missing"
                or observed.grade_action_ids != (old.grade_action_id,)
                or observed.membership_action_ids
            ):
                raise CorrelatedAssessmentSetupError(
                    "Canonical Grade Item state or original receipt changed."
                )
        updated = bind_correlation_action(old, action, family="grade_item_membership")
        result = store.advance_exact(expected=old, updated=updated)
        if result.record != updated or result.disposition != "advanced":
            raise CorrelatedAssessmentSetupError(
                "Membership action identity was not durably recorded."
            )
        current = updated

    if preview.kind == "create_and_link":
        original_grade = prepared.grade_item_action
        if original_grade is None:
            raise CorrelatedAssessmentSetupError("Grade Item action is missing.")
        prepared.grade_item_action = _fenced(
            original_grade, lambda: before_grade(original_grade)
        )
    original_membership_factory = prepared.membership_factory
    if original_membership_factory is None:
        raise CorrelatedAssessmentSetupError("Membership action is missing.")

    def correlated_membership() -> PreparedGuidedAction:
        original = original_membership_factory()
        return _fenced(original, lambda: before_membership(original))

    prepared.membership_factory = correlated_membership
    original_final = prepared.verify_ready

    def verified_final() -> bool:
        # A #122 applied status alone never proves composite readiness.
        if not original_final():
            return False
        recorded = current
        if recorded is None or recorded.stage != "membership_bound":
            return False
        try:
            if store.load(recorded.intent_sha256) != recorded:
                return False
            observed = inspect_assessment_setup_recovery(root, preview)
            receipt_store = TeacherActionReceiptStore(root, preview.class_id)
            verified = inspect_assessment_setup_correlation(
                recorded, observed, receipt_store.list_receipts()
            )
            return verified.advice == "ready_verified"
        except Exception:
            return False

    prepared.verify_ready = verified_final
    return prepared


__all__ = (
    "CorrelatedAssessmentSetupError",
    "bind_correlated_live_assessment_setup",
)
