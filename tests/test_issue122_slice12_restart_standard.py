"""#122 Slice 12: fail-closed exact Standards-association restart recovery."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
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
from meridian.teacher_action_restart_standard import (
    _RestartStandardPort,
    inspect_restart_standard,
    resume_restart_standard,
)

A, B, C, G = "a" * 64, "b" * 64, "c" * 64, "d" * 64
STD = "njsls-ela:RL.CR.11-12.1"


def _preview(root: Path, source_kind: str = "saved") -> TeacherActionPreview:
    actor = TeacherActionActor("teacher_1", A, source_kind)
    identity = _identity(
        "standard_association",
        "class_one",
        "grade_one",
        "scoreform",
        "work_1",
        "publication_1",
        "item_1",
        STD,
    )
    return TeacherActionPreview(
        action_id="ae" * 16,
        kind="standards_association",
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
        target=TeacherActionTarget("standards_association", identity, 1, C, None, None),
        basis=(
            TeacherActionBasis("actor_profile", _identity(actor.actor_id), A),
            TeacherActionBasis(
                "canonical_source",
                identity,
                _identity("standard_source", "publication_1", B, G, G, G, STD),
            ),
        ),
        reviewed_decision_sha256=C,
    )


@pytest.fixture
def example(tmp_path: Path, monkeypatch):
    import meridian.teacher_action_restart_standard as restart

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
        publication_id="publication_1",
        item_id="item_1",
        cache_key=B,
        snapshot_digest=G,
    )
    membership = SimpleNamespace(
        decision_sha256=G,
        decision=SimpleNamespace(
            decision="included",
            grade_item_revision=1,
            grade_item_revision_sha256=G,
            work_reference=SimpleNamespace(registration_revision=1),
            academic_period=SimpleNamespace(
                period=SimpleNamespace(school_year="2026-2027", period_id="mp1"),
                calendar_revision=1,
            ),
        ),
    )
    grade = SimpleNamespace(
        revision_sha256=G, revision=SimpleNamespace(grade_item_revision=1)
    )
    decision = SimpleNamespace(
        class_id="class_one",
        grade_item_id="grade_one",
        source=source,
        standard_id=STD,
        association_revision=1,
        actor=SimpleNamespace(kind="teacher", actor_id="teacher_1"),
    )
    state = {
        "identities": ((source, STD),),
        "history": (1,),
        "digest": C,
        "decision": decision,
        "membership": membership,
        "grade": grade,
        "calendar": B,
        "registration": 1,
        "authorized": True,
        "standard_resolved": True,
        "standard_active": True,
        "valid_source": True,
        "current": None,
        "selection": 0,
        "writes": 0,
        "auth_reads": 0,
    }

    def stored():
        return SimpleNamespace(
            decision=state["decision"], decision_sha256=state["digest"]
        )

    def authorized(_root: Path, _source: object):
        state["auth_reads"] += 1
        if not state["authorized"]:
            raise TeacherActionConflictError("Evidence authorization denied")
        return SimpleNamespace(
            assessment=SimpleNamespace(reusable_for_current_use=state["valid_source"])
        )

    monkeypatch.setattr(
        restart,
        "list_standard_evidence_association_identities",
        lambda *_a: state["identities"],
    )
    monkeypatch.setattr(
        restart,
        "list_standard_evidence_association_revisions",
        lambda *_a: state["history"],
    )
    monkeypatch.setattr(
        restart, "load_standard_evidence_association_revision", lambda *_a: stored()
    )
    monkeypatch.setattr(
        restart,
        "load_current_standard_evidence_association_decision",
        lambda *_a: state["current"],
    )
    monkeypatch.setattr(
        restart,
        "load_current_grade_item_membership_decision",
        lambda *_a: state["membership"],
    )
    monkeypatch.setattr(
        restart, "load_current_grade_item_revision", lambda *_a: state["grade"]
    )
    monkeypatch.setattr(restart, "_calendar_digest", lambda *_a: state["calendar"])
    monkeypatch.setattr(
        restart,
        "get_current_academic_work_registration_revision",
        lambda *_a: state["registration"],
    )
    monkeypatch.setattr(
        restart, "validate_grade_item_membership_dependencies", lambda *_a: None
    )

    def validate(_root, _decision, _authorized):
        if not state["standard_resolved"]:
            raise TeacherActionConflictError("Unresolved Standard")
        return SimpleNamespace(
            grade_item=state["grade"],
            membership=state["membership"],
            standard_resolution=SimpleNamespace(
                resolved=True, active=state["standard_active"]
            ),
        )

    monkeypatch.setattr(
        restart, "validate_standard_evidence_association_dependencies", validate
    )

    def select(_root, _class, _gi, _source, _standard, _revision, **kw):
        assert kw["expected_current_association_revision"] is None
        assert kw["authorized_snapshot"] is not None
        state["selection"] += 1
        state["current"] = stored()
        return SimpleNamespace(stored=stored(), disposition="created")

    monkeypatch.setattr(
        restart, "select_standard_evidence_association_revision", select
    )
    return root, store, receipt, state, authorized


def actor_ok(_: TeacherActionActor) -> None:
    pass


def test_inspection_is_read_only(example) -> None:
    root, store, receipt, state, authorized = example
    inspected = inspect_restart_standard(
        root, store, receipt, authorized_loader=authorized, actor_checker=actor_ok
    )
    assert inspected.can_resume
    assert inspected.status == "written_not_current"
    assert state["selection"] == state["writes"] == 0
    assert state["auth_reads"] > 0


def test_exact_resume_is_selection_only(example) -> None:
    root, store, receipt, state, authorized = example
    result = resume_restart_standard(
        root,
        store,
        receipt,
        confirmation="RESUME",
        authorized_loader=authorized,
        actor_checker=actor_ok,
    )
    assert result.succeeded
    assert state["selection"] == 1
    assert state["writes"] == 0
    assert state["history"] == (1,)


def test_cancel_is_side_effect_free(example) -> None:
    root, store, receipt, state, authorized = example
    with pytest.raises(TeacherActionConflictError, match="not confirmed"):
        resume_restart_standard(
            root,
            store,
            receipt,
            confirmation="CANCEL",
            authorized_loader=authorized,
            actor_checker=actor_ok,
        )
    assert state["auth_reads"] == state["selection"] == 0


def test_port_cannot_write_immutable_record(example) -> None:
    root, _, receipt, _, authorized = example
    with pytest.raises(TeacherActionConflictError, match="cannot write"):
        _RestartStandardPort(root, receipt, authorized, actor_ok).persist_exact(
            receipt.preview
        )


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("identities", ()),
        ("history", (1, 2)),
        ("digest", A),
        ("membership", None),
        ("calendar", A),
        ("grade", None),
        ("registration", 2),
        ("authorized", False),
        ("standard_resolved", False),
        ("standard_active", False),
        ("valid_source", False),
    ],
)
def test_changed_basis_fails_closed(example, field: str, bad: object) -> None:
    root, store, receipt, state, authorized = example
    state[field] = bad
    with pytest.raises((TeacherActionConflictError, AttributeError)):
        inspect_restart_standard(
            root, store, receipt, authorized_loader=authorized, actor_checker=actor_ok
        )
    assert state["selection"] == 0


def test_actor_profile_change_blocks(example) -> None:
    root, store, receipt, state, authorized = example

    def changed(_: TeacherActionActor) -> None:
        raise TeacherActionConflictError("Profile changed")

    with pytest.raises(TeacherActionConflictError, match="Profile changed"):
        inspect_restart_standard(
            root, store, receipt, authorized_loader=authorized, actor_checker=changed
        )
    assert state["selection"] == 0


def test_temporary_attribution_refused(example) -> None:
    root, _store, receipt, _, authorized = example
    changed = replace(
        receipt.preview, actor=replace(receipt.preview.actor, source="temporary")
    )
    with pytest.raises(TeacherActionConflictError):
        _RestartStandardPort(
            root, replace(receipt, preview=changed), authorized, actor_ok
        )


def test_inbox_receipt_generation_change_refused(example) -> None:
    root, store, receipt, state, authorized = example
    store.record_checkpoint(
        receipt.preview,
        expected_generation=receipt.generation,
        checkpoint=TeacherActionCheckpoint("selection_preview", "completed"),
    )
    with pytest.raises(TeacherActionConflictError, match="Journal changed"):
        inspect_restart_standard(
            root, store, receipt, authorized_loader=authorized, actor_checker=actor_ok
        )
    assert state["selection"] == 0


def test_already_selected_is_not_reselected(example) -> None:
    root, store, receipt, state, authorized = example
    state["current"] = SimpleNamespace(
        decision=state["decision"],
        decision_sha256=C,
    )
    result = inspect_restart_standard(
        root, store, receipt, authorized_loader=authorized, actor_checker=actor_ok
    )
    assert result.status == "already_applied"
    assert not result.can_resume
    assert state["selection"] == 0


def test_persisted_actor_mismatch_fails(example) -> None:
    root, store, receipt, state, authorized = example
    state["decision"].actor.actor_id = "other"
    with pytest.raises(TeacherActionConflictError):
        inspect_restart_standard(
            root, store, receipt, authorized_loader=authorized, actor_checker=actor_ok
        )
    assert state["selection"] == 0


def test_inbox_without_authorizer_does_not_inspect(monkeypatch) -> None:
    import meridian.menu_teacher_action_recovery as menu

    output = StringIO()
    called: list[str] = []
    monkeypatch.setattr(
        menu,
        "inspect_restart_standard",
        lambda *_a, **_k: called.append("inspected"),
    )
    menu._offer_standard_resume(
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
def test_menu_requires_exact_resume(monkeypatch, reply: str) -> None:
    import meridian.menu_teacher_action_recovery as menu

    output = StringIO()
    selection: list[str] = []
    monkeypatch.setattr(
        menu,
        "inspect_restart_standard",
        lambda *_a, **_k: SimpleNamespace(can_resume=True),
    )
    monkeypatch.setattr(
        menu, "resume_restart_standard", lambda *_a, **_k: selection.append("selected")
    )
    monkeypatch.setattr(
        menu,
        "load_fresh_restart_standard_authorization",
        lambda *_a, **_k: SimpleNamespace(),
    )
    menu._offer_standard_resume(
        Path("workspace"),
        SimpleNamespace(),
        SimpleNamespace(receipt=object()),
        diagnostics=SimpleNamespace(authorizer=object()),
        input_fn=lambda _: reply,
        output=output,
    )
    assert not selection
    assert "Canceled" in output.getvalue()


def test_identity_catalog_rejects_unknown_collection_entry(tmp_path: Path) -> None:
    from meridian import standards_evidence_storage as storage

    collection = (
        tmp_path / "classes" / "class_one" / "modules" / "meridian" / "std_assoc"
    )
    (collection / "unrecognized").mkdir(parents=True)
    with pytest.raises(storage.StandardsEvidenceStorageIntegrityError):
        storage.list_standard_evidence_association_identities(
            tmp_path, "class_one", "grade_one"
        )


def test_identity_catalog_refuses_invalid_bounded_count(tmp_path: Path) -> None:
    from meridian import standards_evidence_storage as storage

    with pytest.raises(storage.StandardsEvidenceStorageValidationError):
        storage.list_standard_evidence_association_identities(
            tmp_path, "class_one", "grade_one", maximum_relations=0
        )


def test_identity_catalog_uses_verified_first_revision(
    tmp_path: Path, monkeypatch
) -> None:
    import hashlib

    from meridian import standards_evidence_storage as storage

    key = "f" * 64
    collection = (
        tmp_path / "classes" / "class_one" / "modules" / "meridian" / "std_assoc"
    )
    (collection / key).mkdir(parents=True)
    work = SimpleNamespace(
        class_id="class_one", module_id="scoreform", work_id="work_1"
    )
    source = SimpleNamespace(
        work=work, publication_id="publication_1", item_id="item_1"
    )
    body = b"canonical-source-byte-string"
    digest = hashlib.sha256(body).hexdigest()
    monkeypatch.setattr(storage, "_read_revision_pair", lambda *_: (body, digest))
    monkeypatch.setattr(
        storage,
        "standard_evidence_association_from_json_bytes",
        lambda _: SimpleNamespace(
            association_revision=1,
            class_id="class_one",
            grade_item_id="grade_one",
            source=source,
            standard_id=STD,
        ),
    )
    monkeypatch.setattr(storage, "standard_evidence_association_key", lambda *_: key)
    assert storage.list_standard_evidence_association_identities(
        tmp_path, "class_one", "grade_one"
    ) == ((source, STD),)


def test_identity_catalog_rejects_digest_mismatch(tmp_path: Path, monkeypatch) -> None:
    from meridian import standards_evidence_storage as storage

    key = "f" * 64
    collection = (
        tmp_path / "classes" / "class_one" / "modules" / "meridian" / "std_assoc"
    )
    (collection / key).mkdir(parents=True)
    monkeypatch.setattr(storage, "_read_revision_pair", lambda *_: (b"body", "0" * 64))
    with pytest.raises(storage.StandardsEvidenceStorageIntegrityError):
        storage.list_standard_evidence_association_identities(
            tmp_path, "class_one", "grade_one"
        )
