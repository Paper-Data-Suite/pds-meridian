from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.reporting_snapshot_cli as reporting_cli
from meridian.cli import main
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.reporting_snapshot import ReportingActor, ReportingDefinitionReference
from meridian.reporting_snapshot_record import (
    REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
    ReportingSnapshotBuildRequest,
    ReportingSnapshotGradeRequest,
    ReportingSnapshotProjectionInputReference,
)

CLASS_ID = "class_2026"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 20, 19, 0, tzinfo=UTC)
SNAPSHOT_ID = "snapshot_live_001"
SNAPSHOT_SHA256 = "b" * 64
CACHE_KEY = "c" * 64
PROJECTION_SHA256 = "d" * 64


def _build_request(
    *,
    student_id: str = "student_001",
    calendar_revision: int = 1,
) -> ReportingSnapshotBuildRequest:
    definition = ReportingDefinitionReference(
        class_id=CLASS_ID,
        definition_id="progress_report",
        definition_revision=1,
        definition_sha256="a" * 64,
    )
    target = GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=student_id,
        target_period=PERIOD,
        calendar_revision=calendar_revision,
        calculation_family="standards_based",
    )
    return ReportingSnapshotBuildRequest(
        schema_version=REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
        definition_reference=definition,
        grade_requests=(ReportingSnapshotGradeRequest(target, None),),
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        requested_at=NOW,
        predecessor=None,
    )


def _freeze_args(*extra: str) -> tuple[str, ...]:
    return (
        "reporting",
        "snapshots",
        "freeze",
        SNAPSHOT_ID,
        "synthetic-build-request.json",
        "--created-at",
        "2026-09-20T19:05:00Z",
        *extra,
    )


def _compare_args(*extra: str) -> tuple[str, ...]:
    return (
        "reporting",
        "snapshots",
        "compare",
        CLASS_ID,
        SNAPSHOT_ID,
        SNAPSHOT_SHA256,
        *extra,
    )


def test_snapshot_group_exposes_freeze_and_compare(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("reporting", "snapshots")) == 0
    output = capsys.readouterr().out
    assert "freeze" in output
    assert "compare" in output
    assert "ReportingSnapshots" in output


def test_freeze_defaults_to_live_preview_without_snapshot_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = _build_request()
    monkeypatch.setattr(reporting_cli, "_read_build_request_file", lambda path: request)
    monkeypatch.setattr(
        reporting_cli,
        "explain_grade_report_preview",
        lambda *args: SimpleNamespace(),
    )
    monkeypatch.setattr(
        reporting_cli,
        "grade_report_preview_to_dict",
        lambda value: {"summary": {"requested_count": 1}},
    )
    monkeypatch.setattr(
        reporting_cli,
        "grade_report_preview_to_json_bytes",
        lambda value: b"canonical-live-preview\n",
    )

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("preview-only freeze must not write a snapshot")

    monkeypatch.setattr(reporting_cli, "freeze_reporting_snapshot", forbidden)

    assert main(_freeze_args("--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["surface"] == "reporting_snapshot_freeze"
    assert payload["disposition"] == "preview_only"
    assert payload["freeze_confirmed"] is False
    assert payload["official_system_authority"] is False


def test_confirmed_freeze_delegates_to_whole_report_freeze_service(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = _build_request()
    observed: list[dict[str, object]] = []
    monkeypatch.setattr(reporting_cli, "_read_build_request_file", lambda path: request)

    def freeze(*args: object, **kwargs: object) -> object:
        observed.append(kwargs)
        reference = reporting_cli.ReportingSnapshotReference(
            class_id=CLASS_ID,
            snapshot_id=SNAPSHOT_ID,
            snapshot_sha256=SNAPSHOT_SHA256,
        )
        snapshot = SimpleNamespace(
            report_preview_sha256="e" * 64,
            report_preview=SimpleNamespace(rows=(object(),)),
        )
        return SimpleNamespace(reference=reference, snapshot=snapshot)

    monkeypatch.setattr(reporting_cli, "freeze_reporting_snapshot", freeze)

    assert main(_freeze_args("--confirm-freeze", "--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(observed) == 1
    assert observed[0]["snapshot_id"] == SNAPSHOT_ID
    assert observed[0]["build_request"] == request
    assert payload["disposition"] == "committed_or_exact_replay"
    assert payload["snapshot_reference"]["snapshot_sha256"] == SNAPSHOT_SHA256
    assert payload["freeze_confirmed"] is True


def test_projection_reopen_uses_exact_authorization_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = ReportingSnapshotProjectionInputReference(
        publication_id="publication_001",
        cache_key=CACHE_KEY,
        snapshot_digest=PROJECTION_SHA256,
    )
    authorizer = object()
    registry = object()
    adapter_registry = object()
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def load(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return SimpleNamespace(
            stored=SimpleNamespace(snapshot_digest=PROJECTION_SHA256)
        )

    monkeypatch.setattr(reporting_cli, "load_authorized_projection_snapshot", load)
    dependencies = SimpleNamespace(
        authorizer=authorizer,
        producer_registry_state="available",
        producer_registry=registry,
        adapter_registry=adapter_registry,
        distribution_version_resolver=lambda name: "1.0",
    )
    result = reporting_cli._load_live_projection(
        Path("workspace"),
        reference,
        {
            ("publication_001", CACHE_KEY): (
                "reporting_snapshot_freeze",
                ("student_001",),
            )
        },
        dependencies,  # type: ignore[arg-type]
    )

    assert result.stored.snapshot_digest == PROJECTION_SHA256
    assert len(observed) == 1
    _, kwargs = observed[0]
    assert kwargs["authorizer"] is authorizer
    assert kwargs["producer_registry"] is registry
    assert kwargs["adapter_registry"] is adapter_registry
    assert kwargs["authorization_purpose_id"] == "reporting_snapshot_freeze"
    assert kwargs["requested_student_ids"] == ("student_001",)


def test_projection_reopen_requires_deployment_authorizer() -> None:
    reference = ReportingSnapshotProjectionInputReference(
        publication_id="publication_001",
        cache_key=CACHE_KEY,
        snapshot_digest=PROJECTION_SHA256,
    )
    dependencies = SimpleNamespace(
        authorizer=None,
        producer_registry_state="available",
        producer_registry=object(),
        adapter_registry=object(),
        distribution_version_resolver=lambda name: "1.0",
    )
    with pytest.raises(reporting_cli.ReportingSnapshotCliError) as raised:
        reporting_cli._load_live_projection(
            Path("workspace"),
            reference,
            {("publication_001", CACHE_KEY): ("reporting", ())},
            dependencies,  # type: ignore[arg-type]
        )
    assert raised.value.code == "reporting_snapshot.source_unavailable"


def test_unused_projection_authorization_is_rejected() -> None:
    with pytest.raises(reporting_cli.ReportingSnapshotCliError) as raised:
        reporting_cli._preview_requests_from_build_request(
            Path("workspace"),
            _build_request(),
            [["publication_001", CACHE_KEY, "reporting", "student_001"]],
            None,
        )
    assert raised.value.code == "reporting_snapshot.request_invalid"


def test_compare_reuses_issue54_live_report_comparison(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = _build_request()
    snapshot = SimpleNamespace(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        build_request=request,
    )
    monkeypatch.setattr(
        reporting_cli,
        "load_reporting_snapshot_for_comparison",
        lambda *args: SimpleNamespace(snapshot=snapshot),
    )
    monkeypatch.setattr(
        reporting_cli,
        "explain_grade_report_preview",
        lambda *args: SimpleNamespace(),
    )
    observed: list[object] = []

    def compare(frozen: object, live: object) -> tuple[object, ...]:
        observed.extend((frozen, live))
        return (object(),)

    monkeypatch.setattr(
        reporting_cli,
        "compare_reporting_snapshot_to_grade_report_preview",
        compare,
    )
    monkeypatch.setattr(
        reporting_cli,
        "grade_preview_comparison_to_dict",
        lambda value: {
            "relationship": "comparable",
            "changed": False,
            "reasons": [],
        },
    )
    monkeypatch.setattr(
        reporting_cli,
        "grade_report_preview_to_dict",
        lambda value: {"summary": {"requested_count": 1}},
    )

    assert main(_compare_args("--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert observed[0] is snapshot
    assert payload["comparison_engine"] == "issue_54_grade_preview_comparison"
    assert payload["read_only"] is True
    assert payload["official_system_authority"] is False
    assert payload["comparisons"][0]["relationship"] == "comparable"


def test_compare_rejects_explicit_current_request_outside_snapshot_scope() -> None:
    snapshot = SimpleNamespace(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
    )
    with pytest.raises(reporting_cli.ReportingSnapshotCliError) as raised:
        reporting_cli._require_compare_request_scope(
            snapshot,  # type: ignore[arg-type]
            _build_request(calendar_revision=2),
        )
    assert raised.value.code == "reporting_snapshot.comparison_invalid"
