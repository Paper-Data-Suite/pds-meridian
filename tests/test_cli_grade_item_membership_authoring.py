from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
MODULE_ID = "scoreform"
WORK_ID = "test_1"
GRADE_ITEM_DIGEST = "a" * 64


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "grade-items-membership-author",
        CLASS_ID,
        GRADE_ITEM_ID,
        MODULE_ID,
        WORK_ID,
        "--workspace",
        "synthetic-workspace",
        "--operation",
        "create",
        "--grade-item-revision",
        "2",
        "--registration-revision",
        "7",
        "--decision",
        "included",
        "--actor-id",
        "teacher_local",
        "--decided-at",
        "2026-09-01T17:00:00Z",
        "--school-year",
        "2026-2027",
        "--period-id",
        "mp1",
        "--calendar-revision",
        "3",
        *extra,
    )


def _preview_from_call(
    work: object,
    *,
    operation: str,
    grade_item_revision: int,
    registration_revision: int,
    decision: str,
    actor_id: str,
    decided_at: object,
    academic_period: object,
    rationale: str | None,
) -> object:
    candidate = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=grade_item_revision,
        grade_item_revision_sha256=GRADE_ITEM_DIGEST,
        work_reference=SimpleNamespace(
            work=work,
            registration_revision=registration_revision,
        ),
        membership_revision=1,
        supersedes_revision=None,
        decision=decision,
        academic_period=academic_period,
        actor_id=actor_id,
        rationale=rationale,
        decided_at=decided_at,
    )
    return SimpleNamespace(
        operation=operation,
        candidate=candidate,
        history=(),
        latest_persisted_decision_sha256=None,
        expected_current_grade_item_revision=grade_item_revision,
        expected_current_membership_revision=None,
        membership_revision=1,
        decision=decision,
    )


def _result() -> object:
    return SimpleNamespace(
        written_revision=1,
        written_decision="included",
        write_disposition="created",
        previous_current_membership_revision=None,
        selection_action="not_performed",
    )


def test_workflow_help_exposes_membership_authoring_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "grade-items-membership-author" in output
    assert "Preview or write one Grade Item membership revision" in output


def test_included_preview_builds_exact_work_and_period_without_writing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}

    def fake_preview(
        workspace_root: str,
        class_id: str,
        grade_item_id: str,
        work: object,
        **kwargs: object,
    ) -> object:
        observed.update(
            workspace_root=workspace_root,
            class_id=class_id,
            grade_item_id=grade_item_id,
            work=work,
            kwargs=kwargs,
        )
        return _preview_from_call(work, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        cli,
        "preview_grade_item_membership_authoring",
        fake_preview,
    )
    monkeypatch.setattr(
        cli,
        "commit_grade_item_membership_authoring_preview",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("unconfirmed membership authoring must not commit")
        ),
    )

    assert cli.main(_arguments(), dependencies=object()) == 0  # type: ignore[arg-type]
    output = capsys.readouterr().out

    work = observed["work"]
    assert work.module_id == MODULE_ID  # type: ignore[union-attr]
    assert work.class_id == CLASS_ID  # type: ignore[union-attr]
    assert work.work_id == WORK_ID  # type: ignore[union-attr]

    kwargs = observed["kwargs"]
    assignment = kwargs["academic_period"]  # type: ignore[index]
    assert assignment.period.school_year == "2026-2027"
    assert assignment.period.period_id == "mp1"
    assert assignment.calendar_revision == 3
    assert kwargs["registration_revision"] == 7  # type: ignore[index]
    assert kwargs["decision"] == "included"  # type: ignore[index]
    assert "Grade Item membership authoring preview" in output
    assert "membership revision: 1" in output
    assert "registration revision: 7" in output
    assert "academic period: 2026-2027/mp1 @ calendar revision 3" in output
    assert "confirmation supplied: no" in output
    assert "NO MEMBERSHIP WRITE PERFORMED" in output


def test_included_requires_complete_period_coordinates(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_grade_item_membership_authoring",
        lambda *args, **kwargs: pytest.fail("invalid input must not preview"),
    )
    arguments = tuple(
        value
        for value in _arguments()
        if value not in {"--calendar-revision", "3"}
    )

    assert cli.main(arguments, dependencies=object()) == 1  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "membership_authoring_invalid" in captured.err


def test_excluded_rejects_period_coordinates(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_grade_item_membership_authoring",
        lambda *args, **kwargs: pytest.fail("invalid input must not preview"),
    )
    arguments = list(_arguments())
    decision_index = arguments.index("--decision") + 1
    arguments[decision_index] = "excluded"

    assert cli.main(
        tuple(arguments),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "membership_authoring_invalid" in captured.err


def test_confirm_write_commits_exact_preview_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured_preview: list[object] = []

    def fake_preview(
        workspace_root: str,
        class_id: str,
        grade_item_id: str,
        work: object,
        **kwargs: object,
    ) -> object:
        del workspace_root, class_id, grade_item_id
        preview = _preview_from_call(work, **kwargs)  # type: ignore[arg-type]
        captured_preview.append(preview)
        return preview

    monkeypatch.setattr(
        cli,
        "preview_grade_item_membership_authoring",
        fake_preview,
    )
    observed: list[tuple[object, ...]] = []

    def fake_commit(*args: object) -> object:
        observed.append(args)
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_grade_item_membership_authoring_preview",
        fake_commit,
    )

    assert cli.main(
        _arguments("--confirm-write"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed == [("synthetic-workspace", captured_preview[0])]
    assert "confirmation supplied: yes" in output
    assert "Membership revision 1 written (created)" in output
    assert "membership selection action: not performed" in output


def test_json_confirmation_reports_write_without_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_preview(
        workspace_root: str,
        class_id: str,
        grade_item_id: str,
        work: object,
        **kwargs: object,
    ) -> object:
        del workspace_root, class_id, grade_item_id
        return _preview_from_call(work, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        cli,
        "preview_grade_item_membership_authoring",
        fake_preview,
    )
    monkeypatch.setattr(
        cli,
        "commit_grade_item_membership_authoring_preview",
        lambda *args: _result(),
    )

    assert cli.main(
        _arguments("--confirm-write", "--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "written"
    assert data["write_confirmed"] is True
    assert data["preview"]["grade_item_revision"] == 2
    assert data["preview"]["registration_revision"] == 7
    assert data["preview"]["decision"] == "included"
    assert data["preview"]["academic_period"] == {
        "school_year": "2026-2027",
        "period_id": "mp1",
        "calendar_revision": 3,
    }
    assert data["result"]["written_revision"] == 1
    assert data["result"]["selection_action"] == "not_performed"
