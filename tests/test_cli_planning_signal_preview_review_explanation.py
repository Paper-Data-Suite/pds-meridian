from __future__ import annotations

import json
from pathlib import Path

import pytest

from meridian.cli import main
from meridian.grouping_signal_review_storage import (
    write_grouping_signal_review_revision,
)
from tests.test_planning_signal_derivation_explanation import _prepared
from tests.test_planning_signal_preview_review_explanation import (
    CLASS_ID,
    _currentness,
    _patch_live_currentness,
    _review,
    _stored_preview,
)


def _base_args(root: Path, preview_id: str) -> list[str]:
    return [
        "trace",
        "planning-preview-review",
        CLASS_ID,
        preview_id,
        "--workspace",
        str(root),
    ]


def test_trace_help_exposes_exact_review_selectors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["trace", "planning-preview-review", "--help"])
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "--selected-review" in output
    assert "--review-revision" in output
    assert "preview_id" in output


def test_selected_review_mode_text_reports_ready_for_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    preview = _stored_preview(root, derivation)
    _patch_live_currentness(monkeypatch, _currentness(derivation))

    args = _base_args(root, preview.snapshot.preview_id) + ["--selected-review"]
    assert main(args) == 0
    output = capsys.readouterr().out

    assert "Planning preview/review explanation" in output
    assert "path_state: ready_for_review" in output
    assert "review: none selected" in output


def test_exact_review_revision_json_preserves_historical_selection_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    preview = _stored_preview(root, derivation)
    review = _review(preview, 1)
    write_grouping_signal_review_revision(root, review)
    _patch_live_currentness(monkeypatch, _currentness(derivation))

    args = _base_args(root, preview.snapshot.preview_id) + [
        "--review-revision",
        "1",
        "--format",
        "json",
    ]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["target"]["preview_id"] == preview.snapshot.preview_id
    assert payload["path_state"] == "accepted_but_not_selected"
    assert payload["review"]["review_revision"] == 1
    assert payload["review"]["selection_state"] == "not_selected"
    assert payload["review"]["decision"] == "accepted_for_export"


def test_missing_exact_preview_is_not_found(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    missing = "gsp_" + "0" * 64
    args = _base_args(root, missing) + ["--selected-review"]

    assert main(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "explanation_trace.target_not_found" in captured.err
