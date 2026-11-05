"""#124 E2G3I: persisted Grade Item receipt survives menu restart safely."""

from __future__ import annotations

import hashlib
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.menu_teacher_action_recovery import run_teacher_action_recovery_menu
from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionPreview,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_action_recovery_inventory import read_recovery_inbox
from meridian.teacher_session import TeacherSessionContext


def _persist_grade_receipt(root: Path) -> TeacherActionPreview:
    (root / "classes" / "class_one").mkdir(parents=True)
    workspace_digest = hashlib.sha256(
        "\x1f".join(("workspace", str(root))).encode("utf-8")
    ).hexdigest()
    preview = TeacherActionPreview(
        action_id="ab" * 16,
        kind="grade_item",
        scope=TeacherActionScope(
            workspace_sha256=workspace_digest,
            class_id="class_one",
            grade_item_id="grade_one",
        ),
        actor=TeacherActionActor("teacher", "a" * 64, "saved"),
        target=TeacherActionTarget("grade_item", "b" * 64, 1, "c" * 64, None, None),
        basis=(TeacherActionBasis("registration", "d" * 64, "e" * 64),),
        reviewed_decision_sha256="c" * 64,
    )
    TeacherActionReceiptStore(root, "class_one").prepare(preview)
    return preview


def _run(root: Path, *, reconstructed_context_loader=None) -> str:
    answer = iter(("1", "", "B"))
    output = StringIO()
    run_teacher_action_recovery_menu(
        session_context=TeacherSessionContext(active_class_id="class_one"),
        reconstructed_context_loader=reconstructed_context_loader,
        workspace_resolver=lambda: root,
        class_validator=lambda *_: None,
        input_fn=lambda _: next(answer),
        output=output,
        clear_fn=lambda: None,
    )
    return output.getvalue()


def test_restarted_grade_receipt_requires_fresh_context(tmp_path: Path) -> None:
    preview = _persist_grade_receipt(tmp_path)
    store = TeacherActionReceiptStore(tmp_path, "class_one")
    receipt_path = store.path_for(preview.action_id)
    before = receipt_path.read_bytes()
    restarted = read_recovery_inbox(TeacherActionReceiptStore(tmp_path, "class_one"))
    assert restarted.review_count == 1
    assert restarted.entries[0].kind == "grade_item"
    assert restarted.entries[0].receipt.preview == preview
    with (
        patch(
            "meridian.menu_teacher_action_recovery._offer_grade_item_resume"
        ) as legacy,
        patch(
            "meridian.menu_teacher_action_recovery.offer_assessment_setup_recovery"
        ) as prompt,
    ):
        display = _run(
            tmp_path,
            reconstructed_context_loader=lambda *_: (None, None),
        )
    assert "could not be verified safely" in display
    legacy.assert_not_called()
    prompt.assert_not_called()
    assert receipt_path.read_bytes() == before


def test_missing_correlation_blocks_persisted_grade_receipt(tmp_path: Path) -> None:
    preview = _persist_grade_receipt(tmp_path)
    store = TeacherActionReceiptStore(tmp_path, "class_one")
    receipt_path = store.path_for(preview.action_id)
    before = receipt_path.read_bytes()
    reviewed = Mock(spec=AssessmentSetupPreview)
    reviewed.class_id = "class_one"
    reviewed.grade_item_id = "grade_one"
    reviewed.work = SimpleNamespace(module_id="scoreform", work_id="work_one")
    actor = preview.actor
    with (
        patch(
            "meridian.menu_teacher_action_recovery._offer_grade_item_resume"
        ) as legacy,
        patch(
            "meridian.menu_teacher_action_recovery.offer_assessment_setup_recovery"
        ) as prompt,
    ):
        display = _run(
            tmp_path,
            reconstructed_context_loader=lambda *_: (reviewed, actor, lambda: reviewed),
        )
    assert "could not be verified safely" in display
    legacy.assert_not_called()
    prompt.assert_not_called()
    assert receipt_path.read_bytes() == before
    assert not (
        tmp_path
        / "classes"
        / "class_one"
        / "meridian"
        / "assessment_setup_correlations"
    ).exists()


def test_reopened_receipt_list_stable_without_menu_mutations(tmp_path: Path) -> None:
    preview = _persist_grade_receipt(tmp_path)
    store = TeacherActionReceiptStore(tmp_path, "class_one")
    before = {
        p.relative_to(tmp_path).as_posix(): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    with patch("meridian.menu_teacher_action_recovery._offer_grade_item_resume"):
        _run(tmp_path, reconstructed_context_loader=lambda *_: (None, None))
        _run(tmp_path, reconstructed_context_loader=lambda *_: (None, None))
    after = {
        p.relative_to(tmp_path).as_posix(): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert after == before
    assert store.load(preview.action_id).preview == preview
