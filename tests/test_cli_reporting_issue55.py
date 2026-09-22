from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.reporting_snapshot_cli as reporting_cli
from meridian.cli import main
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionReference,
    ReportingDefinitionRevision,
    ReportingSnapshotReference,
    reporting_definition_reference,
)
from meridian.reporting_snapshot_selection import ReportingSnapshotSelectionReference

CLASS_ID = "class_2026"
DEFINITION_ID = "progress_report"
SNAPSHOT_ID = "snapshot_001"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)


def _definition(revision: int = 1) -> ReportingDefinitionRevision:
    return ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS_ID,
        definition_id=DEFINITION_ID,
        definition_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        report_kind="grade_report",
        purpose="Progress report",
        title="Q1 Progress",
        target_period=PERIOD,
        intended_audience="teacher",
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def _stored_snapshot() -> SimpleNamespace:
    definition_reference = ReportingDefinitionReference(
        class_id=CLASS_ID,
        definition_id=DEFINITION_ID,
        definition_revision=1,
        definition_sha256="a" * 64,
    )
    reference = ReportingSnapshotReference(
        class_id=CLASS_ID,
        snapshot_id=SNAPSHOT_ID,
        snapshot_sha256="b" * 64,
    )
    snapshot = SimpleNamespace(
        class_id=CLASS_ID,
        snapshot_id=SNAPSHOT_ID,
        definition_reference=definition_reference,
        target_period=PERIOD,
        calendar_revision=1,
        created_at=NOW,
        report_preview=SimpleNamespace(rows=(object(), object())),
    )
    return SimpleNamespace(
        snapshot=snapshot,
        snapshot_sha256=reference.snapshot_sha256,
        reference=reference,
        relative_path=(
            f"classes/{CLASS_ID}/modules/meridian/reporting_snapshots/"
            f"{SNAPSHOT_ID}.json"
        ),
    )


def _definition_write_args(*extra: str) -> tuple[str, ...]:
    return (
        "reporting",
        "definitions",
        "write",
        CLASS_ID,
        DEFINITION_ID,
        "1",
        "2026-2027",
        "q1",
        "--purpose",
        "Progress report",
        "--title",
        "Q1 Progress",
        "--actor-id",
        "teacher_local",
        "--revised-at",
        "2026-09-20T18:00:00Z",
        *extra,
    )


def _selection_args(*extra: str) -> tuple[str, ...]:
    return (
        "reporting",
        "selection",
        "select",
        CLASS_ID,
        SNAPSHOT_ID,
        "b" * 64,
        "--actor-id",
        "teacher_local",
        "--decided-at",
        "2026-09-20T18:05:00Z",
        *extra,
    )


def test_reporting_group_without_subcommand_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("reporting",)) == 0
    output = capsys.readouterr().out
    assert "usage: meridian reporting" in output
    assert "definitions" in output
    assert "snapshots" in output
    assert "selection" in output
    assert "not an official district/SIS Grade" in output


def test_definition_write_defaults_to_preview_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(_definition_write_args("--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["surface"] == "reporting_definition_write"
    assert payload["disposition"] == "preview_only"
    assert payload["write_confirmed"] is False
    assert payload["reference"]["definition_id"] == DEFINITION_ID


def test_definition_write_requires_explicit_confirmation_for_persistence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: list[ReportingDefinitionRevision] = []

    def write(_workspace: Path, definition: ReportingDefinitionRevision) -> object:
        observed.append(definition)
        return SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(definition=definition),
        )

    monkeypatch.setattr(reporting_cli, "write_reporting_definition_revision", write)

    assert main(_definition_write_args("--confirm-write", "--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(observed) == 1
    assert payload["disposition"] == "created"
    assert payload["write_confirmed"] is True


def test_definition_list_has_no_implicit_current_authority(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    definition = _definition()
    digest = reporting_definition_reference(definition).definition_sha256
    monkeypatch.setattr(
        reporting_cli,
        "list_reporting_definition_ids",
        lambda *args: (DEFINITION_ID,),
    )
    monkeypatch.setattr(
        reporting_cli,
        "list_reporting_definition_revisions",
        lambda *args: (1,),
    )
    monkeypatch.setattr(
        reporting_cli,
        "load_reporting_definition_revision",
        lambda *args: SimpleNamespace(
            definition=definition,
            definition_sha256=digest,
            relative_path="synthetic",
        ),
    )

    assert main(("reporting", "definitions", "list", CLASS_ID, "--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["current_definition_inference"] == "none"
    assert payload["families"][0]["revisions"][0]["definition_revision"] == 1


def test_definition_inspect_rejects_wrong_digest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    definition = _definition()
    monkeypatch.setattr(
        reporting_cli,
        "load_reporting_definition_revision",
        lambda *args: SimpleNamespace(
            definition=definition,
            definition_sha256="a" * 64,
            relative_path="synthetic",
        ),
    )

    assert main(
        (
            "reporting",
            "definitions",
            "inspect",
            CLASS_ID,
            DEFINITION_ID,
            "1",
            "b" * 64,
        )
    ) == 1
    assert "reporting_snapshot.integrity_failed" in capsys.readouterr().err


def test_snapshot_list_does_not_imply_current_use(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = _stored_snapshot()
    monkeypatch.setattr(
        reporting_cli,
        "list_reporting_snapshot_ids",
        lambda *args: (SNAPSHOT_ID,),
    )
    monkeypatch.setattr(reporting_cli, "load_reporting_snapshot", lambda *args: stored)

    assert main(("reporting", "snapshots", "list", CLASS_ID)) == 0
    output = capsys.readouterr().out
    assert "Frozen Meridian ReportingSnapshots" in output
    assert "listing order is not current-use authority" in output
    assert SNAPSHOT_ID in output


def test_snapshot_inspect_exposes_frozen_not_official_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = _stored_snapshot()
    monkeypatch.setattr(reporting_cli, "load_reporting_snapshot", lambda *args: stored)
    monkeypatch.setattr(
        reporting_cli,
        "reporting_snapshot_to_dict",
        lambda value: {"snapshot_id": value.snapshot_id, "rows": 2},
    )

    assert main(
        (
            "reporting",
            "snapshots",
            "inspect",
            CLASS_ID,
            SNAPSHOT_ID,
            "b" * 64,
            "--format",
            "json",
        )
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["surface"] == "frozen_reporting_snapshot"
    assert payload["official_system_authority"] is False
    assert payload["snapshot"]["snapshot_id"] == SNAPSHOT_ID


def test_selection_show_distinguishes_no_current_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        reporting_cli,
        "load_current_reporting_snapshot_selection",
        lambda *args: None,
    )

    assert main(
        (
            "reporting",
            "selection",
            "show",
            CLASS_ID,
            DEFINITION_ID,
            "2026-2027",
            "q1",
            "1",
        )
    ) == 0
    output = capsys.readouterr().out
    assert "currently selected snapshot for reporting use: none" in output
    assert "not an official district/SIS Grade" in output


def test_selection_select_preview_performs_no_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = _stored_snapshot()
    monkeypatch.setattr(reporting_cli, "load_reporting_snapshot", lambda *args: stored)
    monkeypatch.setattr(
        reporting_cli,
        "get_current_reporting_snapshot_selection_reference",
        lambda *args: None,
    )

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("preview must not write selection state")

    monkeypatch.setattr(reporting_cli, "select_reporting_snapshot", forbidden)

    assert main(_selection_args("--expect-none", "--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["disposition"] == "preview_only"
    assert payload["selection_confirmed"] is False
    assert payload["resulting_selection_reference"] is None


def test_selection_select_confirm_uses_exact_digest_bound_cas(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = _stored_snapshot()
    current = ReportingSnapshotSelectionReference(
        class_id=CLASS_ID,
        definition_id=DEFINITION_ID,
        target_period=PERIOD,
        calendar_revision=1,
        selection_revision=2,
        selection_sha256="c" * 64,
    )
    resulting = ReportingSnapshotSelectionReference(
        class_id=CLASS_ID,
        definition_id=DEFINITION_ID,
        target_period=PERIOD,
        calendar_revision=1,
        selection_revision=3,
        selection_sha256="d" * 64,
    )
    observed: list[object] = []
    monkeypatch.setattr(reporting_cli, "load_reporting_snapshot", lambda *args: stored)
    monkeypatch.setattr(
        reporting_cli,
        "get_current_reporting_snapshot_selection_reference",
        lambda *args: current,
    )

    def select(*args: object, **kwargs: object) -> object:
        observed.append(kwargs["expected_current"])
        return SimpleNamespace(
            disposition="updated",
            selection=SimpleNamespace(reference=resulting),
        )

    monkeypatch.setattr(reporting_cli, "select_reporting_snapshot", select)

    assert main(
        _selection_args(
            "--expected-selection-revision",
            "2",
            "--expected-selection-sha256",
            "c" * 64,
            "--confirm-select",
            "--format",
            "json",
        )
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert observed == [current]
    assert payload["disposition"] == "updated"
    assert payload["selection_confirmed"] is True
    assert payload["resulting_selection_reference"]["selection_revision"] == 3


def test_selection_select_rejects_stale_expected_current(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = _stored_snapshot()
    current = ReportingSnapshotSelectionReference(
        class_id=CLASS_ID,
        definition_id=DEFINITION_ID,
        target_period=PERIOD,
        calendar_revision=1,
        selection_revision=2,
        selection_sha256="c" * 64,
    )
    monkeypatch.setattr(reporting_cli, "load_reporting_snapshot", lambda *args: stored)
    monkeypatch.setattr(
        reporting_cli,
        "get_current_reporting_snapshot_selection_reference",
        lambda *args: current,
    )

    assert main(_selection_args("--expect-none")) == 1
    assert "reporting_snapshot.selection_conflict" in capsys.readouterr().err


def test_selection_revision_requires_paired_digest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = _stored_snapshot()
    monkeypatch.setattr(reporting_cli, "load_reporting_snapshot", lambda *args: stored)

    assert main(_selection_args("--expected-selection-revision", "2")) == 1
    assert "reporting_snapshot.selection_invalid" in capsys.readouterr().err
