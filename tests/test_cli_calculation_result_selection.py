from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "class_2026"
GRADE_ITEM_ID = "unit1"
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"
RESULT_REVISION = 2


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "calculation-result-select",
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        str(RESULT_REVISION),
        "--workspace",
        "synthetic-workspace",
        *extra,
    )


def _preview() -> object:
    snapshot = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        result_revision=RESULT_REVISION,
        outcome=SimpleNamespace(
            status="calculated",
            proficiency_level_id="proficient",
        ),
        calculation_fingerprint="a" * 64,
    )
    target = SimpleNamespace(
        snapshot=snapshot,
        result_sha256="b" * 64,
    )
    return SimpleNamespace(
        target=target,
        history=(1, 2, 3),
        expected_current_result_revision=1,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_revision=RESULT_REVISION,
        target_result_sha256="b" * 64,
        target_status="calculated",
        target_proficiency_level_id="proficient",
        target_calculation_fingerprint="a" * 64,
        target_is_latest=False,
        authoring_action="not_performed",
    )


def _result() -> object:
    return SimpleNamespace(
        previous_current_result_revision=1,
        selected_revision=RESULT_REVISION,
        selected_result_sha256="b" * 64,
        selected_status="calculated",
        selected_proficiency_level_id="proficient",
        selection_disposition="updated",
        authoring_action="not_performed",
    )


def test_workflow_help_exposes_calculation_result_select(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "calculation-result-select" in output
    assert "Preview or select one persisted Grade Item proficiency result" in output


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
        "preview_calculation_result_selection",
        preview,
    )
    monkeypatch.setattr(
        cli,
        "commit_calculation_result_selection_preview",
        lambda *args, **kwargs: pytest.fail("preview must not select"),
    )

    assert cli.main(_arguments()) == 0
    output = capsys.readouterr().out

    assert observed == [
        (
            (
                "synthetic-workspace",
                CLASS_ID,
                GRADE_ITEM_ID,
                STUDENT_ID,
                STANDARD_ID,
                RESULT_REVISION,
            ),
            {},
        )
    ]
    assert "Calculation result selection preview" in output
    assert "target result revision: 2" in output
    assert "target is latest: no" in output
    assert "confirmation supplied: no" in output
    assert "NO CURRENT RESULT SELECTION CHANGED" in output
    assert "NO PROFICIENCY RESULT AUTHORED OR RECALCULATED" in output


def test_confirm_select_commits_exact_preview(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        cli,
        "preview_calculation_result_selection",
        lambda *args, **kwargs: preview,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_calculation_result_selection_preview",
        commit,
    )

    assert cli.main(_arguments("--confirm-select")) == 0
    output = capsys.readouterr().out

    assert observed == [
        (("synthetic-workspace", preview), {})
    ]
    assert "confirmation supplied: yes" in output
    assert "Result selection committed: revision 2 (updated)" in output
    assert "previous current result revision: 1" in output
    assert "authoring action: not performed" in output


def test_json_output_preserves_selection_authoring_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_calculation_result_selection",
        lambda *args, **kwargs: _preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_calculation_result_selection_preview",
        lambda *args, **kwargs: _result(),
    )

    assert cli.main(
        _arguments("--confirm-select", "--format", "json")
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "selected"
    assert data["selection_confirmed"] is True
    assert data["preview"]["target_revision"] == 2
    assert data["preview"]["target_is_latest"] is False
    assert data["result"]["selected_revision"] == 2
    assert data["result"]["selection_disposition"] == "updated"
    assert data["result"]["previous_current_result_revision"] == 1
    assert data["result"]["authoring_action"] == "not_performed"


def test_revision_must_be_positive_before_workflow_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_calculation_result_selection",
        lambda *args, **kwargs: pytest.fail(
            "invalid revision must fail in argparse before workflow access"
        ),
    )
    arguments = list(_arguments())
    arguments[6] = "0"

    with pytest.raises(SystemExit) as caught:
        cli.main(tuple(arguments))
    assert caught.value.code == 2
