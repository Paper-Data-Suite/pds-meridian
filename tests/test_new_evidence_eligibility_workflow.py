from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.new_evidence_eligibility_workflow as workflow
from meridian.evidence_eligibility import (
    EvidenceSourceReference,
    EvidenceSourceStateObservation,
)
from meridian.evidence_eligibility_storage import EvidenceEligibilityRevisionWriteResult
from meridian.new_evidence_workflow import (
    NewEvidenceReview,
    NewEvidenceRow,
    NewEvidenceStatusSummary,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
MEMBERSHIP_DIGEST = "4" * 64
NOW = datetime(2026, 9, 1, 22, tzinfo=UTC)


def source() -> EvidenceSourceReference:
    return EvidenceSourceReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        item_id="scoreform_item_1",
    )


def row(*, status: str = "no_decision") -> NewEvidenceRow:
    return NewEvidenceRow(
        source=source(),
        student_id="student_1",
        target_kind="question",
        target_id="q1",
        standard_ids=("RL.CR.9-10.1",),
        result_kind="question_score",
        membership_state="included",
        eligibility_status=status,  # type: ignore[arg-type]
        selected_eligibility_revision=None,
        selected_eligibility_disposition=None,
        eligibility_source_state="current",
        operative_included=False,
        attention_required=True,
        recommended_task="exclusions",
    )


def review(*, target: NewEvidenceRow | None = None) -> NewEvidenceReview:
    target = row() if target is None else target
    return NewEvidenceReview(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        projection_source_status="current",
        membership_state="included",
        membership_revision=2,
        academic_period_id="mp1",
        academic_period_calendar_revision=3,
        rows=(target,),
        status_summary=(
            NewEvidenceStatusSummary(
                status=f"eligibility_{target.eligibility_status}", count=1
            ),
        ),
        attention_count=1,
    )


def authorized() -> AuthorizedProjectionSnapshot:
    publication = SimpleNamespace(work=WORK, publication_id=PUBLICATION_ID)
    snapshot = SimpleNamespace(source=SimpleNamespace(publication=publication))
    stored = SimpleNamespace(
        snapshot=snapshot,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
    )
    return cast(AuthorizedProjectionSnapshot, SimpleNamespace(stored=stored))


def membership() -> SimpleNamespace:
    return SimpleNamespace(
        decision=SimpleNamespace(
            decision="included",
            membership_revision=2,
        ),
        decision_sha256=MEMBERSHIP_DIGEST,
    )


def current_source_state() -> EvidenceSourceStateObservation:
    return EvidenceSourceStateObservation(
        state="current",
        head_publication_id=PUBLICATION_ID,
        successor_publication_id=None,
        withdrawn_at=None,
    )


def allow_runtime_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "AuthorizedProjectionSnapshot", SimpleNamespace)


def install_common_state(
    monkeypatch: pytest.MonkeyPatch, reviewed: NewEvidenceReview
) -> None:
    allow_runtime_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "project_new_evidence_review",
        lambda *args, **kwargs: reviewed,
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args, **kwargs: membership(),
    )
    monkeypatch.setattr(
        workflow,
        "observe_evidence_source_state",
        lambda *args, **kwargs: current_source_state(),
    )


def fake_write_result(decision: object) -> EvidenceEligibilityRevisionWriteResult:
    return cast(
        EvidenceEligibilityRevisionWriteResult,
        SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(decision=decision),
        ),
    )


def test_authors_initial_teacher_revision_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = review()
    install_common_state(monkeypatch, reviewed)
    monkeypatch.setattr(
        workflow, "list_evidence_eligibility_revisions", lambda *a, **k: ()
    )
    selections: list[int | None] = [None, None, None]
    monkeypatch.setattr(
        workflow,
        "get_current_evidence_eligibility_revision",
        lambda *a, **k: selections.pop(0),
    )
    captured: list[object] = []

    def write(
        *args: object, **kwargs: object
    ) -> EvidenceEligibilityRevisionWriteResult:
        decision = args[1]
        captured.append(decision)
        assert kwargs["authorized_snapshot"] is auth
        return fake_write_result(decision)

    monkeypatch.setattr(workflow, "write_evidence_eligibility_revision", write)
    auth = authorized()
    result = workflow.author_new_evidence_eligibility_revision(
        "workspace",
        reviewed,
        auth,
        item_id="scoreform_item_1",
        disposition="included",
        actor_id="teacher_42",
        policy_id="teacher_local_eligibility",
        policy_version="1",
        decided_at=NOW,
    )

    decision = captured[0]
    assert getattr(decision, "eligibility_revision") == 1
    assert getattr(decision, "supersedes_revision") is None
    assert getattr(decision, "membership_revision") == 2
    assert getattr(decision, "membership_revision_sha256") == MEMBERSHIP_DIGEST
    assert getattr(decision, "disposition") == "included"
    assert getattr(decision, "actor").kind == "teacher"
    assert getattr(decision, "actor").actor_id == "teacher_42"
    assert getattr(decision, "policy").policy_id == "teacher_local_eligibility"
    assert getattr(decision, "reason_codes") == ()
    assert result.written_revision == 1
    assert result.selected_revision_before_write is None
    assert result.selected_revision_after_write is None
    assert result.selection_changed_during_write is False


def test_next_revision_supersedes_latest_history_and_requires_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = review()
    install_common_state(monkeypatch, reviewed)
    monkeypatch.setattr(
        workflow, "list_evidence_eligibility_revisions", lambda *a, **k: (1, 2)
    )
    monkeypatch.setattr(
        workflow, "get_current_evidence_eligibility_revision", lambda *a, **k: 1
    )
    captured: list[object] = []

    def write(
        *args: object, **kwargs: object
    ) -> EvidenceEligibilityRevisionWriteResult:
        del kwargs
        decision = args[1]
        captured.append(decision)
        return fake_write_result(decision)

    monkeypatch.setattr(workflow, "write_evidence_eligibility_revision", write)
    result = workflow.author_new_evidence_eligibility_revision(
        "workspace",
        reviewed,
        authorized(),
        item_id="scoreform_item_1",
        disposition="excluded",
        actor_id="teacher_42",
        policy_id="teacher_local_eligibility",
        policy_version="2",
        reason_codes=("eligibility.not_for_grade_item",),
        rationale="This evidence does not belong in this Grade Item.",
        decided_at=NOW,
    )

    decision = captured[0]
    assert getattr(decision, "eligibility_revision") == 3
    assert getattr(decision, "supersedes_revision") == 2
    assert getattr(decision, "reason_codes") == ("eligibility.not_for_grade_item",)
    assert result.written_revision == 3
    assert result.selected_revision_before_write == 1
    assert result.selected_revision_after_write == 1


def test_stale_target_row_fails_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = review()
    changed = row(status="pending")
    fresh = review(target=changed)
    allow_runtime_types(monkeypatch)
    monkeypatch.setattr(workflow, "project_new_evidence_review", lambda *a, **k: fresh)

    def unexpected(*args: object, **kwargs: object) -> object:
        raise AssertionError("no storage mutation should occur after stale review")

    monkeypatch.setattr(workflow, "write_evidence_eligibility_revision", unexpected)
    with pytest.raises(
        workflow.NewEvidenceEligibilityAuthoringStaleError, match="changed"
    ):
        workflow.author_new_evidence_eligibility_revision(
            "workspace",
            reviewed,
            authorized(),
            item_id="scoreform_item_1",
            disposition="included",
            actor_id="teacher_42",
            policy_id="teacher_local_eligibility",
            policy_version="1",
            decided_at=NOW,
        )


def test_teacher_authoring_refuses_noncurrent_core_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = review()
    install_common_state(monkeypatch, reviewed)
    successor = "pub_" + "5" * 32
    monkeypatch.setattr(
        workflow,
        "observe_evidence_source_state",
        lambda *a, **k: EvidenceSourceStateObservation(
            state="superseded",
            head_publication_id=successor,
            successor_publication_id=successor,
            withdrawn_at=None,
        ),
    )
    with pytest.raises(
        workflow.NewEvidenceEligibilityAuthoringStaleError, match="superseded"
    ):
        workflow.author_new_evidence_eligibility_revision(
            "workspace",
            reviewed,
            authorized(),
            item_id="scoreform_item_1",
            disposition="excluded",
            actor_id="teacher_42",
            policy_id="teacher_local_eligibility",
            policy_version="1",
            reason_codes=("eligibility.not_for_grade_item",),
            decided_at=NOW,
        )


def test_request_validation_preserves_academic_and_lifecycle_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allow_runtime_types(monkeypatch)
    reviewed = review()
    auth = authorized()

    with pytest.raises(
        workflow.NewEvidenceEligibilityAuthoringScopeError, match="reason"
    ):
        workflow.author_new_evidence_eligibility_revision(
            "workspace",
            reviewed,
            auth,
            item_id="scoreform_item_1",
            disposition="excluded",
            actor_id="teacher_42",
            policy_id="teacher_local_eligibility",
            policy_version="1",
            decided_at=NOW,
        )
    with pytest.raises(
        workflow.NewEvidenceEligibilityAuthoringScopeError, match="must not carry"
    ):
        workflow.author_new_evidence_eligibility_revision(
            "workspace",
            reviewed,
            auth,
            item_id="scoreform_item_1",
            disposition="included",
            actor_id="teacher_42",
            policy_id="teacher_local_eligibility",
            policy_version="1",
            reason_codes=("eligibility.manual",),
            decided_at=NOW,
        )


def test_preview_is_read_only_and_reports_exact_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = review()
    install_common_state(monkeypatch, reviewed)
    monkeypatch.setattr(
        workflow, "list_evidence_eligibility_revisions", lambda *a, **k: (1, 2)
    )
    monkeypatch.setattr(
        workflow, "get_current_evidence_eligibility_revision", lambda *a, **k: 1
    )

    def unexpected(*args: object, **kwargs: object) -> object:
        raise AssertionError("preview must not write eligibility state")

    monkeypatch.setattr(workflow, "write_evidence_eligibility_revision", unexpected)
    preview = workflow.preview_new_evidence_eligibility_revision(
        "workspace",
        reviewed,
        authorized(),
        item_id="scoreform_item_1",
        disposition="excluded",
        actor_id="teacher_42",
        policy_id="teacher_local_eligibility",
        policy_version="2",
        reason_codes=("eligibility.not_for_grade_item",),
        decided_at=NOW,
    )

    assert preview.candidate_revision == 3
    assert preview.candidate_disposition == "excluded"
    assert preview.selected_revision == 1
    assert preview.decision.supersedes_revision == 2


def test_commit_refuses_selection_change_after_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = review()
    install_common_state(monkeypatch, reviewed)
    monkeypatch.setattr(
        workflow, "list_evidence_eligibility_revisions", lambda *a, **k: (1,)
    )
    selections: list[int | None] = [1, 2]
    monkeypatch.setattr(
        workflow,
        "get_current_evidence_eligibility_revision",
        lambda *a, **k: selections.pop(0),
    )

    def unexpected(*args: object, **kwargs: object) -> object:
        raise AssertionError("stale preview must not be written")

    monkeypatch.setattr(workflow, "write_evidence_eligibility_revision", unexpected)
    preview = workflow.preview_new_evidence_eligibility_revision(
        "workspace",
        reviewed,
        authorized(),
        item_id="scoreform_item_1",
        disposition="excluded",
        actor_id="teacher_42",
        policy_id="teacher_local_eligibility",
        policy_version="2",
        reason_codes=("eligibility.not_for_grade_item",),
        decided_at=NOW,
    )

    with pytest.raises(
        workflow.NewEvidenceEligibilityAuthoringStaleError, match="selection changed"
    ):
        workflow.commit_new_evidence_eligibility_preview(
            "workspace", preview, authorized()
        )
