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
REVIEW_SHA256 = "e" * 64
SIGNAL_SET_ID = "meridian_reading_groups_2026_09_03"
CREATED_AT = "2026-09-03T12:00:00Z"


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


def _export_args(*extra: str) -> tuple[str, ...]:
    return _review_source_args(
        "--export-signal-set-id",
        SIGNAL_SET_ID,
        "--export-created-at",
        CREATED_AT,
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
    review_reference = SimpleNamespace(
        class_id=CLASS_ID,
        derivation_id=DERIVATION_ID,
        review_revision=2,
        review_sha256=REVIEW_SHA256,
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
        derivation_algorithm_version="academic_period_proficiency_band_v1",
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
        insufficient_result_handling="noncontributing",
        coverage=SimpleNamespace(
            roster_student_count=3,
            contributing_student_count=2,
            noncontributing_student_count=1,
            missing_noncontributor_count=1,
            insufficient_noncontributor_count=0,
            occupied_band_count=2,
            empty_band_count=0,
        ),
        band_summaries=(),
        student_assignments=(),
        ties=(),
        noncontributing_students=(
            SimpleNamespace(
                student_id="student_003",
                display_name="Student Three",
                source_state="missing",
                disposition="noncontributing",
                source_result=None,
                proficiency_level_id=None,
                scale_position=None,
                band=None,
            ),
        ),
        diagnostics=(),
        review_status=SimpleNamespace(
            selected_review_reference=review_reference,
            decision="accepted_for_export",
            acknowledged_warning_ids=(),
            actor_id="teacher_local",
            reviewed_at=datetime(2026, 9, 3, 11, 30, tzinfo=UTC),
            applicability=SimpleNamespace(status="current", reason_codes=()),
        ),
        notices=(
            "Previewing does not export.",
            "Accepting does not export.",
            "Export happens only in #40.",
        ),
    )


def _export_preview() -> object:
    projection = _projection()
    eligibility = SimpleNamespace(
        derivation_reference=projection.derivation_reference,
        preview_reference=projection.preview_reference,
        review_reference=projection.review_status.selected_review_reference,
        currentness=projection.live_currentness,
    )
    signal_set = SimpleNamespace(
        schema_version="1",
        record_type="grouping_signal_set",
        signal_set_id=SIGNAL_SET_ID,
        class_id=CLASS_ID,
        created_at=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        source=SimpleNamespace(
            kind="module_generated",
            module_id="meridian",
            snapshot_id=DERIVATION_ID,
            snapshot_digest_algorithm="sha256",
            snapshot_digest=DERIVATION_SHA256,
        ),
        dimensions=(
            SimpleNamespace(dimension_id="reading_support", band_count=2),
        ),
        student_bands=(
            SimpleNamespace(
                student_id="student_001",
                dimension_id="reading_support",
                band=1,
            ),
            SimpleNamespace(
                student_id="student_002",
                dimension_id="reading_support",
                band=2,
            ),
        ),
    )
    return SimpleNamespace(
        projection=projection,
        eligibility=eligibility,
        signal_set=signal_set,
        contributing_student_ids=("student_001", "student_002"),
        noncontributing_student_ids=("student_003",),
        final_core_revalidation_required=True,
        review_write_action="not_performed",
        review_selection_action="not_performed",
        core_export_action="not_performed",
        export_receipt_action="not_performed",
        csv_export_action="not_performed",
    )


def test_core_export_preview_routes_exact_read_only_candidate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _export_preview()
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def build(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return preview

    monkeypatch.setattr(cli, "preview_planning_signal_core_export", build)
    monkeypatch.setattr(
        cli,
        "format_grouping_signal_teacher_projection",
        lambda value: "CANONICAL #39 TEACHER PROJECTION",
    )

    assert cli.main(_export_args()) == 0
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
                "signal_set_id": SIGNAL_SET_ID,
                "created_at": datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
            },
        )
    ]
    assert "Create Planning Signal — #40 Core export preview" in output
    assert "CANONICAL #39 TEACHER PROJECTION" in output
    assert f"Core signal-set ID: {SIGNAL_SET_ID}" in output
    assert "Core candidate contributors: student_001, student_002" in output
    assert "Core candidate noncontributors: student_003" in output
    assert "final Core revalidation before write: required" in output
    assert "NO CORE GROUPING SIGNAL WRITTEN" in output
    assert "NO MERIDIAN EXPORT RECEIPT WRITTEN" in output
    assert "NO CSV EXPORTED" in output
    assert "NO CONCORD GROUP OR GROUPPLAN CREATED" in output


def test_core_export_preview_json_exposes_exact_candidate_and_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_core_export",
        lambda *args, **kwargs: _export_preview(),
    )

    assert cli.main(_export_args("--format", "json")) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["task"] == "create-planning-signal"
    assert data["mode"] == "core_export_preview"
    assert data["core_candidate"]["signal_set_id"] == SIGNAL_SET_ID
    assert data["core_candidate"]["source"]["module_id"] == "meridian"
    assert data["core_candidate"]["source"]["snapshot_id"] == DERIVATION_ID
    assert data["core_candidate"]["student_bands"] == [
        {
            "student_id": "student_001",
            "dimension_id": "reading_support",
            "band": 1,
        },
        {
            "student_id": "student_002",
            "dimension_id": "reading_support",
            "band": 2,
        },
    ]
    assert data["export_authorization"]["selected_review"]["review_revision"] == 2
    assert (
        data["export_authorization"]["selected_review"]["review_sha256"]
        == REVIEW_SHA256
    )
    assert data["export_authorization"]["currentness"]["state"] == "current"
    assert data["final_core_revalidation_required"] is True
    assert data["actions"]["review_write"] == "not_performed"
    assert data["actions"]["review_selection"] == "not_performed"
    assert data["actions"]["core_export"] == "not_performed"
    assert data["actions"]["export_receipt"] == "not_performed"
    assert data["actions"]["csv_export"] == "not_performed"
    assert data["concord_action"] == "not_performed"


def test_core_export_preview_arguments_must_be_paired(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(
        _review_source_args("--export-signal-set-id", SIGNAL_SET_ID)
    ) == 1
    error = capsys.readouterr().err
    assert "core_export_preview_invalid" in error
    assert "requires both --export-signal-set-id and --export-created-at" in error


def test_core_export_preview_requires_exact_persisted_preview(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(
        _arguments(
            "--export-signal-set-id",
            SIGNAL_SET_ID,
            "--export-created-at",
            CREATED_AT,
        )
    ) == 1
    error = capsys.readouterr().err
    assert "core_export_preview_invalid" in error
    assert "requires an exact persisted #39 preview" in error


def test_core_export_preview_cannot_be_combined_with_review_selection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(
        _export_args(
            "--select-review-revision",
            "2",
            "--select-review-sha256",
            REVIEW_SHA256,
        )
    ) == 1
    error = capsys.readouterr().err
    assert "core_export_preview_invalid" in error
    assert "cannot be combined with review authoring or review selection" in error


def test_core_export_preview_cannot_be_combined_with_review_authoring(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(
        _export_args(
            "--review-decision",
            "rejected",
            "--review-actor-id",
            "teacher_local",
            "--reviewed-at",
            "2026-09-03T11:30:00Z",
        )
    ) == 1
    error = capsys.readouterr().err
    assert "core_export_preview_invalid" in error
    assert "cannot be combined with review authoring or review selection" in error
