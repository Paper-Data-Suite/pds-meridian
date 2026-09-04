from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import meridian.cli as cli
from meridian.planning_signal_export_commit_workflow import (
    PlanningSignalCsvExportPartialSuccessError,
)
from tests.test_cli_planning_signal_core_export_commit import (
    CORE_DIGEST,
    RECEIPT_SHA256,
    _commit_result,
)
from tests.test_cli_planning_signal_core_export_preview import (
    SIGNAL_SET_ID,
    _export_args,
    _export_preview,
    _review_source_args,
)

CSV_DIGEST = "c" * 64


def _final_result(destination: Path) -> object:
    return SimpleNamespace(
        core=_commit_result(),
        csv=SimpleNamespace(
            destination=destination.resolve(),
            disposition="created",
            byte_length=321,
            csv_sha256=CSV_DIGEST,
        ),
        core_export_action="performed",
        export_receipt_action="performed",
        csv_export_action="performed",
        concord_action="not_performed",
    )


def _csv_partial(destination: Path) -> PlanningSignalCsvExportPartialSuccessError:
    error = PlanningSignalCsvExportPartialSuccessError.__new__(
        PlanningSignalCsvExportPartialSuccessError
    )
    RuntimeError.__init__(
        error,
        "synthetic Core+receipt success followed by CSV failure",
    )
    error.core_result = _commit_result()  # type: ignore[assignment]
    error.csv_error_code = "csv_destination_conflict"
    error.csv_destination = destination
    return error


def test_csv_destination_is_read_only_export_plan_without_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    destination = tmp_path / "planning.csv"
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_core_export",
        lambda *args, **kwargs: _export_preview(),
    )

    def should_not_commit(*args: object, **kwargs: object) -> object:
        raise AssertionError("CSV plan must remain read-only without confirmation")

    monkeypatch.setattr(cli, "commit_planning_signal_export", should_not_commit)

    assert (
        cli.main(
            _export_args(
                "--csv-destination",
                str(destination),
                "--format",
                "json",
            )
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "core_export_preview"
    assert data["csv_plan"]["requested"] is True
    assert data["csv_plan"]["destination"] == str(destination)
    assert data["actions"]["core_export"] == "not_performed"
    assert data["actions"]["export_receipt"] == "not_performed"
    assert data["actions"]["csv_export"] == "not_performed"
    assert data["concord_action"] == "not_performed"


def test_confirmed_csv_export_routes_through_final_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    destination = tmp_path / "planning.csv"
    preview = _export_preview()
    observed: list[tuple[object, object, object]] = []

    monkeypatch.setattr(
        cli,
        "preview_planning_signal_core_export",
        lambda *args, **kwargs: preview,
    )

    def final_commit(
        workspace: object,
        candidate: object,
        *,
        csv_destination: object,
    ) -> object:
        observed.append((workspace, candidate, csv_destination))
        return _final_result(destination)

    monkeypatch.setattr(cli, "commit_planning_signal_export", final_commit)

    def should_not_direct_core(*args: object, **kwargs: object) -> object:
        raise AssertionError("CSV confirmation must use final export orchestrator")

    monkeypatch.setattr(
        cli,
        "commit_planning_signal_core_export",
        should_not_direct_core,
    )

    assert (
        cli.main(
            _export_args(
                "--csv-destination",
                str(destination),
                "--confirm-core-export",
                "--format",
                "json",
            )
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)

    assert observed == [("synthetic-workspace", preview, destination)]
    assert data["mode"] == "core_export_committed"
    assert data["core_candidate"]["signal_set_id"] == SIGNAL_SET_ID
    assert data["result"]["core_write_disposition"] == "created"
    assert data["result"]["core_signal_digest"] == CORE_DIGEST
    assert data["result"]["receipt_write_disposition"] == "created"
    assert data["result"]["receipt_sha256"] == RECEIPT_SHA256
    assert data["csv_export"]["destination"] == str(destination.resolve())
    assert data["csv_export"]["disposition"] == "created"
    assert data["csv_export"]["byte_length"] == 321
    assert data["csv_export"]["csv_sha256"] == CSV_DIGEST
    assert data["actions"]["csv_export"] == "performed"
    assert data["concord_action"] == "not_performed"


def test_csv_destination_requires_complete_core_export_intent(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    destination = tmp_path / "planning.csv"

    assert (
        cli.main(
            _review_source_args(
                "--csv-destination",
                str(destination),
            )
        )
        == 1
    )
    error = capsys.readouterr().err
    assert "core_export_commit_invalid" in error
    assert "--csv-destination requires the exact #40 export preview intent" in error


def test_csv_partial_success_preserves_durable_core_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    destination = tmp_path / "teacher-edited.csv"
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_core_export",
        lambda *args, **kwargs: _export_preview(),
    )

    def partial(*args: object, **kwargs: object) -> object:
        raise _csv_partial(destination)

    monkeypatch.setattr(cli, "commit_planning_signal_export", partial)

    assert (
        cli.main(
            _export_args(
                "--csv-destination",
                str(destination),
                "--confirm-core-export",
            )
        )
        == 1
    )
    captured = capsys.readouterr()

    assert captured.err == ""
    assert "Create Planning Signal — CSV PARTIAL SUCCESS" in captured.out
    assert f"Core signal-set ID: {SIGNAL_SET_ID}" in captured.out
    assert "Core write disposition: created" in captured.out
    assert "Meridian export receipt disposition: created" in captured.out
    assert "CSV failure code: csv_destination_conflict" in captured.out
    assert f"CSV destination: {destination}" in captured.out
    assert "CORE AND RECEIPT REMAIN DURABLE" in captured.out
    assert "NO CONCORD GROUP OR GROUPPLAN CREATED" in captured.out


def test_csv_partial_success_json_is_machine_distinct(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    destination = tmp_path / "teacher-edited.csv"
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_core_export",
        lambda *args, **kwargs: _export_preview(),
    )

    def partial(*args: object, **kwargs: object) -> object:
        raise _csv_partial(destination)

    monkeypatch.setattr(cli, "commit_planning_signal_export", partial)

    assert (
        cli.main(
            _export_args(
                "--csv-destination",
                str(destination),
                "--confirm-core-export",
                "--format",
                "json",
            )
        )
        == 1
    )
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "csv_export_partial_success"
    assert data["partial_success"]["signal_set_id"] == SIGNAL_SET_ID
    assert data["partial_success"]["core_write_disposition"] == "created"
    assert data["partial_success"]["receipt_write_disposition"] == "created"
    assert data["partial_success"]["csv_error_code"] == "csv_destination_conflict"
    assert data["partial_success"]["csv_destination"] == str(destination)
    assert data["actions"]["core_export"] == "performed"
    assert data["actions"]["export_receipt"] == "performed"
    assert data["actions"]["csv_export"] == "failed_after_core_and_receipt"
    assert data["concord_action"] == "not_performed"
