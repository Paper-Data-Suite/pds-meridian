"""#124 E2G3J: a reopened #122 receipt against actual canonical Grade Item files.

No producer or student records are used. Only the synthetic fixture's initial
Grade Item creation and an explicitly confirmed restart selector may write.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from pds_core.class_metadata import (
    create_class_metadata,
    write_class_metadata_for_class,
)

from meridian import menu_teacher_action_recovery as menu
from meridian.grade_item_storage import (
    GradeItemStorageIntegrityError,
    get_current_grade_item_revision,
    grade_item_current_path,
    grade_item_revision_digest_path,
    grade_item_revision_path,
    list_grade_item_revisions,
    load_current_grade_item_revision,
    load_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import GradeItemRevision
from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionCheckpoint,
    TeacherActionPreview,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_guided import _identity
from meridian.teacher_action_orchestration import TeacherActionConflictError
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_action_restart_grade_item import (
    inspect_restart_grade_item,
    resume_restart_grade_item,
)
from meridian.teacher_session import TeacherSessionContext

CLASS_ID = "class_one"
GRADE_ITEM_ID = "grade_one"
STAMP = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)


def _actor_check(actor: TeacherActionActor) -> None:
    assert actor == TeacherActionActor("test_teacher", "a" * 64, "saved")


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _fixture(root: Path) -> TeacherActionPreview:
    """Write real metadata, canonical immutable revision and interrupted receipt."""
    write_class_metadata_for_class(
        root,
        create_class_metadata(CLASS_ID, "2026-2027", created_at=STAMP),
    )
    revision = GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=1,
        supersedes_revision=None,
        title="Synthetic Unit 1 Assessment",
        purpose="standards_proficiency",
        status="active",
        weighting=None,
        created_at=STAMP,
        revised_at=STAMP,
    )
    stored = write_grade_item_revision(root, revision).stored
    actor = TeacherActionActor("test_teacher", "a" * 64, "saved")
    identity = _identity("grade_item", CLASS_ID, GRADE_ITEM_ID)
    digest = stored.revision_sha256
    preview = TeacherActionPreview(
        action_id="ab" * 16,
        kind="grade_item",
        scope=TeacherActionScope(
            workspace_sha256=_identity("workspace", str(root)),
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
        ),
        actor=actor,
        target=TeacherActionTarget("grade_item", identity, 1, digest, None, None),
        basis=(
            TeacherActionBasis(
                "actor_profile", _identity(actor.actor_id), actor.profile_sha256
            ),
            TeacherActionBasis(
                "canonical_source", identity, _identity("grade_item_candidate", digest)
            ),
        ),
        reviewed_decision_sha256=digest,
    )
    store = TeacherActionReceiptStore(root, CLASS_ID)
    prepared = store.prepare(preview)
    store.record_checkpoint(
        preview,
        expected_generation=prepared.generation,
        checkpoint=TeacherActionCheckpoint("write", "completed"),
    )
    return preview


def _reopen(root: Path, preview: TeacherActionPreview):
    store = TeacherActionReceiptStore(root, CLASS_ID)
    receipt = store.load(preview.action_id)
    assert receipt is not None
    assert receipt.preview == preview
    return store, receipt


def test_real_canonical_and_receipt_reopen_read_only(tmp_path: Path) -> None:
    preview = _fixture(tmp_path)
    before = _files(tmp_path)
    store, receipt = _reopen(tmp_path, preview)
    assert list_grade_item_revisions(tmp_path, CLASS_ID, GRADE_ITEM_ID) == (1,)
    assert load_current_grade_item_revision(tmp_path, CLASS_ID, GRADE_ITEM_ID) is None
    checked = inspect_restart_grade_item(
        tmp_path, store, receipt, actor_checker=_actor_check
    )
    assert checked.status == "written_not_current"
    assert checked.can_resume
    assert checked.title == "Synthetic Unit 1 Assessment"
    assert _files(tmp_path) == before


def test_cancelled_resume_never_selects_canonical_record(tmp_path: Path) -> None:
    preview = _fixture(tmp_path)
    before = _files(tmp_path)
    store, receipt = _reopen(tmp_path, preview)
    with pytest.raises(TeacherActionConflictError, match="not confirmed"):
        resume_restart_grade_item(
            tmp_path, store, receipt, confirmation="B", actor_checker=_actor_check
        )
    assert get_current_grade_item_revision(tmp_path, CLASS_ID, GRADE_ITEM_ID) is None
    assert _files(tmp_path) == before


def test_explicit_resume_selects_once_without_reauthoring(tmp_path: Path) -> None:
    preview = _fixture(tmp_path)
    revision_path = grade_item_revision_path(tmp_path, CLASS_ID, GRADE_ITEM_ID, 1)
    digest_path = grade_item_revision_digest_path(tmp_path, CLASS_ID, GRADE_ITEM_ID, 1)
    unchanged = (revision_path.read_bytes(), digest_path.read_bytes())
    store, receipt = _reopen(tmp_path, preview)
    result = resume_restart_grade_item(
        tmp_path, store, receipt, confirmation="RESUME", actor_checker=_actor_check
    )
    assert result.succeeded
    assert get_current_grade_item_revision(tmp_path, CLASS_ID, GRADE_ITEM_ID) == 1
    assert list_grade_item_revisions(tmp_path, CLASS_ID, GRADE_ITEM_ID) == (1,)
    assert (revision_path.read_bytes(), digest_path.read_bytes()) == unchanged
    checked_store, checked_receipt = _reopen(tmp_path, preview)
    inspected = inspect_restart_grade_item(
        tmp_path, checked_store, checked_receipt, actor_checker=_actor_check
    )
    assert inspected.status == "already_applied"
    assert not inspected.can_resume
    after = _files(tmp_path)
    with pytest.raises(TeacherActionConflictError, match="unavailable"):
        resume_restart_grade_item(
            tmp_path,
            checked_store,
            checked_receipt,
            confirmation="RESUME",
            actor_checker=_actor_check,
        )
    assert _files(tmp_path) == after


def test_later_canonical_revision_prevents_stale_resume(tmp_path: Path) -> None:
    preview = _fixture(tmp_path)
    original = load_grade_item_revision(tmp_path, CLASS_ID, GRADE_ITEM_ID, 1).revision
    second = replace(
        original,
        grade_item_revision=2,
        supersedes_revision=1,
        title="Newer Synthetic Assessment",
        revised_at=STAMP + timedelta(days=1),
    )
    write_grade_item_revision(tmp_path, second)
    before = _files(tmp_path)
    store, receipt = _reopen(tmp_path, preview)
    with pytest.raises(TeacherActionConflictError, match="history changed"):
        inspect_restart_grade_item(tmp_path, store, receipt, actor_checker=_actor_check)
    assert get_current_grade_item_revision(tmp_path, CLASS_ID, GRADE_ITEM_ID) is None
    assert _files(tmp_path) == before


def test_canonical_digest_corruption_blocks_restart(tmp_path: Path) -> None:
    preview = _fixture(tmp_path)
    sidecar = grade_item_revision_digest_path(tmp_path, CLASS_ID, GRADE_ITEM_ID, 1)
    sidecar.write_bytes(("0" * 64 + "\n").encode("ascii"))
    before = _files(tmp_path)
    with pytest.raises(GradeItemStorageIntegrityError):
        load_grade_item_revision(tmp_path, CLASS_ID, GRADE_ITEM_ID, 1)
    store, receipt = _reopen(tmp_path, preview)
    try:
        inspected = inspect_restart_grade_item(
            tmp_path, store, receipt, actor_checker=_actor_check
        )
    except GradeItemStorageIntegrityError:
        pass  # A direct canonical-integrity refusal is also fail-closed.
    else:
        assert not inspected.can_resume
    assert not grade_item_current_path(tmp_path, CLASS_ID, GRADE_ITEM_ID).exists()
    assert _files(tmp_path) == before


def test_restarted_menu_requires_explicit_resume_and_no_duplicate(
    tmp_path: Path,
) -> None:
    preview = _fixture(tmp_path)
    original_inspector = inspect_restart_grade_item
    original_resumer = resume_restart_grade_item

    def inspector(root: Path, store: TeacherActionReceiptStore, receipt: object):
        return original_inspector(root, store, receipt, actor_checker=_actor_check)

    def resumer(
        root: Path,
        store: TeacherActionReceiptStore,
        receipt: object,
        *,
        confirmation: str,
    ):
        return original_resumer(
            root, store, receipt, confirmation=confirmation, actor_checker=_actor_check
        )

    def run_menu(answers: tuple[str, ...]) -> str:
        response = iter(answers)
        output = StringIO()
        menu.run_teacher_action_recovery_menu(
            session_context=TeacherSessionContext(active_class_id=CLASS_ID),
            workspace_resolver=lambda: tmp_path,
            input_fn=lambda _: next(response),
            output=output,
            clear_fn=lambda: None,
        )
        return output.getvalue()

    before = _files(tmp_path)
    with (
        patch.object(menu, "inspect_restart_grade_item", side_effect=inspector),
        patch.object(menu, "resume_restart_grade_item", side_effect=resumer),
    ):
        cancelled = run_menu(("1", "CANCEL", "", "B"))
        assert "Type RESUME" in cancelled
        assert _files(tmp_path) == before
        confirmed = run_menu(("1", "RESUME", "", "B"))
        assert "Type RESUME" in confirmed
        assert get_current_grade_item_revision(tmp_path, CLASS_ID, GRADE_ITEM_ID) == 1
        assert list_grade_item_revisions(tmp_path, CLASS_ID, GRADE_ITEM_ID) == (1,)
        selected = _files(tmp_path)
        reopened = run_menu(("1", "", "B"))
        assert "not authorized" in reopened
        assert _files(tmp_path) == selected
    _, receipt = _reopen(tmp_path, preview)
    assert receipt.checkpoints[-1].stage == "receipt_finalized"
