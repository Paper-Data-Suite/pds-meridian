"""#122 single-save adapter for one explicitly reviewed proficiency result.

The existing #34 preview/writer and CAS selector retain all academic authority.
Journal receipts merely record the action and cannot make a result current.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from meridian.calculation_preview_assembly_workflow import (
    build_bounded_calculation_preview,
)
from meridian.calculation_result_persistence_workflow import (
    CalculationResultPersistencePreview,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
    validate_grade_item_membership_dependencies,
)
from meridian.grade_item_storage import load_current_grade_item_revision
from meridian.guided_proficiency import (
    GuidedProficiencyDependencies,
    commit_guided_proficiency_result,
    commit_guided_proficiency_selection,
    preview_guided_proficiency_selection,
)
from meridian.proficiency_mapping_storage import load_current_proficiency_scale
from meridian.standards_proficiency import (
    standard_proficiency_result_snapshot_to_json_bytes,
)
from meridian.standards_proficiency_storage import (
    list_standard_proficiency_result_revisions,
    load_current_standard_proficiency_policy,
    load_current_standard_proficiency_result,
    load_standard_proficiency_result_revision,
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
    raise TeacherActionConflictError("Unexpected proficiency selection disposition.")


def prepare_proficiency_result_action(
    root: Path,
    authoring: CalculationResultPersistencePreview,
    actor: TeacherActionActor,
    dependencies: GuidedProficiencyDependencies,
) -> PreparedGuidedAction:
    """Bind an immutable calculated result to one guarded teacher Save/Apply."""
    root = _root(root)
    candidate = authoring.candidate
    reviewed = authoring.reviewed
    class_id = candidate.class_id
    gi = candidate.grade_item_id
    student = candidate.student_id
    standard = candidate.standard_id
    revision = candidate.result_revision
    if authoring.actor_id != actor.actor_id:
        raise TeacherActionConflictError("Reviewed proficiency attribution changed.")
    if (
        reviewed.class_id != class_id
        or reviewed.grade_item_id != gi
        or reviewed.student_id != student
        or reviewed.standard_id != standard
        or reviewed.inputs != candidate.inputs
        or reviewed.calculation.outcome != candidate.outcome
    ):
        raise TeacherActionConflictError(
            "Proficiency candidate differs from reviewed calculation."
        )
    if len(reviewed.bindings) != 1:
        raise TeacherActionConflictError(
            "Guided proficiency requires one exact evidence binding."
        )
    binding = reviewed.bindings[0]
    source = binding.source
    work = source.work
    if work.class_id != class_id:
        raise TeacherActionConflictError("Proficiency source class changed.")
    digest = hashlib.sha256(
        standard_proficiency_result_snapshot_to_json_bytes(candidate)
    ).hexdigest()

    membership = load_current_grade_item_membership_decision(root, class_id, gi, work)
    if membership is None or membership.decision.decision != "included":
        raise TeacherActionConflictError(
            "Proficiency requires an included work relationship."
        )
    assignment = membership.decision.academic_period
    if assignment is None:
        raise TeacherActionConflictError(
            "Proficiency work has no current academic period."
        )
    period = assignment.period
    calendar_sha = _calendar_digest(
        root, period.school_year, assignment.calendar_revision
    )
    current = load_current_standard_proficiency_result(
        root, class_id, gi, student, standard
    )
    baseline_rev = None if current is None else current.snapshot.result_revision
    baseline_sha = None if current is None else current.result_sha256
    if baseline_rev != authoring.selected_revision_before:
        raise TeacherActionConflictError("Proficiency selection changed after review.")
    if revision != (
        authoring.history_before[-1] + 1 if authoring.history_before else 1
    ):
        raise TeacherActionConflictError(
            "Proficiency result revision changed after review."
        )

    def validate() -> None:
        _actor_now(actor)
        fresh_member = load_current_grade_item_membership_decision(
            root, class_id, gi, work
        )
        if (
            fresh_member is None
            or fresh_member.decision_sha256 != membership.decision_sha256
            or fresh_member.decision.decision != "included"
        ):
            raise TeacherActionConflictError("Current proficiency membership changed.")
        validate_grade_item_membership_dependencies(root, membership.decision)
        grade_item = load_current_grade_item_revision(root, class_id, gi)
        if (
            grade_item is None
            or grade_item.revision_sha256
            != reviewed.grade_item_basis.grade_item_revision_sha256
        ):
            raise TeacherActionConflictError("Selected proficiency Grade Item changed.")
        policy = load_current_standard_proficiency_policy(
            root, class_id, candidate.policy_reference.policy_id
        )
        if policy is None or policy.reference != candidate.policy_reference:
            raise TeacherActionConflictError(
                "Current proficiency calculation policy changed."
            )
        scale = load_current_proficiency_scale(
            root, class_id, candidate.target_scale.scale_id
        )
        if scale is None or scale.reference != candidate.target_scale:
            raise TeacherActionConflictError("Current proficiency scale changed.")
        if (
            _calendar_digest(root, period.school_year, assignment.calendar_revision)
            != calendar_sha
        ):
            raise TeacherActionConflictError(
                "Current academic period calendar changed."
            )
        # Fresh evidence authorization, mapping, source lifecycle, policy,
        # Grade Item, and pure calculation; allow only expected new result history.
        fresh = build_bounded_calculation_preview(
            root,
            gi,
            student,
            standard,
            reviewed.inputs.target_scale,
            reviewed.bindings,
            reviewed.calculation.policy_reference,
        )
        if (
            fresh.grade_item_basis != reviewed.grade_item_basis
            or fresh.source_keys != reviewed.source_keys
            or fresh.inputs != reviewed.inputs
            or fresh.calculation.policy_reference
            != reviewed.calculation.policy_reference
            or fresh.calculation.outcome != reviewed.calculation.outcome
        ):
            raise TeacherActionConflictError(
                "Proficiency evidence or calculation changed."
            )
        history = list_standard_proficiency_result_revisions(
            root, class_id, gi, student, standard
        )
        if history not in (
            authoring.history_before,
            (*authoring.history_before, revision),
        ):
            raise TeacherActionConflictError("Proficiency result history changed.")
        if history == authoring.history_before and history:
            latest = load_standard_proficiency_result_revision(
                root, class_id, gi, student, standard, history[-1]
            )
            if latest.result_sha256 != authoring.latest_result_sha256_before:
                raise TeacherActionConflictError("Previous proficiency result changed.")

    def read() -> Observation:
        history = list_standard_proficiency_result_revisions(
            root, class_id, gi, student, standard
        )
        target = (
            load_standard_proficiency_result_revision(
                root, class_id, gi, student, standard, revision
            )
            if revision in history
            else None
        )
        selected = load_current_standard_proficiency_result(
            root, class_id, gi, student, standard
        )
        try:
            validate()
            status: Literal["current", "stale"] = "current"
        except Exception:
            status = "stale"
        return (
            None if target is None else target.result_sha256,
            None if selected is None else selected.snapshot.result_revision,
            None if selected is None else selected.result_sha256,
            status,
        )

    def write() -> Literal["created", "existing"]:
        result = commit_guided_proficiency_result(
            root, authoring, dependencies=dependencies
        )
        if result.written_result_sha256 != digest:
            raise TeacherActionConflictError(
                "Persisted proficiency digest differs from review."
            )
        if result.write_result.disposition == "created":
            return "created"
        if result.write_result.disposition == "existing":
            return "existing"
        raise TeacherActionConflictError("Unexpected proficiency write disposition.")

    def select() -> SelectionDisposition:
        preview = preview_guided_proficiency_selection(
            root, reviewed, revision, dependencies=dependencies
        )
        if (
            preview.target_result_sha256 != digest
            or preview.expected_current_result_revision != baseline_rev
        ):
            raise TeacherActionConflictError(
                "Exact proficiency selection baseline changed."
            )
        result = commit_guided_proficiency_selection(
            root, preview, dependencies=dependencies
        )
        if result.selected_result_sha256 != digest:
            raise TeacherActionConflictError(
                "Proficiency CAS selected another result digest."
            )
        return _selection(result.selection_disposition)

    kind: ActionKind = "proficiency_result"
    return _prepare(
        root=root,
        class_id=class_id,
        grade_item_id=gi,
        actor=actor,
        kind=kind,
        revision=revision,
        candidate_sha256=digest,
        current_revision=baseline_rev,
        current_sha256=baseline_sha,
        identity=_identity("proficiency_result", class_id, gi, student, standard),
        source_binding=_identity(
            "proficiency_source",
            source.publication_id,
            source.cache_key,
            source.snapshot_digest,
            source.item_id,
            candidate.inputs_sha256,
            candidate.calculation_fingerprint,
            candidate.policy_reference.policy_sha256,
            candidate.target_scale.scale_sha256,
            membership.decision_sha256,
        ),
        school_year=period.school_year,
        academic_period_id=period.period_id,
        calendar_sha256=calendar_sha,
        work_identity_sha256=_identity("work", class_id, work.module_id, work.work_id),
        port=_GuidedPort(
            kind=kind, revalidate=validate, read=read, write=write, select=select
        ),
    )


__all__ = ("prepare_proficiency_result_action",)
