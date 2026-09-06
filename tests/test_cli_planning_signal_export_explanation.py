from __future__ import annotations

import json
from pathlib import Path

import pytest

from meridian.cli import main
from tests.test_planning_signal_derivation_explanation import CLASS_ID
from tests.test_planning_signal_export_explanation import (
    SIGNAL_SET_ID,
    _exported,
)


def _base_args(root: Path, signal_set_id: str = SIGNAL_SET_ID) -> list[str]:
    return [
        "trace",
        "planning-export",
        CLASS_ID,
        signal_set_id,
        "--workspace",
        str(root),
    ]


def test_trace_help_exposes_exact_export_target(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["trace", "planning-export", "--help"])
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "class_id" in output
    assert "signal_set_id" in output
    assert "--format" in output
    assert "--current" not in output
    assert "--review-revision" not in output


def test_exact_export_text_renders_receipt_bound_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, derivation, preview, review, _, _ = _exported(tmp_path, monkeypatch)

    assert main(_base_args(root)) == 0
    output = capsys.readouterr().out

    assert "Planning signal export trace" in output
    assert SIGNAL_SET_ID in output
    assert derivation.snapshot.derivation_id in output
    assert preview.snapshot.preview_id in output
    assert f"revision={review.review.review_revision}" in output
    assert "student_1" in output and "exported=yes" in output
    assert "student_3" in output and "reason=missing_result" in output


def test_exact_export_json_preserves_core_receipt_and_student_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, derivation, preview, review, core, receipt = _exported(
        tmp_path,
        monkeypatch,
    )

    args = _base_args(root) + ["--format", "json"]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["target"] == {
        "class_id": CLASS_ID,
        "signal_set_id": SIGNAL_SET_ID,
    }
    assert payload["core_signal"]["contract"] == "grouping_signal_set_v1"
    assert payload["core_signal"]["signal_digest"] == core.digest
    assert payload["export_receipt"]["receipt_sha256"] == receipt.receipt_sha256
    assert (
        payload["export_receipt"]["derivation"]["derivation_id"]
        == derivation.snapshot.derivation_id
    )
    assert (
        payload["export_receipt"]["preview"]["preview_id"]
        == preview.snapshot.preview_id
    )
    assert payload["export_receipt"]["review"]["review_revision"] == (
        review.review.review_revision
    )
    students = {item["student_id"]: item for item in payload["students"]}
    assert students["student_1"]["exported"] is True
    assert students["student_2"]["noncontribution_reason"] == (
        "insufficient_evidence"
    )
    assert students["student_3"]["noncontribution_reason"] == "missing_result"


def test_missing_exact_export_is_not_found(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    args = _base_args(root, "missing_signal_set")

    assert main(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "explanation_trace.target_not_found" in captured.err
