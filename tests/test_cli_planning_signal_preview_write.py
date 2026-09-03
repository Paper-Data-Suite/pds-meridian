from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "class_2026"
POLICY_ID = "reading_groups"
DERIVATION_ID = "gsd_" + "a" * 64
DERIVATION_SHA256 = "b" * 64
PREVIEW_ID = "gsp_" + "c" * 64


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


def _source_args(*extra: str) -> tuple[str, ...]:
    return _arguments(
        "--preview-derivation-id",
        DERIVATION_ID,
        "--preview-derivation-sha256",
        DERIVATION_SHA256,
        *extra,
    )


def _preflight() -> object:
    return SimpleNamespace(
        class_id=CLASS_ID,
        policy_id=POLICY_ID,
        policy_reference=SimpleNamespace(
            class_id=CLASS_ID,
            policy_id=POLICY_ID,
            policy_revision=2,
            policy_sha256="d" * 64,
        ),
        derivation_id=DERIVATION_ID,
        derivation_sha256=DERIVATION_SHA256,
        calculation_fingerprint="e" * 64,
        roster_student_count=24,
        contributing_student_count=21,
        noncontributing_student_count=3,
        preview_write_action="not_performed",
        review_write_action="not_performed",
        review_selection_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )


def _result() -> object:
    return SimpleNamespace(
        write_disposition="created",
        preview_id=PREVIEW_ID,
        preview_sha256="f" * 64,
        preview_fingerprint="0" * 64,
        currentness_state="current",
        currentness_reason_codes=(),
        diagnostic_count=2,
        warning_diagnostic_ids=("gpd_" + "1" * 64,),
        blocking_diagnostic_ids=(),
        roster_student_count=24,
        contributing_student_count=21,
        noncontributing_student_count=3,
        review_write_action="not_performed",
        review_selection_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )


def test_exact_source_default_is_read_only_preview_write_intent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preflight = _preflight()
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def preview(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return preflight

    monkeypatch.setattr(cli, "preview_planning_signal_preview_write", preview)
    monkeypatch.setattr(
        cli,
        "commit_planning_signal_preview_write",
        lambda *args, **kwargs: pytest.fail("default must not create #39"),
    )
    monkeypatch.setattr(
        cli,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: pytest.fail(
            "exact persisted #38 mode must not reroute through readiness"
        ),
    )

    assert cli.main(_source_args()) == 0
    output = capsys.readouterr().out

    assert observed == [
        (
            (
                "synthetic-workspace",
                CLASS_ID,
                POLICY_ID,
                DERIVATION_ID,
                DERIVATION_SHA256,
            ),
            {},
        )
    ]
    assert "Create Planning Signal — #39 preview write" in output
    assert f"exact #38 derivation: {DERIVATION_ID}" in output
    assert "preview write confirmation supplied: no" in output
    assert "NO #39 PREVIEW WRITTEN" in output
    assert "NO TEACHER REVIEW WRITTEN" in output


def test_confirm_preview_write_commits_exact_preflight(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preflight = _preflight()
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_preview_write",
        lambda *args, **kwargs: preflight,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(cli, "commit_planning_signal_preview_write", commit)

    assert cli.main(_source_args("--confirm-preview-write")) == 0
    output = capsys.readouterr().out

    assert observed == [(("synthetic-workspace", preflight), {})]
    assert "preview write confirmation supplied: yes" in output
    assert f"#39 preview persisted: {PREVIEW_ID}" in output
    assert "write disposition: created" in output
    assert "preview currentness: current" in output
    assert "NO TEACHER REVIEW WRITTEN" in output
    assert "NO CORE GROUPING SIGNAL OR CSV EXPORTED" in output


def test_confirmed_json_preserves_review_and_export_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_preview_write",
        lambda *args, **kwargs: _preflight(),
    )
    monkeypatch.setattr(
        cli,
        "commit_planning_signal_preview_write",
        lambda *args, **kwargs: _result(),
    )

    assert cli.main(
        _source_args("--confirm-preview-write", "--format", "json")
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["task"] == "create-planning-signal"
    assert data["mode"] == "preview_written"
    assert data["preview_write_confirmed"] is True
    assert data["source_derivation"]["derivation_id"] == DERIVATION_ID
    assert data["preview"]["preview_id"] == PREVIEW_ID
    assert data["preview"]["write_disposition"] == "created"
    assert data["actions"]["preview_write"] == "performed"
    assert data["actions"]["review_write"] == "not_performed"
    assert data["actions"]["review_selection"] == "not_performed"
    assert data["actions"]["core_export"] == "not_performed"
    assert data["actions"]["csv_export"] == "not_performed"
    assert data["concord_action"] == "not_performed"


def test_preview_source_arguments_must_be_paired(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(
        _arguments("--preview-derivation-id", DERIVATION_ID)
    ) == 1
    assert "preview source requires both" in capsys.readouterr().err


def test_preview_write_confirmation_requires_exact_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(_arguments("--confirm-preview-write")) == 1
    assert "requires an exact persisted #38 source" in capsys.readouterr().err


def test_preview_stage_cannot_be_combined_with_derivation_write(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(
        _source_args(
            "--confirm-preview-write",
            "--confirm-derivation-write",
        )
    ) == 1
    assert "cannot be combined" in capsys.readouterr().err
