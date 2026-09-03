from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.exclusions_eligibility_authoring_workflow as workflow
from meridian.evidence_eligibility import (
    EvidenceSourceReference,
    EvidenceSourceStateObservation,
)
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityRevisionWriteResult,
)
from meridian.exclusions_workflow import (
    ExclusionReviewRow,
    ExclusionsProjection,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="test_1",
)
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
MEMBERSHIP_DIGEST = "a" * 64
NOW = datetime(2026, 9, 2, 16, 0, tzinfo=UTC)


def source() -> EvidenceSourceReference:
    return EvidenceSourceReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        item_id="scoreform_item_1",
    )


def row(*, source_state: str = "current") -> ExclusionReviewRow:
    return ExclusionReviewRow(
        source=source(),
        student_id="student_001",
        selected_disposition=None,
        selected_eligibility_revision=None,
        selected_decision_sha256=None,
        reviewed_membership_revision=None,
        current_membership_revision=2,
        reason_codes=(),
        rationale=None,
        actor_kind=None,
        actor_id=None,
        policy_id=None,
        policy_version=None,
        reviewed_source_state=None,
        source_state=source_state,
        successor_publication_id=(
            "pub_" + ("4" * 32)
            if source_state == "superseded"
            else None
        ),
        head_publication_id=(
            "pub_" + ("4" * 32)
            if source_state == "superseded"
            else PUBLICATION_ID
        ),
        operative_included=False,
        review_state="no_decision",
    )


def projection(
    *,
    target: ExclusionReviewRow | None = None,
) -> ExclusionsProjection:
    return ExclusionsProjection(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        rows=(row() if target is None else target,),
    )


def authorized() -> AuthorizedProjectionSnapshot:
    publication = SimpleNamespace(
        work=WORK,
        publication_id=PUBLICATION_ID,
    )
    stored = SimpleNamespace(
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        snapshot=SimpleNamespace(
            source=SimpleNamespace(publication=publication),
        ),
    )
    return cast(
        AuthorizedProjectionSnapshot,
        SimpleNamespace(stored=stored),
    )


def membership() -> SimpleNamespace:
    return SimpleNamespace(
        decision=SimpleNamespace(
            decision="included",
            membership_revision=2,
        ),
        decision_sha256=MEMBERSHIP_DIGEST,
    )


def source_state(
    value: str = "current",
) -> EvidenceSourceStateObservation:
    successor = (
        "pub_" + ("4" * 32)
        if value in {"superseded", "withdrawn_superseded"}
        else None
    )
    return EvidenceSourceStateObservation(
        state=value,  # type: ignore[arg-type]
        head_publication_id=successor or PUBLICATION_ID,
        successor_publication_id=successor,
        withdrawn_at=(
            NOW
            if value in {"withdrawn", "withdrawn_superseded"}
            else None
        ),
    )


def allow_runtime_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "AuthorizedProjectionSnapshot",
        SimpleNamespace,
    )


def install_common(
    monkeypatch: pytest.MonkeyPatch,
    reviewed: ExclusionsProjection,
    *,
    state: str = "current",
) -> None:
    allow_runtime_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "build_exclusions_projection",
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
        lambda *args, **kwargs: source_state(state),
    )
    monkeypatch.setattr(
        workflow,
        "list_evidence_eligibility_revisions",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_evidence_eligibility_revision",
        lambda *args, **kwargs: None,
    )


def fake_write_result(
    decision: object,
) -> EvidenceEligibilityRevisionWriteResult:
    return cast(
        EvidenceEligibilityRevisionWriteResult,
        SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(decision=decision),
        ),
    )


def test_preview_authors_exact_academic_candidate_without_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = projection()
    install_common(monkeypatch, reviewed)
    monkeypatch.setattr(
        workflow,
        "write_evidence_eligibility_revision",
        lambda *args, **kwargs: pytest.fail("preview must not write"),
    )

    preview = workflow.preview_exclusion_eligibility_authoring(
        "workspace",
        reviewed,
        authorized_snapshot=authorized(),
        item_id="scoreform_item_1",
        disposition="excluded",
        actor_id="teacher_42",
        policy_id="teacher_local_eligibility",
        policy_version="1",
        reason_codes=("eligibility.teacher_exclusion",),
        rationale="Do not use this observation for this Grade Item.",
        decided_at=NOW,
    )

    candidate = preview.candidate
    assert candidate.eligibility_revision == 1
    assert candidate.supersedes_revision is None
    assert candidate.membership_revision == 2
    assert candidate.membership_revision_sha256 == MEMBERSHIP_DIGEST
    assert candidate.disposition == "excluded"
    assert candidate.actor.kind == "teacher"
    assert candidate.actor.actor_id == "teacher_42"
    assert candidate.policy is not None
    assert candidate.policy.policy_id == "teacher_local_eligibility"
    assert candidate.reason_codes == ("eligibility.teacher_exclusion",)
    assert candidate.source_state.state == "current"
    assert preview.selection_action == "not_performed"


def test_preview_allows_teacher_academic_decision_on_superseded_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = projection(
        target=row(source_state="superseded"),
    )
    install_common(
        monkeypatch,
        reviewed,
        state="superseded",
    )

    preview = workflow.preview_exclusion_eligibility_authoring(
        "workspace",
        reviewed,
        authorized_snapshot=authorized(),
        item_id="scoreform_item_1",
        disposition="included",
        actor_id="teacher_42",
        policy_id="teacher_local_eligibility",
        policy_version="1",
        decided_at=NOW,
    )

    assert preview.candidate.disposition == "included"
    assert preview.candidate.source_state.state == "superseded"


def test_preview_rejects_teacher_authoring_against_withdrawn_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = projection(
        target=row(source_state="withdrawn"),
    )
    install_common(
        monkeypatch,
        reviewed,
        state="withdrawn",
    )

    with pytest.raises(
        workflow.ExclusionEligibilityAuthoringScopeError,
        match="withdrawn",
    ):
        workflow.preview_exclusion_eligibility_authoring(
            "workspace",
            reviewed,
            authorized_snapshot=authorized(),
            item_id="scoreform_item_1",
            disposition="excluded",
            actor_id="teacher_42",
            policy_id="teacher_local_eligibility",
            policy_version="1",
            reason_codes=("eligibility.teacher_exclusion",),
            decided_at=NOW,
        )


def test_preview_preserves_reason_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = projection()
    allow_runtime_types(monkeypatch)

    with pytest.raises(
        workflow.ExclusionEligibilityAuthoringScopeError,
        match="requires at least one",
    ):
        workflow.preview_exclusion_eligibility_authoring(
            "workspace",
            reviewed,
            authorized_snapshot=authorized(),
            item_id="scoreform_item_1",
            disposition="pending",
            actor_id="teacher_42",
            policy_id="teacher_local_eligibility",
            policy_version="1",
            decided_at=NOW,
        )

    with pytest.raises(
        workflow.ExclusionEligibilityAuthoringScopeError,
        match="must not carry",
    ):
        workflow.preview_exclusion_eligibility_authoring(
            "workspace",
            reviewed,
            authorized_snapshot=authorized(),
            item_id="scoreform_item_1",
            disposition="included",
            actor_id="teacher_42",
            policy_id="teacher_local_eligibility",
            policy_version="1",
            reason_codes=("eligibility.manual",),
            decided_at=NOW,
        )


def test_commit_writes_exact_preview_but_never_selects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = projection()
    install_common(monkeypatch, reviewed)
    preview = workflow.preview_exclusion_eligibility_authoring(
        "workspace",
        reviewed,
        authorized_snapshot=authorized(),
        item_id="scoreform_item_1",
        disposition="unsupported",
        actor_id="teacher_42",
        policy_id="teacher_local_eligibility",
        policy_version="1",
        reason_codes=("eligibility.unsupported_semantics",),
        decided_at=NOW,
    )

    selected_values: list[int | None] = [None, None]
    monkeypatch.setattr(
        workflow,
        "get_current_evidence_eligibility_revision",
        lambda *args, **kwargs: selected_values.pop(0),
    )
    captured: list[object] = []

    def write(
        *args: object,
        **kwargs: object,
    ) -> object:
        captured.append(args[1])
        assert kwargs["authorized_snapshot"] is auth
        return fake_write_result(args[1])

    monkeypatch.setattr(
        workflow,
        "write_evidence_eligibility_revision",
        write,
    )
    auth = authorized()
    result = workflow.commit_exclusion_eligibility_authoring_preview(
        "workspace",
        preview,
        authorized_snapshot=auth,
    )

    assert captured == [preview.candidate]
    assert result.written_revision == 1
    assert result.written_disposition == "unsupported"
    assert result.selected_revision_before_write is None
    assert result.selected_revision_after_write is None
    assert result.selection_changed_during_write is False
    assert result.selection_action == "not_performed"


def test_commit_rejects_selection_change_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = projection()
    install_common(monkeypatch, reviewed)
    preview = workflow.preview_exclusion_eligibility_authoring(
        "workspace",
        reviewed,
        authorized_snapshot=authorized(),
        item_id="scoreform_item_1",
        disposition="excluded",
        actor_id="teacher_42",
        policy_id="teacher_local_eligibility",
        policy_version="1",
        reason_codes=("eligibility.teacher_exclusion",),
        decided_at=NOW,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_evidence_eligibility_revision",
        lambda *args, **kwargs: 1,
    )
    monkeypatch.setattr(
        workflow,
        "write_evidence_eligibility_revision",
        lambda *args, **kwargs: pytest.fail(
            "stale preview must not write"
        ),
    )

    with pytest.raises(
        workflow.ExclusionEligibilityAuthoringStaleError,
        match="selection changed",
    ):
        workflow.commit_exclusion_eligibility_authoring_preview(
            "workspace",
            preview,
            authorized_snapshot=authorized(),
        )


def test_commit_rejects_lifecycle_change_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = projection()
    install_common(monkeypatch, reviewed)
    preview = workflow.preview_exclusion_eligibility_authoring(
        "workspace",
        reviewed,
        authorized_snapshot=authorized(),
        item_id="scoreform_item_1",
        disposition="included",
        actor_id="teacher_42",
        policy_id="teacher_local_eligibility",
        policy_version="1",
        decided_at=NOW,
    )
    monkeypatch.setattr(
        workflow,
        "observe_evidence_source_state",
        lambda *args, **kwargs: source_state("superseded"),
    )
    monkeypatch.setattr(
        workflow,
        "write_evidence_eligibility_revision",
        lambda *args, **kwargs: pytest.fail(
            "stale preview must not write"
        ),
    )

    with pytest.raises(
        workflow.ExclusionEligibilityAuthoringStaleError,
        match="lifecycle changed",
    ):
        workflow.commit_exclusion_eligibility_authoring_preview(
            "workspace",
            preview,
            authorized_snapshot=authorized(),
        )
