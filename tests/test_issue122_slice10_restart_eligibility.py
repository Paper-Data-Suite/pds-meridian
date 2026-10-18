"""#122 Slice 10: exact eligibility recovery only with fresh authorization."""

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
from meridian.teacher_action_restart_eligibility import (
    _RestartEligibilityPort,
    inspect_restart_eligibility,
    resume_restart_eligibility,
)

A, B, C, G = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)


def _preview(root: Path, source: str = "saved") -> TeacherActionPreview:
    actor = TeacherActionActor("teacher_1", A, source)
    ident = _identity(
        "eligibility",
        "class_one",
        "grade_one",
        "scoreform",
        "work_1",
        "pub_1",
        "item_1",
    )
    return TeacherActionPreview(
        action_id="ed" * 16,
        kind="eligibility",
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
        target=TeacherActionTarget("eligibility", ident, 1, C, None, None),
        basis=(
            TeacherActionBasis("actor_profile", _identity(actor.actor_id), A),
            TeacherActionBasis(
                "canonical_source", ident, _identity("source", "pub_1", B, G, G)
            ),
        ),
        reviewed_decision_sha256=C,
    )


@pytest.fixture
def example(tmp_path: Path, monkeypatch):
    import meridian.teacher_action_restart_eligibility as restart

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
        work=work,
        publication_id="pub_1",
        item_id="item_1",
        cache_key=B,
        snapshot_digest=G,
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
        source=source,
        eligibility_revision=1,
        membership_revision=1,
        membership_revision_sha256=G,
        actor=SimpleNamespace(kind="teacher", actor_id="teacher_1"),
    )
    state = {
        "works": (work,),
        "sources": (source,),
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
        "selections": 0,
        "authorized_reads": 0,
        "dependency_checks": 0,
    }

    def stored():
        return SimpleNamespace(
            decision=state["decision"], decision_sha256=state["digest"]
        )

    def auth(_root: Path, _source: object):
        state["authorized_reads"] += 1
        if not state["allowed"]:
            raise TeacherActionConflictError("Authorization denied")
        return SimpleNamespace(
            assessment=SimpleNamespace(reusable_for_current_use=True)
        )

    monkeypatch.setattr(
        restart, "list_grade_item_membership_work_refs", lambda *_: state["works"]
    )
    monkeypatch.setattr(
        restart, "list_evidence_eligibility_sources", lambda *_: state["sources"]
    )
    monkeypatch.setattr(
        restart, "list_evidence_eligibility_revisions", lambda *_: state["history"]
    )
    monkeypatch.setattr(
        restart, "load_evidence_eligibility_revision", lambda *_: stored()
    )
    monkeypatch.setattr(
        restart,
        "load_current_evidence_eligibility_decision",
        lambda *_: state["current"],
    )
    monkeypatch.setattr(
        restart,
        "load_current_grade_item_membership_decision",
        lambda *_: state["membership"],
    )
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
        "get_current_academic_work_registration_revision",
        lambda *_: state["registration"],
    )
    monkeypatch.setattr(restart, "_calendar_digest", lambda *_: state["calendar"])
    monkeypatch.setattr(
        restart, "validate_grade_item_membership_dependencies", lambda *_: None
    )
    monkeypatch.setattr(
        restart,
        "validate_evidence_eligibility_dependencies",
        lambda *_a, **_k: state.__setitem__(
            "dependency_checks", state["dependency_checks"] + 1
        ),
    )
    monkeypatch.setattr(
        restart, "project_new_evidence_review", lambda *_: SimpleNamespace()
    )
    monkeypatch.setattr(
        restart,
        "preview_new_evidence_eligibility_selection",
        lambda *_a, **_k: SimpleNamespace(
            target=stored(),
            expected_current_revision=None if state["current"] is None else 1,
        ),
    )

    def commit(_root: Path, _preview: object, _authorized: object):
        state["selections"] += 1
        state["current"] = stored()
        return SimpleNamespace(
            selection_result=SimpleNamespace(stored=stored()),
            selection_disposition="created",
        )

    monkeypatch.setattr(
        restart, "commit_new_evidence_eligibility_selection_preview", commit
    )
    return root, store, receipt, state, auth


def accept(_: TeacherActionActor) -> None:
    return None


def test_read_only_inspection_requires_current_authorization(example) -> None:
    root, store, receipt, state, auth = example
    status = inspect_restart_eligibility(
        root, store, receipt, authorized_loader=auth, actor_checker=accept
    )
    assert status.can_resume and status.status == "written_not_current"
    assert state["authorized_reads"] >= 2
    assert state["dependency_checks"] >= 2
    assert state["selections"] == 0


def test_exact_resume_selects_no_new_revision(example) -> None:
    root, store, receipt, state, auth = example
    result = resume_restart_eligibility(
        root,
        store,
        receipt,
        confirmation="RESUME",
        authorized_loader=auth,
        actor_checker=accept,
    )
    assert result.succeeded
    assert state["selections"] == 1
    assert state["history"] == (1,)


def test_cancel_has_zero_changes(example) -> None:
    root, store, receipt, state, auth = example
    with pytest.raises(TeacherActionConflictError, match="not confirmed"):
        resume_restart_eligibility(
            root,
            store,
            receipt,
            confirmation="CANCEL",
            authorized_loader=auth,
            actor_checker=accept,
        )
    assert state["selections"] == 0
    assert state["authorized_reads"] == 0


def test_port_cannot_write(example) -> None:
    root, _store, receipt, _, auth = example
    port = _RestartEligibilityPort(root, receipt, auth, accept)
    with pytest.raises(TeacherActionConflictError, match="cannot author"):
        port.persist_exact(receipt.preview)


@pytest.mark.parametrize(
    "kind",
    [
        "works",
        "sources",
        "history",
        "digest",
        "calendar",
        "grade_revision",
        "grade_digest",
        "registration",
        "allowed",
    ],
)
def test_stale_or_missing_source_fails_closed(example, kind: str) -> None:
    root, store, receipt, state, auth = example
    changes = {
        "works": (),
        "sources": (),
        "history": (1, 2),
        "digest": A,
        "calendar": A,
        "grade_revision": 2,
        "grade_digest": A,
        "registration": 2,
        "allowed": False,
    }
    state[kind] = changes[kind]
    with pytest.raises(TeacherActionConflictError):
        inspect_restart_eligibility(
            root, store, receipt, authorized_loader=auth, actor_checker=accept
        )
    assert state["selections"] == 0


def test_changed_membership_fails(example) -> None:
    root, store, receipt, state, auth = example
    state["membership"] = None
    with pytest.raises(TeacherActionConflictError, match="relationship changed"):
        inspect_restart_eligibility(
            root, store, receipt, authorized_loader=auth, actor_checker=accept
        )


def test_changed_actor_profile_fails_closed(example) -> None:
    root, store, receipt, state, auth = example

    def reject(_: TeacherActionActor) -> None:
        raise TeacherActionConflictError("Changed profile")

    with pytest.raises(TeacherActionConflictError, match="Changed profile"):
        inspect_restart_eligibility(
            root, store, receipt, authorized_loader=auth, actor_checker=reject
        )
    assert state["selections"] == 0


def test_temporary_actor_refused(example) -> None:
    root, _store, receipt, _, auth = example
    changed = replace(
        receipt.preview, actor=replace(receipt.preview.actor, source="temporary")
    )
    with pytest.raises(TeacherActionConflictError, match="Temporary"):
        _RestartEligibilityPort(root, replace(receipt, preview=changed), auth, accept)


def test_changed_receipt_generation_refused(example) -> None:
    root, store, receipt, state, auth = example
    store.record_checkpoint(
        receipt.preview,
        expected_generation=receipt.generation,
        checkpoint=TeacherActionCheckpoint("selection_preview", "completed"),
    )
    with pytest.raises(TeacherActionConflictError, match="Receipt changed"):
        inspect_restart_eligibility(
            root, store, receipt, authorized_loader=auth, actor_checker=accept
        )
    assert state["selections"] == 0


def test_source_binding_mismatch_refused(example) -> None:
    root, store, receipt, state, auth = example
    state["decision"].membership_revision_sha256 = A
    with pytest.raises(TeacherActionConflictError):
        inspect_restart_eligibility(
            root, store, receipt, authorized_loader=auth, actor_checker=accept
        )


def test_already_selected_is_not_replayed(example) -> None:
    root, store, receipt, state, auth = example
    state["current"] = SimpleNamespace(decision=state["decision"], decision_sha256=C)
    status = inspect_restart_eligibility(
        root, store, receipt, authorized_loader=auth, actor_checker=accept
    )
    assert status.status == "already_applied" and not status.can_resume
    assert state["selections"] == 0


def test_would_reject_wrong_selector_digest(example, monkeypatch) -> None:
    import meridian.teacher_action_restart_eligibility as module

    root, store, receipt, state, auth = example
    monkeypatch.setattr(
        module,
        "preview_new_evidence_eligibility_selection",
        lambda *_a, **_k: SimpleNamespace(
            target=SimpleNamespace(decision_sha256=A),
            expected_current_revision=None,
        ),
    )
    result = resume_restart_eligibility(
        root,
        store,
        receipt,
        confirmation="RESUME",
        authorized_loader=auth,
        actor_checker=accept,
    )
    assert not result.succeeded
    assert state["selections"] == 0


def test_recovery_menu_requires_configured_access(monkeypatch) -> None:
    from io import StringIO

    import meridian.menu_teacher_action_recovery as menu

    output = StringIO()
    calls: list[str] = []
    monkeypatch.setattr(
        menu, "inspect_restart_eligibility", lambda *a, **k: calls.append("inspect")
    )
    menu._offer_eligibility_resume(
        Path("/workspace"),
        object(),
        SimpleNamespace(receipt=object()),
        diagnostics=None,
        input_fn=lambda _: "RESUME",
        output=output,
    )
    assert "Set Up Evidence Access" in output.getvalue()
    assert not calls


def test_recovery_menu_requires_explicit_confirmation(monkeypatch) -> None:
    from io import StringIO

    import meridian.menu_teacher_action_recovery as menu

    output = StringIO()
    calls: list[str] = []
    monkeypatch.setattr(
        menu, "load_fresh_restart_authorization", lambda *a: SimpleNamespace()
    )
    monkeypatch.setattr(
        menu,
        "inspect_restart_eligibility",
        lambda *a, **k: SimpleNamespace(can_resume=True),
    )
    monkeypatch.setattr(
        menu, "resume_restart_eligibility", lambda *a, **k: calls.append("select")
    )
    menu._offer_eligibility_resume(
        Path("/workspace"),
        object(),
        SimpleNamespace(receipt=object()),
        diagnostics=SimpleNamespace(authorizer=object()),
        input_fn=lambda _: "CANCEL",
        output=output,
    )
    assert "Canceled" in output.getvalue()
    assert not calls


def test_recovery_menu_denied_access_never_selects(monkeypatch) -> None:
    from io import StringIO

    import meridian.menu_teacher_action_recovery as menu

    output = StringIO()
    calls: list[str] = []

    def denied(*a, **k):
        raise TeacherActionConflictError("Access denied")

    monkeypatch.setattr(menu, "inspect_restart_eligibility", denied)
    monkeypatch.setattr(
        menu, "resume_restart_eligibility", lambda *a, **k: calls.append("select")
    )
    menu._offer_eligibility_resume(
        Path("/workspace"),
        object(),
        SimpleNamespace(receipt=object()),
        diagnostics=SimpleNamespace(authorizer=object()),
        input_fn=lambda _: "RESUME",
        output=output,
    )
    assert "could not be verified" in output.getvalue()
    assert not calls


def test_fresh_authorization_refuses_missing_provider(monkeypatch) -> None:
    import meridian.teacher_action_restart_eligibility as restart

    calls: list[str] = []
    monkeypatch.setattr(
        restart,
        "load_authorized_projection_snapshot",
        lambda *_a, **_k: calls.append("read"),
    )
    diag = SimpleNamespace(
        authorizer=None, producer_registry_state="available", producer_registry=object()
    )
    with pytest.raises(TeacherActionConflictError, match="Current authorized"):
        restart.load_fresh_restart_authorization(
            Path("/workspace"), SimpleNamespace(), diag
        )
    assert not calls


def test_fresh_authorization_rejects_noncurrent_projection(monkeypatch) -> None:
    import meridian.teacher_action_restart_eligibility as restart

    snapshot = SimpleNamespace(
        assessment=SimpleNamespace(reusable_for_current_use=False)
    )
    monkeypatch.setattr(
        restart, "load_authorized_projection_snapshot", lambda *_a, **_k: snapshot
    )
    diag = SimpleNamespace(
        authorizer=object(),
        producer_registry_state="available",
        producer_registry=object(),
        adapter_registry=object(),
        distribution_version_resolver=object(),
    )
    source = SimpleNamespace(publication_id="pub_1", cache_key=B)
    with pytest.raises(TeacherActionConflictError, match="no longer current"):
        restart.load_fresh_restart_authorization(Path("/workspace"), source, diag)


def test_fresh_authorization_rejects_changed_snapshot(monkeypatch) -> None:
    import meridian.teacher_action_restart_eligibility as restart

    source = SimpleNamespace(
        publication_id="pub_1", cache_key=B, snapshot_digest=G, work=object()
    )
    snapshot = SimpleNamespace(
        assessment=SimpleNamespace(reusable_for_current_use=True),
        stored=SimpleNamespace(cache_key=B, snapshot_digest=A),
        current_context=SimpleNamespace(
            publication=SimpleNamespace(publication_id="pub_1", work=source.work)
        ),
    )
    monkeypatch.setattr(
        restart, "load_authorized_projection_snapshot", lambda *_a, **_k: snapshot
    )
    diag = SimpleNamespace(
        authorizer=object(),
        producer_registry_state="available",
        producer_registry=object(),
        adapter_registry=object(),
        distribution_version_resolver=object(),
    )
    with pytest.raises(TeacherActionConflictError, match="another source"):
        restart.load_fresh_restart_authorization(Path("/workspace"), source, diag)


def test_fresh_authorization_uses_exact_purpose_and_source(monkeypatch) -> None:
    import meridian.teacher_action_restart_eligibility as restart

    source = SimpleNamespace(
        publication_id="pub_1", cache_key=B, snapshot_digest=G, work=object()
    )
    authorized = SimpleNamespace(
        assessment=SimpleNamespace(reusable_for_current_use=True),
        stored=SimpleNamespace(cache_key=B, snapshot_digest=G),
        current_context=SimpleNamespace(
            publication=SimpleNamespace(publication_id="pub_1", work=source.work)
        ),
    )
    calls: list[tuple[object, object, object]] = []

    def load(*args, **kwargs):
        calls.append((args[1], args[2], kwargs["authorization_purpose_id"]))
        return authorized

    monkeypatch.setattr(restart, "load_authorized_projection_snapshot", load)
    diag = SimpleNamespace(
        authorizer=object(),
        producer_registry_state="available",
        producer_registry=object(),
        adapter_registry=object(),
        distribution_version_resolver=object(),
    )
    result = restart.load_fresh_restart_authorization(Path("/workspace"), source, diag)
    assert result is authorized
    assert calls == [("pub_1", B, restart.GUIDED_EVIDENCE_REVIEW_PURPOSE_ID)]
