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
DERIVATION_SHA256 = "d" * 64
DIAGNOSTIC_ID = "gpd_" + "e" * 64


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


def _projection() -> object:
    preview_reference = SimpleNamespace(
        class_id=CLASS_ID,
        preview_id=PREVIEW_ID,
        preview_sha256=PREVIEW_SHA256,
    )
    derivation_reference = SimpleNamespace(
        class_id=CLASS_ID,
        derivation_id=DERIVATION_ID,
        derivation_sha256=DERIVATION_SHA256,
    )
    policy_reference = SimpleNamespace(
        class_id=CLASS_ID,
        policy_id=POLICY_ID,
        policy_revision=2,
        policy_sha256="f" * 64,
    )
    source_policy = SimpleNamespace(
        class_id=CLASS_ID,
        policy_id="period_proficiency",
        policy_revision=3,
        policy_sha256="0" * 64,
    )
    scale_reference = SimpleNamespace(
        class_id=CLASS_ID,
        scale_id="four_level",
        scale_revision=2,
        scale_sha256="1" * 64,
    )
    source_result = SimpleNamespace(
        class_id=CLASS_ID,
        school_year="2026-2027",
        period_id="mp1",
        student_id="student_001",
        standard_id="NJSLSA.R1",
        result_revision=4,
        result_sha256="2" * 64,
    )
    contributor = SimpleNamespace(
        student_id="student_001",
        display_name="Student One",
        source_state="calculated",
        disposition="contributing",
        source_result=source_result,
        proficiency_level_id="meeting",
        scale_position=3,
        band=2,
    )
    noncontributor = SimpleNamespace(
        student_id="student_002",
        display_name="Student Two",
        source_state="missing",
        disposition="noncontributing",
        source_result=None,
        proficiency_level_id=None,
        scale_position=None,
        band=None,
    )
    diagnostic = SimpleNamespace(
        diagnostic_id=DIAGNOSTIC_ID,
        code="missing_noncontributors",
        severity="warning",
        message="One roster student has no selected Academic Period result.",
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
        source_policy_reference=source_policy,
        target_scale_reference=scale_reference,
        derivation_reference=derivation_reference,
        derivation_algorithm_version="grouping_signal_derivation_v1",
        derivation_calculation_fingerprint="3" * 64,
        live_currentness=SimpleNamespace(
            state="current",
            reason_codes=(),
            current_derivation_reference=derivation_reference,
        ),
        policy_reference=policy_reference,
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
        band_summaries=(
            SimpleNamespace(
                band=1,
                label="Band 1",
                minimum_scale_position=1,
                maximum_scale_position=2,
                proficiency_level_ids=(),
                student_ids=(),
                student_display_names=(),
                student_count=0,
            ),
            SimpleNamespace(
                band=2,
                label="Band 2",
                minimum_scale_position=3,
                maximum_scale_position=4,
                proficiency_level_ids=("meeting",),
                student_ids=("student_001",),
                student_display_names=("Student One",),
                student_count=1,
            ),
        ),
        student_assignments=(contributor, noncontributor),
        ties=(),
        noncontributing_students=(noncontributor,),
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


def test_exact_review_preview_is_read_only_and_bypasses_earlier_stages(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projection = _projection()
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def project(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return projection

    monkeypatch.setattr(
        cli,
        "project_planning_signal_preview_diagnostics",
        project,
    )
    monkeypatch.setattr(
        cli,
        "format_grouping_signal_teacher_projection",
        lambda value: "CANONICAL #39 TEACHER PROJECTION",
    )
    monkeypatch.setattr(
        cli,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: pytest.fail("review stage must not rebuild #38"),
    )
    monkeypatch.setattr(
        cli,
        "commit_planning_signal_preview_write",
        lambda *args, **kwargs: pytest.fail("review stage must not write #39"),
    )

    assert cli.main(_review_source_args()) == 0
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
            {},
        )
    ]
    assert "Create Planning Signal — #39 preview / diagnostics" in output
    assert f"exact #39 preview: {PREVIEW_ID}" in output
    assert "CANONICAL #39 TEACHER PROJECTION" in output
    assert "NO TEACHER REVIEW WRITTEN" in output
    assert "NO REVIEW SELECTION CHANGED" in output
    assert "NO CORE GROUPING SIGNAL OR CSV EXPORTED" in output


def test_json_exposes_detailed_diagnostics_and_all_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "project_planning_signal_preview_diagnostics",
        lambda *args, **kwargs: _projection(),
    )

    assert cli.main(_review_source_args("--format", "json")) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["task"] == "create-planning-signal"
    assert data["mode"] == "preview_diagnostics"
    assert data["preview"]["preview_id"] == PREVIEW_ID
    assert data["academic_basis"]["period_id"] == "mp1"
    assert data["academic_basis"]["standard_id"] == "NJSLSA.R1"
    assert data["derivation"]["derivation_id"] == DERIVATION_ID
    assert data["derivation"]["live_currentness"]["state"] == "current"
    assert data["policy"]["policy_id"] == POLICY_ID
    assert data["policy"]["band_count"] == 2
    assert data["coverage"]["noncontributing_student_count"] == 1
    assert data["student_assignments"][0]["display_name"] == "Student One"
    assert data["noncontributing_students"][0]["student_id"] == "student_002"
    assert data["diagnostics"][0]["diagnostic_id"] == DIAGNOSTIC_ID
    assert data["diagnostics"][0]["severity"] == "warning"
    assert data["diagnostics"][0]["student_ids"] == ["student_002"]
    assert data["review_status"]["selected_review"] is None
    assert data["actions"]["derivation_write"] == "not_performed"
    assert data["actions"]["preview_write"] == "not_performed"
    assert data["actions"]["review_write"] == "not_performed"
    assert data["actions"]["review_selection"] == "not_performed"
    assert data["actions"]["core_export"] == "not_performed"
    assert data["actions"]["csv_export"] == "not_performed"
    assert data["concord_action"] == "not_performed"


def test_selected_review_status_is_visible_in_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projection = _projection()
    projection.review_status = SimpleNamespace(
        selected_review_reference=SimpleNamespace(
            class_id=CLASS_ID,
            derivation_id=DERIVATION_ID,
            review_revision=3,
            review_sha256="4" * 64,
        ),
        decision="accepted_for_export",
        acknowledged_warning_ids=(DIAGNOSTIC_ID,),
        actor_id="teacher_local",
        reviewed_at=datetime(2026, 9, 3, 4, 0, tzinfo=UTC),
        applicability=SimpleNamespace(status="current", reason_codes=()),
    )
    monkeypatch.setattr(
        cli,
        "project_planning_signal_preview_diagnostics",
        lambda *args, **kwargs: projection,
    )

    assert cli.main(_review_source_args("--format", "json")) == 0
    data = json.loads(capsys.readouterr().out)
    review = data["review_status"]

    assert review["selected_review"]["review_revision"] == 3
    assert review["decision"] == "accepted_for_export"
    assert review["acknowledged_warning_ids"] == [DIAGNOSTIC_ID]
    assert review["actor_id"] == "teacher_local"
    assert review["applicability"]["status"] == "current"


def test_review_preview_arguments_must_be_paired(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(_arguments("--review-preview-id", PREVIEW_ID)) == 1
    error = capsys.readouterr().err
    assert "preview_diagnostics_invalid" in error
    assert "requires both --review-preview-id" in error


def test_review_stage_cannot_be_combined_with_preview_write_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(
        _review_source_args(
            "--preview-derivation-id",
            DERIVATION_ID,
            "--preview-derivation-sha256",
            DERIVATION_SHA256,
        )
    ) == 1
    error = capsys.readouterr().err
    assert "preview_diagnostics_invalid" in error
    assert "cannot be combined" in error
