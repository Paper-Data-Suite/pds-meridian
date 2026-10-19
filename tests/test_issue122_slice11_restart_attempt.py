"""#122 Slice 11: exact, freshly authorized attempt-decision recovery."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionCheckpoint,
    TeacherActionPreview,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_guided import _identity
from meridian.teacher_action_orchestration import TeacherActionConflictError
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_action_restart_attempt import (
    _RestartAttemptPort,
    inspect_restart_attempt,
    resume_restart_attempt,
)

A, B, C, G = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)


def _preview(root: Path, source: str = "saved") -> TeacherActionPreview:
    actor = TeacherActionActor("teacher_1", A, source)
    identity = _identity(
        "attempt_decision", "class_one", "grade_one", "scoreform", "work_1", "00001"
    )
    return TeacherActionPreview(
        action_id="ad" * 16,
        kind="attempt_decision",
        scope=TeacherActionScope(
            _identity("workspace", str(root)),
            "class_one",
            "grade_one",
            school_year="2026-2027",
            academic_period_id="mp1",
            calendar_sha256=B,
            work_identity_sha256=_identity("work", "class_one", "scoreform", "work_1"),
        ),
        actor=actor,
        target=TeacherActionTarget("attempt_decision", identity, 1, C, None, None),
        basis=(
            TeacherActionBasis("actor_profile", _identity(actor.actor_id), A),
            TeacherActionBasis(
                "canonical_source",
                identity,
                _identity("attempt_source", "pub_1", B, G, G, G),
            ),
        ),
        reviewed_decision_sha256=C,
    )


@pytest.fixture
def example(tmp_path: Path, monkeypatch):
    import meridian.teacher_action_restart_attempt as restart

    root = tmp_path
    (root / "classes" / "class_one").mkdir(parents=True)
    store = TeacherActionReceiptStore(root, "class_one")
    preview = _preview(root)
    receipt = store.prepare(preview)
    receipt = store.record_checkpoint(
        preview,
        expected_generation=receipt.generation,
        checkpoint=TeacherActionCheckpoint("write", "completed"),
    )
    work = SimpleNamespace(
        class_id="class_one", module_id="scoreform", work_id="work_1"
    )
    source = SimpleNamespace(
        work=work, publication_id="pub_1", cache_key=B, snapshot_digest=G
    )
    policy_ref = SimpleNamespace(
        policy_id="policy_1", policy_revision=1, policy_revision_sha256=G
    )
    period = SimpleNamespace(school_year="2026-2027", period_id="mp1")
    membership = SimpleNamespace(
        decision_sha256=G,
        decision=SimpleNamespace(
            decision="included",
            membership_revision=1,
            grade_item_revision=1,
            grade_item_revision_sha256=G,
            work_reference=SimpleNamespace(registration_revision=1),
            academic_period=SimpleNamespace(period=period, calendar_revision=1),
        ),
    )
    decision = SimpleNamespace(
        class_id="class_one",
        grade_item_id="grade_one",
        work=work,
        student_id="00001",
        decision_revision=1,
        actor=SimpleNamespace(kind="teacher", actor_id="teacher_1"),
        membership_revision=1,
        membership_revision_sha256=G,
        policy=policy_ref,
        source_snapshot=source,
        candidates=("candidate_1",),
    )
    state = {
        "works": (work,),
        "students": ("00001",),
        "history": (1,),
        "digest": C,
        "decision": decision,
        "membership": membership,
        "current": None,
        "calendar": B,
        "grade_revision": 1,
        "grade_digest": G,
        "registration": 1,
        "allowed": True,
        "policy_revision": 1,
        "policy_digest": G,
        "candidate_status": "applicable",
        "candidates": decision.candidates,
        "selections": 0,
        "auth_reads": 0,
        "writes": 0,
    }

    def stored():
        return SimpleNamespace(
            decision=state["decision"], decision_sha256=state["digest"]
        )

    def auth(_root: Path, _source: object):
        state["auth_reads"] += 1
        if not state["allowed"]:
            raise TeacherActionConflictError("Authorization denied")
        return SimpleNamespace(
            assessment=SimpleNamespace(reusable_for_current_use=True)
        )

    monkeypatch.setattr(
        restart, "list_grade_item_membership_work_refs", lambda *_: state["works"]
    )
    monkeypatch.setattr(
        restart,
        "load_roster",
        lambda *_: SimpleNamespace(
            class_id="class_one",
            students=tuple(SimpleNamespace(student_id=s) for s in state["students"]),
        ),
    )
    monkeypatch.setattr(
        restart,
        "list_attempt_selection_decision_revisions",
        lambda *_: state["history"],
    )
    monkeypatch.setattr(
        restart, "load_attempt_selection_decision_revision", lambda *_: stored()
    )
    monkeypatch.setattr(
        restart, "load_current_attempt_selection_decision", lambda *_: state["current"]
    )
    monkeypatch.setattr(
        restart,
        "load_current_grade_item_membership_decision",
        lambda *_: state["membership"],
    )
    monkeypatch.setattr(
        restart, "validate_grade_item_membership_dependencies", lambda *_: None
    )
    monkeypatch.setattr(
        restart,
        "get_current_academic_work_registration_revision",
        lambda *_: state["registration"],
    )
    monkeypatch.setattr(restart, "_calendar_digest", lambda *_: state["calendar"])
    monkeypatch.setattr(
        restart,
        "load_current_grade_item_revision",
        lambda *_: SimpleNamespace(
            revision=SimpleNamespace(grade_item_revision=state["grade_revision"]),
            revision_sha256=state["grade_digest"],
        ),
    )
    monkeypatch.setattr(
        restart,
        "load_current_attempt_selection_policy",
        lambda *_: SimpleNamespace(
            policy=SimpleNamespace(policy_revision=state["policy_revision"]),
            policy_sha256=state["policy_digest"],
        ),
    )
    monkeypatch.setattr(
        restart,
        "derive_attempt_candidates",
        lambda *_: SimpleNamespace(
            status=state["candidate_status"],
            source_snapshot=source,
            candidates=state["candidates"],
        ),
    )
    monkeypatch.setattr(
        restart,
        "preview_attempt_decision_selection",
        lambda *_a, **_kw: SimpleNamespace(
            target_sha256=state["digest"],
            expected_current_decision_revision=(
                None if state["current"] is None else 1
            ),
            history=state["history"],
        ),
    )

    def commit(_root: Path, _preview: object, **_kw):
        state["selections"] += 1
        state["current"] = stored()
        return SimpleNamespace(
            selected_decision_sha256=C, selection_disposition="created"
        )

    monkeypatch.setattr(restart, "commit_attempt_decision_selection_preview", commit)
    return root, store, receipt, state, auth


def actor_ok(_: TeacherActionActor) -> None:
    return None


def test_exact_inspection_is_read_only(example) -> None:
    root, store, receipt, state, auth = example
    inspection = inspect_restart_attempt(
        root, store, receipt, authorized_loader=auth, actor_checker=actor_ok
    )
    assert inspection.status == "written_not_current"
    assert inspection.can_resume
    assert state["selections"] == state["writes"] == 0
    assert state["auth_reads"] > 0


def test_exact_resume_selects_only_existing_decision(example) -> None:
    root, store, receipt, state, auth = example
    outcome = resume_restart_attempt(
        root,
        store,
        receipt,
        confirmation="RESUME",
        authorized_loader=auth,
        actor_checker=actor_ok,
    )
    assert outcome.succeeded
    assert state["selections"] == 1
    assert state["writes"] == 0
    assert state["history"] == (1,)


def test_cancellation_is_side_effect_free(example) -> None:
    root, store, receipt, state, auth = example
    with pytest.raises(TeacherActionConflictError, match="not confirmed"):
        resume_restart_attempt(
            root,
            store,
            receipt,
            confirmation="CANCEL",
            authorized_loader=auth,
            actor_checker=actor_ok,
        )
    assert state["auth_reads"] == state["selections"] == 0


def test_restart_port_has_no_immutable_writer(example) -> None:
    root, _store, receipt, _, auth = example
    port = _RestartAttemptPort(root, receipt, auth, actor_ok)
    with pytest.raises(TeacherActionConflictError, match="cannot write"):
        port.persist_exact(receipt.preview)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("works", ()),
        ("students", ()),
        ("history", (1, 2)),
        ("digest", A),
        ("calendar", A),
        ("grade_revision", 2),
        ("grade_digest", A),
        ("registration", 2),
        ("policy_revision", 2),
        ("policy_digest", A),
        ("candidate_status", "source_unverifiable"),
        ("candidates", ()),
        ("allowed", False),
    ],
)
def test_changed_basis_blocks_without_selection(
    example, field: str, bad: object
) -> None:
    root, store, receipt, state, auth = example
    state[field] = bad
    with pytest.raises(TeacherActionConflictError):
        inspect_restart_attempt(
            root,
            store,
            receipt,
            authorized_loader=auth,
            actor_checker=actor_ok,
        )
    assert state["selections"] == 0


def test_profile_replacement_fails_closed(example) -> None:
    root, store, receipt, state, auth = example

    def changed(_: TeacherActionActor) -> None:
        raise TeacherActionConflictError("Actor profile changed")

    with pytest.raises(TeacherActionConflictError, match="profile changed"):
        inspect_restart_attempt(
            root, store, receipt, authorized_loader=auth, actor_checker=changed
        )
    assert state["selections"] == 0


def test_temporary_attribution_does_not_rehydrate(example) -> None:
    root, _store, receipt, _, auth = example
    modified = replace(
        receipt.preview, actor=replace(receipt.preview.actor, source="temporary")
    )
    with pytest.raises(TeacherActionConflictError, match="temporary"):
        _RestartAttemptPort(root, replace(receipt, preview=modified), auth, actor_ok)


def test_receipt_generation_change_blocks(example) -> None:
    root, store, receipt, state, auth = example
    store.record_checkpoint(
        receipt.preview,
        expected_generation=receipt.generation,
        checkpoint=TeacherActionCheckpoint("selection_preview", "completed"),
    )
    with pytest.raises(TeacherActionConflictError, match="Journal changed"):
        inspect_restart_attempt(
            root,
            store,
            receipt,
            authorized_loader=auth,
            actor_checker=actor_ok,
        )
    assert state["selections"] == 0


def test_previously_applied_decision_is_not_selected_again(example) -> None:
    root, store, receipt, state, auth = example
    state["current"] = SimpleNamespace(decision=state["decision"], decision_sha256=C)
    inspected = inspect_restart_attempt(
        root, store, receipt, authorized_loader=auth, actor_checker=actor_ok
    )
    assert inspected.status == "already_applied"
    assert not inspected.can_resume
    assert state["selections"] == 0


def test_changed_actor_in_saved_decision_blocks(example) -> None:
    root, store, receipt, state, auth = example
    state["decision"].actor.actor_id = "another_teacher"
    with pytest.raises(TeacherActionConflictError):
        inspect_restart_attempt(
            root, store, receipt, authorized_loader=auth, actor_checker=actor_ok
        )
    assert state["selections"] == 0


def test_unexpected_selector_digest_never_selects(example, monkeypatch) -> None:
    import meridian.teacher_action_restart_attempt as restart

    root, store, receipt, state, auth = example
    monkeypatch.setattr(
        restart,
        "preview_attempt_decision_selection",
        lambda *_a, **_kw: SimpleNamespace(
            target_sha256=A,
            expected_current_decision_revision=None,
            history=(1,),
        ),
    )
    result = resume_restart_attempt(
        root,
        store,
        receipt,
        confirmation="RESUME",
        authorized_loader=auth,
        actor_checker=actor_ok,
    )
    assert not result.succeeded
    assert state["selections"] == 0


def test_recovery_menu_without_authorization_does_not_inspect(monkeypatch) -> None:
    from io import StringIO

    import meridian.menu_teacher_action_recovery as menu

    output = StringIO()
    called: list[str] = []
    monkeypatch.setattr(
        menu,
        "inspect_restart_attempt",
        lambda *_a, **_kw: called.append("inspected"),
    )
    menu._offer_attempt_resume(
        Path("workspace"),
        SimpleNamespace(),
        SimpleNamespace(receipt=object()),
        diagnostics=None,
        input_fn=lambda _: "RESUME",
        output=output,
    )
    assert "Set Up Evidence Access" in output.getvalue()
    assert not called


@pytest.mark.parametrize("reply", ["CANCEL", "", "resume", "2"])
def test_recovery_menu_requires_exact_resume(monkeypatch, reply: str) -> None:
    from io import StringIO

    import meridian.menu_teacher_action_recovery as menu

    output = StringIO()
    attempts: list[str] = []
    monkeypatch.setattr(
        menu,
        "inspect_restart_attempt",
        lambda *_a, **_kw: SimpleNamespace(
            can_resume=True,
        ),
    )
    monkeypatch.setattr(
        menu,
        "resume_restart_attempt",
        lambda *_a, **_kw: attempts.append("selected"),
    )
    monkeypatch.setattr(
        menu,
        "load_fresh_restart_attempt_authorization",
        lambda *_a, **_kw: SimpleNamespace(),
    )
    menu._offer_attempt_resume(
        Path("workspace"),
        SimpleNamespace(),
        SimpleNamespace(receipt=object()),
        diagnostics=SimpleNamespace(authorizer=object()),
        input_fn=lambda _: reply,
        output=output,
    )
    assert not attempts
    assert "Canceled" in output.getvalue()


def test_recovery_menu_no_resume_if_canonical_state_changed(monkeypatch) -> None:
    from io import StringIO

    import meridian.menu_teacher_action_recovery as menu

    output = StringIO()
    attempts: list[str] = []
    monkeypatch.setattr(
        menu,
        "inspect_restart_attempt",
        lambda *_a, **_kw: SimpleNamespace(
            can_resume=False,
        ),
    )
    monkeypatch.setattr(
        menu,
        "resume_restart_attempt",
        lambda *_a, **_kw: attempts.append("selected"),
    )
    menu._offer_attempt_resume(
        Path("workspace"),
        SimpleNamespace(),
        SimpleNamespace(receipt=object()),
        diagnostics=SimpleNamespace(authorizer=object()),
        input_fn=lambda _: "RESUME",
        output=output,
    )
    assert not attempts
    assert "not eligible" in output.getvalue()
