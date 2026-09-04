from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "class_2026"
POLICY_ID = "reading_groups"
PREVIEW_ID = "gsp_" + "a" * 64
PREVIEW_SHA256 = "b" * 64
DERIVATION_ID = "gsd_" + "c" * 64
WARNING_ID = "gpd_" + "d" * 64
REVIEW_SHA256 = "e" * 64
REVIEWED_AT = "2026-09-03T05:00:00Z"


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


def _review_source_args(*extra: str) -> tuple[str, ...]:
    return _arguments(
        "--review-preview-id",
        PREVIEW_ID,
        "--review-preview-sha256",
        PREVIEW_SHA256,
        *extra,
    )


def _author_args(*extra: str) -> tuple[str, ...]:
    return _review_source_args(
        "--review-decision",
        "accepted_for_export",
        "--acknowledge-warning-id",
        WARNING_ID,
        "--review-actor-id",
        "teacher_local",
        "--reviewed-at",
        REVIEWED_AT,
        *extra,
    )


def _projection() -> object:
    preview_reference = SimpleNamespace(
        class_id=CLASS_ID,
        preview_id=PREVIEW_ID,
        preview_sha256=PREVIEW_SHA256,
    )
    derivation_reference = SimpleNamespace(
        class_id=CLASS_ID,
        derivation_id=DERIVATION_ID,
        derivation_sha256="f" * 64,
    )
    diagnostic = SimpleNamespace(
        diagnostic_id=WARNING_ID,
        code="missing_noncontributors",
        severity="warning",
        message="One roster student is noncontributing.",
        student_ids=("student_002",),
        student_display_names=("Student Two",),
        bands=(),
        details=("missing_count_1",),
    )
    return SimpleNamespace(
        preview_reference=preview_reference,
        class_id=CLASS_ID,
        school_year="2026-2027",
        period_id="mp1",
        calendar_revision=4,
        standard_id="NJSLSA.R1",
        source_policy_reference=SimpleNamespace(
            class_id=CLASS_ID,
            policy_id="period_proficiency",
            policy_revision=3,
            policy_sha256="0" * 64,
        ),
        target_scale_reference=SimpleNamespace(
            class_id=CLASS_ID,
            scale_id="four_level",
            scale_revision=2,
            scale_sha256="1" * 64,
        ),
        derivation_reference=derivation_reference,
        derivation_algorithm_version="grouping_signal_derivation_v1",
        derivation_calculation_fingerprint="2" * 64,
        live_currentness=SimpleNamespace(
            state="current",
            reason_codes=(),
            current_derivation_reference=derivation_reference,
        ),
        policy_reference=SimpleNamespace(
            class_id=CLASS_ID,
            policy_id=POLICY_ID,
            policy_revision=2,
            policy_sha256="3" * 64,
        ),
        policy_title="Reading support bands",
        dimension_id="reading_support",
        band_count=2,
        band_definitions=(
            SimpleNamespace(
                band=1,
                minimum_scale_position=1,
                maximum_scale_position=2,
            ),
            SimpleNamespace(
                band=2,
                minimum_scale_position=3,
                maximum_scale_position=4,
            ),
        ),
        tie_handling="same_level_same_band",
        missing_result_handling="noncontributing",
        insufficient_result_handling="blocking",
        coverage=SimpleNamespace(
            roster_student_count=2,
            contributing_student_count=1,
            noncontributing_student_count=1,
            missing_noncontributor_count=1,
            insufficient_noncontributor_count=0,
            occupied_band_count=1,
            empty_band_count=1,
        ),
        band_summaries=(),
        student_assignments=(),
        ties=(),
        noncontributing_students=(),
        diagnostics=(diagnostic,),
        review_status=SimpleNamespace(
            selected_review_reference=None,
            decision=None,
            acknowledged_warning_ids=(),
            actor_id=None,
            reviewed_at=None,
            applicability=None,
        ),
        notices=(
            "Previewing does not export.",
            "Accepting does not export.",
            "Export happens only in #40.",
        ),
    )


def _author_preview() -> object:
    projection = _projection()
    candidate = SimpleNamespace(
        class_id=CLASS_ID,
        derivation_reference=projection.derivation_reference,
        preview_reference=projection.preview_reference,
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=(WARNING_ID,),
        actor=SimpleNamespace(kind="teacher", actor_id="teacher_local"),
        reviewed_at=datetime(2026, 9, 3, 5, 0, tzinfo=UTC),
    )
    return SimpleNamespace(
        projection=projection,
        candidate=candidate,
        history=(),
        expected_current_review_revision=None,
        warning_diagnostic_ids=(WARNING_ID,),
        blocking_diagnostic_ids=(),
        class_id=CLASS_ID,
        derivation_id=DERIVATION_ID,
        review_revision=1,
        decision="accepted_for_export",
        acknowledged_warning_ids=(WARNING_ID,),
        actor_id="teacher_local",
        reviewed_at=candidate.reviewed_at,
        review_write_action="not_performed",
        review_selection_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )


def _result() -> object:
    return SimpleNamespace(
        write_disposition="created",
        review_revision=1,
        review_sha256=REVIEW_SHA256,
        decision="accepted_for_export",
        selected_revision_before_write=None,
        selected_revision_after_write=None,
        selection_changed_during_write=False,
        review_selection_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )


def test_review_authoring_default_is_read_only_candidate_preview(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _author_preview()
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def build(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return preview

    monkeypatch.setattr(cli, "preview_planning_signal_review_authoring", build)
    monkeypatch.setattr(
        cli,
        "commit_planning_signal_review_authoring",
        lambda *args, **kwargs: pytest.fail("default review mode must not write"),
    )
    monkeypatch.setattr(
        cli,
        "format_grouping_signal_teacher_projection",
        lambda value: "CANONICAL #39 TEACHER PROJECTION",
    )

    assert cli.main(_author_args()) == 0
    output = capsys.readouterr().out

    assert observed == [
        (
            (
                "synthetic-workspace",
                CLASS_ID,
                POLICY_ID,
                PREVIEW_ID,
                PREVIEW_SHA256,
            ),
            {
                "decision": "accepted_for_export",
                "acknowledged_warning_ids": (WARNING_ID,),
                "actor_id": "teacher_local",
                "reviewed_at": datetime(2026, 9, 3, 5, 0, tzinfo=UTC),
            },
        )
    ]
    assert "Create Planning Signal — #39 teacher review" in output
    assert "CANONICAL #39 TEACHER PROJECTION" in output
    assert "candidate review revision: 1" in output
    assert "decision: accepted_for_export" in output
    assert f"required warning acknowledgments: {WARNING_ID}" in output
    assert "review write confirmation supplied: no" in output
    assert "NO TEACHER REVIEW WRITTEN" in output
    assert "NO REVIEW SELECTION CHANGED" in output


def test_confirm_review_write_persists_only_review_revision(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _author_preview()
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_review_authoring",
        lambda *args, **kwargs: preview,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(cli, "commit_planning_signal_review_authoring", commit)
    monkeypatch.setattr(
        cli,
        "format_grouping_signal_teacher_projection",
        lambda value: "CANONICAL #39 TEACHER PROJECTION",
    )

    assert cli.main(_author_args("--confirm-review-write")) == 0
    output = capsys.readouterr().out

    assert observed == [(("synthetic-workspace", preview), {})]
    assert "review write confirmation supplied: yes" in output
    assert "#39 review persisted: revision 1" in output
    assert f"review SHA-256: {REVIEW_SHA256}" in output
    assert "NO REVIEW SELECTION CHANGED BY THIS COMMAND" in output
    assert "NO CORE GROUPING SIGNAL OR CSV EXPORTED" in output


def test_confirmed_json_preserves_selection_and_export_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_review_authoring",
        lambda *args, **kwargs: _author_preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_planning_signal_review_authoring",
        lambda *args, **kwargs: _result(),
    )

    assert cli.main(
        _author_args("--confirm-review-write", "--format", "json")
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["task"] == "create-planning-signal"
    assert data["mode"] == "review_written"
    assert data["review_write_confirmed"] is True
    assert data["review"]["review_revision"] == 1
    assert data["review"]["review_sha256"] == REVIEW_SHA256
    assert data["review"]["decision"] == "accepted_for_export"
    assert data["actions"]["review_write"] == "performed"
    assert data["actions"]["review_selection"] == "not_performed"
    assert data["actions"]["core_export"] == "not_performed"
    assert data["actions"]["csv_export"] == "not_performed"
    assert data["concord_action"] == "not_performed"


def test_review_authoring_fields_require_exact_review_preview_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(
        _arguments(
            "--review-decision",
            "rejected",
            "--review-actor-id",
            "teacher_local",
            "--reviewed-at",
            REVIEWED_AT,
        )
    ) == 1
    error = capsys.readouterr().err
    assert "review_authoring_invalid" in error
    assert "requires an exact persisted #39 preview" in error


def test_review_decision_requires_actor_and_reviewed_at(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(
        _review_source_args("--review-decision", "rejected")
    ) == 1
    error = capsys.readouterr().err
    assert "review_authoring_invalid" in error
    assert "requires --review-actor-id and --reviewed-at" in error


def test_confirm_review_write_requires_review_decision(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(
        _review_source_args("--confirm-review-write")
    ) == 1
    error = capsys.readouterr().err
    assert "review_authoring_invalid" in error
    assert "requires --review-decision" in error
