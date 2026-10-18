"""#122 Slice 3: no real pupils, teacher workspace, or producer dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from meridian.teacher_action_contract import (
    ActionKind,
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_orchestration import (
    TeacherActionConflictError,
    TeacherActionOrchestrationError,
    apply_reviewed_teacher_action,
    resume_exact_teacher_selection,
)
from meridian.teacher_action_receipts import (
    CanonicalActionObservation,
    TeacherActionReceiptStore,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


def preview(kind: ActionKind = "eligibility") -> TeacherActionPreview:
    return TeacherActionPreview(
        action_id="ab" * 16,
        kind=kind,
        scope=TeacherActionScope(
            workspace_sha256=A,
            class_id="synthetic_class",
            grade_item_id="synthetic_item",
            school_year="2026-2027",
            academic_period_id="mp1",
            calendar_sha256=B,
            work_identity_sha256=C,
        ),
        actor=TeacherActionActor(
            actor_id="teacher-synthetic", profile_sha256=A, source="saved"
        ),
        target=TeacherActionTarget(
            family=kind,
            identity_sha256=D,
            revision=2,
            candidate_sha256=C,
            expected_current_revision=1,
            expected_current_sha256=B,
        ),
        basis=(
            TeacherActionBasis("authorization", A, B),
            TeacherActionBasis("publication", C, D),
        ),
        reviewed_decision_sha256=A,
    )


@dataclass
class FakeDomain:
    kind: ActionKind = "eligibility"
    target_digest: str | None = None
    selected_revision: int | None = 1
    selected_digest: str | None = B
    current_basis: str = "current"
    fail_at: str | None = None
    writes: int = 0
    selections: int = 0
    reads: int = 0
    checks: int = 0
    events: list[str] = field(default_factory=list)

    def revalidate_basis(self, action: TeacherActionPreview) -> None:
        self.events.append("revalidate")
        self.checks += 1
        if self.fail_at == "preflight" or self.current_basis != "current":
            raise TeacherActionConflictError("Source or actor changed.")
        assert action.kind == self.kind

    def observe(self, action: TeacherActionPreview) -> CanonicalActionObservation:
        self.events.append("observe")
        self.reads += 1
        if self.fail_at == "observe":
            raise OSError("synthetic canonical read failure")
        return CanonicalActionObservation(
            target_sha256=self.target_digest,
            current_revision=self.selected_revision,
            current_sha256=self.selected_digest,
            current_basis=self.current_basis,  # type: ignore[arg-type]
        )

    def persist_exact(self, action: TeacherActionPreview) -> TeacherActionRecord:
        self.events.append("write")
        self.writes += 1
        if self.fail_at == "before_write":
            raise OSError("before write")
        self.target_digest = action.target.candidate_sha256
        if self.fail_at == "after_write":
            raise OSError("process stops after immutable write")
        return TeacherActionRecord(
            action.kind,
            action.target.identity_sha256,
            action.target.revision,
            action.target.candidate_sha256,
            "created",
        )

    def select_exact(
        self, action: TeacherActionPreview, record: TeacherActionRecord
    ) -> str:
        self.events.append("select")
        self.selections += 1
        assert record.matches_target(action.target)
        # Model canonical CAS, including another actor's intervening pointer.
        if (
            self.selected_revision != action.target.expected_current_revision
            or self.selected_digest != action.target.expected_current_sha256
        ):
            raise TeacherActionConflictError("CAS failed")
        if self.fail_at == "before_select":
            raise OSError("selection refused")
        self.selected_revision = action.target.revision
        self.selected_digest = action.target.candidate_sha256
        if self.fail_at == "after_select":
            raise OSError("crash after selection")
        return "updated"


@pytest.fixture
def store(tmp_path: Path) -> TeacherActionReceiptStore:
    (tmp_path / "classes" / "synthetic_class").mkdir(parents=True)
    return TeacherActionReceiptStore(tmp_path, "synthetic_class")


def test_one_confirmation_writes_selects_and_verifies(
    store: TeacherActionReceiptStore,
) -> None:
    domain = FakeDomain()
    action = preview()
    result = apply_reviewed_teacher_action(action, domain, store, confirmation="APPLY")
    assert result.status == "applied"
    assert result.succeeded
    assert result.current_record is not None
    assert result.current_record.matches_target(action.target)
    assert result.selection_disposition == "updated"
    assert domain.writes == domain.selections == 1
    assert domain.events.index("write") < domain.events.index("select")
    assert domain.events[-1] == "observe"
    receipt = store.load(action.action_id)
    assert receipt is not None
    assert receipt.checkpoints[-1].stage == "receipt_finalized"
    assert receipt.observed_records[0].matches_target(action.target)


def test_cancellation_creates_no_journal_or_canonical_write(
    store: TeacherActionReceiptStore,
) -> None:
    domain = FakeDomain()
    result = apply_reviewed_teacher_action(preview(), domain, store, confirmation="B")
    assert result.status == "blocked_before_write"
    assert domain.events == []
    assert not store.directory.exists()


def test_repeat_apply_verifies_and_does_not_duplicate(
    store: TeacherActionReceiptStore,
) -> None:
    domain = FakeDomain()
    action = preview()
    assert apply_reviewed_teacher_action(
        action, domain, store, confirmation="APPLY"
    ).succeeded
    again = apply_reviewed_teacher_action(action, domain, store, confirmation="APPLY")
    assert again.status == "already_applied"
    assert again.selection_disposition == "existing"
    assert domain.writes == domain.selections == 1


@pytest.mark.parametrize(
    "kind",
    [
        "grade_item",
        "grade_item_membership",
        "eligibility",
        "attempt_policy",
        "attempt_decision",
        "standards_association",
        "proficiency_result",
    ],
)
def test_all_supported_families_use_same_exact_protocol(
    store: TeacherActionReceiptStore, kind: ActionKind
) -> None:
    assert (
        apply_reviewed_teacher_action(
            preview(kind), FakeDomain(kind), store, confirmation="APPLY"
        ).status
        == "applied"
    )


@pytest.mark.parametrize("failure", ["preflight", "observe"])
def test_preflight_failures_cannot_mutate(
    store: TeacherActionReceiptStore, failure: str
) -> None:
    domain = FakeDomain(fail_at=failure)
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status == (
        "conflict_requires_review" if failure == "preflight" else "blocked_before_write"
    )
    assert domain.writes == domain.selections == 0


def test_receipt_storage_unavailable_fails_closed(tmp_path: Path) -> None:
    root = tmp_path
    (root / "classes" / "synthetic_class").mkdir(parents=True)
    store = TeacherActionReceiptStore(root, "synthetic_class")
    store.directory.parent.mkdir(parents=True)
    store.directory.write_text("not a directory")
    domain = FakeDomain()
    outcome = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert outcome.status == "recovery_required"
    assert domain.writes == domain.selections == 0


def test_wrong_family_and_write_only_path_refused(
    store: TeacherActionReceiptStore,
) -> None:
    with pytest.raises(TeacherActionOrchestrationError, match="Wrong domain"):
        apply_reviewed_teacher_action(
            preview("grade_item"), FakeDomain(), store, confirmation="APPLY"
        )
    with pytest.raises(TeacherActionOrchestrationError, match="Write-only"):
        apply_reviewed_teacher_action(
            replace(preview(), make_current=False),
            FakeDomain(),
            store,
            confirmation="APPLY",
        )


def test_interruption_after_write_is_truthful_and_not_rewritten(
    store: TeacherActionReceiptStore,
) -> None:
    domain = FakeDomain(fail_at="after_write")
    action = preview()
    result = apply_reviewed_teacher_action(action, domain, store, confirmation="APPLY")
    assert result.status == "written_not_current"
    assert domain.writes == 1 and domain.selections == 0
    domain.fail_at = None
    again = apply_reviewed_teacher_action(action, domain, store, confirmation="APPLY")
    assert again.status == "written_not_current"
    assert domain.writes == 1 and domain.selections == 0
    resume = resume_exact_teacher_selection(
        action, domain, store, confirmation="RESUME"
    )
    # Journal's earlier stage is only preflight: record was committed before
    # the failure, and the recovery route must establish exact history first.
    assert resume.status == "applied"
    assert domain.writes == 1 and domain.selections == 1


def test_resume_refuses_unconfirmed_replay(store: TeacherActionReceiptStore) -> None:
    domain = FakeDomain(fail_at="after_write")
    action = preview()
    apply_reviewed_teacher_action(action, domain, store, confirmation="APPLY")
    assert (
        resume_exact_teacher_selection(
            action, domain, store, confirmation="cancel"
        ).status
        == "blocked_before_write"
    )
    assert domain.selections == 0


def test_preexisting_revision_without_receipt_is_not_selected(
    store: TeacherActionReceiptStore,
) -> None:
    domain = FakeDomain(target_digest=C)
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status == "recovery_required"
    assert domain.writes == domain.selections == 0


def test_superseded_current_pointer_blocks_resume(
    store: TeacherActionReceiptStore,
) -> None:
    action = preview()
    domain = FakeDomain(fail_at="after_write")
    apply_reviewed_teacher_action(action, domain, store, confirmation="APPLY")
    domain.fail_at = None
    domain.selected_revision = 3
    domain.selected_digest = D
    result = resume_exact_teacher_selection(
        action, domain, store, confirmation="RESUME"
    )
    assert result.status == "conflict_requires_review"
    assert domain.selections == 0


def test_wrong_target_digest_is_not_adopted(store: TeacherActionReceiptStore) -> None:
    domain = FakeDomain(target_digest=D)
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status == "conflict_requires_review"
    assert domain.writes == 0


def test_authorization_revoked_between_write_and_selection(
    store: TeacherActionReceiptStore,
) -> None:
    class Revoking(FakeDomain):
        def persist_exact(self, action: TeacherActionPreview) -> TeacherActionRecord:
            record = super().persist_exact(action)
            self.current_basis = "stale"
            return record

    domain = Revoking()
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status == "conflict_requires_review"
    assert domain.writes == 1 and domain.selections == 0


def test_selection_refused_remains_written_not_current(
    store: TeacherActionReceiptStore,
) -> None:
    domain = FakeDomain(fail_at="before_select")
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    # Canonical reread proves it was written but the original selector remains.
    assert result.status == "written_not_current"
    assert domain.writes == domain.selections == 1


def test_selection_committed_then_raised_is_not_false_success(
    store: TeacherActionReceiptStore,
) -> None:
    domain = FakeDomain(fail_at="after_select")
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status == "current_unverified"
    assert domain.selected_revision == 2
    domain.fail_at = None
    recovered = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert recovered.status == "already_applied"
    assert domain.selections == 1


def test_canonical_pointer_changes_after_selection(
    store: TeacherActionReceiptStore,
) -> None:
    class Concurrent(FakeDomain):
        def select_exact(
            self, action: TeacherActionPreview, record: TeacherActionRecord
        ) -> str:
            disposition = super().select_exact(action, record)
            self.selected_revision = 3
            self.selected_digest = D
            return disposition

    domain = Concurrent()
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status == "conflict_requires_review"
    assert not result.succeeded


def test_postselection_authority_change_denies_success(
    store: TeacherActionReceiptStore,
) -> None:
    class RevokedAfterSelect(FakeDomain):
        def select_exact(
            self, action: TeacherActionPreview, record: TeacherActionRecord
        ) -> str:
            result = super().select_exact(action, record)
            self.current_basis = "stale"
            return result

    domain = RevokedAfterSelect()
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status == "conflict_requires_review"


def test_after_write_receipt_failure_reports_mutation_without_success(
    store: TeacherActionReceiptStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = store.record_checkpoint

    def sabotage(*args: object, **kwargs: object):
        checkpoint = kwargs.get("checkpoint")
        if getattr(checkpoint, "stage", None) == "write":
            from meridian.teacher_action_receipts import TeacherActionReceiptUnsafeError

            raise TeacherActionReceiptUnsafeError("disk fault after canonical write")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "record_checkpoint", sabotage)
    domain = FakeDomain()
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status == "recovery_required"
    assert result.persisted
    assert not result.succeeded
    assert domain.writes == 1 and domain.selections == 0


def test_no_duplicate_during_concurrent_action_claim(
    store: TeacherActionReceiptStore,
) -> None:
    class Nested(FakeDomain):
        nested_status: str = ""

        def persist_exact(self, action: TeacherActionPreview) -> TeacherActionRecord:
            self.nested_status = apply_reviewed_teacher_action(
                action, self, store, confirmation="APPLY"
            ).status
            return super().persist_exact(action)

    domain = Nested()
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status == "applied"
    assert domain.nested_status == "blocked_before_write"
    assert domain.writes == 1


def test_wrong_writer_record_never_selected(store: TeacherActionReceiptStore) -> None:
    class Wrong(FakeDomain):
        def persist_exact(self, action: TeacherActionPreview) -> TeacherActionRecord:
            self.target_digest = C
            return TeacherActionRecord(
                action.kind,
                action.target.identity_sha256,
                action.target.revision + 1,
                C,
                "created",
            )

    domain = Wrong()
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status != "applied"
    assert domain.selections == 0


def test_failed_write_stage_has_durable_machine_reason(
    store: TeacherActionReceiptStore,
) -> None:
    domain = FakeDomain(fail_at="after_write")
    action = preview()
    outcome = apply_reviewed_teacher_action(action, domain, store, confirmation="APPLY")
    assert outcome.status == "written_not_current"
    receipt = store.load(action.action_id)
    assert receipt is not None
    assert receipt.checkpoints[-1].stage == "write"
    assert receipt.checkpoints[-1].disposition == "unknown"
    assert receipt.checkpoints[-1].reason_code == "write_failed"
    assert len(receipt.observed_records) == 1


def test_selection_fault_journals_unknown_without_lying(
    store: TeacherActionReceiptStore,
) -> None:
    domain = FakeDomain(fail_at="after_select")
    action = preview()
    result = apply_reviewed_teacher_action(action, domain, store, confirmation="APPLY")
    receipt = store.load(action.action_id)
    assert result.status == "current_unverified"
    assert receipt is not None
    assert receipt.checkpoints[-1].stage == "selection_commit"
    assert receipt.checkpoints[-1].disposition == "unknown"
    assert receipt.checkpoints[-1].reason_code == "selection_failed"


def test_recovery_is_safe_across_new_process_objects(
    store: TeacherActionReceiptStore,
) -> None:
    action = preview()
    domain = FakeDomain(fail_at="after_write")
    apply_reviewed_teacher_action(action, domain, store, confirmation="APPLY")
    domain.fail_at = None
    restarted_store = TeacherActionReceiptStore(store.root, store.class_id)
    assert (
        resume_exact_teacher_selection(
            action, domain, restarted_store, confirmation="RESUME"
        ).status
        == "applied"
    )
    assert domain.writes == 1


def test_new_actor_binding_cannot_reuse_receipt(
    store: TeacherActionReceiptStore,
) -> None:
    action = preview()
    domain = FakeDomain(fail_at="after_write")
    apply_reviewed_teacher_action(action, domain, store, confirmation="APPLY")
    domain.fail_at = None
    changed = replace(action, actor=replace(action.actor, actor_id="different-teacher"))
    outcome = apply_reviewed_teacher_action(
        changed, domain, store, confirmation="APPLY"
    )
    assert outcome.status == "conflict_requires_review"
    assert domain.selections == 0 and domain.writes == 1


def test_uncertain_currentness_blocks_initial_write(
    store: TeacherActionReceiptStore,
) -> None:
    domain = FakeDomain(current_basis="unknown")
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status == "conflict_requires_review"
    assert domain.writes == 0


def test_invalid_store_class_refuses_before_confirmation(
    tmp_path: Path,
) -> None:
    (tmp_path / "classes" / "another_class").mkdir(parents=True)
    other = TeacherActionReceiptStore(tmp_path, "another_class")
    with pytest.raises(TeacherActionOrchestrationError, match="class scope"):
        apply_reviewed_teacher_action(
            preview(), FakeDomain(), other, confirmation="APPLY"
        )


def test_failed_early_write_does_not_claim_that_history_is_absent(
    store: TeacherActionReceiptStore,
) -> None:
    domain = FakeDomain(fail_at="before_write")
    result = apply_reviewed_teacher_action(
        preview(), domain, store, confirmation="APPLY"
    )
    assert result.status == "recovery_required"
    assert domain.writes == 1 and domain.selections == 0
