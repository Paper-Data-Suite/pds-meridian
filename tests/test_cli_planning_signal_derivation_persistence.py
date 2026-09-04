from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "class_2026"
POLICY_ID = "reading_groups"
DERIVATION_ID = "gsd_" + "d" * 64


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "create-planning-signal",
        CLASS_ID,
        POLICY_ID,
        "--workspace",
        "synthetic-workspace",
        *extra,
    )


def _readiness(*, ready: bool = True) -> object:
    reference = SimpleNamespace(
        class_id=CLASS_ID,
        policy_id=POLICY_ID,
        policy_revision=2,
        policy_sha256="a" * 64,
    )
    policy = SimpleNamespace(
        reference=reference,
        title="Reading support bands",
        target_period=SimpleNamespace(
            period=SimpleNamespace(
                school_year="2026-2027",
                period_id="mp1",
            ),
            calendar_revision=4,
        ),
        standard_id="NJSLSA.R1",
        source_policy_reference=SimpleNamespace(
            class_id=CLASS_ID,
            policy_id="period_proficiency",
            policy_revision=3,
            policy_sha256="b" * 64,
        ),
        target_scale_reference=SimpleNamespace(
            class_id=CLASS_ID,
            scale_id="four_level",
            scale_revision=2,
            scale_sha256="c" * 64,
        ),
        dimension_id="reading_support",
        band_count=3,
        band_definitions=(),
        tie_handling="same_level_same_band",
        missing_result_handling="noncontributing",
        insufficient_result_handling="blocking",
        actor_kind="teacher",
        actor_id="teacher_42",
        rationale=None,
        revised_at=SimpleNamespace(
            isoformat=lambda: "2026-09-03T03:00:00+00:00"
        ),
    )
    generation = SimpleNamespace(
        status="generated" if ready else "blocked",
        blockers=(
            ()
            if ready
            else (
                SimpleNamespace(
                    code="stale_result",
                    student_id="student_001",
                    source_result=None,
                    freshness_reasons=("inputs_changed",),
                ),
            )
        ),
        snapshot=SimpleNamespace() if ready else None,
    )
    return SimpleNamespace(
        class_id=CLASS_ID,
        policy_id=POLICY_ID,
        policy=policy,
        generation=generation,
        generation_status=generation.status,
        blocker_codes=tuple(item.code for item in generation.blockers),
        ready_for_derivation_persistence=ready,
        candidate_derivation_id=DERIVATION_ID if ready else None,
        candidate_calculation_fingerprint="e" * 64 if ready else None,
        roster_student_count=24 if ready else None,
        contributing_student_count=21 if ready else None,
        noncontributing_student_count=3 if ready else None,
        derivation_write_action="not_performed",
        preview_write_action="not_performed",
        review_write_action="not_performed",
        review_selection_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )


def _persistence_preview(readiness: object) -> object:
    return SimpleNamespace(
        readiness=readiness,
        candidate=SimpleNamespace(),
        class_id=CLASS_ID,
        policy_id=POLICY_ID,
        derivation_id=DERIVATION_ID,
        calculation_fingerprint="e" * 64,
        roster_student_count=24,
        contributing_student_count=21,
        noncontributing_student_count=3,
        derivation_write_action="not_performed",
        preview_write_action="not_performed",
        review_write_action="not_performed",
        review_selection_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )


def _persistence_result(preview: object) -> object:
    return SimpleNamespace(
        preview=preview,
        write_result=SimpleNamespace(disposition="created"),
        write_disposition="created",
        derivation_id=DERIVATION_ID,
        derivation_sha256="f" * 64,
        calculation_fingerprint="e" * 64,
        preview_write_action="not_performed",
        review_write_action="not_performed",
        review_selection_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )


def test_default_ready_command_previews_exact_derivation_without_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    readiness = _readiness()
    preview = _persistence_preview(readiness)
    monkeypatch.setattr(
        cli,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: readiness,
    )
    observed_preview: list[object] = []

    def build_preview(value: object) -> object:
        observed_preview.append(value)
        return preview

    monkeypatch.setattr(
        cli,
        "preview_planning_signal_derivation_persistence",
        build_preview,
    )
    monkeypatch.setattr(
        cli,
        "commit_planning_signal_derivation_persistence_preview",
        lambda *args, **kwargs: pytest.fail("default command must not write"),
    )

    assert cli.main(_arguments()) == 0
    output = capsys.readouterr().out

    assert observed_preview == [readiness]
    assert "Create Planning Signal — readiness" in output
    assert "derivation write candidate: " + DERIVATION_ID in output
    assert "derivation write confirmation supplied: no" in output
    assert "NO #38 DERIVATION PERSISTED" in output


def test_blocked_default_remains_read_only_without_persistence_preview(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    readiness = _readiness(ready=False)
    monkeypatch.setattr(
        cli,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: readiness,
    )
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_derivation_persistence",
        lambda *args, **kwargs: pytest.fail(
            "blocked default view must not create persistence preview"
        ),
    )

    assert cli.main(_arguments()) == 0
    output = capsys.readouterr().out

    assert "generation readiness: blocked" in output
    assert "stale_result | student=student_001" in output
    assert "NO #38 DERIVATION PERSISTED" in output


def test_confirm_derivation_write_commits_exact_preview(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    readiness = _readiness()
    preview = _persistence_preview(readiness)
    result = _persistence_result(preview)
    monkeypatch.setattr(
        cli,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: readiness,
    )
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_derivation_persistence",
        lambda value: preview,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return result

    monkeypatch.setattr(
        cli,
        "commit_planning_signal_derivation_persistence_preview",
        commit,
    )

    assert cli.main(_arguments("--confirm-derivation-write")) == 0
    output = capsys.readouterr().out

    assert observed == [(("synthetic-workspace", preview), {})]
    assert "derivation write confirmation supplied: yes" in output
    assert "#38 derivation persisted: " + DERIVATION_ID in output
    assert "write disposition: created" in output
    assert "NO #39 PREVIEW OR REVIEW WRITTEN" in output
    assert "NO CORE GROUPING SIGNAL OR CSV EXPORTED" in output
    assert "NO CONCORD GROUP OR GROUPPLAN CREATED" in output


def test_confirmed_json_preserves_later_stage_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    readiness = _readiness()
    preview = _persistence_preview(readiness)
    monkeypatch.setattr(
        cli,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: readiness,
    )
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_derivation_persistence",
        lambda value: preview,
    )
    monkeypatch.setattr(
        cli,
        "commit_planning_signal_derivation_persistence_preview",
        lambda *args, **kwargs: _persistence_result(preview),
    )

    assert cli.main(
        _arguments("--confirm-derivation-write", "--format", "json")
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["task"] == "create-planning-signal"
    assert data["mode"] == "derivation_written"
    assert data["derivation_write_confirmed"] is True
    assert data["derivation"]["derivation_id"] == DERIVATION_ID
    assert data["derivation"]["write_disposition"] == "created"
    assert data["actions"]["preview_write"] == "not_performed"
    assert data["actions"]["review_write"] == "not_performed"
    assert data["actions"]["review_selection"] == "not_performed"
    assert data["actions"]["core_export"] == "not_performed"
    assert data["actions"]["csv_export"] == "not_performed"
    assert data["concord_action"] == "not_performed"


def test_parser_accepts_explicit_derivation_confirmation() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(_arguments("--confirm-derivation-write"))
    assert args.confirm_derivation_write is True
