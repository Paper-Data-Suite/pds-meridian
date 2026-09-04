from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.standards_association_authoring_workflow as workflow
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.standards_review_workflow import StandardsReviewProjection

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STANDARD_ID = "NJSLSA.R1"
NOW = datetime(2026, 9, 2, 18, 0, tzinfo=UTC)


def authorized() -> AuthorizedProjectionSnapshot:
    work = ModuleWorkRef(
        module_id="scoreform",
        class_id=CLASS_ID,
        work_id="test_1",
    )
    publication = SimpleNamespace(
        work=work,
        publication_id="pub_" + ("1" * 32),
    )
    stored = SimpleNamespace(
        cache_key="2" * 64,
        snapshot_digest="3" * 64,
        snapshot=SimpleNamespace(
            source=SimpleNamespace(publication=publication),
        ),
    )
    return cast(
        AuthorizedProjectionSnapshot,
        SimpleNamespace(stored=stored),
    )


def projection() -> StandardsReviewProjection:
    auth = authorized()
    publication = auth.stored.snapshot.source.publication
    source = EvidenceSourceReference(
        work=publication.work,
        publication_id=publication.publication_id,
        cache_key=auth.stored.cache_key,
        snapshot_digest=auth.stored.snapshot_digest,
        item_id="scoreform_item_1",
    )
    return cast(
        StandardsReviewProjection,
        SimpleNamespace(
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            standard_id=STANDARD_ID,
            source=source,
        ),
    )


def dependencies() -> object:
    return SimpleNamespace(
        grade_item=SimpleNamespace(
            revision=SimpleNamespace(grade_item_revision=4),
            revision_sha256="a" * 64,
        ),
        membership=SimpleNamespace(
            decision=SimpleNamespace(membership_revision=5),
            decision_sha256="b" * 64,
        ),
        standard_resolution=SimpleNamespace(
            resolved=True,
            active=True,
        ),
    )


def install_runtime_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "AuthorizedProjectionSnapshot",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "StandardsReviewProjection",
        SimpleNamespace,
    )


def install_create_state(monkeypatch: pytest.MonkeyPatch) -> None:
    install_runtime_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "list_standard_evidence_association_revisions",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        workflow,
        "validate_standard_evidence_association_dependencies",
        lambda *args, **kwargs: dependencies(),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_standard_evidence_association_revision",
        lambda *args, **kwargs: None,
    )


def test_create_preview_builds_exact_candidate_without_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_create_state(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "write_standard_evidence_association_revision",
        lambda *args, **kwargs: pytest.fail("preview must not write"),
    )

    preview = workflow.preview_standards_association_authoring(
        "workspace",
        projection(),
        authorized_snapshot=authorized(),
        operation="create",
        disposition="associated",
        basis="explicit",
        actor_id="teacher_42",
        rationale="Teacher reviewed the evidence-standard relationship.",
        decided_at=NOW,
    )

    assert preview.candidate_revision == 1
    assert preview.candidate.supersedes_revision is None
    assert preview.candidate_disposition == "associated"
    assert preview.candidate_basis == "explicit"
    assert preview.candidate.actor.kind == "teacher"
    assert preview.candidate.actor.actor_id == "teacher_42"
    assert preview.grade_item_revision == 4
    assert preview.membership_revision == 5
    assert preview.standard_resolved is True
    assert preview.expected_current_association_revision is None
    assert preview.selection_action == "not_performed"


def test_producer_declared_basis_is_validated_by_canonical_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_create_state(monkeypatch)

    observed: dict[str, object] = {}

    def validate(*args: object, **kwargs: object) -> object:
        observed["candidate"] = args[1]
        return dependencies()

    monkeypatch.setattr(
        workflow,
        "validate_standard_evidence_association_dependencies",
        validate,
    )

    preview = workflow.preview_standards_association_authoring(
        "workspace",
        projection(),
        authorized_snapshot=authorized(),
        operation="create",
        disposition="associated",
        basis="producer_declared",
        actor_id="teacher_42",
        rationale=None,
        decided_at=NOW,
    )

    assert observed["candidate"] is preview.candidate
    assert preview.candidate.basis == "producer_declared"


def test_create_and_revise_enforce_history_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_create_state(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "list_standard_evidence_association_revisions",
        lambda *args, **kwargs: (1,),
    )

    with pytest.raises(
        workflow.StandardsAssociationAuthoringScopeError,
        match="create requires",
    ):
        workflow.preview_standards_association_authoring(
            "workspace",
            projection(),
            authorized_snapshot=authorized(),
            operation="create",
            disposition="associated",
            basis="explicit",
            actor_id="teacher_42",
            rationale=None,
            decided_at=NOW,
        )

    monkeypatch.setattr(
        workflow,
        "list_standard_evidence_association_revisions",
        lambda *args, **kwargs: (),
    )
    with pytest.raises(
        workflow.StandardsAssociationAuthoringScopeError,
        match="revise requires",
    ):
        workflow.preview_standards_association_authoring(
            "workspace",
            projection(),
            authorized_snapshot=authorized(),
            operation="revise",
            disposition="not_associated",
            basis="explicit",
            actor_id="teacher_42",
            rationale=None,
            decided_at=NOW,
        )


def test_revise_supersedes_latest_persisted_not_selected_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_runtime_types(monkeypatch)
    latest = SimpleNamespace(decision_sha256="d" * 64)
    monkeypatch.setattr(
        workflow,
        "list_standard_evidence_association_revisions",
        lambda *args, **kwargs: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "load_standard_evidence_association_revision",
        lambda *args, **kwargs: latest,
    )
    monkeypatch.setattr(
        workflow,
        "validate_standard_evidence_association_dependencies",
        lambda *args, **kwargs: dependencies(),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_standard_evidence_association_revision",
        lambda *args, **kwargs: 1,
    )

    preview = workflow.preview_standards_association_authoring(
        "workspace",
        projection(),
        authorized_snapshot=authorized(),
        operation="revise",
        disposition="not_associated",
        basis="explicit",
        actor_id="teacher_42",
        rationale="Revision after further review.",
        decided_at=NOW,
    )

    assert preview.history == (1, 2, 3)
    assert preview.latest_revision_sha256 == "d" * 64
    assert preview.candidate_revision == 4
    assert preview.candidate.supersedes_revision == 3
    assert preview.expected_current_association_revision == 1


def test_commit_writes_candidate_and_does_not_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_create_state(monkeypatch)
    preview = workflow.preview_standards_association_authoring(
        "workspace",
        projection(),
        authorized_snapshot=authorized(),
        operation="create",
        disposition="associated",
        basis="explicit",
        actor_id="teacher_42",
        rationale=None,
        decided_at=NOW,
    )

    selected_values: list[int | None] = [None, None]
    monkeypatch.setattr(
        workflow,
        "get_current_standard_evidence_association_revision",
        lambda *args, **kwargs: selected_values.pop(0),
    )
    captured: list[object] = []

    def write(*args: object, **kwargs: object) -> object:
        captured.append(args[1])
        return SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(decision=args[1]),
        )

    monkeypatch.setattr(
        workflow,
        "write_standard_evidence_association_revision",
        write,
    )

    result = workflow.commit_standards_association_authoring_preview(
        "workspace",
        preview,
        authorized_snapshot=authorized(),
    )

    assert captured == [preview.candidate]
    assert result.written_revision == 1
    assert result.written_disposition == "associated"
    assert result.written_basis == "explicit"
    assert result.selected_revision_before_write is None
    assert result.selected_revision_after_write is None
    assert result.selection_changed_during_write is False
    assert result.selection_action == "not_performed"


def test_commit_rejects_history_change_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_create_state(monkeypatch)
    preview = workflow.preview_standards_association_authoring(
        "workspace",
        projection(),
        authorized_snapshot=authorized(),
        operation="create",
        disposition="associated",
        basis="explicit",
        actor_id="teacher_42",
        rationale=None,
        decided_at=NOW,
    )
    monkeypatch.setattr(
        workflow,
        "list_standard_evidence_association_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        workflow,
        "write_standard_evidence_association_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not write"),
    )

    with pytest.raises(
        workflow.StandardsAssociationAuthoringStaleError,
        match="history changed",
    ):
        workflow.commit_standards_association_authoring_preview(
            "workspace",
            preview,
            authorized_snapshot=authorized(),
        )


def test_commit_rejects_grade_item_or_membership_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_create_state(monkeypatch)
    preview = workflow.preview_standards_association_authoring(
        "workspace",
        projection(),
        authorized_snapshot=authorized(),
        operation="create",
        disposition="not_associated",
        basis="explicit",
        actor_id="teacher_42",
        rationale=None,
        decided_at=NOW,
    )
    changed = dependencies()
    changed.membership = SimpleNamespace(
        decision=SimpleNamespace(membership_revision=6),
        decision_sha256="e" * 64,
    )
    monkeypatch.setattr(
        workflow,
        "validate_standard_evidence_association_dependencies",
        lambda *args, **kwargs: changed,
    )
    monkeypatch.setattr(
        workflow,
        "write_standard_evidence_association_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not write"),
    )

    with pytest.raises(
        workflow.StandardsAssociationAuthoringStaleError,
        match="membership changed",
    ):
        workflow.commit_standards_association_authoring_preview(
            "workspace",
            preview,
            authorized_snapshot=authorized(),
        )


def test_commit_rejects_current_selection_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_create_state(monkeypatch)
    preview = workflow.preview_standards_association_authoring(
        "workspace",
        projection(),
        authorized_snapshot=authorized(),
        operation="create",
        disposition="associated",
        basis="explicit",
        actor_id="teacher_42",
        rationale=None,
        decided_at=NOW,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_standard_evidence_association_revision",
        lambda *args, **kwargs: 1,
    )
    monkeypatch.setattr(
        workflow,
        "write_standard_evidence_association_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not write"),
    )

    with pytest.raises(
        workflow.StandardsAssociationAuthoringStaleError,
        match="selection changed",
    ):
        workflow.commit_standards_association_authoring_preview(
            "workspace",
            preview,
            authorized_snapshot=authorized(),
        )
