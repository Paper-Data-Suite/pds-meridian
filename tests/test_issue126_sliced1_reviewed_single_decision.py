"""#126-D1: one reviewed academic intention, exactly one #30 selection."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_issue126_sliceb_attempt_inventory import _attempt, _build, _case, _selection
from test_issue126_slicec_correction_interpretation import _correction

import meridian.attempt_resolution_execution as resolution
from meridian.attempt_correction_interpretation import preview_attempt_interpretation
from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptPolicyPreset,
)
from meridian.teacher_action_contract import TeacherActionActor


class _Action:
    def __init__(self, actor, candidate, digest):
        self.preview = SimpleNamespace(
            kind="attempt_decision",
            actor=actor,
            scope=SimpleNamespace(
                class_id=candidate.class_id, grade_item_id=candidate.grade_item_id
            ),
            target=SimpleNamespace(
                candidate_sha256=digest,
                revision=candidate.decision_revision,
                expected_current_revision=1,
            ),
        )
        self.calls: list[bool] = []
        self.status = "applied"
        self.current_state = "matches"
        self.throws = False

    def apply(self, *, confirmed):
        self.calls.append(confirmed)
        if self.throws:
            raise RuntimeError("Simulated incomplete canonical action")
        return SimpleNamespace(
            status=(self.status if confirmed else "blocked_before_write"),
            current_state=(self.current_state if confirmed else "not_checked"),
            current_record=(
                SimpleNamespace(matches_target=lambda target: True)
                if confirmed and self.current_state == "matches"
                else None
            ),
            reason_code=None if self.status == "applied" else "canonical_block",
        )


def _setup(monkeypatch, *, inventory=None, selected=None):
    # Replace only the external prepared-projection type check. Every real C
    # invariant runs against a typed 29-student synthetic B projection.
    monkeypatch.setattr(resolution, "GuidedProjectionResult", SimpleNamespace)
    monkeypatch.setattr(
        resolution,
        "attempt_selection_decision_to_json_bytes",
        lambda candidate: b"synthetic #30 exact immutable decision",
    )
    view = _build(_case()) if inventory is None else inventory
    intent = _correction(view)
    actor = TeacherActionActor("synthetic_teacher", "e" * 64, "saved")
    preset = GuidedAttemptPolicyPreset(
        "Select exactly one attempt",
        "One explicit current selection",
        "teacher_guided_exactly_one",
        1,
        1,
    )
    deps = GuidedAttemptDependencies(policies=(preset,))
    published = SimpleNamespace(
        work=intent.source_snapshot.work,
        publication_id=intent.source_snapshot.publication_id,
    )
    prepared = SimpleNamespace(
        authorized=SimpleNamespace(
            current_context=SimpleNamespace(publication=published)
        )
    )
    candidate = SimpleNamespace(
        class_id=intent.class_id,
        grade_item_id=intent.grade_item_id,
        student_id=intent.student_id,
        work=intent.source_snapshot.work,
        source_snapshot=intent.source_snapshot,
        selected_attempts=intent.intended_selected_attempts,
        rationale=intent.suggested_canonical_rationale,
        actor=SimpleNamespace(kind="teacher", actor_id=actor.actor_id),
        policy=SimpleNamespace(policy_id=preset.policy_id),
        decision_revision=2,
    )
    authoring = SimpleNamespace(
        candidate=candidate, reviewed_current_decision_revision=1
    )
    digest = hashlib.sha256(b"synthetic #30 exact immutable decision").hexdigest()
    action = _Action(actor, candidate, digest)
    current = replace(
        _selection(intent.student_id, candidates=(2,), selected=(2,)),
        selected_decision_revision=2,
        selected_decision_sha256=digest,
    )
    read_calls: list[str] = []

    def inventory_loader(*args, **kwargs):
        read_calls.append("inventory")
        return view

    def policy_planner(*args, **kwargs):
        read_calls.append("policy")
        return SimpleNamespace(action="ready", preset=preset)

    def authoring_previewer(*args, **kwargs):
        read_calls.append("authoring")
        assert kwargs["selected_attempts"] == intent.intended_selected_attempts
        assert kwargs["rationale"] == intent.suggested_canonical_rationale
        return authoring

    def action_preparer(*args, **kwargs):
        read_calls.append("#122")
        return action

    def selection_loader(*args, **kwargs):
        read_calls.append("#30 reload")
        return current

    ports = resolution.AttemptResolutionPorts(
        inventory_loader=inventory_loader,
        policy_planner=policy_planner,
        authoring_previewer=authoring_previewer,
        action_preparer=action_preparer,
        selection_loader=selection_loader,
    )
    return SimpleNamespace(
        view=view,
        intent=intent,
        actor=actor,
        preset=preset,
        deps=deps,
        prepared=prepared,
        candidate=candidate,
        action=action,
        current=current,
        ports=ports,
        read_calls=read_calls,
    )


def _prepare(case):
    return resolution.prepare_reviewed_attempt_resolution(
        Path.cwd(),
        prepared=case.prepared,
        interpretation=case.intent,
        preset=case.preset,
        actor=case.actor,
        dependencies=case.deps,
        ports=case.ports,
    )


def test_teacher_correction_prepare_is_read_only_and_exact(monkeypatch) -> None:
    case = _setup(monkeypatch)
    prior = repr(case.view)
    plan = _prepare(case)
    assert repr(case.view) == prior
    assert case.action.calls == []
    assert case.read_calls == ["inventory", "policy", "authoring", "#122"]
    rendered = resolution.render_reviewed_attempt_resolution(plan)
    assert "NOT YET SAVED" in rendered
    assert "Attempt 2" in rendered
    assert "WILL NOT remove old attempts" in rendered
    assert "synthetic_student_01" not in rendered


def test_cancel_does_not_commit_or_reload_canonical(monkeypatch) -> None:
    case = _setup(monkeypatch)
    plan = _prepare(case)
    result = plan.apply(confirmed=False)
    assert result.status == "canceled_before_write"
    assert not result.exact_current
    assert not result.continue_to_standards_review
    assert case.action.calls == [False]
    assert "#30 reload" not in case.read_calls


def test_one_confirmation_and_independent_exact_selection(monkeypatch) -> None:
    case = _setup(monkeypatch)
    plan = _prepare(case)
    result = plan.apply(confirmed=True)
    assert result.status == "applied_current"
    assert result.action_status == "applied"
    assert result.canonical_resolution_status == "selected"
    assert result.exact_current and result.continue_to_standards_review
    assert case.action.calls == [True]
    assert case.read_calls == [
        "inventory",
        "policy",
        "authoring",
        "#122",
        "inventory",
        "#30 reload",
    ]


def test_already_applied_requires_canonical_truth(monkeypatch) -> None:
    case = _setup(monkeypatch)
    case.action.status = "already_applied"
    result = _prepare(case).apply(confirmed=True)
    assert result.status == "already_current"
    assert result.exact_current


def test_canonical_reload_mismatch_cannot_claim_applied(monkeypatch) -> None:
    case = _setup(monkeypatch)
    wrong = replace(case.current, selected_decision_sha256="9" * 64)
    case.ports = replace(case.ports, selection_loader=lambda *a, **k: wrong)
    result = _prepare(case).apply(confirmed=True)
    assert result.status == "current_unverified"
    assert not result.exact_current and not result.continue_to_standards_review
    assert result.reason == "independent_current_selection_mismatch"


def test_canonical_reload_error_is_uncertain_not_rollback(monkeypatch) -> None:
    case = _setup(monkeypatch)

    def unavailable(*a, **k):
        raise RuntimeError("source revoked after commit")

    case.ports = replace(case.ports, selection_loader=unavailable)
    result = _prepare(case).apply(confirmed=True)
    assert result.status == "current_unverified"
    assert result.reason == "canonical_reload_unavailable"
    assert case.action.calls == [True]


def test_write_failure_is_recovery_required_not_no_write(monkeypatch) -> None:
    case = _setup(monkeypatch)
    case.action.throws = True
    result = _prepare(case).apply(confirmed=True)
    assert result.status == "recovery_required"
    assert result.reason == "canonical_action_outcome_unknown"
    assert case.action.calls == [True]


def test_canonical_written_not_current_does_not_claim_success(monkeypatch) -> None:
    case = _setup(monkeypatch)
    case.action.status = "written_not_current"
    result = _prepare(case).apply(confirmed=True)
    assert result.status == "written_not_current"
    assert not result.continue_to_standards_review


def test_precommit_roster_or_source_drift_blocks_all_writes(monkeypatch) -> None:
    case = _setup(monkeypatch)
    original_loader = case.ports.inventory_loader
    count = 0

    def drifts(*args, **kwargs):
        nonlocal count
        count += 1
        view = original_loader(*args, **kwargs)
        return view if count == 1 else replace(view, source_status="withdrawn")

    case.ports = replace(case.ports, inventory_loader=drifts)
    result = _prepare(case).apply(confirmed=True)
    assert result.status == "conflict_requires_review"
    assert case.action.calls == []


def test_change_in_selected_revision_before_apply_blocks(monkeypatch) -> None:
    case = _setup(monkeypatch)
    original_loader = case.ports.inventory_loader
    count = 0

    def changed(*args, **kwargs):
        nonlocal count
        count += 1
        value = original_loader(*args, **kwargs)
        if count == 1:
            return value
        students = list(value.students)
        students[0] = replace(students[0], selected_decision_revision=7)
        return replace(value, students=tuple(students))

    case.ports = replace(case.ports, inventory_loader=changed)
    result = _prepare(case).apply(confirmed=True)
    assert result.status == "conflict_requires_review"
    assert case.action.calls == []


def test_policy_authoring_is_never_a_hidden_side_effect(monkeypatch) -> None:
    case = _setup(monkeypatch)
    case.ports = replace(
        case.ports,
        policy_planner=lambda *a, **kw: SimpleNamespace(
            action="revise", preset=case.preset
        ),
    )
    with pytest.raises(resolution.AttemptResolutionExecutionError, match="separately"):
        _prepare(case)
    assert case.action.calls == []


def test_altered_122_candidate_digest_fails_closed(monkeypatch) -> None:
    case = _setup(monkeypatch)
    case.action.preview.target.candidate_sha256 = "9" * 64
    with pytest.raises(resolution.AttemptResolutionExecutionError, match="exact #30"):
        _prepare(case)
    assert case.action.calls == []


def test_unresolved_cannot_be_saved(monkeypatch) -> None:
    case = _setup(monkeypatch)
    case.intent = preview_attempt_interpretation(
        case.view, student_id="synthetic_student_01", treatment="unresolved"
    )
    with pytest.raises(resolution.AttemptResolutionExecutionError, match="Unresolved"):
        _prepare(case)
    assert case.action.calls == []


def test_multi_selected_reassessment_refused_without_31(monkeypatch) -> None:
    case = _setup(monkeypatch)
    case.intent = preview_attempt_interpretation(
        case.view,
        student_id="synthetic_student_02",
        treatment="teacher_reviewed_reassessment",
        selected_attempts=(
            _attempt("synthetic_student_02", 1),
            _attempt("synthetic_student_02", 2),
        ),
        teacher_rationale="Two distinct performances needing #31 treatment",
    )
    with pytest.raises(resolution.AttemptResolutionNeedsReassessment, match="#31"):
        _prepare(case)
    assert case.action.calls == []


def test_foreign_publication_fails_before_any_review(monkeypatch) -> None:
    case = _setup(monkeypatch)
    case.prepared.authorized.current_context.publication.publication_id = (
        "pub_" + "f" * 32
    )
    with pytest.raises(resolution.AttemptResolutionExecutionError, match="publication"):
        _prepare(case)
    assert case.read_calls == []


def test_another_teacher_cannot_reuse_foreign_actor_review(monkeypatch) -> None:
    case = _setup(monkeypatch)
    case.candidate.actor.actor_id = "foreign_actor"
    with pytest.raises(resolution.AttemptResolutionExecutionError, match="differs"):
        _prepare(case)
    assert case.action.calls == []
