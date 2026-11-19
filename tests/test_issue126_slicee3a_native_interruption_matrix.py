"""#126 E3A: real #30/#31 files, CAS pointers and #122 journal interruption.

Only unavailable ScoreForm/roster/eligibility inputs are substituted. Academic
storage, immutable digests, CAS writes, receipt journaling and recovery are real.
Every case uses synthetic identities and an isolated temporary workspace.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_attempt_selection_storage import (
    CLASS_ID,
    GRADE_ITEM_ID,
    MEMBERSHIP_DIGEST,
    WORK,
    derivation,
    policy_reference,
)
from test_attempt_selection_storage import (
    attempt as attempt30,
)
from test_attempt_selection_storage import (
    decision as decision30,
)
from test_attempt_selection_storage import (
    policy as policy30,
)
from test_reassessment_storage import (
    attempt as attempt31,
)
from test_reassessment_storage import (
    decision as decision31,
)
from test_reassessment_storage import (
    policy as policy31,
)

import meridian.attempt_selection_storage as storage30
import meridian.reassessment_storage as storage31
from meridian.reassessment import (
    AttemptSelectionDecisionReference,
    ReassessmentPolicyReference,
)
from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_guided import _identity
from meridian.teacher_action_orchestration import (
    apply_reviewed_teacher_action,
    resume_exact_teacher_selection,
)
from meridian.teacher_action_receipts import (
    CanonicalActionObservation,
    TeacherActionReceiptStore,
    assess_teacher_action_recovery,
)

# A Test World deliberately uses the *real* native storage implementation.
# It substitutes only a synthetic, fixed #29 eligibility and roster context.


@dataclass
class World:
    root: Path
    first: object
    second: object
    preview: TeacherActionPreview
    store: TeacherActionReceiptStore
    port: Native31Port
    source: dict[str, bool]

    def current30(self):
        return storage30.load_current_attempt_selection_decision(
            self.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
        )

    def current31(self):
        return storage31.load_current_reassessment_decision(
            self.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
        )

    def thirty_one_history(self):
        return storage31.list_reassessment_decision_revisions(
            self.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
        )

    def resolution(self):
        return storage31.resolve_current_reassessment(
            self.root,
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            "student_1",
            authorized_snapshot=object(),  # synthetic external publication only
        )


class Native31Port:
    """#122 domain port using actual #31 author, select and file readbacks."""

    kind = "reassessment_decision"

    def __init__(self, root: Path, second: object, source: dict[str, bool]):
        self.root = root
        self.second = second
        self.source = source
        self.writes = 0
        self.selections = 0
        self.revalidations = 0
        self.failpoint: str | None = None

    def revalidate_basis(self, preview: TeacherActionPreview) -> None:
        self.revalidations += 1
        if self.failpoint == "prewrite_drift" and self.revalidations >= 2:
            self.source["reusable"] = False
        if not self.source["reusable"]:
            raise RuntimeError("Synthetic producer authority was withdrawn")
        upstream = storage30.resolve_current_attempt_selection(
            self.root,
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            "student_1",
            authorized_snapshot=object(),
        )
        if not upstream.operative_selection or upstream.selected is None:
            raise RuntimeError("Actual #30 selected pointer is not operative")
        if (
            upstream.selected.decision_sha256
            != self.second.attempt_selection.decision_sha256
        ):
            raise RuntimeError("Actual #30 digest changed")
        policy = storage31.load_current_reassessment_policy(
            self.root, CLASS_ID, GRADE_ITEM_ID, WORK, "teacher_reassessment"
        )
        if (
            policy is None
            or policy.policy_sha256 != self.second.policy.policy_revision_sha256
        ):
            raise RuntimeError("Actual #31 policy changed")
        if preview.target.candidate_sha256 != self._candidate_digest():
            raise RuntimeError("Reviewed #31 candidate changed")

    def _candidate_digest(self) -> str:
        import hashlib

        from meridian.reassessment import reassessment_decision_to_json_bytes

        return hashlib.sha256(
            reassessment_decision_to_json_bytes(self.second)
        ).hexdigest()

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation:
        candidate = self.second
        history = self._native_history()
        target = (
            storage31.load_reassessment_decision_revision(
                self.root,
                CLASS_ID,
                GRADE_ITEM_ID,
                WORK,
                "student_1",
                candidate.decision_revision,
            )
            if candidate.decision_revision in history
            else None
        )
        current = storage31.load_current_reassessment_decision(
            self.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
        )
        return CanonicalActionObservation(
            target_sha256=None if target is None else target.decision_sha256,
            current_revision=(
                None if current is None else current.decision.decision_revision
            ),
            current_sha256=None if current is None else current.decision_sha256,
            current_basis="current" if self.source["reusable"] else "stale",
        )

    def _native_history(self) -> tuple[int, ...]:
        return storage31.list_reassessment_decision_revisions(
            self.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
        )

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord:
        self.writes += 1
        saved = storage31.write_reassessment_decision_revision(
            self.root, self.second, authorized_snapshot=object()
        )
        if self.failpoint == "after_immutable_write":
            raise OSError("Injected interruption after real #31 write")
        return TeacherActionRecord(
            "reassessment_decision",
            preview.target.identity_sha256,
            self.second.decision_revision,
            saved.stored.decision_sha256,
            saved.disposition,
        )

    def select_exact(self, preview: TeacherActionPreview, record: TeacherActionRecord):
        self.selections += 1
        if self.failpoint == "before_pointer_cas":
            raise OSError("Injected interruption before real #31 pointer update")
        selected = storage31.select_reassessment_decision_revision(
            self.root,
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            "student_1",
            self.second.decision_revision,
            expected_current_decision_revision=preview.target.expected_current_revision,
            authorized_snapshot=object(),
        )
        if self.failpoint == "after_pointer_cas":
            raise OSError("Injected interruption after real #31 pointer update")
        return selected.disposition


def _world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, selected30: bool = True):
    root = tmp_path / "workspace"
    root.mkdir()
    # Substitute the unavailable live producer/roster/eligibility source only.
    source = {"reusable": True}
    monkeypatch.setattr(storage30, "_require_membership_history", lambda *a: None)
    monkeypatch.setattr(
        storage30, "_validate_decision_dependencies", lambda *a, **k: derivation()
    )
    monkeypatch.setattr(storage30, "derive_attempt_candidates", lambda *a: derivation())
    monkeypatch.setattr(
        storage30,
        "load_current_grade_item_membership_decision",
        lambda *a: SimpleNamespace(
            decision=SimpleNamespace(decision="included", membership_revision=1),
            decision_sha256=MEMBERSHIP_DIGEST,
        ),
    )
    p30 = storage30.write_attempt_selection_policy_revision(
        root, policy30(maximum=None)
    ).stored
    storage30.select_attempt_selection_policy_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        p30.policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    assert (attempt30(1), attempt30(2)) == (attempt31(1), attempt31(2))
    first = decision30(policy_reference(p30), selected=(attempt30(1), attempt30(2)))
    saved30 = storage30.write_attempt_selection_decision_revision(
        root, first, authorized_snapshot=object()
    ).stored
    if selected30:
        storage30.select_attempt_selection_decision_revision(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            "student_1",
            1,
            authorized_snapshot=object(),
            expected_current_decision_revision=None,
        )
    p31 = storage31.write_reassessment_policy_revision(root, policy31()).stored
    storage31.select_reassessment_policy_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        p31.policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    from dataclasses import replace

    second = replace(
        decision31(mode="retain"),
        attempt_selection=AttemptSelectionDecisionReference(
            first.decision_revision, saved30.decision_sha256
        ),
        policy=ReassessmentPolicyReference(
            p31.policy.policy_id, p31.policy.policy_revision, p31.policy_sha256
        ),
    )
    import hashlib

    from meridian.reassessment import reassessment_decision_to_json_bytes

    digest = hashlib.sha256(reassessment_decision_to_json_bytes(second)).hexdigest()
    actor = TeacherActionActor("teacher_local", "c" * 64, "saved")
    identity = _identity(
        "reassessment_decision",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK.module_id,
        WORK.work_id,
        "student_1",
    )
    preview = TeacherActionPreview(
        action_id="e" * 32,
        kind="reassessment_decision",
        scope=TeacherActionScope(
            workspace_sha256=_identity("workspace", str(root)),
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            work_identity_sha256=_identity(
                "work", CLASS_ID, WORK.module_id, WORK.work_id
            ),
        ),
        actor=actor,
        target=TeacherActionTarget(
            family="reassessment_decision",
            identity_sha256=identity,
            revision=second.decision_revision,
            candidate_sha256=digest,
            expected_current_revision=None,
            expected_current_sha256=None,
        ),
        basis=(
            TeacherActionBasis(
                "actor_profile", _identity(actor.actor_id), actor.profile_sha256
            ),
            TeacherActionBasis(
                "canonical_source",
                identity,
                _identity(
                    "reassessment_source",
                    saved30.decision_sha256,
                    p31.policy_sha256,
                    WORK.module_id,
                    WORK.work_id,
                ),
            ),
        ),
        reviewed_decision_sha256=digest,
    )
    port = Native31Port(root, second, source)
    store = TeacherActionReceiptStore(root, CLASS_ID)
    return World(root, first, second, preview, store, port, source)


def _run(world: World):
    return apply_reviewed_teacher_action(
        world.preview, world.port, world.store, confirmation="APPLY"
    )


def _assert_history_30_stable(world: World):
    assert storage30.list_attempt_selection_decision_revisions(
        world.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    ) == (1,)
    assert world.current30() is not None


def test_real_31_write_and_cas_and_receipt_are_independently_verifiable(
    monkeypatch, tmp_path
):
    world = _world(monkeypatch, tmp_path)
    result = _run(world)
    assert result.status == "applied"
    assert world.thirty_one_history() == (1,)
    assert world.current31() is not None
    assert world.current31().decision_sha256 == world.preview.target.candidate_sha256
    assert world.resolution().status == "resolved"
    assert world.resolution().operative_reassessment
    receipt = world.store.load(world.preview.action_id)
    assert receipt is not None
    assert receipt.preview == world.preview
    assert "receipt_finalized" in tuple(x.stage for x in receipt.checkpoints)
    assert (world.port.writes, world.port.selections) == (1, 1)
    _assert_history_30_stable(world)


def test_cancellation_creates_no_receipt_or_31_data(monkeypatch, tmp_path):
    world = _world(monkeypatch, tmp_path)
    result = apply_reviewed_teacher_action(
        world.preview, world.port, world.store, confirmation="CANCEL"
    )
    assert result.status == "blocked_before_write"
    assert world.store.load(world.preview.action_id) is None
    assert world.thirty_one_history() == ()
    assert world.current31() is None
    assert world.port.writes == world.port.selections == 0
    _assert_history_30_stable(world)


def test_missing_current_30_blocks_before_31_write(monkeypatch, tmp_path):
    world = _world(monkeypatch, tmp_path, selected30=False)
    result = _run(world)
    assert result.status in ("blocked_before_write", "conflict_requires_review")
    assert world.thirty_one_history() == ()
    assert world.store.load(world.preview.action_id) is None
    assert world.port.writes == 0


@pytest.mark.parametrize(
    "failpoint",
    [
        "prewrite_drift",
        "after_immutable_write",
        "before_pointer_cas",
        "after_pointer_cas",
    ],
)
def test_native_interruption_reconciliation_is_never_a_false_success(
    monkeypatch, tmp_path, failpoint
):
    world = _world(monkeypatch, tmp_path)
    world.port.failpoint = failpoint
    result = _run(world)
    assert result.status not in ("applied", "already_applied")
    current = world.current31()
    history = world.thirty_one_history()
    if failpoint == "prewrite_drift":
        assert history == ()
        assert current is None
        assert world.port.writes == 0
    elif failpoint == "after_immutable_write":
        assert history == (1,)
        assert current is None
    elif failpoint == "before_pointer_cas":
        assert history == (1,)
        assert current is None
    else:
        assert history == (1,)
        assert current is not None
    recovered = assess_teacher_action_recovery(
        world.store, world.preview, world.port.observe
    )
    assert recovered.reason != "missing_receipt" or failpoint == "prewrite_drift"
    assert world.port.writes <= 1
    _assert_history_30_stable(world)


def test_restart_resumes_exact_written_31_without_reauthoring(monkeypatch, tmp_path):
    world = _world(monkeypatch, tmp_path)
    world.port.failpoint = "before_pointer_cas"
    interrupted = _run(world)
    assert interrupted.status not in ("applied", "already_applied")
    assert world.thirty_one_history() == (1,)
    assert world.current31() is None
    initial = assess_teacher_action_recovery(
        world.store, world.preview, world.port.observe
    )
    assert initial.reason == "eligible_to_resume"
    assert initial.can_resume_exact_selection
    new_process_port = Native31Port(world.root, world.second, world.source)
    restarted_preview = world.store.load(world.preview.action_id).preview
    assert restarted_preview == world.preview
    # Same action ID, exact immutable target, never call the writer again.
    # The #122 resume kernel only selects the existing stored revision.
    finished = resume_exact_teacher_selection(
        restarted_preview, new_process_port, world.store, confirmation="RESUME"
    )
    assert finished.status == "applied"
    assert world.current31() is not None
    assert world.resolution().operative_reassessment
    assert new_process_port.writes == 0
    assert new_process_port.selections == 1
    assert world.thirty_one_history() == (1,)
    _assert_history_30_stable(world)


def test_reapplying_original_action_never_duplicates_31(monkeypatch, tmp_path):
    world = _world(monkeypatch, tmp_path)
    assert _run(world).status == "applied"
    # A second APPLY reconciles the same receipt; no new immutable authoring.
    second = _run(world)
    assert second.status == "already_applied"
    assert world.port.writes == 1
    assert world.thirty_one_history() == (1,)


def test_restart_without_original_receipt_is_not_authorized(monkeypatch, tmp_path):
    world = _world(monkeypatch, tmp_path)
    world.port.failpoint = "before_pointer_cas"
    _run(world)
    path = world.store.path_for(world.preview.action_id)
    path.unlink()
    recovered = assess_teacher_action_recovery(
        world.store, world.preview, world.port.observe
    )
    assert recovered.reason == "missing_receipt_target_present"
    assert not recovered.can_resume_exact_selection
    new_port = Native31Port(world.root, world.second, world.source)
    refused = resume_exact_teacher_selection(
        world.preview, new_port, world.store, confirmation="RESUME"
    )
    assert refused.status not in ("applied", "already_applied")
    assert new_port.writes == new_port.selections == 0
    assert world.current31() is None


def test_changed_30_cas_pointer_blocks_original_31_restart(monkeypatch, tmp_path):
    world = _world(monkeypatch, tmp_path)
    world.port.failpoint = "before_pointer_cas"
    _run(world)
    pointer = storage30.attempt_selection_decision_current_path(
        world.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    )
    pointer.unlink()
    new_port = Native31Port(world.root, world.second, world.source)
    result = resume_exact_teacher_selection(
        world.preview, new_port, world.store, confirmation="RESUME"
    )
    assert result.status not in ("applied", "already_applied")
    assert world.current31() is None
    assert new_port.writes == 0


def test_31_digest_tamper_blocks_recovery(monkeypatch, tmp_path):
    world = _world(monkeypatch, tmp_path)
    world.port.failpoint = "before_pointer_cas"
    _run(world)
    immutable = storage31.reassessment_decision_revision_path(
        world.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1", 1
    )
    assert immutable.is_file()
    # No normalization: corruption remains visible to the native loader.
    data = json.loads(immutable.read_bytes())
    data["rationale"] = "tampered"
    immutable.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    new_port = Native31Port(world.root, world.second, world.source)
    result = resume_exact_teacher_selection(
        world.preview, new_port, world.store, confirmation="RESUME"
    )
    assert result.status not in ("applied", "already_applied")
    with pytest.raises(storage31.ReassessmentStorageIntegrityError):
        storage31.load_reassessment_decision_revision(
            world.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1", 1
        )
    assert new_port.writes == 0


def test_31_pointer_cas_conflict_does_not_select_reviewed_revision(
    monkeypatch, tmp_path
):
    world = _world(monkeypatch, tmp_path)
    world.port.failpoint = "before_pointer_cas"
    _run(world)
    # Exact canonical target exists, but competing pointer state should block.
    competing = storage31.select_reassessment_decision_revision(
        world.root,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        1,
        authorized_snapshot=object(),
        expected_current_decision_revision=None,
    )
    assert competing.disposition == "created"
    recovered = assess_teacher_action_recovery(
        world.store, world.preview, world.port.observe
    )
    assert recovered.reason == "exact_current"
    # The correct state is already-current, not another write or another CAS.
    new_port = Native31Port(world.root, world.second, world.source)
    done = resume_exact_teacher_selection(
        world.preview, new_port, world.store, confirmation="RESUME"
    )
    assert done.status == "already_applied"
    assert new_port.writes == new_port.selections == 0
    assert world.thirty_one_history() == (1,)


def test_noncanonical_31_pointer_blocks_claimed_operative_pair(monkeypatch, tmp_path):
    world = _world(monkeypatch, tmp_path)
    assert _run(world).status == "applied"
    path = storage31.reassessment_decision_current_path(
        world.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    )
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(storage31.ReassessmentStorageIntegrityError):
        world.current31()
    new_port = Native31Port(world.root, world.second, world.source)
    result = resume_exact_teacher_selection(
        world.preview, new_port, world.store, confirmation="RESUME"
    )
    assert result.status not in ("applied", "already_applied")


def test_competing_receipt_reuse_with_another_digest_is_rejected(monkeypatch, tmp_path):
    from dataclasses import replace

    world = _world(monkeypatch, tmp_path)
    world.store.prepare(world.preview)
    different_target = replace(world.preview.target, candidate_sha256="9" * 64)
    different = replace(
        world.preview, target=different_target, reviewed_decision_sha256="9" * 64
    )
    from meridian.teacher_action_receipts import TeacherActionReceiptConflictError

    with pytest.raises(TeacherActionReceiptConflictError):
        world.store.prepare(different)
    assert world.thirty_one_history() == ()


def test_changed_real_31_policy_blocks_pending_selection(monkeypatch, tmp_path):
    world = _world(monkeypatch, tmp_path)
    world.port.failpoint = "before_pointer_cas"
    _run(world)
    # The immutable #31 decision exists, but the reviewed policy is no longer current.
    storage31.write_reassessment_policy_revision(world.root, policy31(revision=2))
    storage31.select_reassessment_policy_revision(
        world.root,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "teacher_reassessment",
        2,
        expected_current_policy_revision=1,
    )
    new_port = Native31Port(world.root, world.second, world.source)
    result = resume_exact_teacher_selection(
        world.preview, new_port, world.store, confirmation="RESUME"
    )
    assert result.status not in ("applied", "already_applied")
    assert world.current31() is None
    assert new_port.writes == new_port.selections == 0
    assert world.thirty_one_history() == (1,)


def test_selected_31_becomes_nonoperative_if_real_30_pointer_disappears(
    monkeypatch, tmp_path
):
    world = _world(monkeypatch, tmp_path)
    assert _run(world).status == "applied"
    pointer = storage30.attempt_selection_decision_current_path(
        world.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    )
    pointer.unlink()
    resolution = world.resolution()
    assert not resolution.operative_reassessment
    assert resolution.status == "attempt_selection_stale"
    # Both immutable histories remain available for explicit manual review.
    assert world.thirty_one_history() == (1,)
    assert storage30.list_attempt_selection_decision_revisions(
        world.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    ) == (1,)


def test_native_receipt_generation_cas_rejects_stale_restart(monkeypatch, tmp_path):
    from meridian.teacher_action_contract import TeacherActionCheckpoint
    from meridian.teacher_action_receipts import TeacherActionReceiptConflictError

    world = _world(monkeypatch, tmp_path)
    first = world.store.prepare(world.preview)
    newer = world.store.record_checkpoint(
        world.preview,
        expected_generation=first.generation,
        checkpoint=TeacherActionCheckpoint("write", "unknown", "write_failed"),
    )
    assert newer.generation == first.generation + 1
    with pytest.raises(TeacherActionReceiptConflictError):
        world.store.record_checkpoint(
            world.preview,
            expected_generation=first.generation,
            checkpoint=TeacherActionCheckpoint("write", "unknown", "write_failed"),
        )
    assert world.thirty_one_history() == ()
    assert world.current31() is None


def test_source_withdrawal_after_pair_current_prevents_false_resume(
    monkeypatch, tmp_path
):
    world = _world(monkeypatch, tmp_path)
    assert _run(world).status == "applied"
    world.source["reusable"] = False
    observation = world.port.observe(world.preview)
    assert observation.current_basis == "stale"
    recovered = assess_teacher_action_recovery(
        world.store, world.preview, world.port.observe
    )
    assert recovered.reason == "dependencies_changed"
    assert not recovered.can_resume_exact_selection
    new_port = Native31Port(world.root, world.second, world.source)
    result = resume_exact_teacher_selection(
        world.preview, new_port, world.store, confirmation="RESUME"
    )
    assert result.status not in ("applied", "already_applied")
    assert new_port.writes == new_port.selections == 0
