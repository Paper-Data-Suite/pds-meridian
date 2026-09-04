from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
MODULE_ID = "scoreform"
WORK_ID = "test_1"
POLICY_ID = "explicit_one"
REVISED_AT = "2026-09-02T14:00:00+00:00"


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "attempt-policy-author",
        CLASS_ID,
        GRADE_ITEM_ID,
        MODULE_ID,
        WORK_ID,
        POLICY_ID,
        "--workspace",
        "synthetic-workspace",
        "--operation",
        "create",
        "--minimum-selected",
        "1",
        "--maximum-selected",
        "1",
        "--actor-id",
        "teacher_local",
        "--revised-at",
        REVISED_AT,
        *extra,
    )


def _preview() -> object:
    policy = SimpleNamespace(
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
        minimum_selected=1,
        maximum_selected=1,
        actor=SimpleNamespace(
            kind="teacher",
            actor_id="teacher_local",
        ),
        rationale="Use exactly one explicit attempt.",
        revised_at=datetime(2026, 9, 2, 14, 0, tzinfo=UTC),
    )
    return SimpleNamespace(
        operation="create",
        candidate=policy,
        history=(),
        latest_persisted_policy_sha256=None,
        reviewed_current_policy_revision=None,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=policy.work,
        policy_id=POLICY_ID,
        policy_revision=1,
    )


def _result() -> object:
    return SimpleNamespace(
        written_revision=1,
        write_disposition="created",
        selection_action="not_performed",
    )


def test_workflow_help_exposes_attempt_policy_author_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "attempt-policy-author" in output
    assert "Preview or write an explicit attempt-selection policy" in output


def test_without_confirmation_previews_and_performs_no_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}
    preview = _preview()

    def fake_preview(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return preview

    monkeypatch.setattr(cli, "preview_attempt_policy_authoring", fake_preview)
    monkeypatch.setattr(
        cli,
        "commit_attempt_policy_authoring_preview",
        lambda *args: pytest.fail("unconfirmed policy authoring must not commit"),
    )

    assert cli.main(
        _arguments("--rationale", "Use exactly one explicit attempt."),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed["args"][:3] == (  # type: ignore[index]
        "synthetic-workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
    )
    kwargs = observed["kwargs"]
    assert kwargs["operation"] == "create"  # type: ignore[index]
    assert kwargs["minimum_selected"] == 1  # type: ignore[index]
    assert kwargs["maximum_selected"] == 1  # type: ignore[index]
    assert kwargs["actor_id"] == "teacher_local"  # type: ignore[index]
    assert "Attempt-selection policy authoring preview" in output
    assert "selection basis: explicit" in output
    assert "cardinality: 1..1" in output
    assert "confirmation supplied: no" in output
    assert "NO POLICY WRITE PERFORMED" in output


def test_confirm_write_commits_preview_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _preview()
    observed: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        cli,
        "preview_attempt_policy_authoring",
        lambda *args, **kwargs: preview,
    )

    def fake_commit(*args: object) -> object:
        observed.append(args)
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_attempt_policy_authoring_preview",
        fake_commit,
    )

    assert cli.main(
        _arguments("--confirm-write"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed == [("synthetic-workspace", preview)]
    assert "confirmation supplied: yes" in output
    assert "Policy write committed: revision 1" in output
    assert "current-policy selection: not performed" in output


def test_json_output_reports_explicit_policy_and_no_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_attempt_policy_authoring",
        lambda *args, **kwargs: _preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_attempt_policy_authoring_preview",
        lambda *args: _result(),
    )

    assert cli.main(
        _arguments("--confirm-write", "--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "written"
    assert data["write_confirmed"] is True
    assert data["preview"]["selection_basis"] == "explicit"
    assert data["preview"]["minimum_selected"] == 1
    assert data["preview"]["maximum_selected"] == 1
    assert data["result"]["written_revision"] == 1
    assert data["result"]["selection_action"] == "not_performed"


def test_unbounded_maximum_uses_omission_not_sentinel(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}

    def fake_preview(*args: object, **kwargs: object) -> object:
        observed.update(kwargs)
        preview = _preview()
        preview.candidate.maximum_selected = None
        return preview

    monkeypatch.setattr(cli, "preview_attempt_policy_authoring", fake_preview)

    arguments = list(_arguments())
    index = arguments.index("--maximum-selected")
    del arguments[index : index + 2]

    assert cli.main(
        tuple(arguments),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    capsys.readouterr()

    assert observed["maximum_selected"] is None


def test_invalid_work_identity_uses_policy_authoring_error_boundary(
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
        "teacher_workflow.attempt_decisions.policy_authoring_invalid"
        in captured.err
    )
