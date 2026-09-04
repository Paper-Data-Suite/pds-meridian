from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

import meridian.grade_item_authoring_workflow as workflow
from meridian.grade_items import (
    GRADE_ITEM_RECORD_TYPE,
    GRADE_ITEM_SCHEMA_VERSION,
    GradeItemRevision,
    GradeItemWeightingMetadata,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
CREATED = datetime(2026, 8, 25, 18, tzinfo=UTC)


def _revision(
    number: int,
    *,
    status: str = "active",
    title: str = "Unit 1",
) -> GradeItemRevision:
    return GradeItemRevision(
        schema_version=GRADE_ITEM_SCHEMA_VERSION,
        record_type=GRADE_ITEM_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=number,
        supersedes_revision=None if number == 1 else number - 1,
        title=title,
        purpose="standards_proficiency",
        status=status,  # type: ignore[arg-type]
        weighting=None,
        created_at=CREATED,
        revised_at=CREATED + timedelta(hours=number - 1),
    )


def _install_class(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "load_class_metadata",
        lambda path: SimpleNamespace(class_id=CLASS_ID),
    )


def _stored(revision: GradeItemRevision, digest: str = "a" * 64) -> object:
    return SimpleNamespace(revision=revision, revision_sha256=digest)


def test_create_preview_is_read_only_and_requires_explicit_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_class(monkeypatch)
    monkeypatch.setattr(workflow, "list_grade_item_revisions", lambda *args: ())
    monkeypatch.setattr(
        workflow,
        "write_grade_item_revision",
        lambda *args: (_ for _ in ()).throw(AssertionError("preview must not write")),
    )

    preview = workflow.preview_grade_item_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        operation="create",
        actor_id="teacher_local",
        revised_at=CREATED,
        title="Unit 1",
        purpose="standards_proficiency",
    )

    assert preview.actor_id == "teacher_local"
    assert preview.history_before == ()
    assert preview.candidate.grade_item_revision == 1
    assert preview.candidate.status == "active"
    assert preview.candidate.created_at == CREATED
    with pytest.raises(workflow.GradeItemAuthoringScopeError, match="actor_id"):
        workflow.preview_grade_item_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            operation="create",
            actor_id="",
            revised_at=CREATED,
            title="Unit 1",
            purpose="standards_proficiency",
        )


def test_revise_uses_latest_history_not_current_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_class(monkeypatch)
    latest = _revision(2, title="Latest")
    monkeypatch.setattr(workflow, "list_grade_item_revisions", lambda *args: (1, 2))
    monkeypatch.setattr(
        workflow,
        "load_grade_item_revision",
        lambda *args: _stored(latest),
    )

    preview = workflow.preview_grade_item_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        operation="revise",
        actor_id="teacher_local",
        revised_at=CREATED + timedelta(hours=3),
        title="Revised title",
        purpose="reporting_only",
    )

    assert preview.history_before == (1, 2)
    assert preview.candidate.grade_item_revision == 3
    assert preview.candidate.supersedes_revision == 2
    assert preview.candidate.created_at == CREATED
    assert preview.candidate.title == "Revised title"
    assert preview.candidate.purpose == "reporting_only"
    assert preview.candidate.status == "active"


def test_archive_and_reactivate_are_lifecycle_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_class(monkeypatch)
    active = _revision(1)
    history: tuple[int, ...] = (1,)
    latest = active

    monkeypatch.setattr(workflow, "list_grade_item_revisions", lambda *args: history)
    monkeypatch.setattr(
        workflow,
        "load_grade_item_revision",
        lambda *args: _stored(latest),
    )

    archived = workflow.preview_grade_item_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        operation="archive",
        actor_id="teacher_local",
        revised_at=CREATED + timedelta(hours=1),
    )
    assert archived.candidate.status == "archived"
    assert archived.candidate.title == active.title

    with pytest.raises(workflow.GradeItemAuthoringScopeError, match="lifecycle"):
        workflow.preview_grade_item_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            operation="archive",
            actor_id="teacher_local",
            revised_at=CREATED + timedelta(hours=1),
            title="Also change title",
        )

    history = (1, 2)
    latest = _revision(2, status="archived")
    reactivated = workflow.preview_grade_item_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        operation="reactivate",
        actor_id="teacher_local",
        revised_at=CREATED + timedelta(hours=2),
    )
    assert reactivated.candidate.status == "active"
    assert reactivated.candidate.title == latest.title


def test_commit_writes_exact_preview_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_class(monkeypatch)
    monkeypatch.setattr(workflow, "list_grade_item_revisions", lambda *args: ())
    preview = workflow.preview_grade_item_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        operation="create",
        actor_id="teacher_local",
        revised_at=CREATED,
        title="Unit 1",
        purpose="standards_proficiency",
    )
    calls: list[GradeItemRevision] = []

    def write(root: object, revision: GradeItemRevision) -> object:
        calls.append(revision)
        return SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(
                revision=revision,
                revision_sha256=preview.candidate_sha256,
            ),
        )

    monkeypatch.setattr(workflow, "write_grade_item_revision", write)
    import meridian.grade_item_storage as storage

    monkeypatch.setattr(storage, "get_current_grade_item_revision", lambda *args: None)
    monkeypatch.setattr(
        storage,
        "select_grade_item_revision",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("authoring must not select")
        ),
    )

    result = workflow.commit_grade_item_authoring_preview("workspace", preview)

    assert calls == [preview.candidate]
    assert result.write_disposition == "created"
    assert result.stored_revision_sha256 == preview.candidate_sha256
    assert result.selected_revision_after is None


def test_commit_fails_closed_when_history_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_class(monkeypatch)
    state: tuple[int, ...] = ()
    monkeypatch.setattr(workflow, "list_grade_item_revisions", lambda *args: state)
    preview = workflow.preview_grade_item_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        operation="create",
        actor_id="teacher_local",
        revised_at=CREATED,
        title="Unit 1",
        purpose="standards_proficiency",
    )
    state = (1,)
    monkeypatch.setattr(
        workflow,
        "write_grade_item_revision",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("stale preview must not write")
        ),
    )

    with pytest.raises(workflow.GradeItemAuthoringStaleError, match="history changed"):
        workflow.commit_grade_item_authoring_preview("workspace", preview)


def test_operation_preconditions_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_class(monkeypatch)
    monkeypatch.setattr(workflow, "list_grade_item_revisions", lambda *args: (1,))
    monkeypatch.setattr(
        workflow,
        "load_grade_item_revision",
        lambda *args: _stored(_revision(1)),
    )

    with pytest.raises(workflow.GradeItemAuthoringScopeError, match="Create requires"):
        workflow.preview_grade_item_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            operation="create",
            actor_id="teacher_local",
            revised_at=CREATED,
            title="Unit 1",
            purpose="standards_proficiency",
        )
    with pytest.raises(workflow.GradeItemAuthoringScopeError, match="archived"):
        workflow.preview_grade_item_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            operation="reactivate",
            actor_id="teacher_local",
            revised_at=CREATED + timedelta(hours=1),
        )

def _weighted_revision(
    number: int,
    *,
    category_id: str = "summative",
    relative_weight: Decimal = Decimal("2.5"),
) -> GradeItemRevision:
    return GradeItemRevision(
        schema_version=GRADE_ITEM_SCHEMA_VERSION,
        record_type=GRADE_ITEM_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=number,
        supersedes_revision=None if number == 1 else number - 1,
        title="Unit 1",
        purpose="standards_proficiency",
        status="active",
        weighting=GradeItemWeightingMetadata(
            category_id=category_id,
            relative_weight=relative_weight,
        ),
        created_at=CREATED,
        revised_at=CREATED + timedelta(hours=number - 1),
    )


def test_revise_omitted_weighting_preserves_previous_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_class(monkeypatch)
    latest = _weighted_revision(2)
    monkeypatch.setattr(
        workflow,
        "list_grade_item_revisions",
        lambda *args: (1, 2),
    )
    monkeypatch.setattr(
        workflow,
        "load_grade_item_revision",
        lambda *args: _stored(latest),
    )

    preview = workflow.preview_grade_item_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        operation="revise",
        actor_id="teacher_local",
        revised_at=CREATED + timedelta(hours=3),
        title="Revised title",
        purpose="standards_proficiency",
    )

    assert preview.candidate.weighting == latest.weighting


def test_revise_weighting_clear_and_replace_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_class(monkeypatch)
    latest = _weighted_revision(2)
    monkeypatch.setattr(
        workflow,
        "list_grade_item_revisions",
        lambda *args: (1, 2),
    )
    monkeypatch.setattr(
        workflow,
        "load_grade_item_revision",
        lambda *args: _stored(latest),
    )

    cleared = workflow.preview_grade_item_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        operation="revise",
        actor_id="teacher_local",
        revised_at=CREATED + timedelta(hours=3),
        title="Clear weighting",
        purpose="standards_proficiency",
        weighting_action="clear",
    )
    assert cleared.candidate.weighting is None

    replacement = GradeItemWeightingMetadata(
        category_id="performance",
        relative_weight=Decimal("4"),
    )
    replaced = workflow.preview_grade_item_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        operation="revise",
        actor_id="teacher_local",
        revised_at=CREATED + timedelta(hours=3),
        title="Replace weighting",
        purpose="standards_proficiency",
        weighting=replacement,
        weighting_action="replace",
    )
    assert replaced.candidate.weighting == replacement


def test_weighting_actions_respect_operation_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_class(monkeypatch)
    monkeypatch.setattr(workflow, "list_grade_item_revisions", lambda *args: ())

    with pytest.raises(
        workflow.GradeItemAuthoringScopeError,
        match="Create cannot clear",
    ):
        workflow.preview_grade_item_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            operation="create",
            actor_id="teacher_local",
            revised_at=CREATED,
            title="Unit 1",
            purpose="standards_proficiency",
            weighting_action="clear",
        )
