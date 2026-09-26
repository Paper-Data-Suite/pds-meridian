from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import cast

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.export_profile import ExportProfileReference
from meridian.menu_export import (
    ExportCommitResult,
    ExportMenuDependencies,
    ExportPreviewPresentation,
    ExportProfileListItem,
    ExportProfilePresentation,
    ExportProfileSelectionPlan,
    ExportProfileWritePlan,
    ExportReceiptPresentation,
    run_export_menu,
)
from meridian.report_export_preview import BuiltExportPreview


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _profile() -> ExportProfilePresentation:
    return ExportProfilePresentation(
        class_id="class_1",
        profile_id="sis",
        title="SIS Grade Export",
        purpose="Local gradebook transfer",
        revision=2,
        profile_sha256="a" * 64,
        columns=(("student_id", "Student ID"), ("effective_grade", "Grade")),
        format="csv",
        include_header=True,
        line_ending="crlf",
        utf8_bom=False,
    )


def _preview() -> ExportPreviewPresentation:
    return ExportPreviewPresentation(
        built=cast(BuiltExportPreview, object()),
        class_id="class_1",
        snapshot_id="snapshot_1",
        snapshot_sha256="b" * 64,
        profile_id="sis",
        profile_revision=2,
        profile_sha256="a" * 64,
        format="csv",
        row_count=2,
        payload_byte_length=42,
        payload_sha256="c" * 64,
        preview_sha256="d" * 64,
        diagnostic_lines=(),
        payload_text="Student ID,Grade\n1001,91\n1002,87\n",
    )


def _deps(log: list[str] | None = None) -> ExportMenuDependencies:
    events = [] if log is None else log
    return ExportMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        clock=lambda: datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
        profile_lister=lambda *_args: (
            ExportProfileListItem("sis", "SIS Grade Export", 2, 2),
        ),
        profile_loader=lambda *_args: _profile(),
        profile_write_previewer=lambda *_args: ExportProfileWritePlan(
            profile=cast(object, object()),  # type: ignore[arg-type]
            presentation=_profile(),
        ),
        profile_writer=lambda *_args: events.append("write") or "created",
        profile_selection_previewer=lambda *_args: ExportProfileSelectionPlan(
            target=ExportProfileReference("class_1", "sis", 2, "a" * 64),
            title="SIS Grade Export",
            expected_current=None,
        ),
        profile_selector=lambda *_args: events.append("select") or "created",
        preview_builder=lambda *_args: _preview(),
        export_committer=lambda *_args: ExportCommitResult(
            export_id="export_1",
            receipt_sha256="e" * 64,
            artifact_disposition="copyable",
            destination_kind="copyable_text",
            destination_name=None,
            copyable_text="Student ID,Grade\n1001,91\n1002,87\n",
        ),
        receipt_lister=lambda *_args: ("export_1",),
        receipt_loader=lambda *_args: ExportReceiptPresentation(
            export_id="export_1",
            receipt_sha256="e" * 64,
            snapshot_id="snapshot_1",
            profile_id="sis",
            profile_revision=2,
            row_count=2,
            payload_sha256="c" * 64,
            destination_kind="copyable_text",
            destination_name=None,
            actor_id="teacher_1",
            exported_at="2026-09-23T20:00:00+00:00",
        ),
    )


def test_profile_listing_is_teacher_first() -> None:
    output = StringIO()
    run_export_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput("1", "class_1", "", "b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "SIS Grade Export" in rendered
    assert "current r2" in rendered
    assert "aaaaaaaa" not in rendered


def test_profile_write_requires_exact_write_confirmation() -> None:
    log: list[str] = []
    output = StringIO()
    run_export_menu(
        dependencies=_deps(log),
        input_fn=ScriptedInput(
            "3",
            "class_1",
            "sis",
            "SIS Grade Export",
            "Local gradebook transfer",
            "student_id=Student ID;effective_grade=Grade",
            "csv",
            "yes",
            "crlf",
            "no",
            "teacher_1",
            "",
            "no",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == []
    assert "No Export Profile revision was written." in output.getvalue()


def test_profile_selection_requires_select_confirmation() -> None:
    log: list[str] = []
    run_export_menu(
        dependencies=_deps(log),
        input_fn=ScriptedInput(
            "4",
            "class_1",
            "sis",
            "teacher_1",
            "",
            "SELECT",
            "",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == ["select"]


def test_export_preview_does_not_claim_external_write() -> None:
    output = StringIO()
    run_export_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput(
            "5",
            "class_1",
            "sis",
            "snapshot_1",
            "b" * 64,
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Outgoing payload:" in rendered
    assert "No external-system write has occurred." in rendered
    assert "Student ID,Grade" in rendered


def test_copyable_export_requires_export_confirmation_and_scopes_receipt() -> None:
    output = StringIO()
    run_export_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput(
            "5",
            "class_1",
            "sis",
            "snapshot_1",
            "b" * 64,
            "2",
            "export_1",
            "teacher_1",
            "",
            "EXPORT",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Artifact: copyable" in rendered
    assert "Copyable text:" in rendered
    assert "No external-system import or acceptance is claimed." in rendered


def test_receipt_does_not_claim_external_acknowledgement() -> None:
    output = StringIO()
    run_export_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput(
            "6",
            "class_1",
            "export_1",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "ExportReceipt" in rendered
    assert "local export provenance only" in rendered
    assert "does not prove external-system acknowledgement" in rendered


@pytest.mark.parametrize(
    ("choice", "error"),
    [("m", ReturnToMainMenu), ("q", QuitPDS)],
)
def test_export_menu_preserves_shared_navigation(
    choice: str,
    error: type[BaseException],
) -> None:
    with pytest.raises(error):
        run_export_menu(
            dependencies=_deps(),
            input_fn=ScriptedInput(choice),
            output=StringIO(),
            clear_fn=lambda: None,
        )
