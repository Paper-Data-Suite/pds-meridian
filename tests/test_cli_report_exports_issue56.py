from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.report_export_cli as export_cli
from meridian.cli import build_parser, main

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def test_parser_exposes_all_issue56_reporting_command_groups() -> None:
    parser = build_parser()

    profile = parser.parse_args(
        [
            "reporting",
            "export-profiles",
            "current",
            "english_12",
            "district_gradebook",
        ]
    )
    assert profile.export_profile_command == "current"

    export = parser.parse_args(
        [
            "reporting",
            "exports",
            "preview",
            "english_12",
            "snapshot_001",
            SHA_A,
            "district_gradebook",
            "1",
            SHA_B,
        ]
    )
    assert export.report_export_command == "preview"

    receipt = parser.parse_args(
        [
            "reporting",
            "export-receipts",
            "inspect",
            "english_12",
            "export_001",
            SHA_C,
        ]
    )
    assert receipt.export_receipt_command == "inspect"


def test_profile_write_without_confirmation_is_read_only(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden_write(*args: object, **kwargs: object) -> object:
        raise AssertionError("dry-run profile write mutated storage")

    monkeypatch.setattr(export_cli, "write_export_profile_revision", forbidden_write)

    result = main(
        [
            "reporting",
            "export-profiles",
            "write",
            "english_12",
            "district_gradebook",
            "1",
            "--title",
            "District gradebook",
            "--purpose",
            "Teacher-controlled Grade transfer",
            "--column",
            "target.student_id",
            "Student ID",
            "--column",
            "grade.effective_grade",
            "Grade",
            "--output-format",
            "csv",
            "--actor-id",
            "teacher_local",
            "--revised-at",
            "2026-09-22T03:00:00+00:00",
            "--workspace",
            str(tmp_path),
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "NO EXPORT PROFILE REVISION WRITTEN" in output
    assert "NO REPORT EXPORT PERFORMED" in output


def test_profile_selection_invalid_cas_pair_is_structured_cli_error(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        [
            "reporting",
            "export-profiles",
            "select",
            "english_12",
            "district_gradebook",
            "1",
            SHA_A,
            "--actor-id",
            "teacher_local",
            "--decided-at",
            "2026-09-22T03:00:00+00:00",
            "--expected-selection-revision",
            "1",
            "--workspace",
            str(tmp_path),
        ]
    )

    assert result == 1
    error = capsys.readouterr().err
    assert "export_profile.selection_invalid" in error


def test_export_commit_without_confirmation_never_commits(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = SimpleNamespace(preview_sha256=SHA_C)
    built = SimpleNamespace(preview=preview, payload=b"Student ID,Grade\n1001,90\n")
    rendered: list[dict[str, object] | None] = []

    monkeypatch.setattr(export_cli, "build_export_preview", lambda *args: built)
    monkeypatch.setattr(
        export_cli,
        "_render_export_preview",
        lambda built, output_format, *, commit_context: rendered.append(
            commit_context
        ),
    )

    def forbidden_commit(*args: object, **kwargs: object) -> object:
        raise AssertionError("unconfirmed export called commit_report_export")

    monkeypatch.setattr(export_cli, "commit_report_export", forbidden_commit)

    result = main(
        [
            "reporting",
            "exports",
            "commit",
            "english_12",
            "snapshot_001",
            SHA_A,
            "district_gradebook",
            "1",
            SHA_B,
            "--approved-preview-sha256",
            SHA_C,
            "--export-id",
            "export_001",
            "--actor-id",
            "teacher_local",
            "--exported-at",
            "2026-09-22T03:05:00+00:00",
            "--copyable-text",
            "--workspace",
            str(tmp_path),
        ]
    )

    assert result == 0
    assert rendered == [
        {
            "confirmed": False,
            "export_id": "export_001",
            "destination_kind": "copyable_text",
            "receipt_write": "not_performed",
        }
    ]


def test_export_commit_rejects_unapproved_rebuilt_preview(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    built = SimpleNamespace(
        preview=SimpleNamespace(preview_sha256=SHA_C),
        payload=b"Student ID,Grade\n1001,90\n",
    )
    monkeypatch.setattr(export_cli, "build_export_preview", lambda *args: built)

    result = main(
        [
            "reporting",
            "exports",
            "commit",
            "english_12",
            "snapshot_001",
            SHA_A,
            "district_gradebook",
            "1",
            SHA_B,
            "--approved-preview-sha256",
            "d" * 64,
            "--export-id",
            "export_001",
            "--actor-id",
            "teacher_local",
            "--exported-at",
            "2026-09-22T03:05:00+00:00",
            "--copyable-text",
            "--confirm-export",
            "--workspace",
            str(tmp_path),
        ]
    )

    assert result == 1
    assert "report_export.preview_mismatch" in capsys.readouterr().err
