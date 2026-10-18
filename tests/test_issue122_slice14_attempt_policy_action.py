"""#122 Slice 14: one reviewed Save for a canonical attempt policy.

All fixtures are synthetic and contained in tmp_path; no teacher data is read.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_policy_authoring_workflow import AttemptPolicyAuthoringPreview
from meridian.attempt_selection import (
    ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
    ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
    AttemptSelectionActor,
    AttemptSelectionPolicy,
    attempt_selection_policy_to_json_bytes,
)
from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptPolicyPlan,
    GuidedAttemptPolicyPreset,
)
from meridian.teacher_action_attempt_policy import prepare_attempt_policy_action
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_orchestration import TeacherActionConflictError

A = "a" * 64
B = "b" * 64
C = "c" * 64


@pytest.fixture
def example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import hashlib

    import meridian.teacher_action_attempt_policy as policy_action

    (tmp_path / "classes" / "class_one").mkdir(parents=True)
    work = ModuleWorkRef(module_id="scoreform", class_id="class_one", work_id="work_1")
    preset = GuidedAttemptPolicyPreset(
        title="Select one attempt",
        description="Explicit selection",
        policy_id="teacher_guided_exactly_one",
        minimum_selected=1,
        maximum_selected=1,
    )
    current_revision: int | None = None
    stored: dict[int, SimpleNamespace] = {}
    written: list[int] = []
    selected: list[int] = []
    checks: list[str] = []
    stale = {"membership": False, "grade": False, "calendar": False}
    crash = {"after_write": False}
    assignment = SimpleNamespace(
        calendar_revision=1,
        period=SimpleNamespace(school_year="2026-2027", period_id="mp1"),
    )
    membership = SimpleNamespace(
        decision_sha256=B,
        decision=SimpleNamespace(
            decision="included",
            academic_period=assignment,
            grade_item_revision_sha256=C,
            work_reference=SimpleNamespace(registration_revision=1),
        ),
    )
    grade = SimpleNamespace(revision_sha256=C)

    def make_candidate(revision: int) -> AttemptSelectionPolicy:
        return AttemptSelectionPolicy(
            schema_version=ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
            record_type=ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
            class_id="class_one",
            grade_item_id="grade_1",
            work=work,
            policy_id=preset.policy_id,
            policy_revision=revision,
            supersedes_revision=None if revision == 1 else revision - 1,
            selection_basis="explicit",
            minimum_selected=1,
            maximum_selected=1,
            actor=AttemptSelectionActor(kind="teacher", actor_id="teacher_one"),
            rationale=preset.description,
            revised_at=datetime(2026, 10, 18, 14, 30, tzinfo=UTC),
        )

    def record(candidate: AttemptSelectionPolicy) -> SimpleNamespace:
        content = attempt_selection_policy_to_json_bytes(candidate)
        return SimpleNamespace(
            policy=candidate,
            policy_sha256=hashlib.sha256(content).hexdigest(),
            content=content,
        )

    def history(*_args):
        return tuple(sorted(stored))

    def loaded(*args):
        return stored[args[-1]]

    def current(*_args):
        return None if current_revision is None else stored[current_revision]

    def authoring_preview(_root, _class, _item, _work, _id, **kwargs):
        rev = len(stored) + 1
        candidate = make_candidate(rev)
        return AttemptPolicyAuthoringPreview(
            operation=kwargs["operation"],
            candidate=candidate,
            history=tuple(sorted(stored)),
            latest_persisted_policy_sha256=(
                None if not stored else stored[max(stored)].policy_sha256
            ),
            reviewed_current_policy_revision=current_revision,
        )

    def authoring_commit(_root, preview):
        rev = preview.candidate.policy_revision
        stored[rev] = record(preview.candidate)
        written.append(rev)
        if crash["after_write"]:
            raise OSError("Synthetic crash after durable policy authoring")
        return SimpleNamespace(
            write_result=SimpleNamespace(disposition="created", stored=stored[rev])
        )

    def selection_preview(_root, _class, _item, _work, _policy, revision):
        return SimpleNamespace(
            target_sha256=stored[revision].policy_sha256,
            expected_current_policy_revision=current_revision,
            history=tuple(sorted(stored)),
        )

    def selection_commit(_root, preview):
        nonlocal current_revision
        target = next(
            number
            for number, stored_value in stored.items()
            if stored_value.policy_sha256 == preview.target_sha256
        )
        if current_revision != preview.expected_current_policy_revision:
            raise TeacherActionConflictError("Synthetic CAS race")
        disposition = "created" if current_revision is None else "updated"
        current_revision = target
        selected.append(target)
        return SimpleNamespace(
            selected_policy_sha256=stored[target].policy_sha256,
            selection_disposition=disposition,
        )

    def member(*_args):
        return None if stale["membership"] else membership

    def grade_loader(*_args):
        return None if stale["grade"] else grade

    def calendar(*_args):
        return A if not stale["calendar"] else "f" * 64

    monkeypatch.setattr(
        policy_action, "list_attempt_selection_policy_revisions", history
    )
    monkeypatch.setattr(policy_action, "load_attempt_selection_policy_revision", loaded)
    monkeypatch.setattr(policy_action, "load_current_attempt_selection_policy", current)
    monkeypatch.setattr(
        policy_action, "load_current_grade_item_membership_decision", member
    )
    monkeypatch.setattr(policy_action, "load_current_grade_item_revision", grade_loader)
    monkeypatch.setattr(
        policy_action,
        "validate_grade_item_membership_dependencies",
        lambda *_: None,
    )
    monkeypatch.setattr(
        policy_action,
        "get_current_academic_work_registration_revision",
        lambda *_: 1,
    )
    monkeypatch.setattr(policy_action, "_calendar_digest", calendar)
    monkeypatch.setattr(
        policy_action, "_actor_now", lambda actor: checks.append(actor.actor_id)
    )
    dependencies = GuidedAttemptDependencies(
        policy_authoring_previewer=authoring_preview,
        policy_authoring_committer=authoring_commit,
        policy_selection_previewer=selection_preview,
        policy_selection_committer=selection_commit,
        clock=lambda: datetime(2026, 10, 18, 14, 30, tzinfo=UTC),
    )

    def prepare(mode: str = "create"):
        plan = GuidedAttemptPolicyPlan(
            mode, preset, max(stored) if mode == "select_existing" else None
        )
        return prepare_attempt_policy_action(
            tmp_path,
            class_id="class_one",
            grade_item_id="grade_1",
            work=work,
            plan=plan,
            actor=TeacherActionActor("teacher_one", A, "saved"),
            dependencies=dependencies,
        )

    def seed(revision: int, *, make_current: bool = False) -> None:
        nonlocal current_revision
        stored[revision] = record(make_candidate(revision))
        if make_current:
            current_revision = revision

    return SimpleNamespace(
        root=tmp_path,
        prepare=prepare,
        seed=seed,
        stored=stored,
        selected=selected,
        written=written,
        stale=stale,
        crash=crash,
        checks=checks,
        current=lambda: current_revision,
    )


def test_create_one_confirm_writes_selects_and_verifies(example) -> None:
    action = example.prepare()
    result = action.apply(confirmed=True)
    assert result.succeeded and result.status == "applied"
    assert example.written == [1] and example.selected == [1]
    assert example.current() == 1
    assert example.checks


def test_cancel_before_write_leaves_no_receipt(example) -> None:
    action = example.prepare()
    result = action.apply(confirmed=False)
    assert result.status == "blocked_before_write"
    assert not example.written and not example.selected


def test_existing_matching_policy_selects_without_writing(example) -> None:
    example.seed(1)
    action = example.prepare("select_existing")
    result = action.apply(confirmed=True)
    assert result.succeeded and result.status == "applied"
    assert example.written == [] and example.selected == [1]
    journal = action.store.load(action.preview.action_id)
    assert journal is not None
    assert journal.checkpoints[-1].stage == "receipt_finalized"


def test_revise_writes_next_exact_revision(example) -> None:
    example.seed(1, make_current=True)
    action = example.prepare("revise")
    assert action.apply(confirmed=True).succeeded
    assert example.written == [2]
    assert example.current() == 2


def test_repeat_does_not_duplicate_policy_revision(example) -> None:
    action = example.prepare()
    assert action.apply(confirmed=True).succeeded
    repeat = action.apply(confirmed=True)
    assert repeat.status == "already_applied"
    assert example.written == [1]


@pytest.mark.parametrize("cause", ["membership", "grade", "calendar"])
def test_changed_scope_fails_closed(example, cause: str) -> None:
    action = example.prepare()
    example.stale[cause] = True
    result = action.apply(confirmed=True)
    assert not result.succeeded
    assert example.written == [] and example.selected == []


def test_ready_policy_requires_no_mutation(example) -> None:
    with pytest.raises(TeacherActionConflictError, match="no Save"):
        example.prepare("ready")


def test_policy_write_interruption_does_not_select_unreviewed_revision(
    example, monkeypatch: pytest.MonkeyPatch
) -> None:
    action = example.prepare()
    # A later Grade Item change after preview must stop before write.
    example.stale["grade"] = True
    assert not action.apply(confirmed=True).succeeded
    assert example.written == [] and example.selected == []


def test_no_direct_legacy_policy_write_in_routine_menu() -> None:
    import inspect

    import meridian.menu_teacher_attempts as menu

    routine = inspect.getsource(menu.run_guided_attempt_menu)
    assert "prepare_attempt_policy_action(" in routine
    assert "apply_guided_attempt_policy(" not in routine
    assert routine.count("_review_apply(") >= 2


def test_crash_after_immutable_policy_write_recovers_without_duplicate(example) -> None:
    action = example.prepare()
    example.crash["after_write"] = True
    result = action.apply(confirmed=True)
    assert result.status == "written_not_current"
    assert example.written == [1] and example.selected == []
    example.crash["after_write"] = False
    resumed = action.resume(confirmed=True)
    assert resumed.succeeded
    assert example.written == [1] and example.selected == [1]


def test_recovery_requires_explicit_confirmation(example) -> None:
    action = example.prepare()
    example.crash["after_write"] = True
    assert not action.apply(confirmed=True).succeeded
    canceled = action.resume(confirmed=False)
    assert canceled.status == "blocked_before_write"
    assert not example.selected


def test_existing_policy_cancel_never_creates_receipt_or_changes_pointer(
    example,
) -> None:
    example.seed(1)
    action = example.prepare("select_existing")
    assert action.apply(confirmed=False).status == "blocked_before_write"
    assert action.store.load(action.preview.action_id) is None
    assert example.written == example.selected == []


def test_existing_policy_invalidated_grade_item_never_selects(example) -> None:
    example.seed(1)
    action = example.prepare("select_existing")
    example.stale["grade"] = True
    result = action.apply(confirmed=True)
    assert not result.succeeded
    assert example.selected == example.written == []
    assert action.store.load(action.preview.action_id) is None


def test_existing_policy_missing_canonical_revision_never_selects(example) -> None:
    example.seed(1)
    action = example.prepare("select_existing")
    example.stored.clear()
    result = action.apply(confirmed=True)
    assert not result.succeeded
    assert example.selected == example.written == []


def test_existing_policy_repeat_is_already_applied_without_another_select(
    example,
) -> None:
    example.seed(1)
    action = example.prepare("select_existing")
    assert action.apply(confirmed=True).status == "applied"
    assert action.apply(confirmed=True).status == "already_applied"
    assert example.written == [] and example.selected == [1]
