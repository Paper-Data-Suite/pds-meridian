from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli
from meridian.grade_item_membership_selection_workflow import (
    GradeItemMembershipSelectionStaleError,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
MODULE_ID = "scoreform"
WORK_ID = "test_1"
TARGET_DIGEST = "c" * 64


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "grade-items-membership-select",
        CLASS_ID,
        GRADE_ITEM_ID,
        MODULE_ID,
        WORK_ID,
        "1",
        "--workspace",
        "synthetic-workspace",
        *extra,
    )


def _preview(work: object) -> object:
    decision = SimpleNamespace(
        membership_revision=1,
        decision="included",
        grade_item_revision=2,
        grade_item_revision_sha256="a" * 64,
        work_reference=SimpleNamespace(
            work=work,
            registration_revision=7,
        ),
        academic_period=SimpleNamespace(
            period=SimpleNamespace(
                school_year="2026-2027",
                period_id="mp1",
            ),
            calendar_revision=3,
        ),
    )
    return SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        target=SimpleNamespace(
            decision=decision,
            decision_sha256=TARGET_DIGEST,
        ),
        history=(1, 2),
        expected_current_membership_revision=2,
        target_revision=1,
        target_decision="included",
        target_grade_item_revision=2,
        target_registration_revision=7,
        latest_revision=2,
        target_is_latest=False,
    )


def _result() -> object:
    return SimpleNamespace(
        previous_current_membership_revision=2,
        selected_revision=1,
        selected_decision="included",
        selection_disposition="updated",
        authoring_action="not_performed",
    )


def test_workflow_help_exposes_membership_selection_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "grade-items-membership-select" in output
    assert "Preview or select one Grade Item membership revision" in output


def test_without_confirmation_previews_and_performs_no_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}

    def fake_preview(
        workspace_root: str,
        class_id: str,
        grade_item_id: str,
        work: object,
        membership_revision: int,
    ) -> object:
        observed.update(
            workspace_root=workspace_root,
            class_id=class_id,
            grade_item_id=grade_item_id,
            work=work,
            membership_revision=membership_revision,
        )
        return _preview(work)

    monkeypatch.setattr(
        cli,
        "preview_grade_item_membership_selection",
        fake_preview,
    )
    monkeypatch.setattr(
        cli,
        "commit_grade_item_membership_selection_preview",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("unconfirmed membership selection must not commit")
        ),
    )

    assert cli.main(_arguments(), dependencies=object()) == 0  # type: ignore[arg-type]
    output = capsys.readouterr().out

    work = observed["work"]
    assert work.module_id == MODULE_ID  # type: ignore[union-attr]
    assert work.class_id == CLASS_ID  # type: ignore[union-attr]
    assert work.work_id == WORK_ID  # type: ignore[union-attr]
    assert observed["membership_revision"] == 1
    assert "Grade Item membership current-selection preview" in output
    assert "target membership revision: 1" in output
    assert "target decision: included" in output
    assert "target Grade Item revision: 2" in output
    assert "target registration revision: 7" in output
    assert "currently selected membership revision: 2" in output
    assert "confirmation supplied: no" in output
    assert "NO MEMBERSHIP SELECTION PERFORMED" in output


def test_confirm_select_commits_exact_preview_without_authoring(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previews: list[object] = []

    def fake_preview(
        workspace_root: str,
        class_id: str,
        grade_item_id: str,
        work: object,
        membership_revision: int,
    ) -> object:
        del workspace_root, class_id, grade_item_id, membership_revision
        preview = _preview(work)
        previews.append(preview)
        return preview

    monkeypatch.setattr(
        cli,
        "preview_grade_item_membership_selection",
        fake_preview,
    )
    observed: list[tuple[object, ...]] = []

    def fake_commit(*args: object) -> object:
        observed.append(args)
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_grade_item_membership_selection_preview",
        fake_commit,
    )

    assert cli.main(
        _arguments("--confirm-select"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed == [("synthetic-workspace", previews[0])]
    assert "confirmation supplied: yes" in output
    assert "Membership selection committed: revision 1" in output
    assert "selected decision: included" in output
    assert "membership authoring action: not performed" in output


def test_json_confirmation_reports_exact_historical_basis(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_preview(
        workspace_root: str,
        class_id: str,
        grade_item_id: str,
        work: object,
        membership_revision: int,
    ) -> object:
        del workspace_root, class_id, grade_item_id, membership_revision
        return _preview(work)

    monkeypatch.setattr(
        cli,
        "preview_grade_item_membership_selection",
        fake_preview,
    )
    monkeypatch.setattr(
        cli,
        "commit_grade_item_membership_selection_preview",
        lambda *args: _result(),
    )

    assert cli.main(
        _arguments("--confirm-select", "--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "selected"
    assert data["selection_confirmed"] is True
    assert data["preview"]["target_revision"] == 1
    assert data["preview"]["target_decision_sha256"] == TARGET_DIGEST
    assert data["preview"]["target_is_latest"] is False
    assert data["preview"]["target_grade_item_revision"] == 2
    assert data["preview"]["target_registration_revision"] == 7
    assert data["preview"]["academic_period"] == {
        "school_year": "2026-2027",
        "period_id": "mp1",
        "calendar_revision": 3,
    }
    assert data["result"]["selected_revision"] == 1
    assert data["result"]["selected_decision"] == "included"
    assert data["result"]["authoring_action"] == "not_performed"


def test_invalid_work_identity_uses_membership_selection_error_boundary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = list(_arguments())
    arguments[4] = "ScoreForm"

    assert cli.main(
        tuple(arguments),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        "teacher_workflow.grade_items.membership_selection_invalid"
        in captured.err
    )


def test_stale_preview_is_reported_as_workflow_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_grade_item_membership_selection",
        lambda *args: (_ for _ in ()).throw(
            GradeItemMembershipSelectionStaleError("selector changed")
        ),
    )

    assert cli.main(_arguments(), dependencies=object()) == 1  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        "teacher_workflow.grade_items.membership_selection_stale"
        in captured.err
    )
