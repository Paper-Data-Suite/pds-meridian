from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli
from tests.test_cli_planning_signal_core_export_preview import (
    SIGNAL_SET_ID,
    _export_args,
    _export_preview,
    _review_source_args,
)

CORE_DIGEST = "f" * 64
RECEIPT_SHA256 = "9" * 64


def _commit_result() -> object:
    return SimpleNamespace(
        core_write_disposition="created",
        receipt_write_disposition="created",
        core_signal_digest=CORE_DIGEST,
        receipt_sha256=RECEIPT_SHA256,
        review_write_action="not_performed",
        review_selection_action="not_performed",
        core_export_action="performed",
        export_receipt_action="performed",
        csv_export_action="not_performed",
        concord_action="not_performed",
    )


def test_core_export_default_remains_read_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _export_preview()
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_core_export",
        lambda *args, **kwargs: preview,
    )

    def should_not_commit(*args: object, **kwargs: object) -> object:
        raise AssertionError("default Core export path must remain read-only")

    monkeypatch.setattr(
        cli,
        "commit_planning_signal_core_export",
        should_not_commit,
    )
    monkeypatch.setattr(
        cli,
        "format_grouping_signal_teacher_projection",
        lambda value: "CANONICAL #39 TEACHER PROJECTION",
    )

    assert cli.main(_export_args()) == 0
    output = capsys.readouterr().out
    assert "Create Planning Signal — #40 Core export preview" in output
    assert "NO CORE GROUPING SIGNAL WRITTEN" in output
    assert "NO MERIDIAN EXPORT RECEIPT WRITTEN" in output


def test_core_export_confirmation_commits_exact_preview(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _export_preview()
    observed: list[tuple[object, object]] = []
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_core_export",
        lambda *args, **kwargs: preview,
    )

    def commit(workspace: object, candidate: object) -> object:
        observed.append((workspace, candidate))
        return _commit_result()

    monkeypatch.setattr(cli, "commit_planning_signal_core_export", commit)

    assert cli.main(_export_args("--confirm-core-export")) == 0
    output = capsys.readouterr().out

    assert observed == [("synthetic-workspace", preview)]
    assert "Create Planning Signal — #40 Core export committed" in output
    assert f"Core signal-set ID: {SIGNAL_SET_ID}" in output
    assert "Core write disposition: created" in output
    assert f"Core signal SHA-256: {CORE_DIGEST}" in output
    assert "Meridian export receipt disposition: created" in output
    assert f"Meridian export receipt SHA-256: {RECEIPT_SHA256}" in output
    assert "NO CSV EXPORTED" in output
    assert "NO REVIEW STATE CHANGED" in output
    assert "NO CONCORD GROUP OR GROUPPLAN CREATED" in output


def test_core_export_confirmation_json_reports_exact_commit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_core_export",
        lambda *args, **kwargs: _export_preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_planning_signal_core_export",
        lambda *args, **kwargs: _commit_result(),
    )

    assert cli.main(_export_args("--confirm-core-export", "--format", "json")) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "core_export_committed"
    assert data["core_candidate"]["signal_set_id"] == SIGNAL_SET_ID
    assert data["result"]["core_write_disposition"] == "created"
    assert data["result"]["core_signal_digest"] == CORE_DIGEST
    assert data["result"]["receipt_write_disposition"] == "created"
    assert data["result"]["receipt_sha256"] == RECEIPT_SHA256
    assert data["final_core_revalidation_completed"] is True
    assert data["actions"]["core_export"] == "performed"
    assert data["actions"]["export_receipt"] == "performed"
    assert data["actions"]["csv_export"] == "not_performed"
    assert data["actions"]["review_write"] == "not_performed"
    assert data["actions"]["review_selection"] == "not_performed"
    assert data["concord_action"] == "not_performed"


def test_core_export_confirmation_requires_complete_export_intent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(_review_source_args("--confirm-core-export")) == 1
    error = capsys.readouterr().err
    assert "core_export_commit_invalid" in error
    assert (
        "--confirm-core-export requires the exact #40 export preview intent"
        in error
    )


def test_core_export_partial_success_is_distinct_and_recoverable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_core_export",
        lambda *args, **kwargs: _export_preview(),
    )

    def partial(*args: object, **kwargs: object) -> object:
        raise cli.PlanningSignalCoreExportCommitPartialSuccessError(
            signal_set_id=SIGNAL_SET_ID,
            core_digest_algorithm="sha256",
            core_signal_digest=CORE_DIGEST,
            core_disposition="created",
        )

    monkeypatch.setattr(cli, "commit_planning_signal_core_export", partial)

    assert cli.main(_export_args("--confirm-core-export")) == 1
    captured = capsys.readouterr()

    assert captured.err == ""
    assert "Create Planning Signal — #40 PARTIAL SUCCESS" in captured.out
    assert f"Core signal-set ID: {SIGNAL_SET_ID}" in captured.out
    assert "Core write disposition: created" in captured.out
    assert f"Core signal SHA-256: {CORE_DIGEST}" in captured.out
    assert "MERIDIAN EXPORT RECEIPT NOT VERIFIED" in captured.out
    assert "retry the exact same export request" in captured.out.lower()
    assert "NO CSV EXPORTED" in captured.out
    assert "NO CONCORD GROUP OR GROUPPLAN CREATED" in captured.out


def test_core_export_partial_success_json_is_machine_distinct(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_core_export",
        lambda *args, **kwargs: _export_preview(),
    )

    def partial(*args: object, **kwargs: object) -> object:
        raise cli.PlanningSignalCoreExportCommitPartialSuccessError(
            signal_set_id=SIGNAL_SET_ID,
            core_digest_algorithm="sha256",
            core_signal_digest=CORE_DIGEST,
            core_disposition="existing",
        )

    monkeypatch.setattr(cli, "commit_planning_signal_core_export", partial)

    assert (
        cli.main(_export_args("--confirm-core-export", "--format", "json"))
        == 1
    )
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "core_export_partial_success"
    assert data["partial_success"]["signal_set_id"] == SIGNAL_SET_ID
    assert data["partial_success"]["core_disposition"] == "existing"
    assert data["partial_success"]["core_signal_digest"] == CORE_DIGEST
    assert data["actions"]["core_export"] == "performed"
    assert data["actions"]["export_receipt"] == "failed_after_core_write"
    assert data["actions"]["csv_export"] == "not_performed"
    assert data["concord_action"] == "not_performed"
