from __future__ import annotations

from pathlib import Path

import pytest

from meridian.grouping_signal_preview_storage import (
    GroupingSignalPreviewStorageConflictError,
    GroupingSignalPreviewStorageIntegrityError,
    grouping_signal_preview_path,
    grouping_signal_preview_relative_path,
    grouping_signal_previews_directory,
    list_grouping_signal_preview_ids,
    load_grouping_signal_preview,
    load_grouping_signal_preview_reference,
    write_grouping_signal_preview,
)
from tests.test_grouping_signal_preview import _preview

CLASS_ID = "synthetic_class_2026"


def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


def test_preview_storage_is_content_addressed_and_idempotent(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    preview = _preview()

    first = write_grouping_signal_preview(root, preview)
    second = write_grouping_signal_preview(root, preview)

    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert first.stored.reference == second.stored.reference
    assert first.stored.content == second.stored.content
    assert list_grouping_signal_preview_ids(root, CLASS_ID) == (
        preview.preview_id,
    )
    assert not (
        grouping_signal_previews_directory(root, CLASS_ID) / "current.json"
    ).exists()
    assert not (
        grouping_signal_previews_directory(root, CLASS_ID) / "latest.json"
    ).exists()


def test_preview_storage_exact_reference_round_trip(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    preview = _preview()
    stored = write_grouping_signal_preview(root, preview).stored

    loaded = load_grouping_signal_preview_reference(root, stored.reference)

    assert loaded.snapshot == preview
    assert loaded.reference == stored.reference
    assert loaded.relative_path == grouping_signal_preview_relative_path(
        CLASS_ID,
        preview.preview_id,
    )
    assert loaded.path == grouping_signal_preview_path(
        root,
        CLASS_ID,
        preview.preview_id,
    )


def test_preview_storage_rejects_tampered_bytes(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    preview = _preview()
    stored = write_grouping_signal_preview(root, preview).stored
    stored.path.write_bytes(stored.content + b" ")

    with pytest.raises(GroupingSignalPreviewStorageIntegrityError):
        load_grouping_signal_preview(
            root,
            CLASS_ID,
            preview.preview_id,
        )


def test_preview_storage_rejects_incomplete_pair(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    preview = _preview()
    stored = write_grouping_signal_preview(root, preview).stored
    Path(str(stored.path) + ".sha256").unlink()

    with pytest.raises(GroupingSignalPreviewStorageIntegrityError):
        load_grouping_signal_preview(
            root,
            CLASS_ID,
            preview.preview_id,
        )


def test_preview_storage_rejects_visible_collection_junk(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    preview = _preview()
    write_grouping_signal_preview(root, preview)
    collection = grouping_signal_previews_directory(root, CLASS_ID)
    (collection / "unexpected.txt").write_text("junk", encoding="utf-8")

    with pytest.raises(GroupingSignalPreviewStorageIntegrityError):
        list_grouping_signal_preview_ids(root, CLASS_ID)


def test_same_identity_with_different_content_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = workspace(tmp_path)
    preview = _preview()
    write_grouping_signal_preview(root, preview)

    import meridian.grouping_signal_preview_storage as storage

    real_serializer = storage.grouping_signal_preview_snapshot_to_json_bytes
    monkeypatch.setattr(
        storage,
        "grouping_signal_preview_snapshot_to_json_bytes",
        lambda value: real_serializer(value) + b" ",
    )

    with pytest.raises(GroupingSignalPreviewStorageConflictError):
        write_grouping_signal_preview(root, preview)
