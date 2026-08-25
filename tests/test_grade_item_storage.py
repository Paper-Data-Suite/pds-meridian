from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from meridian.grade_item_storage import (
    GRADE_ITEM_CURRENT_RECORD_TYPE,
    GRADE_ITEM_CURRENT_SCHEMA_VERSION,
    GradeItemCurrentSelection,
    GradeItemSelectionResult,
    GradeItemStorageConflictError,
    GradeItemStorageIntegrityError,
    GradeItemStorageLockError,
    GradeItemStorageNotFoundError,
    GradeItemStorageTooLargeError,
    GradeItemStorageValidationError,
    StoredGradeItemRevision,
    get_current_grade_item_revision,
    grade_item_current_path,
    grade_item_directory,
    grade_item_revision_digest_path,
    grade_item_revision_path,
    grade_item_revision_relative_path,
    list_grade_item_ids,
    list_grade_item_revisions,
    load_current_grade_item_revision,
    load_grade_item_revision,
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import (
    GradeItemRevision,
    GradeItemWeightingMetadata,
    grade_item_revision_to_json_bytes,
)

CREATED = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)
CLASS_ID = "english10_p2"
ITEM_ID = "unit1_assessment"


def make_workspace(tmp_path: Path) -> Path:
    class_root = tmp_path / "classes" / CLASS_ID
    class_root.mkdir(parents=True)
    (class_root / "roster.csv").write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "english10_p2,s001,Synthetic,Student,2\n",
        encoding="utf-8",
    )
    return tmp_path


def revision(number: int, *, title: str | None = None) -> GradeItemRevision:
    return GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=CLASS_ID,
        grade_item_id=ITEM_ID,
        grade_item_revision=number,
        supersedes_revision=None if number == 1 else number - 1,
        title=title or f"Unit 1 Assessment r{number}",
        purpose="standards_and_conventional",
        status="active",
        weighting=GradeItemWeightingMetadata(
            category_id="assessment", relative_weight=Decimal("1.0")
        ),
        created_at=CREATED,
        revised_at=CREATED if number == 1 else CREATED + timedelta(hours=number),
    )


def test_write_revision_uses_canonical_class_module_path(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    result = write_grade_item_revision(root, revision(1))
    assert result.disposition == "created"
    assert result.stored.relative_path == (
        "classes/english10_p2/modules/meridian/grade_items/"
        "unit1_assessment/revisions/1.json"
    )
    assert result.stored.path == grade_item_revision_path(root, CLASS_ID, ITEM_ID, 1)
    assert result.stored.path.is_file()
    assert grade_item_revision_digest_path(root, CLASS_ID, ITEM_ID, 1).is_file()
    assert get_current_grade_item_revision(root, CLASS_ID, ITEM_ID) is None


def test_write_does_not_create_missing_core_class(tmp_path: Path) -> None:
    with pytest.raises(GradeItemStorageNotFoundError):
        write_grade_item_revision(tmp_path, revision(1))
    assert not (tmp_path / "classes" / CLASS_ID).exists()


def test_write_preserves_history_and_requires_linear_revision(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    first = write_grade_item_revision(root, revision(1)).stored.content
    write_grade_item_revision(root, revision(2))
    assert load_grade_item_revision(root, CLASS_ID, ITEM_ID, 1).content == first
    assert list_grade_item_revisions(root, CLASS_ID, ITEM_ID) == (1, 2)

    skipped = GradeItemRevision(
        **{
            "schema_version": "1",
            "record_type": "meridian_grade_item",
            "class_id": CLASS_ID,
            "grade_item_id": ITEM_ID,
            "grade_item_revision": 4,
            "supersedes_revision": 3,
            "title": "Skipped",
            "purpose": "standards_proficiency",
            "status": "active",
            "weighting": None,
            "created_at": CREATED,
            "revised_at": CREATED + timedelta(hours=4),
        }
    )
    with pytest.raises(GradeItemStorageConflictError):
        write_grade_item_revision(root, skipped)


def test_exact_revision_retry_is_idempotent(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    created = write_grade_item_revision(root, revision(1))
    existing = write_grade_item_revision(root, revision(1))
    assert created.stored.revision_sha256 == existing.stored.revision_sha256
    assert existing.disposition == "existing"


def test_same_revision_identity_different_content_conflicts(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_grade_item_revision(root, revision(1))
    with pytest.raises(GradeItemStorageConflictError):
        write_grade_item_revision(root, revision(1, title="Different title"))


def test_listing_ids_and_revisions_is_deterministic(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_grade_item_revision(root, revision(1))
    other = GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=CLASS_ID,
        grade_item_id="another_item",
        grade_item_revision=1,
        supersedes_revision=None,
        title="Another",
        purpose="reporting_only",
        status="active",
        weighting=None,
        created_at=CREATED,
        revised_at=CREATED,
    )
    write_grade_item_revision(root, other)
    assert list_grade_item_ids(root, CLASS_ID) == ("another_item", ITEM_ID)


def test_selection_is_explicit_and_can_select_history(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_grade_item_revision(root, revision(1))
    write_grade_item_revision(root, revision(2))
    assert load_current_grade_item_revision(root, CLASS_ID, ITEM_ID) is None

    selected2 = select_grade_item_revision(
        root, CLASS_ID, ITEM_ID, 2, expected_current_revision=None
    )
    assert selected2.disposition == "created"
    assert get_current_grade_item_revision(root, CLASS_ID, ITEM_ID) == 2
    assert (
        load_current_grade_item_revision(root, CLASS_ID, ITEM_ID).revision
        == revision(2)
    )

    selected1 = select_grade_item_revision(
        root, CLASS_ID, ITEM_ID, 1, expected_current_revision=2
    )
    assert selected1.disposition == "updated"
    assert get_current_grade_item_revision(root, CLASS_ID, ITEM_ID) == 1


def test_selection_retry_and_stale_compare_and_swap(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_grade_item_revision(root, revision(1))
    first = select_grade_item_revision(
        root, CLASS_ID, ITEM_ID, 1, expected_current_revision=None
    )
    retry = select_grade_item_revision(
        root, CLASS_ID, ITEM_ID, 1, expected_current_revision=1
    )
    assert first.disposition == "created"
    assert retry.disposition == "existing"

    with pytest.raises(GradeItemStorageConflictError):
        select_grade_item_revision(
            root, CLASS_ID, ITEM_ID, 1, expected_current_revision=None
        )


def test_selection_rejects_missing_target(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_grade_item_revision(root, revision(1))
    with pytest.raises(GradeItemStorageNotFoundError):
        select_grade_item_revision(
            root, CLASS_ID, ITEM_ID, 2, expected_current_revision=None
        )


def test_revision_digest_is_exact_and_tampering_fails(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored = write_grade_item_revision(root, revision(1)).stored
    assert stored.revision_sha256 == hashlib.sha256(stored.content).hexdigest()

    path = grade_item_revision_path(root, CLASS_ID, ITEM_ID, 1)
    path.write_bytes(stored.content.replace(b"Unit 1", b"Unit X", 1))
    with pytest.raises(GradeItemStorageIntegrityError):
        load_grade_item_revision(root, CLASS_ID, ITEM_ID, 1)


def test_digest_sidecar_tampering_fails(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_grade_item_revision(root, revision(1))
    digest = grade_item_revision_digest_path(root, CLASS_ID, ITEM_ID, 1)
    digest.write_bytes(("0" * 64 + "\n").encode("ascii"))
    with pytest.raises(GradeItemStorageIntegrityError):
        load_grade_item_revision(root, CLASS_ID, ITEM_ID, 1)


def test_digest_sidecar_rejects_crlf_as_noncanonical(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    created = write_grade_item_revision(root, revision(1))
    digest = grade_item_revision_digest_path(root, CLASS_ID, ITEM_ID, 1)
    digest.write_bytes(
        (created.stored.revision_sha256 + "\r\n").encode("ascii")
    )
    with pytest.raises(GradeItemStorageIntegrityError, match="not canonical"):
        load_grade_item_revision(root, CLASS_ID, ITEM_ID, 1)


def test_current_pointer_digest_and_identity_are_verified(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_grade_item_revision(root, revision(1))
    select_grade_item_revision(
        root, CLASS_ID, ITEM_ID, 1, expected_current_revision=None
    )
    current = grade_item_current_path(root, CLASS_ID, ITEM_ID)
    data = json.loads(current.read_text(encoding="utf-8"))
    data["revision_sha256"] = "0" * 64
    current.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(GradeItemStorageIntegrityError):
        load_current_grade_item_revision(root, CLASS_ID, ITEM_ID)


def test_malformed_or_noncanonical_pointer_fails(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored = write_grade_item_revision(root, revision(1)).stored
    current = grade_item_current_path(root, CLASS_ID, ITEM_ID)
    current.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "record_type": "meridian_grade_item_current",
                "class_id": CLASS_ID,
                "grade_item_id": ITEM_ID,
                "grade_item_revision": 1,
                "revision_sha256": stored.revision_sha256,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(GradeItemStorageIntegrityError):
        get_current_grade_item_revision(root, CLASS_ID, ITEM_ID)


def test_unexpected_visible_entry_fails_closed(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_grade_item_revision(root, revision(1))
    (grade_item_directory(root, CLASS_ID, ITEM_ID) / "notes.txt").write_text(
        "unexpected", encoding="utf-8"
    )
    with pytest.raises(GradeItemStorageIntegrityError):
        list_grade_item_revisions(root, CLASS_ID, ITEM_ID)


def test_lock_conflict_fails_closed(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_grade_item_revision(root, revision(1))
    lock = grade_item_directory(root, CLASS_ID, ITEM_ID) / ".write.lock"
    lock.write_text("leftover", encoding="utf-8")
    with pytest.raises(GradeItemStorageLockError):
        write_grade_item_revision(root, revision(2))


def test_bounded_revision_read_rejects_oversize(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_grade_item_revision(root, revision(1))
    with pytest.raises(GradeItemStorageTooLargeError):
        load_grade_item_revision(
            root,
            CLASS_ID,
            ITEM_ID,
            1,
            maximum_revision_bytes=8,
        )


def test_relative_path_is_platform_neutral(tmp_path: Path) -> None:
    make_workspace(tmp_path)
    assert grade_item_revision_relative_path(CLASS_ID, ITEM_ID, 3) == (
        "classes/english10_p2/modules/meridian/grade_items/"
        "unit1_assessment/revisions/3.json"
    )
    assert "\\" not in grade_item_revision_relative_path(CLASS_ID, ITEM_ID, 3)


def test_invalid_identifier_cannot_traverse(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    with pytest.raises(Exception):
        grade_item_directory(root, CLASS_ID, "../outside")
    assert not (tmp_path / "outside").exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_symlinked_revision_is_rejected(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_grade_item_revision(root, revision(1))
    path = grade_item_revision_path(root, CLASS_ID, ITEM_ID, 1)
    target = tmp_path / "outside.json"
    target.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not permitted on this platform")
    with pytest.raises(GradeItemStorageIntegrityError):
        load_grade_item_revision(root, CLASS_ID, ITEM_ID, 1)


def test_grade_item_storage_contains_no_student_or_producer_mutation(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    producer_root = (
        root / "classes" / CLASS_ID / "modules" / "scoreform" / "work" / "unit1"
    )
    producer_root.mkdir(parents=True)
    marker = producer_root / "marker.txt"
    marker.write_text("producer-owned", encoding="utf-8")
    before = marker.read_bytes()

    write_grade_item_revision(root, revision(1))

    assert marker.read_bytes() == before
    serialized = load_grade_item_revision(root, CLASS_ID, ITEM_ID, 1).content
    assert b"student_id" not in serialized
    assert b"student_ids" not in serialized



def test_stored_revision_rejects_content_model_mismatch(tmp_path: Path) -> None:
    first = revision(1)
    second = GradeItemRevision(
        schema_version=first.schema_version,
        record_type=first.record_type,
        class_id=first.class_id,
        grade_item_id=first.grade_item_id,
        grade_item_revision=first.grade_item_revision,
        supersedes_revision=first.supersedes_revision,
        title="Different",
        purpose=first.purpose,
        status=first.status,
        weighting=first.weighting,
        created_at=first.created_at,
        revised_at=first.revised_at,
    )
    content = grade_item_revision_to_json_bytes(first)
    digest = hashlib.sha256(content).hexdigest()
    with pytest.raises(
        GradeItemStorageValidationError,
        match="content does not decode to revision",
    ):
        StoredGradeItemRevision(
            revision=second,
            revision_sha256=digest,
            path=tmp_path / "1.json",
            relative_path=grade_item_revision_relative_path(
                CLASS_ID, ITEM_ID, 1
            ),
            content=content,
        )


def test_selection_result_rejects_mismatched_stored_revision(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    first = write_grade_item_revision(workspace, revision(1)).stored
    selection = GradeItemCurrentSelection(
        schema_version=GRADE_ITEM_CURRENT_SCHEMA_VERSION,
        record_type=GRADE_ITEM_CURRENT_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=ITEM_ID,
        grade_item_revision=1,
        revision_sha256="0" * 64,
    )
    with pytest.raises(
        GradeItemStorageValidationError,
        match="selection digest must match",
    ):
        GradeItemSelectionResult(
            disposition="created",
            selection=selection,
            stored=first,
        )
