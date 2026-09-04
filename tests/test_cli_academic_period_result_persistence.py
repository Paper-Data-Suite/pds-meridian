from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "class_2026"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "mp1"
CALENDAR_REVISION = 4
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"
POLICY_ID = "period_policy"
POLICY_REVISION = 2
POLICY_SHA256 = "a" * 64
CALCULATED_AT = "2026-09-03T02:30:00Z"
GRADE_ITEM_ID = "unit1"
GRADE_ITEM_REVISION = 5
GRADE_ITEM_SHA256 = "b" * 64


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "academic-period-result-write",
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        str(CALENDAR_REVISION),
        STUDENT_ID,
        STANDARD_ID,
        POLICY_ID,
        str(POLICY_REVISION),
        POLICY_SHA256,
        "--workspace",
        "synthetic-workspace",
        "--actor-id",
        "teacher_42",
        "--calculated-at",
        CALCULATED_AT,
        "--candidate",
        GRADE_ITEM_ID,
        str(GRADE_ITEM_REVISION),
        GRADE_ITEM_SHA256,
        *extra,
    )


def _reviewed() -> object:
    period = SimpleNamespace(
        school_year=SCHOOL_YEAR,
        period_id=PERIOD_ID,
    )
    return SimpleNamespace(
        target_period=SimpleNamespace(
            period=period,
            calendar_revision=CALENDAR_REVISION,
        ),
        candidate_specs=(),
        inputs=SimpleNamespace(
            class_id=CLASS_ID,
            student_id=STUDENT_ID,
            standard_id=STANDARD_ID,
        ),
        calculation=SimpleNamespace(
            policy_reference=SimpleNamespace(
                class_id=CLASS_ID,
                policy_id=POLICY_ID,
                policy_revision=POLICY_REVISION,
                policy_sha256=POLICY_SHA256,
            )
        ),
        result_write_performed=False,
        result_selection_performed=False,
    )


def _persistence_preview() -> object:
    period = SimpleNamespace(
        school_year=SCHOOL_YEAR,
        period_id=PERIOD_ID,
    )
    candidate = SimpleNamespace(
        class_id=CLASS_ID,
        target_period=SimpleNamespace(
            period=period,
            calendar_revision=CALENDAR_REVISION,
        ),
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        result_revision=3,
        calculated_at=datetime(2026, 9, 3, 2, 30, tzinfo=UTC),
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


def test_workflow_help_exposes_academic_period_result_write(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "academic-period-result-write" in output
    assert "Preview or write one immutable Academic Period proficiency result" in output


def test_default_is_preview_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reviewed = _reviewed()
    persistence = _persistence_preview()
    observed_build: list[tuple[object, ...]] = []

    def build(*args: object, **kwargs: object) -> object:
        assert kwargs == {}
        observed_build.append(args)
        return reviewed

    monkeypatch.setattr(
        cli,
        "build_bounded_academic_period_calculation_preview",
        build,
    )
    observed_preview: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def preview(*args: object, **kwargs: object) -> object:
        observed_preview.append((args, kwargs))
        return persistence

    monkeypatch.setattr(
        cli,
        "preview_academic_period_result_persistence",
        preview,
    )
    monkeypatch.setattr(
        cli,
        "commit_academic_period_result_persistence_preview",
        lambda *args, **kwargs: pytest.fail("preview must not write"),
    )

    assert cli.main(_arguments()) == 0
    output = capsys.readouterr().out

    assert len(observed_build) == 1
    build_args = observed_build[0]
    assert build_args[0] == "synthetic-workspace"
    target = build_args[1]
    assert target.period.school_year == SCHOOL_YEAR
    assert target.period.period_id == PERIOD_ID
    assert target.calendar_revision == CALENDAR_REVISION
    assert build_args[2:4] == (STUDENT_ID, STANDARD_ID)
    specs = build_args[4]
    assert len(specs) == 1
    assert specs[0].grade_item_id == GRADE_ITEM_ID
    assert specs[0].grade_item_revision == GRADE_ITEM_REVISION
    assert specs[0].grade_item_revision_sha256 == GRADE_ITEM_SHA256
    policy = build_args[5]
    assert policy.policy_id == POLICY_ID
    assert policy.policy_revision == POLICY_REVISION
    assert policy.policy_sha256 == POLICY_SHA256

    assert observed_preview == [
        (
            ("synthetic-workspace", reviewed),
            {
                "actor_id": "teacher_42",
                "calculated_at": datetime(
                    2026, 9, 3, 2, 30, tzinfo=UTC
                ),
            },
        )
    ]
    assert "Academic Period result write preview" in output
    assert "candidate period-result revision: 3" in output
    assert "confirmation supplied: no" in output
    assert "NO ACADEMIC PERIOD PROFICIENCY RESULT WRITTEN" in output
    assert "NO CURRENT ACADEMIC PERIOD RESULT SELECTION CHANGED" in output


def test_confirm_write_commits_exact_preview(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    persistence = _persistence_preview()
    monkeypatch.setattr(
        cli,
        "build_bounded_academic_period_calculation_preview",
        lambda *args, **kwargs: _reviewed(),
    )
    monkeypatch.setattr(
        cli,
        "preview_academic_period_result_persistence",
        lambda *args, **kwargs: persistence,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_academic_period_result_persistence_preview",
        commit,
    )

    assert cli.main(_arguments("--confirm-write")) == 0
    output = capsys.readouterr().out

    assert observed == [(
        ("synthetic-workspace", persistence),
        {},
    )]
    assert "confirmation supplied: yes" in output
    assert (
        "Academic Period proficiency result revision 3 written (created)"
        in output
    )
    assert "current Academic Period result selection after write: 1" in output
    assert "Academic Period result selection action: not performed" in output


def test_json_result_preserves_write_select_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "build_bounded_academic_period_calculation_preview",
        lambda *args, **kwargs: _reviewed(),
    )
    monkeypatch.setattr(
        cli,
        "preview_academic_period_result_persistence",
        lambda *args, **kwargs: _persistence_preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_academic_period_result_persistence_preview",
        lambda *args, **kwargs: _result(),
    )

    assert cli.main(
        _arguments("--confirm-write", "--format", "json")
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
        "build_bounded_academic_period_calculation_preview",
        lambda *args, **kwargs: _reviewed(),
    )
    monkeypatch.setattr(
        cli,
        "preview_academic_period_result_persistence",
        lambda *args, **kwargs: _persistence_preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_academic_period_result_persistence_preview",
        lambda *args, **kwargs: result,
    )

    assert cli.main(_arguments("--confirm-write")) == 0
    output = capsys.readouterr().out

    assert (
        "WARNING: current Academic Period result selection changed "
        "concurrently: 1 -> 2"
    ) in output
    assert "Academic Period result selection action: not performed" in output
