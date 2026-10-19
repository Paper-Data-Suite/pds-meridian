"""#122 guided single-save adapters for attempt decisions and Standards.

All authority stays with existing immutable writer / CAS selector services.
The journal records *attempted* operations; verified canonical current state
remains the sole authority for an Applied result.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from meridian.attempt_decision_authoring_workflow import (
    AttemptDecisionAuthoringPreview,
)
from meridian.attempt_selection import attempt_selection_decision_to_json_bytes
from meridian.attempt_selection_storage import (
    derive_attempt_candidates,
    list_attempt_selection_decision_revisions,
    load_attempt_selection_decision_revision,
    load_current_attempt_selection_decision,
    load_current_attempt_selection_policy,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
    validate_grade_item_membership_dependencies,
)
from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    commit_guided_attempt_decision,
    commit_guided_attempt_selection,
    preview_guided_attempt_selection,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.guided_standards import (
    GuidedStandardsDependencies,
    commit_guided_standard_association,
    commit_guided_standard_selection,
    preview_guided_standard_selection,
)
from meridian.standards_association_authoring_workflow import (
    StandardsAssociationAuthoringPreview,
)
from meridian.standards_evidence import standard_evidence_association_to_json_bytes
from meridian.standards_evidence_storage import (
    list_standard_evidence_association_revisions,
    load_current_standard_evidence_association_decision,
    load_standard_evidence_association_revision,
    validate_standard_evidence_association_dependencies,
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


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _selection(value: str) -> SelectionDisposition:
    if value == "created":
        return "created"
    if value == "updated":
        return "updated"
    if value == "existing":
        return "existing"
    raise TeacherActionConflictError("Unexpected authoritative selection disposition.")


def prepare_attempt_decision_action(
    root: Path,
    prepared: GuidedProjectionResult,
    authoring: AttemptDecisionAuthoringPreview,
    actor: TeacherActionActor,
    dependencies: GuidedAttemptDependencies,
) -> PreparedGuidedAction:
    """Bind an explicit, selected-attempt decision to one guarded Save/Apply."""
    root = _root(root)
    decision = authoring.candidate
    class_id, gi, work, student = (
        decision.class_id,
        decision.grade_item_id,
        decision.work,
        decision.student_id,
    )
    if decision.actor.kind != "teacher" or decision.actor.actor_id != actor.actor_id:
        raise TeacherActionConflictError("Reviewed attempt actor changed.")
    digest = _hash(attempt_selection_decision_to_json_bytes(decision))
    membership = load_current_grade_item_membership_decision(root, class_id, gi, work)
    if (
        membership is None
        or membership.decision.decision != "included"
        or membership.decision.membership_revision != decision.membership_revision
        or membership.decision_sha256 != decision.membership_revision_sha256
    ):
        raise TeacherActionConflictError("Current attempt membership changed.")
    assignment = membership.decision.academic_period
    if assignment is None:
        raise TeacherActionConflictError("Attempt has no reviewed academic period.")
    period = assignment.period
    calendar_sha = _calendar_digest(
        root, period.school_year, assignment.calendar_revision
    )
    prior = load_current_attempt_selection_decision(root, class_id, gi, work, student)
    prior_revision = None if prior is None else prior.decision.decision_revision
    prior_sha = None if prior is None else prior.decision_sha256
    if prior_revision != authoring.reviewed_current_decision_revision:
        raise TeacherActionConflictError("Current attempt selection changed.")

    def validate() -> None:
        _actor_now(actor)
        validate_grade_item_membership_dependencies(root, membership.decision)
        current = load_current_grade_item_membership_decision(root, class_id, gi, work)
        if (
            current is None
            or current.decision_sha256 != decision.membership_revision_sha256
        ):
            raise TeacherActionConflictError("Current attempt membership changed.")
        policy = load_current_attempt_selection_policy(
            root,
            class_id,
            gi,
            work,
            decision.policy.policy_id,
        )
        if (
            policy is None
            or policy.policy_sha256 != decision.policy.policy_revision_sha256
        ):
            raise TeacherActionConflictError("Current attempt policy changed.")
        derivation = derive_attempt_candidates(
            root,
            class_id,
            gi,
            student,
            prepared.authorized,
        )
        if (
            derivation.status != "applicable"
            or derivation.source_snapshot != decision.source_snapshot
            or derivation.candidates != decision.candidates
        ):
            raise TeacherActionConflictError(
                "Eligible attempts or publication changed."
            )
        if (
            _calendar_digest(root, period.school_year, assignment.calendar_revision)
            != calendar_sha
        ):
            raise TeacherActionConflictError("Academic calendar changed.")
        history = list_attempt_selection_decision_revisions(
            root, class_id, gi, work, student
        )
        if history not in (
            authoring.history,
            (*authoring.history, decision.decision_revision),
        ):
            raise TeacherActionConflictError("Attempt decision history changed.")

    def read() -> Observation:
        history = list_attempt_selection_decision_revisions(
            root, class_id, gi, work, student
        )
        target = (
            load_attempt_selection_decision_revision(
                root,
                class_id,
                gi,
                work,
                student,
                decision.decision_revision,
            )
            if decision.decision_revision in history
            else None
        )
        current = load_current_attempt_selection_decision(
            root, class_id, gi, work, student
        )
        try:
            validate()
            state: Literal["current", "stale"] = "current"
        except Exception:
            state = "stale"
        return (
            None if target is None else target.decision_sha256,
            None if current is None else current.decision.decision_revision,
            None if current is None else current.decision_sha256,
            state,
        )

    def write() -> Literal["created", "existing"]:
        result = commit_guided_attempt_decision(
            root,
            prepared=prepared,
            preview=authoring,
            dependencies=dependencies,
        )
        if result.write_disposition == "created":
            return "created"
        if result.write_disposition == "existing":
            return "existing"
        raise TeacherActionConflictError("Unexpected attempt write disposition.")

    def select() -> SelectionDisposition:
        preview = preview_guided_attempt_selection(
            root,
            prepared=prepared,
            grade_item_id=gi,
            student_id=student,
            written_revision=decision.decision_revision,
            dependencies=dependencies,
        )
        if (
            preview.target_sha256 != digest
            or preview.expected_current_decision_revision != prior_revision
        ):
            raise TeacherActionConflictError("Exact attempt selector baseline changed.")
        result = commit_guided_attempt_selection(
            root,
            prepared=prepared,
            preview=preview,
            dependencies=dependencies,
        )
        if result.selected_decision_sha256 != digest:
            raise TeacherActionConflictError("Attempt CAS selected another digest.")
        return _selection(result.selection_disposition)

    kind: ActionKind = "attempt_decision"
    return _prepare(
        root=root,
        class_id=class_id,
        grade_item_id=gi,
        actor=actor,
        kind=kind,
        revision=decision.decision_revision,
        candidate_sha256=digest,
        current_revision=prior_revision,
        current_sha256=prior_sha,
        identity=_identity(
            "attempt_decision", class_id, gi, work.module_id, work.work_id, student
        ),
        source_binding=_identity(
            "attempt_source",
            decision.source_snapshot.publication_id,
            decision.source_snapshot.cache_key,
            decision.source_snapshot.snapshot_digest,
            decision.membership_revision_sha256,
            decision.policy.policy_revision_sha256,
        ),
        school_year=period.school_year,
        academic_period_id=period.period_id,
        calendar_sha256=calendar_sha,
        work_identity_sha256=_identity("work", class_id, work.module_id, work.work_id),
        port=_GuidedPort(
            kind=kind,
            revalidate=validate,
            read=read,
            write=write,
            select=select,
        ),
    )


def prepare_standard_association_action(
    root: Path,
    prepared: GuidedProjectionResult,
    authoring: StandardsAssociationAuthoringPreview,
    actor: TeacherActionActor,
    dependencies: GuidedStandardsDependencies,
) -> PreparedGuidedAction:
    """Bind an explicit Standard/basis judgment to the exact evidence source."""
    root = _root(root)
    decision = authoring.candidate
    class_id, gi, source, standard_id = (
        decision.class_id,
        decision.grade_item_id,
        decision.source,
        decision.standard_id,
    )
    if decision.actor.kind != "teacher" or decision.actor.actor_id != actor.actor_id:
        raise TeacherActionConflictError("Reviewed Standard actor changed.")
    digest = _hash(standard_evidence_association_to_json_bytes(decision))
    membership = load_current_grade_item_membership_decision(
        root,
        class_id,
        gi,
        source.work,
    )
    if (
        membership is None
        or membership.decision.decision != "included"
        or membership.decision.membership_revision != authoring.membership_revision
        or membership.decision_sha256 != authoring.membership_revision_sha256
    ):
        raise TeacherActionConflictError("Standard membership changed since review.")
    assignment = membership.decision.academic_period
    if assignment is None:
        raise TeacherActionConflictError("Standard membership has no academic period.")
    period = assignment.period
    calendar_sha = _calendar_digest(
        root, period.school_year, assignment.calendar_revision
    )
    prior = load_current_standard_evidence_association_decision(
        root,
        class_id,
        gi,
        source,
        standard_id,
    )
    prior_rev = None if prior is None else prior.decision.association_revision
    prior_sha = None if prior is None else prior.decision_sha256
    if prior_rev != authoring.expected_current_association_revision:
        raise TeacherActionConflictError("Standard association selection changed.")

    def validate() -> None:
        _actor_now(actor)
        resolved = validate_standard_evidence_association_dependencies(
            root,
            decision,
            prepared.authorized,
        )
        if (
            resolved.grade_item.revision.grade_item_revision
            != authoring.grade_item_revision
            or resolved.grade_item.revision_sha256
            != authoring.grade_item_revision_sha256
            or resolved.membership.decision_sha256
            != authoring.membership_revision_sha256
            or resolved.standard_resolution.resolved != authoring.standard_resolved
            or resolved.standard_resolution.active != authoring.standard_active
        ):
            raise TeacherActionConflictError(
                "Standard, Grade Item or membership changed."
            )
        if (
            _calendar_digest(root, period.school_year, assignment.calendar_revision)
            != calendar_sha
        ):
            raise TeacherActionConflictError("Academic calendar changed.")
        history = list_standard_evidence_association_revisions(
            root,
            class_id,
            gi,
            source,
            standard_id,
        )
        if history not in (
            authoring.history,
            (*authoring.history, decision.association_revision),
        ):
            raise TeacherActionConflictError("Standard association history changed.")

    def read() -> Observation:
        history = list_standard_evidence_association_revisions(
            root,
            class_id,
            gi,
            source,
            standard_id,
        )
        target = (
            load_standard_evidence_association_revision(
                root,
                class_id,
                gi,
                source,
                standard_id,
                decision.association_revision,
            )
            if decision.association_revision in history
            else None
        )
        current = load_current_standard_evidence_association_decision(
            root,
            class_id,
            gi,
            source,
            standard_id,
        )
        try:
            validate()
            state: Literal["current", "stale"] = "current"
        except Exception:
            state = "stale"
        return (
            None if target is None else target.decision_sha256,
            None if current is None else current.decision.association_revision,
            None if current is None else current.decision_sha256,
            state,
        )

    def write() -> Literal["created", "existing"]:
        result = commit_guided_standard_association(
            root,
            prepared,
            authoring,
            dependencies=dependencies,
        )
        value = result.write_result.disposition
        if value == "created":
            return "created"
        if value == "existing":
            return "existing"
        raise TeacherActionConflictError("Unexpected Standard write disposition.")

    def select() -> SelectionDisposition:
        preview = preview_guided_standard_selection(
            root,
            prepared,
            authoring.projection,
            decision.association_revision,
            dependencies=dependencies,
        )
        if (
            preview.target_sha256 != digest
            or preview.expected_current_association_revision != prior_rev
        ):
            raise TeacherActionConflictError(
                "Exact Standard selector baseline changed."
            )
        result = commit_guided_standard_selection(
            root,
            prepared,
            preview,
            dependencies=dependencies,
        )
        if result.selected_decision_sha256 != digest:
            raise TeacherActionConflictError("Standard CAS selected another digest.")
        return _selection(result.selection_disposition)

    kind: ActionKind = "standards_association"
    return _prepare(
        root=root,
        class_id=class_id,
        grade_item_id=gi,
        actor=actor,
        kind=kind,
        revision=decision.association_revision,
        candidate_sha256=digest,
        current_revision=prior_rev,
        current_sha256=prior_sha,
        identity=_identity(
            "standard_association",
            class_id,
            gi,
            source.work.module_id,
            source.work.work_id,
            source.publication_id,
            source.item_id,
            standard_id,
        ),
        source_binding=_identity(
            "standard_source",
            source.publication_id,
            source.cache_key,
            source.snapshot_digest,
            authoring.membership_revision_sha256,
            authoring.grade_item_revision_sha256,
            standard_id,
        ),
        school_year=period.school_year,
        academic_period_id=period.period_id,
        calendar_sha256=calendar_sha,
        work_identity_sha256=_identity(
            "work",
            class_id,
            source.work.module_id,
            source.work.work_id,
        ),
        port=_GuidedPort(
            kind=kind,
            revalidate=validate,
            read=read,
            write=write,
            select=select,
        ),
    )


__all__ = (
    "prepare_attempt_decision_action",
    "prepare_standard_association_action",
)
