"""#122 Slice 13: exact, authorization-checked proficiency restart only."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.evidence_eligibility import EvidenceSourceReference
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
from meridian.teacher_action_restart_proficiency import (
    _RestartProficiencyPort,
    inspect_restart_proficiency,
    resume_restart_proficiency,
)

A, B, C, D = "a" * 64, "b" * 64, "c" * 64, "d" * 64
STD = "njsls-ela:RL.CR.11-12.1"


def _preview(root: Path) -> TeacherActionPreview:
    actor = TeacherActionActor("teacher_1", A, "saved")
    identity = _identity(
        "proficiency_result", "class_one", "grade_one", "student_1", STD
    )
    return TeacherActionPreview(
        action_id="ab" * 16,
        kind="proficiency_result",
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
        target=TeacherActionTarget("proficiency_result", identity, 1, C, None, None),
        basis=(
            TeacherActionBasis("actor_profile", _identity(actor.actor_id), A),
            TeacherActionBasis(
                "canonical_source",
                identity,
                _identity(
                    "proficiency_source",
                    "pub_0123456789abcdef0123456789abcdef",
                    B,
                    D,
                    "item_1",
                    B,
                    D,
                    D,
                    D,
                    D,
                ),
            ),
        ),
        reviewed_decision_sha256=C,
    )


@pytest.fixture
def example(tmp_path: Path, monkeypatch):
    import meridian.teacher_action_restart_proficiency as restart

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
    work = ModuleWorkRef(module_id="scoreform", class_id="class_one", work_id="work_1")
    source = EvidenceSourceReference(
        work=work,
        publication_id="pub_0123456789abcdef0123456789abcdef",
        cache_key=B,
        snapshot_digest=D,
        item_id="item_1",
    )
    basis = SimpleNamespace(grade_item_revision=1, grade_item_revision_sha256=D)
    entry = SimpleNamespace(source=source, mapping_profile_reference=None)
    inputs = SimpleNamespace(entries=(entry,), grade_item=basis)
    policy_ref = SimpleNamespace(policy_id="policy_1", policy_sha256=D)
    scale_ref = SimpleNamespace(scale_id="scale_1", scale_sha256=D)
    outcome = SimpleNamespace(status="sufficient")
    snapshot = SimpleNamespace(
        class_id="class_one",
        grade_item_id="grade_one",
        student_id="student_1",
        standard_id=STD,
        result_revision=1,
        inputs=inputs,
        inputs_sha256=B,
        calculation_fingerprint=D,
        policy_reference=policy_ref,
        target_scale=scale_ref,
        outcome=outcome,
    )
    membership = SimpleNamespace(
        decision_sha256=D,
        decision=SimpleNamespace(
            decision="included",
            grade_item_revision_sha256=D,
            work_reference=SimpleNamespace(registration_revision=1),
            academic_period=SimpleNamespace(
                period=SimpleNamespace(school_year="2026-2027", period_id="mp1"),
                calendar_revision=1,
            ),
        ),
    )
    grade = SimpleNamespace(
        revision_sha256=D, revision=SimpleNamespace(grade_item_revision=1)
    )
    authorized = SimpleNamespace(
        assessment=SimpleNamespace(reusable_for_current_use=True)
    )
    state = {
        "snapshot": snapshot,
        "membership": membership,
        "grade": grade,
        "auth": True,
        "calendar": B,
        "registration": 1,
        "history": (1,),
        "digest": C,
        "roster": ["student_1"],
        "identities": (("grade_one", "student_1", STD),),
        "policy": SimpleNamespace(reference=policy_ref),
        "scale": SimpleNamespace(reference=scale_ref),
        "recalc": SimpleNamespace(
            grade_item_basis=basis,
            inputs=inputs,
            calculation=SimpleNamespace(outcome=outcome, policy_reference=policy_ref),
        ),
        "current": None,
        "selects": 0,
        "writes": 0,
        "checks": 0,
    }

    def stored():
        return SimpleNamespace(
            snapshot=state["snapshot"], result_sha256=state["digest"]
        )

    monkeypatch.setattr(
        restart,
        "load_roster",
        lambda *_: SimpleNamespace(
            class_id="class_one",
            students=tuple(SimpleNamespace(student_id=i) for i in state["roster"]),
        ),
    )
    monkeypatch.setattr(
        restart,
        "list_standard_proficiency_result_identities",
        lambda *_a, **_kw: state["identities"],
    )
    monkeypatch.setattr(
        restart,
        "list_standard_proficiency_result_revisions",
        lambda *_a: state["history"],
    )
    monkeypatch.setattr(
        restart, "load_standard_proficiency_result_revision", lambda *_a: stored()
    )
    monkeypatch.setattr(
        restart,
        "load_current_standard_proficiency_result",
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
    monkeypatch.setattr(
        restart, "load_current_standard_proficiency_policy", lambda *_a: state["policy"]
    )
    monkeypatch.setattr(
        restart, "load_current_proficiency_scale", lambda *_a: state["scale"]
    )
    monkeypatch.setattr(
        restart, "build_bounded_calculation_preview", lambda *_a: state["recalc"]
    )

    # The canonical type-checked aggregation constructor is outside this unit.
    # Keep its strict source contract, but replace the authorized-snapshot
    # dependency with a narrow fixture collaborator rather than weakening
    # production checks or fabricating a production authorization token.
    def binding_for_fixture(source, authorized_snapshot, mapping_profile, attempt):
        assert isinstance(source, EvidenceSourceReference)
        assert authorized_snapshot is authorized
        assert mapping_profile is None
        assert attempt is None
        return SimpleNamespace(
            source=source,
            authorized_snapshot=authorized_snapshot,
            mapping_profile=mapping_profile,
            attempt=attempt,
        )

    monkeypatch.setattr(
        restart, "StandardAggregationCandidateBinding", binding_for_fixture
    )

    def load_authorized(_root: Path, _source: object):
        if not state["auth"]:
            raise TeacherActionConflictError("Current authorization unavailable")
        return authorized

    def selection_preview(*_args):
        return SimpleNamespace(
            target_result_sha256=state["digest"],
            expected_current_result_revision=None,
            history=(1,),
        )

    def selection_commit(_root: Path, _preview: object, *, currentness_check):
        currentness_check()
        state["selects"] += 1
        state["current"] = stored()
        return SimpleNamespace(
            selected_result_sha256=state["digest"], selection_disposition="created"
        )

    monkeypatch.setattr(
        restart, "preview_calculation_result_selection", selection_preview
    )
    monkeypatch.setattr(
        restart, "commit_calculation_result_selection_preview", selection_commit
    )
    return root, store, receipt, state, load_authorized


def test_inspection_is_read_only(example):
    root, store, receipt, state, authorized = example
    checked = inspect_restart_proficiency(
        root, store, receipt, authorized_loader=authorized, actor_checker=lambda _: None
    )
    assert checked.can_resume
    assert state["selects"] == state["writes"] == 0


def test_resume_selects_exact_existing_revision_without_authoring(example):
    root, store, receipt, state, authorized = example
    outcome = resume_restart_proficiency(
        root,
        store,
        receipt,
        confirmation="RESUME",
        authorized_loader=authorized,
        actor_checker=lambda _: None,
    )
    assert outcome.status in ("applied", "already_applied")
    assert state["selects"] == 1
    assert state["writes"] == 0
    assert state["current"].result_sha256 == C


def test_no_immutable_writer(example):
    root, _store, receipt, _state, authorized = example
    port = _RestartProficiencyPort(root, receipt, authorized, lambda _: None)
    with pytest.raises(TeacherActionConflictError):
        port.persist_exact(receipt.preview)


def test_missing_confirmation_is_no_op(example):
    root, store, receipt, state, authorized = example
    with pytest.raises(TeacherActionConflictError):
        resume_restart_proficiency(
            root,
            store,
            receipt,
            confirmation="SAVE",
            authorized_loader=authorized,
            actor_checker=lambda _: None,
        )
    assert state["selects"] == 0


@pytest.mark.parametrize(
    "change",
    [
        "digest",
        "history",
        "roster",
        "identities",
        "membership",
        "calendar",
        "registration",
        "grade",
        "policy",
        "scale",
        "inputs",
        "outcome",
        "auth",
        "source_entries",
        "student",
        "standard",
        "workspace",
        "basis",
    ],
)
def test_changed_or_unverifiable_basis_blocks_without_selection(example, change):
    root, store, receipt, state, authorized = example
    if change == "digest":
        state["digest"] = A
    elif change == "history":
        state["history"] = (1, 2)
    elif change == "roster":
        state["roster"] = []
    elif change == "identities":
        state["identities"] = ()
    elif change == "membership":
        state["membership"] = None
    elif change == "calendar":
        state["calendar"] = A
    elif change == "registration":
        state["registration"] = 3
    elif change == "grade":
        state["grade"] = None
    elif change == "policy":
        state["policy"] = None
    elif change == "scale":
        state["scale"] = None
    elif change == "inputs":
        state["recalc"].inputs = object()
    elif change == "outcome":
        state["recalc"].calculation.outcome = object()
    elif change == "auth":
        state["auth"] = False
    elif change == "source_entries":
        state["snapshot"].inputs.entries = ()
    elif change == "student":
        state["snapshot"].student_id = "student_other"
    elif change == "standard":
        state["snapshot"].standard_id = "other"
    elif change == "workspace":
        changed = replace(receipt.preview.scope, workspace_sha256=A)
        receipt = replace(receipt, preview=replace(receipt.preview, scope=changed))
    elif change == "basis":
        changed = replace(receipt.preview, reviewed_decision_sha256=A)
        receipt = replace(receipt, preview=changed)
    with pytest.raises((TeacherActionConflictError, ValueError, RuntimeError)):
        inspect_restart_proficiency(
            root,
            store,
            receipt,
            authorized_loader=authorized,
            actor_checker=lambda _: None,
        )
    assert state["selects"] == 0


def test_replaced_actor_profile_blocks(example):
    root, store, receipt, state, authorized = example
    with pytest.raises(TeacherActionConflictError):
        inspect_restart_proficiency(
            root,
            store,
            receipt,
            authorized_loader=authorized,
            actor_checker=lambda _: (_ for _ in ()).throw(
                TeacherActionConflictError("profile changed")
            ),
        )
    assert state["selects"] == 0


def test_temporary_attribution_refused(example):
    root, store, receipt, _state, authorized = example
    preview = replace(
        receipt.preview, actor=replace(receipt.preview.actor, source="temporary")
    )
    changed = replace(receipt, preview=preview)
    with pytest.raises(TeacherActionConflictError):
        inspect_restart_proficiency(
            root,
            store,
            changed,
            authorized_loader=authorized,
            actor_checker=lambda _: None,
        )


def test_menu_requires_explicit_resume(example, monkeypatch):
    import meridian.menu_teacher_action_recovery as menu

    root, store, receipt, _state, _authorized = example
    entry = SimpleNamespace(receipt=receipt)
    diagnostics = SimpleNamespace(authorizer=object())
    monkeypatch.setattr(
        menu,
        "inspect_restart_proficiency",
        lambda *_a, **_kw: SimpleNamespace(can_resume=True),
    )
    monkeypatch.setattr(
        menu, "load_fresh_restart_proficiency_authorization", lambda *_a: object()
    )
    called = []
    monkeypatch.setattr(
        menu,
        "resume_restart_proficiency",
        lambda *_a, **_kw: called.append(1) or SimpleNamespace(status="applied"),
    )
    monkeypatch.setattr(menu, "teacher_action_outcome_message", lambda *_a: "Applied")
    out = StringIO()
    menu._offer_proficiency_resume(
        root,
        store,
        entry,
        diagnostics=diagnostics,
        input_fn=lambda *_: "NO",
        output=out,
    )
    assert not called
    menu._offer_proficiency_resume(
        root,
        store,
        entry,
        diagnostics=diagnostics,
        input_fn=lambda *_: "RESUME",
        output=out,
    )
    assert called == [1]


def test_menu_no_authorizer_never_reads_protected_data(example, monkeypatch):
    import meridian.menu_teacher_action_recovery as menu

    root, store, receipt, _state, _authorized = example
    monkeypatch.setattr(
        menu,
        "inspect_restart_proficiency",
        lambda *_a, **_kw: pytest.fail("protected read"),
    )
    menu._offer_proficiency_resume(
        root,
        store,
        SimpleNamespace(receipt=receipt),
        diagnostics=None,
        input_fn=lambda *_: "RESUME",
        output=StringIO(),
    )


def test_proficiency_identity_discovery_uses_validated_revision_one(
    tmp_path: Path, monkeypatch
) -> None:
    import meridian.standards_proficiency_storage as storage

    if not hasattr(storage, "standard_proficiency_results_directory"):
        pytest.skip("isolated harness has no canonical result storage")
    collection = storage.standard_proficiency_results_directory(tmp_path, "class_one")
    key = storage.storage_path_key(
        "standard_proficiency_result", "class_one", "grade_one", "student_1", STD
    )
    (collection / key).mkdir(parents=True)
    fake = SimpleNamespace(
        class_id="class_one",
        grade_item_id="grade_one",
        student_id="student_1",
        standard_id=STD,
        result_revision=1,
    )
    monkeypatch.setattr(storage, "_read_revision_pair", lambda *_a: (b"valid", C))
    monkeypatch.setattr(
        storage,
        "standard_proficiency_result_snapshot_from_json_bytes",
        lambda _payload: fake,
    )
    result = storage.list_standard_proficiency_result_identities(tmp_path, "class_one")
    assert result == (("grade_one", "student_1", STD),)
    (collection / "unexpected").mkdir()
    with pytest.raises(storage.StandardProficiencyStorageIntegrityError):
        storage.list_standard_proficiency_result_identities(tmp_path, "class_one")


def test_proficiency_selection_currentness_hook_blocks_before_write(
    tmp_path: Path, monkeypatch
) -> None:
    import meridian.standards_proficiency_storage as storage

    if not hasattr(storage, "select_standard_proficiency_result_revision"):
        pytest.skip("isolated harness has no canonical result selector")
    calls: list[str] = []
    monkeypatch.setattr(
        storage, "load_standard_proficiency_result_revision", lambda *_a: object()
    )
    monkeypatch.setattr(
        storage, "standard_proficiency_result_family_directory", lambda *_a: tmp_path
    )
    monkeypatch.setattr(storage, "_acquire_lock", lambda _lock: calls.append("lock"))
    monkeypatch.setattr(storage, "_remove_lock", lambda _lock: calls.append("unlock"))
    monkeypatch.setattr(storage, "_load_result_pointer", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        storage, "_atomic_write_pointer", lambda *_a: calls.append("write")
    )

    def reject() -> None:
        calls.append("currentness")
        raise RuntimeError("authorized evidence revoked during selection")

    with pytest.raises(RuntimeError, match="revoked"):
        storage.select_standard_proficiency_result_revision(
            tmp_path,
            "class_one",
            "grade_one",
            "student_1",
            STD,
            1,
            expected_current_result_revision=None,
            currentness_check=reject,
        )
    assert calls == ["lock", "currentness", "unlock"]
