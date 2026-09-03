from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import meridian.grade_item_selection_workflow as workflow
from meridian.grade_item_storage import StoredGradeItemRevision
from meridian.grade_items import GradeItemRevision, grade_item_revision_to_json_bytes

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
CREATED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _revision(number: int, *, status: str = "active") -> GradeItemRevision:
    return GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=number,
        supersedes_revision=None if number == 1 else number - 1,
        title=f"Unit 1 revision {number}",
        purpose="standards_proficiency",
        status=status,  # type: ignore[arg-type]
        weighting=None,
        created_at=CREATED,
        revised_at=CREATED,
    )


def _stored(
    number: int,
    *,
    status: str = "active",
    digest: str | None = None,
) -> StoredGradeItemRevision:
    revision = _revision(number, status=status)
    content = grade_item_revision_to_json_bytes(revision)
    import hashlib

    actual = hashlib.sha256(content).hexdigest()
    return StoredGradeItemRevision(
        revision=revision,
        revision_sha256=digest or actual,
        path=Path(f"{number}.json"),
        relative_path=(
            f"classes/{CLASS_ID}/modules/meridian/grade_items/"
            f"{GRADE_ITEM_ID}/revisions/{number}.json"
        ),
        content=content,
    )


def _install_read_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    history: tuple[int, ...] = (1, 2),
    current: int | None = 2,
    target_status: str = "active",
) -> StoredGradeItemRevision:
    target = _stored(1, status=target_status)
    monkeypatch.setattr(
        workflow,
        "list_grade_item_revisions",
        lambda *args: history,
    )
    monkeypatch.setattr(
        workflow,
        "load_grade_item_revision",
        lambda *args: target,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_grade_item_revision",
        lambda *args: current,
    )
    return target


def test_preview_exact_historical_revision_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _install_read_state(monkeypatch, current=2)
    monkeypatch.setattr(
        workflow,
        "select_grade_item_revision",
        lambda *args, **kwargs: pytest.fail("preview must not select"),
    )

    preview = workflow.preview_grade_item_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        1,
    )

    assert preview.target is target
    assert preview.target_revision == 1
    assert preview.latest_revision == 2
    assert preview.target_is_latest is False
    assert preview.expected_current_revision == 2


def test_preview_allows_archived_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_read_state(monkeypatch, current=1, target_status="archived")

    preview = workflow.preview_grade_item_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        1,
    )

    assert preview.target_status == "archived"


def test_commit_selects_exact_target_with_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _install_read_state(monkeypatch, current=2)
    preview = workflow.preview_grade_item_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        1,
    )
    observed: dict[str, object] = {}

    def select(
        workspace_root: str,
        class_id: str,
        grade_item_id: str,
        grade_item_revision: int,
        *,
        expected_current_revision: int | None,
    ) -> object:
        observed.update(
            workspace_root=workspace_root,
            class_id=class_id,
            grade_item_id=grade_item_id,
            grade_item_revision=grade_item_revision,
            expected_current_revision=expected_current_revision,
        )
        selection = SimpleNamespace(grade_item_revision=1)
        return SimpleNamespace(
            selection=selection,
            stored=target,
            disposition="updated",
        )

    monkeypatch.setattr(workflow, "select_grade_item_revision", select)

    result = workflow.commit_grade_item_selection_preview(
        "workspace",
        preview,
    )

    assert observed == {
        "workspace_root": "workspace",
        "class_id": CLASS_ID,
        "grade_item_id": GRADE_ITEM_ID,
        "grade_item_revision": 1,
        "expected_current_revision": 2,
    }
    assert result.previous_current_revision == 2
    assert result.selected_revision == 1
    assert result.selected_status == "active"
    assert result.selection_disposition == "updated"


def test_commit_fails_if_history_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_read_state(monkeypatch, current=2)
    preview = workflow.preview_grade_item_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        1,
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_revisions",
        lambda *args: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "select_grade_item_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not select"),
    )

    with pytest.raises(workflow.GradeItemSelectionStaleError, match="history"):
        workflow.commit_grade_item_selection_preview("workspace", preview)


def test_commit_fails_if_current_selection_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_read_state(monkeypatch, current=2)
    preview = workflow.preview_grade_item_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        1,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_grade_item_revision",
        lambda *args: 1,
    )
    monkeypatch.setattr(
        workflow,
        "select_grade_item_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not select"),
    )

    with pytest.raises(workflow.GradeItemSelectionStaleError, match="selection"):
        workflow.commit_grade_item_selection_preview("workspace", preview)


def test_invalid_or_missing_target_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "list_grade_item_revisions",
        lambda *args: (1, 2),
    )

    with pytest.raises(workflow.GradeItemSelectionScopeError, match="positive"):
        workflow.preview_grade_item_selection(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            0,
        )

    with pytest.raises(workflow.GradeItemSelectionScopeError, match="not present"):
        workflow.preview_grade_item_selection(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            3,
        )
