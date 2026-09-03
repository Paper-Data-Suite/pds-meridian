from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "class_2026"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "mp1"
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"
RESULT_REVISION = 2


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "academic-period-result-select",
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        str(RESULT_REVISION),
        "--workspace",
        "synthetic-workspace",
        *extra,
    )


def _preview() -> object:
    return SimpleNamespace(
        class_id=CLASS_ID,
        school_year=SCHOOL_YEAR,
        period_id=PERIOD_ID,
        calendar_revision=4,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_revision=RESULT_REVISION,
        target_result_sha256="a" * 64,
        target_status="calculated",
        target_proficiency_level_id="proficient",
        target_calculation_fingerprint="b" * 64,
        history=(1, 2, 3),
        target_is_latest=False,
        expected_current_result_revision=3,
        authoring_action="not_performed",
    )


def _result() -> object:
    return SimpleNamespace(
        selection_disposition="updated",
        previous_current_result_revision=3,
        selected_revision=RESULT_REVISION,
        selected_result_sha256="a" * 64,
        selected_status="calculated",
        selected_proficiency_level_id="proficient",
        authoring_action="not_performed",
    )


def test_workflow_help_exposes_academic_period_result_select(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "academic-period-result-select" in output
    assert (
        "Preview or select one persisted Academic Period proficiency result"
        in output
    )


def test_default_is_preview_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def preview(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _preview()

    monkeypatch.setattr(
        cli,
        "preview_academic_period_result_selection",
        preview,
    )
    monkeypatch.setattr(
        cli,
        "commit_academic_period_result_selection_preview",
        lambda *args, **kwargs: pytest.fail("preview must not select"),
    )

    assert cli.main(_arguments()) == 0
    output = capsys.readouterr().out

    assert observed == [
        (
            (
                "synthetic-workspace",
                CLASS_ID,
                SCHOOL_YEAR,
                PERIOD_ID,
                STUDENT_ID,
                STANDARD_ID,
                RESULT_REVISION,
            ),
            {},
        )
    ]
    assert "Academic Period result selection preview" in output
    assert "target result revision: 2" in output
    assert "target is latest: no" in output
    assert "confirmation supplied: no" in output
    assert "NO CURRENT ACADEMIC PERIOD RESULT SELECTION CHANGED" in output
    assert "NO ACADEMIC PERIOD PROFICIENCY RESULT AUTHORED OR RECALCULATED" in output


def test_confirm_select_commits_exact_preview(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        cli,
        "preview_academic_period_result_selection",
        lambda *args, **kwargs: preview,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_academic_period_result_selection_preview",
        commit,
    )

    assert cli.main(_arguments("--confirm-select")) == 0
    output = capsys.readouterr().out

    assert observed == [(("synthetic-workspace", preview), {})]
    assert "confirmation supplied: yes" in output
    assert "Academic Period result selection committed: revision 2 (updated)" in output
    assert "previous current Academic Period result revision: 3" in output
    assert "authoring action: not performed" in output


def test_json_result_preserves_selection_authoring_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_academic_period_result_selection",
        lambda *args, **kwargs: _preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_academic_period_result_selection_preview",
        lambda *args, **kwargs: _result(),
    )

    assert cli.main(
        _arguments("--confirm-select", "--format", "json")
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "selected"
    assert data["selection_confirmed"] is True
    assert data["preview"]["target_revision"] == RESULT_REVISION
    assert data["preview"]["target_is_latest"] is False
    assert data["result"]["selection_disposition"] == "updated"
    assert data["result"]["selected_revision"] == RESULT_REVISION
    assert data["result"]["authoring_action"] == "not_performed"


def test_positive_result_revision_is_enforced() -> None:
    arguments = list(_arguments())
    index = arguments.index(str(RESULT_REVISION))
    arguments[index] = "0"

    with pytest.raises(SystemExit) as exc_info:
        cli.main(tuple(arguments))
    assert exc_info.value.code == 2
