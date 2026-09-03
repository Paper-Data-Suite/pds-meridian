from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
MODULE_ID = "scoreform"
WORK_ID = "test_1"
POLICY_ID = "explicit_one"


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "attempt-policy-select",
        CLASS_ID,
        GRADE_ITEM_ID,
        MODULE_ID,
        WORK_ID,
        POLICY_ID,
        "1",
        "--workspace",
        "synthetic-workspace",
        *extra,
    )


def _policy() -> object:
    return SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=SimpleNamespace(
            module_id=MODULE_ID,
            class_id=CLASS_ID,
            work_id=WORK_ID,
        ),
        policy_id=POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        selection_basis="explicit",
        minimum_selected=0,
        maximum_selected=1,
        actor=SimpleNamespace(
            kind="teacher",
            actor_id="teacher_local",
        ),
        rationale=None,
    )


def _preview() -> object:
    target = SimpleNamespace(
        policy=_policy(),
        policy_sha256="a" * 64,
    )
    return SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=target.policy.work,
        policy_id=POLICY_ID,
        target=target,
        history=(1, 2),
        expected_current_policy_revision=2,
        target_revision=1,
        target_sha256="a" * 64,
        latest_revision=2,
        target_is_latest=False,
    )


def _result() -> object:
    return SimpleNamespace(
        selected_revision=1,
        selected_policy_sha256="a" * 64,
        selection_disposition="updated",
        previous_current_policy_revision=2,
        authoring_action="not_performed",
    )


def test_workflow_help_exposes_attempt_policy_select_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "attempt-policy-select" in output
    assert "Preview or select one persisted attempt-selection policy" in output


def test_without_confirmation_previews_and_performs_no_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}
    preview = _preview()

    def fake_preview(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return preview

    monkeypatch.setattr(cli, "preview_attempt_policy_selection", fake_preview)
    monkeypatch.setattr(
        cli,
        "commit_attempt_policy_selection_preview",
        lambda *args: pytest.fail("unconfirmed selection must not commit"),
    )

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    routed = observed["args"]
    assert routed[0:3] == (
        "synthetic-workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
    )
    work = routed[3]
    assert work.module_id == MODULE_ID
    assert work.class_id == CLASS_ID
    assert work.work_id == WORK_ID
    assert routed[4:] == (POLICY_ID, 1)
    assert observed["kwargs"] == {}
    assert "Attempt-selection policy selection preview" in output
    assert "target policy: explicit_one@1" in output
    assert "currently selected policy revision: 2" in output
    assert "target is latest: no" in output
    assert "confirmation supplied: no" in output
    assert "NO POLICY SELECTION PERFORMED" in output


def test_confirm_select_commits_exact_preview_without_authoring(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _preview()
    observed: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        cli,
        "preview_attempt_policy_selection",
        lambda *args, **kwargs: preview,
    )

    def fake_commit(*args: object) -> object:
        observed.append(args)
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_attempt_policy_selection_preview",
        fake_commit,
    )

    assert cli.main(
        _arguments("--confirm-select"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed == [("synthetic-workspace", preview)]
    assert "confirmation supplied: yes" in output
    assert "Policy selection committed: revision 1" in output
    assert "policy authoring: not performed" in output


def test_json_output_reports_historical_target_and_selection_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_attempt_policy_selection",
        lambda *args, **kwargs: _preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_attempt_policy_selection_preview",
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
    assert data["preview"]["latest_revision"] == 2
    assert data["preview"]["target_is_latest"] is False
    assert data["preview"]["expected_current_policy_revision"] == 2
    assert data["result"]["selected_revision"] == 1
    assert data["result"]["previous_current_policy_revision"] == 2
    assert data["result"]["authoring_action"] == "not_performed"


def test_invalid_work_identity_uses_policy_selection_error_boundary(
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
        "teacher_workflow.attempt_decisions.policy_selection_invalid"
        in captured.err
    )
