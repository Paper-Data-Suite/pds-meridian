from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli
from meridian.grade_item_selection_workflow import GradeItemSelectionStaleError

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
TARGET_DIGEST = "4" * 64


def _preview_stub() -> object:
    return SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        target=SimpleNamespace(
            revision=SimpleNamespace(
                class_id=CLASS_ID,
                grade_item_id=GRADE_ITEM_ID,
                grade_item_revision=1,
                status="archived",
            ),
            revision_sha256=TARGET_DIGEST,
        ),
        history=(1, 2),
        expected_current_revision=2,
        target_revision=1,
        target_status="archived",
        latest_revision=2,
        target_is_latest=False,
    )


def _result_stub() -> object:
    return SimpleNamespace(
        previous_current_revision=2,
        selected_revision=1,
        selected_status="archived",
        selection_disposition="updated",
    )


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "grade-items-select",
        CLASS_ID,
        GRADE_ITEM_ID,
        "1",
        "--workspace",
        "synthetic-workspace",
        *extra,
    )


def test_workflow_help_exposes_explicit_grade_item_selection_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "grade-items-select" in output
    assert "Preview or select one persisted Grade Item revision" in output


def test_without_confirmation_previews_and_performs_no_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _preview_stub()
    observed: dict[str, object] = {}

    def fake_preview(*args: object) -> object:
        observed["args"] = args
        return preview

    monkeypatch.setattr(cli, "preview_grade_item_selection", fake_preview)
    monkeypatch.setattr(
        cli,
        "commit_grade_item_selection_preview",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("unconfirmed Grade Item selection must not commit")
        ),
    )

    assert cli.main(_arguments(), dependencies=object()) == 0  # type: ignore[arg-type]
    output = capsys.readouterr().out

    assert observed["args"] == (
        "synthetic-workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        1,
    )
    assert "Grade Item current-selection preview" in output
    assert "target revision: 1" in output
    assert "target status: archived" in output
    assert "latest persisted revision: 2" in output
    assert "currently selected revision: 2" in output
    assert "confirmation supplied: no" in output
    assert "NO SELECTION PERFORMED" in output


def test_confirm_select_commits_exact_preview_without_authoring(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _preview_stub()
    result = _result_stub()
    monkeypatch.setattr(
        cli,
        "preview_grade_item_selection",
        lambda *args: preview,
    )
    observed: list[tuple[object, ...]] = []

    def fake_commit(*args: object) -> object:
        observed.append(args)
        return result

    monkeypatch.setattr(cli, "commit_grade_item_selection_preview", fake_commit)

    assert cli.main(
        _arguments("--confirm-select"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed == [("synthetic-workspace", preview)]
    assert "confirmation supplied: yes" in output
    assert "Selection committed: Grade Item revision 1" in output
    assert "previous current revision: 2" in output
    assert "selected status: archived" in output
    assert "authoring action: not performed" in output


def test_json_confirmation_reports_exact_selector_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_grade_item_selection",
        lambda *args: _preview_stub(),
    )
    monkeypatch.setattr(
        cli,
        "commit_grade_item_selection_preview",
        lambda *args: _result_stub(),
    )

    assert cli.main(
        _arguments("--confirm-select", "--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "selected"
    assert payload["selection_confirmed"] is True
    assert payload["preview"]["target_revision"] == 1
    assert payload["preview"]["target_revision_sha256"] == TARGET_DIGEST
    assert payload["preview"]["target_status"] == "archived"
    assert payload["preview"]["latest_revision"] == 2
    assert payload["preview"]["target_is_latest"] is False
    assert payload["preview"]["expected_current_revision"] == 2
    assert payload["result"]["selection_disposition"] == "updated"
    assert payload["result"]["previous_current_revision"] == 2
    assert payload["result"]["selected_revision"] == 1
    assert payload["result"]["selected_status"] == "archived"
    assert payload["result"]["authoring_action"] == "not_performed"


def test_stale_selection_preview_is_reported_as_workflow_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_grade_item_selection",
        lambda *args: (_ for _ in ()).throw(
            GradeItemSelectionStaleError("selection changed")
        ),
    )

    assert cli.main(_arguments(), dependencies=object()) == 1  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "teacher_workflow.grade_items.selection_stale" in captured.err
