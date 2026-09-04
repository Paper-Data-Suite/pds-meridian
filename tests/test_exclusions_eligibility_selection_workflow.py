from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.exclusions_eligibility_selection_workflow as workflow
from meridian.evidence_eligibility import (
    EVIDENCE_ELIGIBILITY_RECORD_TYPE,
    EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
    EvidenceDecisionActor,
    EvidenceEligibilityDecision,
    EvidenceEligibilityPolicyReference,
    EvidenceSourceReference,
    EvidenceSourceStateObservation,
    evidence_eligibility_decision_to_json_bytes,
)
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityDependencyError,
    EvidenceEligibilitySelectionResult,
    StoredEvidenceEligibilityDecision,
    evidence_eligibility_revision_relative_path,
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
NOW = datetime(2026, 9, 2, 17, 0, tzinfo=UTC)


def source() -> EvidenceSourceReference:
    return EvidenceSourceReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        item_id="scoreform_item_1",
    )


def source_state(
    value: str = "superseded",
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


def decision(
    revision: int,
    *,
    disposition: str = "excluded",
) -> EvidenceEligibilityDecision:
    return EvidenceEligibilityDecision(
        schema_version=EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
        record_type=EVIDENCE_ELIGIBILITY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        source=source(),
        membership_revision=2,
        membership_revision_sha256=MEMBERSHIP_DIGEST,
        eligibility_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        disposition=disposition,  # type: ignore[arg-type]
        actor=EvidenceDecisionActor(
            kind="teacher",
            actor_id="teacher_42",
        ),
        policy=EvidenceEligibilityPolicyReference(
            policy_id="teacher_local_eligibility",
            policy_version="1",
        ),
        reason_codes=(
            ()
            if disposition == "included"
            else ("eligibility.teacher_exclusion",)
        ),
        rationale=None,
        source_state=EvidenceSourceStateObservation(
            state="current",
            head_publication_id=PUBLICATION_ID,
            successor_publication_id=None,
            withdrawn_at=None,
        ),
        decided_at=NOW,
    )


def stored(
    revision: int,
    *,
    disposition: str = "excluded",
) -> StoredEvidenceEligibilityDecision:
    value = decision(revision, disposition=disposition)
    content = evidence_eligibility_decision_to_json_bytes(value)
    digest = hashlib.sha256(content).hexdigest()
    relative = evidence_eligibility_revision_relative_path(
        CLASS_ID,
        GRADE_ITEM_ID,
        value.source,
        revision,
    )
    return StoredEvidenceEligibilityDecision(
        decision=value,
        decision_sha256=digest,
        path=Path(f"{revision}.json"),
        relative_path=relative,
        content=content,
    )


def row(
    *,
    selected_revision: int | None = 2,
    current_source_state: str = "superseded",
) -> ExclusionReviewRow:
    return ExclusionReviewRow(
        source=source(),
        student_id="student_001",
        selected_disposition=(
            None if selected_revision is None else "excluded"
        ),
        selected_eligibility_revision=selected_revision,
        selected_decision_sha256=(
            None if selected_revision is None else "b" * 64
        ),
        reviewed_membership_revision=(
            None if selected_revision is None else 2
        ),
        current_membership_revision=2,
        reason_codes=(
            ()
            if selected_revision is None
            else ("eligibility.teacher_exclusion",)
        ),
        rationale=None,
        actor_kind=None if selected_revision is None else "teacher",
        actor_id=None if selected_revision is None else "teacher_42",
        policy_id=(
            None
            if selected_revision is None
            else "teacher_local_eligibility"
        ),
        policy_version=None if selected_revision is None else "1",
        reviewed_source_state=(
            None if selected_revision is None else "current"
        ),
        source_state=current_source_state,
        successor_publication_id=(
            "pub_" + ("4" * 32)
            if current_source_state
            in {"superseded", "withdrawn_superseded"}
            else None
        ),
        head_publication_id=(
            "pub_" + ("4" * 32)
            if current_source_state
            in {"superseded", "withdrawn_superseded"}
            else PUBLICATION_ID
        ),
        operative_included=False,
        review_state=(
            "no_decision" if selected_revision is None else "current"
        ),
    )


def projection(
    *,
    target_row: ExclusionReviewRow | None = None,
) -> ExclusionsProjection:
    return ExclusionsProjection(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        rows=(row() if target_row is None else target_row,),
    )


def authorized() -> AuthorizedProjectionSnapshot:
    publication = SimpleNamespace(
        work=WORK,
        publication_id=PUBLICATION_ID,
    )
    stored_snapshot = SimpleNamespace(
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        snapshot=SimpleNamespace(
            source=SimpleNamespace(publication=publication),
        ),
    )
    return cast(
        AuthorizedProjectionSnapshot,
        SimpleNamespace(stored=stored_snapshot),
    )


def membership() -> SimpleNamespace:
    return SimpleNamespace(
        decision=SimpleNamespace(
            decision="included",
            membership_revision=2,
        ),
        decision_sha256=MEMBERSHIP_DIGEST,
    )


def install_preview_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    selected_revision: int | None = 2,
    target_disposition: str = "excluded",
    lifecycle: str = "superseded",
) -> tuple[
    ExclusionsProjection,
    AuthorizedProjectionSnapshot,
    StoredEvidenceEligibilityDecision,
]:
    reviewed = projection(
        target_row=row(
            selected_revision=selected_revision,
            current_source_state=lifecycle,
        )
    )
    auth = authorized()
    target = stored(1, disposition=target_disposition)
    monkeypatch.setattr(
        workflow,
        "AuthorizedProjectionSnapshot",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "build_exclusions_projection",
        lambda *args, **kwargs: reviewed,
    )
    monkeypatch.setattr(
        workflow,
        "load_evidence_eligibility_revision",
        lambda *args, **kwargs: target,
    )
    monkeypatch.setattr(
        workflow,
        "validate_evidence_eligibility_dependencies",
        lambda *args, **kwargs: SimpleNamespace(
            membership=membership(),
            current_source_state=source_state(lifecycle),
        ),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_evidence_eligibility_revision",
        lambda *args, **kwargs: selected_revision,
    )
    return reviewed, auth, target


def test_preview_exact_historical_revision_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, target = install_preview_state(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "select_evidence_eligibility_revision",
        lambda *args, **kwargs: pytest.fail("preview must not select"),
    )

    preview = workflow.preview_exclusion_eligibility_selection(
        "workspace",
        reviewed,
        authorized_snapshot=auth,
        item_id="scoreform_item_1",
        eligibility_revision=1,
    )

    assert preview.target is target
    assert preview.target_revision == 1
    assert preview.target_disposition == "excluded"
    assert preview.expected_current_revision == 2
    assert preview.membership_revision == 2
    assert preview.membership_revision_sha256 == MEMBERSHIP_DIGEST
    assert preview.source_state.state == "superseded"
    assert preview.authoring_action == "not_performed"


def test_preview_allows_live_historical_included_on_superseded_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, _ = install_preview_state(
        monkeypatch,
        target_disposition="included",
        lifecycle="superseded",
    )

    preview = workflow.preview_exclusion_eligibility_selection(
        "workspace",
        reviewed,
        authorized_snapshot=auth,
        item_id="scoreform_item_1",
        eligibility_revision=1,
    )

    assert preview.target_disposition == "included"
    assert preview.source_state.state == "superseded"


def test_preview_translates_canonical_withdrawn_included_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, _ = install_preview_state(
        monkeypatch,
        target_disposition="included",
        lifecycle="withdrawn",
    )
    monkeypatch.setattr(
        workflow,
        "validate_evidence_eligibility_dependencies",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            EvidenceEligibilityDependencyError(
                "Withdrawn source evidence cannot be operative as included."
            )
        ),
    )

    with pytest.raises(
        workflow.ExclusionEligibilitySelectionStaleError,
        match="Withdrawn source evidence",
    ):
        workflow.preview_exclusion_eligibility_selection(
            "workspace",
            reviewed,
            authorized_snapshot=auth,
            item_id="scoreform_item_1",
            eligibility_revision=1,
        )


def test_commit_selects_exact_preview_with_cas_and_no_authoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, target = install_preview_state(monkeypatch)
    preview = workflow.preview_exclusion_eligibility_selection(
        "workspace",
        reviewed,
        authorized_snapshot=auth,
        item_id="scoreform_item_1",
        eligibility_revision=1,
    )
    monkeypatch.setattr(
        workflow,
        "load_evidence_eligibility_revision",
        lambda *args, **kwargs: target,
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args, **kwargs: membership(),
    )
    monkeypatch.setattr(
        workflow,
        "observe_evidence_source_state",
        lambda *args, **kwargs: source_state("superseded"),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_evidence_eligibility_revision",
        lambda *args, **kwargs: 2,
    )
    observed: dict[str, object] = {}
    canonical = cast(
        EvidenceEligibilitySelectionResult,
        SimpleNamespace(
            disposition="updated",
            selection=SimpleNamespace(eligibility_revision=1),
            stored=target,
        ),
    )

    def select(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return canonical

    monkeypatch.setattr(
        workflow,
        "select_evidence_eligibility_revision",
        select,
    )

    result = workflow.commit_exclusion_eligibility_selection_preview(
        "workspace",
        preview,
        authorized_snapshot=auth,
    )

    assert observed["args"] == (
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        source(),
        1,
    )
    assert observed["kwargs"] == {
        "authorized_snapshot": auth,
        "expected_current_eligibility_revision": 2,
    }
    assert result.previous_current_revision == 2
    assert result.selected_revision == 1
    assert result.selected_disposition == "excluded"
    assert result.selected_decision_sha256 == target.decision_sha256
    assert result.selection_disposition == "updated"
    assert result.authoring_action == "not_performed"


def test_commit_rejects_changed_current_selector_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, target = install_preview_state(monkeypatch)
    preview = workflow.preview_exclusion_eligibility_selection(
        "workspace",
        reviewed,
        authorized_snapshot=auth,
        item_id="scoreform_item_1",
        eligibility_revision=1,
    )
    monkeypatch.setattr(
        workflow,
        "load_evidence_eligibility_revision",
        lambda *args, **kwargs: target,
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args, **kwargs: membership(),
    )
    monkeypatch.setattr(
        workflow,
        "observe_evidence_source_state",
        lambda *args, **kwargs: source_state("superseded"),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_evidence_eligibility_revision",
        lambda *args, **kwargs: 3,
    )
    monkeypatch.setattr(
        workflow,
        "select_evidence_eligibility_revision",
        lambda *args, **kwargs: pytest.fail(
            "stale preview must not select"
        ),
    )

    with pytest.raises(
        workflow.ExclusionEligibilitySelectionStaleError,
        match="Current eligibility selection changed",
    ):
        workflow.commit_exclusion_eligibility_selection_preview(
            "workspace",
            preview,
            authorized_snapshot=auth,
        )


def test_commit_rejects_changed_target_bytes_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, _ = install_preview_state(monkeypatch)
    preview = workflow.preview_exclusion_eligibility_selection(
        "workspace",
        reviewed,
        authorized_snapshot=auth,
        item_id="scoreform_item_1",
        eligibility_revision=1,
    )
    changed = stored(1, disposition="pending")
    monkeypatch.setattr(
        workflow,
        "load_evidence_eligibility_revision",
        lambda *args, **kwargs: changed,
    )
    monkeypatch.setattr(
        workflow,
        "select_evidence_eligibility_revision",
        lambda *args, **kwargs: pytest.fail(
            "changed target must not select"
        ),
    )

    with pytest.raises(
        workflow.ExclusionEligibilitySelectionStaleError,
        match="Target eligibility revision changed",
    ):
        workflow.commit_exclusion_eligibility_selection_preview(
            "workspace",
            preview,
            authorized_snapshot=auth,
        )
