"""#122 ordinary, attributable, exact CAS attempt-policy Save/Apply.

The Grade Item relationship and academic calendar are independently checked.
The existing immutable writer and policy selector retain their authority.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pds_core.academic_work_registration_storage import (
    get_current_academic_work_registration_revision,
)

from meridian.attempt_policy_authoring_workflow import (
    AttemptPolicyAuthoringPreview,
)
from meridian.attempt_selection import attempt_selection_policy_to_json_bytes
from meridian.attempt_selection_storage import (
    StoredAttemptSelectionPolicy,
    list_attempt_selection_policy_revisions,
    load_attempt_selection_policy_revision,
    load_current_attempt_selection_policy,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
    validate_grade_item_membership_dependencies,
)
from meridian.grade_item_storage import load_current_grade_item_revision
from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptPolicyPlan,
)
from meridian.teacher_action_contract import (
    ActionKind,
    SelectionDisposition,
    TeacherActionActor,
)
from meridian.teacher_action_guided import (
    PreparedGuidedAction,
    _actor_now,
    _calendar_digest,
    _GuidedPort,
    _identity,
    _prepare,
    _root,
)
from meridian.teacher_action_orchestration import TeacherActionConflictError

Observation = tuple[str | None, int | None, str | None, Literal["current", "stale"]]


def _selection(value: str) -> SelectionDisposition:
    if value == "created":
        return "created"
    if value == "updated":
        return "updated"
    if value == "existing":
        return "existing"
    raise TeacherActionConflictError("Unexpected policy CAS disposition.")


def prepare_attempt_policy_action(
    root: Path,
    *,
    class_id: str,
    grade_item_id: str,
    work: object,
    plan: GuidedAttemptPolicyPlan,
    actor: TeacherActionActor,
    dependencies: GuidedAttemptDependencies,
) -> PreparedGuidedAction:
    """Bind one explicit policy plan to an immutable record and exact selector.

    Ready policies have no academic mutation and must not be sent to this path.
    All mutating plans require one confirmed teacher action and a durable receipt.
    """
    from pds_core.routing_models import ModuleWorkRef

    root = _root(root)
    if not isinstance(work, ModuleWorkRef) or work.class_id != class_id:
        raise TeacherActionConflictError("Policy work identity is invalid.")
    if plan.action == "ready":
        raise TeacherActionConflictError("Already-current policy requires no Save.")
    if plan.action not in {"create", "revise", "select_existing"}:
        raise TeacherActionConflictError("Unsupported attempt-policy plan.")
    policy_id = plan.preset.policy_id
    history_before = list_attempt_selection_policy_revisions(
        root, class_id, grade_item_id, work, policy_id
    )
    authoring: AttemptPolicyAuthoringPreview | None = None
    if plan.action == "select_existing":
        revision = plan.target_revision
        if revision is None or not history_before or revision != history_before[-1]:
            raise TeacherActionConflictError("Existing-policy plan changed.")
        existing = load_attempt_selection_policy_revision(
            root, class_id, grade_item_id, work, policy_id, revision
        )
        candidate = existing.policy
        digest = existing.policy_sha256
        if (
            candidate.minimum_selected != plan.preset.minimum_selected
            or candidate.maximum_selected != plan.preset.maximum_selected
            or candidate.selection_basis != "explicit"
        ):
            raise TeacherActionConflictError("Stored policy does not match preset.")
    else:
        operation: Literal["create", "revise"] = (
            "create" if plan.action == "create" else "revise"
        )
        authoring = dependencies.policy_authoring_previewer(
            root,
            class_id,
            grade_item_id,
            work,
            policy_id,
            operation=operation,
            minimum_selected=plan.preset.minimum_selected,
            maximum_selected=plan.preset.maximum_selected,
            actor_id=actor.actor_id,
            revised_at=dependencies.clock(),
            rationale=plan.preset.description,
        )
        candidate = authoring.candidate
        revision = candidate.policy_revision
        digest = hashlib.sha256(
            attempt_selection_policy_to_json_bytes(candidate)
        ).hexdigest()
        if (
            authoring.history != history_before
            or (plan.action == "create" and history_before)
            or (plan.action == "revise" and not history_before)
            or candidate.actor.kind != "teacher"
            or candidate.actor.actor_id != actor.actor_id
        ):
            raise TeacherActionConflictError(
                "Reviewed policy authoring context changed."
            )
    if (
        candidate.work != work
        or candidate.class_id != class_id
        or candidate.grade_item_id != grade_item_id
        or candidate.policy_id != policy_id
        or candidate.policy_revision != revision
    ):
        raise TeacherActionConflictError("Reviewed policy identity differs.")
    current = load_current_attempt_selection_policy(
        root, class_id, grade_item_id, work, policy_id
    )
    baseline_revision = None if current is None else current.policy.policy_revision
    baseline_sha = None if current is None else current.policy_sha256
    if authoring is not None and (
        authoring.reviewed_current_policy_revision != baseline_revision
    ):
        raise TeacherActionConflictError("Policy current selection changed.")
    if plan.action == "select_existing" and baseline_revision == revision:
        raise TeacherActionConflictError("Existing policy is already current.")

    membership = load_current_grade_item_membership_decision(
        root, class_id, grade_item_id, work
    )
    if membership is None or membership.decision.decision != "included":
        raise TeacherActionConflictError("Policy needs an included work relationship.")
    assignment = membership.decision.academic_period
    if assignment is None:
        raise TeacherActionConflictError("Policy work lacks an academic period.")
    period = assignment.period
    calendar_sha = _calendar_digest(
        root, period.school_year, assignment.calendar_revision
    )
    grade = load_current_grade_item_revision(root, class_id, grade_item_id)
    if (
        grade is None
        or grade.revision_sha256 != membership.decision.grade_item_revision_sha256
    ):
        raise TeacherActionConflictError("Policy Grade Item is not current.")
    validate_grade_item_membership_dependencies(root, membership.decision)
    if get_current_academic_work_registration_revision(root, work) != (
        membership.decision.work_reference.registration_revision
    ):
        raise TeacherActionConflictError("Policy work registration changed.")
    expected_history = (
        history_before if authoring is None else (*history_before, revision)
    )

    def validate() -> None:
        _actor_now(actor)
        live_member = load_current_grade_item_membership_decision(
            root, class_id, grade_item_id, work
        )
        if (
            live_member is None
            or live_member.decision.decision != "included"
            or live_member.decision_sha256 != membership.decision_sha256
        ):
            raise TeacherActionConflictError("Policy membership changed.")
        validate_grade_item_membership_dependencies(root, live_member.decision)
        live_grade = load_current_grade_item_revision(root, class_id, grade_item_id)
        if live_grade is None or live_grade.revision_sha256 != grade.revision_sha256:
            raise TeacherActionConflictError("Policy Grade Item changed.")
        if get_current_academic_work_registration_revision(root, work) != (
            membership.decision.work_reference.registration_revision
        ):
            raise TeacherActionConflictError("Policy work registration changed.")
        if (
            _calendar_digest(root, period.school_year, assignment.calendar_revision)
            != calendar_sha
        ):
            raise TeacherActionConflictError("Policy academic period changed.")
        history = list_attempt_selection_policy_revisions(
            root, class_id, grade_item_id, work, policy_id
        )
        if history not in (history_before, expected_history):
            raise TeacherActionConflictError("Policy history changed.")
        if history_before:
            previous = load_attempt_selection_policy_revision(
                root, class_id, grade_item_id, work, policy_id, history_before[-1]
            )
            if authoring is not None and (
                previous.policy_sha256 != authoring.latest_persisted_policy_sha256
            ):
                raise TeacherActionConflictError("Previous policy digest changed.")
        if revision in history:
            stored = load_attempt_selection_policy_revision(
                root, class_id, grade_item_id, work, policy_id, revision
            )
            if stored.policy_sha256 != digest or stored.policy != candidate:
                raise TeacherActionConflictError(
                    "Persisted policy differs from review."
                )
        selected = load_current_attempt_selection_policy(
            root, class_id, grade_item_id, work, policy_id
        )
        observed_revision = (
            None if selected is None else selected.policy.policy_revision
        )
        observed_digest = None if selected is None else selected.policy_sha256
        if (observed_revision, observed_digest) not in (
            (baseline_revision, baseline_sha),
            (revision, digest),
        ):
            raise TeacherActionConflictError("Another policy was selected.")

    def read() -> Observation:
        history = list_attempt_selection_policy_revisions(
            root, class_id, grade_item_id, work, policy_id
        )
        stored: StoredAttemptSelectionPolicy | None = (
            load_attempt_selection_policy_revision(
                root, class_id, grade_item_id, work, policy_id, revision
            )
            if revision in history
            else None
        )
        selected = load_current_attempt_selection_policy(
            root, class_id, grade_item_id, work, policy_id
        )
        try:
            validate()
            state: Literal["current", "stale"] = "current"
        except Exception:
            state = "stale"
        return (
            None if stored is None else stored.policy_sha256,
            None if selected is None else selected.policy.policy_revision,
            None if selected is None else selected.policy_sha256,
            state,
        )

    def write() -> Literal["created", "existing"]:
        if authoring is None:
            return "existing"
        result = dependencies.policy_authoring_committer(root, authoring)
        if result.write_result.stored.policy_sha256 != digest:
            raise TeacherActionConflictError("Written policy digest differs.")
        disposition = result.write_result.disposition
        if disposition == "created":
            return "created"
        if disposition == "existing":
            return "existing"
        raise TeacherActionConflictError("Unexpected immutable policy write status.")

    def select() -> SelectionDisposition:
        preview = dependencies.policy_selection_previewer(
            root, class_id, grade_item_id, work, policy_id, revision
        )
        if (
            preview.target_sha256 != digest
            or preview.expected_current_policy_revision != baseline_revision
            or preview.history != expected_history
        ):
            raise TeacherActionConflictError("Exact policy selector changed.")
        result = dependencies.policy_selection_committer(root, preview)
        if result.selected_policy_sha256 != digest:
            raise TeacherActionConflictError("Canonical policy selection differs.")
        return _selection(result.selection_disposition)

    identity = _identity(
        "attempt_policy",
        class_id,
        grade_item_id,
        work.module_id,
        work.work_id,
        policy_id,
    )
    source_binding = _identity(
        "attempt_policy_source",
        work.module_id,
        work.work_id,
        policy_id,
        str(revision),
        digest,
        plan.action,
        membership.decision_sha256,
        grade.revision_sha256,
        calendar_sha,
    )
    kind: ActionKind = "attempt_policy"
    return _prepare(
        root=root,
        class_id=class_id,
        grade_item_id=grade_item_id,
        actor=actor,
        kind=kind,
        revision=revision,
        candidate_sha256=digest,
        current_revision=baseline_revision,
        current_sha256=baseline_sha,
        identity=identity,
        source_binding=source_binding,
        school_year=period.school_year,
        academic_period_id=period.period_id,
        calendar_sha256=calendar_sha,
        work_identity_sha256=_identity("work", class_id, work.module_id, work.work_id),
        port=_GuidedPort(
            kind=kind, revalidate=validate, read=read, write=write, select=select
        ),
        existing_policy_selection=authoring is None,
    )


__all__ = ("prepare_attempt_policy_action",)
