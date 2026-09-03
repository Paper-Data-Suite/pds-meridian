from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"
SCALE_ID = "four_level"
SCALE_REVISION = 3
SCALE_SHA256 = "a" * 64
POLICY_ID = "teacher_default"
POLICY_REVISION = 2
POLICY_SHA256 = "b" * 64
CALCULATED_AT = "2026-09-02T20:30:00Z"


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "calculation-result-write",
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        SCALE_ID,
        str(SCALE_REVISION),
        SCALE_SHA256,
        POLICY_ID,
        str(POLICY_REVISION),
        POLICY_SHA256,
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--scope-student-id",
        STUDENT_ID,
        "--actor-id",
        "teacher_42",
        "--calculated-at",
        CALCULATED_AT,
        *extra,
    )


def _reviewed() -> object:
    return SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
    )


def _persistence_preview() -> object:
    candidate = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        result_revision=3,
        calculated_at=datetime(2026, 9, 2, 20, 30, tzinfo=UTC),
        outcome=SimpleNamespace(
            status="calculated",
            proficiency_level_id="proficient",
        ),
        calculation_fingerprint="c" * 64,
    )
    return SimpleNamespace(
        actor_id="teacher_42",
        reviewed=_reviewed(),
        candidate=candidate,
        history_before=(1, 2),
        latest_result_sha256_before="d" * 64,
        selected_revision_before=1,
        candidate_revision=3,
        candidate_status="calculated",
        candidate_proficiency_level_id="proficient",
        candidate_calculation_fingerprint="c" * 64,
        selection_action="not_performed",
    )


def _result() -> object:
    return SimpleNamespace(
        write_result=SimpleNamespace(disposition="created"),
        written_revision=3,
        written_result_sha256="e" * 64,
        written_status="calculated",
        written_proficiency_level_id="proficient",
        selected_revision_after_write=1,
        selection_changed_during_write=False,
        selection_action="not_performed",
    )


def test_workflow_help_exposes_calculation_result_write(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "calculation-result-write" in output
    assert "Preview or write one immutable Grade Item proficiency result" in output


def test_default_is_preview_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reviewed = _reviewed()
    persistence = _persistence_preview()
    monkeypatch.setattr(
        cli,
        "_build_calculation_result_review_from_args",
        lambda *args, **kwargs: reviewed,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def preview(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return persistence

    monkeypatch.setattr(cli, "preview_calculation_result_persistence", preview)
    monkeypatch.setattr(
        cli,
        "commit_calculation_result_persistence_preview",
        lambda *args, **kwargs: pytest.fail("preview must not write"),
    )

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed == [
        (
            ("synthetic-workspace", reviewed),
            {
                "actor_id": "teacher_42",
                "calculated_at": datetime(
                    2026, 9, 2, 20, 30, tzinfo=UTC
                ),
            },
        )
    ]
    assert "Calculation result write preview" in output
    assert "candidate result revision: 3" in output
    assert "confirmation supplied: no" in output
    assert "NO PROFICIENCY RESULT WRITTEN" in output
    assert "NO CURRENT RESULT SELECTION CHANGED" in output


def test_confirm_write_commits_exact_preview(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    persistence = _persistence_preview()
    monkeypatch.setattr(
        cli,
        "_build_calculation_result_review_from_args",
        lambda *args, **kwargs: _reviewed(),
    )
    monkeypatch.setattr(
        cli,
        "preview_calculation_result_persistence",
        lambda *args, **kwargs: persistence,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_calculation_result_persistence_preview",
        commit,
    )

    assert cli.main(
        _arguments("--confirm-write"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed == [(("synthetic-workspace", persistence), {})]
    assert "confirmation supplied: yes" in output
    assert "Proficiency result revision 3 written (created)" in output
    assert "current result selection after write: 1" in output
    assert "result selection action: not performed" in output


def test_json_result_preserves_write_select_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "_build_calculation_result_review_from_args",
        lambda *args, **kwargs: _reviewed(),
    )
    monkeypatch.setattr(
        cli,
        "preview_calculation_result_persistence",
        lambda *args, **kwargs: _persistence_preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_calculation_result_persistence_preview",
        lambda *args, **kwargs: _result(),
    )

    assert cli.main(
        _arguments("--confirm-write", "--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "written"
    assert data["write_confirmed"] is True
    assert data["preview"]["actor_id"] == "teacher_42"
    assert data["preview"]["candidate_revision"] == 3
    assert data["result"]["written_revision"] == 3
    assert data["result"]["write_disposition"] == "created"
    assert data["result"]["selected_revision_after_write"] == 1
    assert data["result"]["selection_action"] == "not_performed"


def test_concurrent_selection_change_is_reported_not_overwritten(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _result()
    result.selected_revision_after_write = 2
    result.selection_changed_during_write = True
    monkeypatch.setattr(
        cli,
        "_build_calculation_result_review_from_args",
        lambda *args, **kwargs: _reviewed(),
    )
    monkeypatch.setattr(
        cli,
        "preview_calculation_result_persistence",
        lambda *args, **kwargs: _persistence_preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_calculation_result_persistence_preview",
        lambda *args, **kwargs: result,
    )

    assert cli.main(
        _arguments("--confirm-write"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert "WARNING: current result selection changed concurrently: 1 -> 2" in output
    assert "result selection action: not performed" in output
