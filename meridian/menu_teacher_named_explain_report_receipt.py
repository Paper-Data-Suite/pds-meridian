"""Named, read-only explanation of an exact local report ExportReceipt (#123 9H).

Only immutable receipts, frozen ReportingSnapshots, exact Export Profile revisions,
and Core's exact historical calendar provide display metadata. A teacher choice is
never an export, selection, proof of file existence, or proof of SIS acceptance.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.academic_period_queries import get_academic_period
from pds_core.academic_period_storage import load_academic_period_calendar_revision
from pds_core.academic_periods import AcademicPeriod, AcademicPeriodCalendar
from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.export_profile_storage import (
    StoredExportProfileRevision,
    load_export_profile_revision,
)
from meridian.menu_teacher_named_grades import _current_choice, _ScopeChanged
from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.report_export_receipt import (
    StoredExportReceipt,
    list_export_receipt_ids,
    load_export_receipt,
)
from meridian.reporting_snapshot_storage import (
    StoredReportingSnapshot,
    load_reporting_snapshot,
)
from meridian.teacher_navigation_choices import TeacherChoice, TeacherChoiceUnavailable
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_explain import ExplanationPresentation

ReportReceiptExplainer: TypeAlias = Callable[
    [Path, str, str], "ExplanationPresentation"
]
_MAX_RECEIPTS = 200


class _ReportReceiptChanged(RuntimeError):
    """Verified receipt, source or class identity changed during explanation."""


@dataclass(frozen=True, slots=True)
class ReportReceiptSummary:
    """Teacher label, school-year scope, and exact historical provenance."""

    export_id: str
    receipt_sha256: str
    snapshot_id: str
    snapshot_sha256: str
    profile_id: str
    profile_revision: int
    profile_sha256: str
    profile_title: str
    school_year: str
    period_label: str
    exported_at: str
    row_count: int
    destination_kind: str
    destination_name: str | None
    actor_id: str
    preview_sha256: str
    payload_sha256: str
    payload_byte_length: int

    def choice(self) -> TeacherChoice:
        """Bounded exact-state fingerprint, never concatenated SHA-256 strings."""
        destination = (
            f"Local file {self.destination_name}"
            if self.destination_kind == "file"
            else "Copyable report text"
        )
        detail = (
            f"{self.period_label} ({self.school_year}) · "
            f"{destination} · {self.row_count} rows"
        )
        if len(detail) > 240:
            detail = detail[:239] + "…"
        original = (
            self.export_id,
            self.receipt_sha256,
            self.snapshot_id,
            self.snapshot_sha256,
            self.profile_id,
            self.profile_revision,
            self.profile_sha256,
            self.preview_sha256,
            self.payload_sha256,
            self.payload_byte_length,
        )
        witness = (
            "sha256:"
            + hashlib.sha256(
                b"pds.meridian.report-receipt-choice.v1\0"
                + json.dumps(original, ensure_ascii=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
        )
        return TeacherChoice(
            identity=(self.export_id,),
            label=self.profile_title,
            detail=detail,
            status=f"Local export · {self.exported_at}",
            witness=witness,
        )


@dataclass(frozen=True, slots=True)
class ReportReceiptReaders:
    """Public read adapters only; no report generation or write operations."""

    lister: Callable[[Path, str], tuple[str, ...]] = list_export_receipt_ids
    receipt_loader: Callable[[Path, str, str], StoredExportReceipt] = (
        load_export_receipt
    )
    snapshot_loader: Callable[[Path, str, str], StoredReportingSnapshot] = (
        load_reporting_snapshot
    )
    profile_loader: Callable[[Path, str, str, int], StoredExportProfileRevision] = (
        load_export_profile_revision
    )
    calendar_loader: Callable[[Path, str, int], AcademicPeriodCalendar] = (
        load_academic_period_calendar_revision
    )
    period_lookup: Callable[[AcademicPeriodCalendar, str], AcademicPeriod] = (
        get_academic_period
    )


@dataclass(slots=True)
class ReportReceiptChoiceCatalog:
    """Choose only bounded, verified, class/year-matching historical receipts."""

    navigation: TeacherNavigationContext
    readers: ReportReceiptReaders = field(default_factory=ReportReceiptReaders)

    def inspect(
        self, root: Path, class_id: str, export_id: str
    ) -> ReportReceiptSummary:
        stored = self.readers.receipt_loader(root, class_id, export_id)
        receipt = stored.receipt
        if (
            receipt.class_id != class_id
            or receipt.export_id != export_id
            or stored.reference.class_id != class_id
            or stored.reference.export_id != export_id
            or stored.reference.receipt_sha256 != stored.receipt_sha256
        ):
            raise TeacherChoiceUnavailable("Local receipt identity changed.")
        snapshot = self.readers.snapshot_loader(
            root, class_id, receipt.snapshot_reference.snapshot_id
        )
        profile = self.readers.profile_loader(
            root,
            class_id,
            receipt.profile_reference.profile_id,
            receipt.profile_reference.profile_revision,
        )
        if (
            snapshot.reference != receipt.snapshot_reference
            or profile.reference != receipt.profile_reference
        ):
            raise TeacherChoiceUnavailable("Receipt source digest/identity changed.")
        period_ref = snapshot.snapshot.target_period
        calendar = self.readers.calendar_loader(
            root, period_ref.school_year, snapshot.snapshot.calendar_revision
        )
        period = self.readers.period_lookup(calendar, period_ref.period_id)
        if (
            snapshot.snapshot.class_id != class_id
            or profile.profile.class_id != class_id
            or period.period_id != period_ref.period_id
        ):
            raise TeacherChoiceUnavailable("Receipt reporting scope changed.")
        return ReportReceiptSummary(
            export_id=export_id,
            receipt_sha256=stored.receipt_sha256,
            snapshot_id=receipt.snapshot_reference.snapshot_id,
            snapshot_sha256=receipt.snapshot_reference.snapshot_sha256,
            profile_id=receipt.profile_reference.profile_id,
            profile_revision=receipt.profile_reference.profile_revision,
            profile_sha256=receipt.profile_reference.profile_sha256,
            profile_title=profile.profile.title,
            school_year=period_ref.school_year,
            period_label=period.label,
            exported_at=receipt.exported_at.isoformat(),
            row_count=receipt.row_count,
            destination_kind=receipt.destination.kind,
            destination_name=receipt.destination.basename,
            actor_id=receipt.actor.actor_id,
            preview_sha256=receipt.preview_sha256,
            payload_sha256=receipt.payload_sha256,
            payload_byte_length=receipt.payload_byte_length,
        )

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "report_export_receipt":
            raise TeacherChoiceUnavailable("Unsupported report-receipt scope.")
        current = self.navigation.current_class()
        if current is None or selected.get("class") != current.class_id:
            raise TeacherChoiceUnavailable("Choose a verified class first.")
        try:
            ids = self.readers.lister(current.workspace, current.class_id)
            if len(ids) > _MAX_RECEIPTS or len(ids) != len(set(ids)):
                raise TeacherChoiceUnavailable(
                    "Receipt inventory exceeds verified bound. Use Advanced."
                )
            choices: list[TeacherChoice] = []
            for export_id in ids:
                summary = self.inspect(current.workspace, current.class_id, export_id)
                if summary.school_year == current.school_year:
                    choices.append(summary.choice())
            return tuple(choices)
        except TeacherChoiceUnavailable:
            raise
        except Exception as error:
            raise TeacherChoiceUnavailable(
                "Saved local export receipts could not be verified."
            ) from error


def _checked_ordinary_lines(
    value: ExplanationPresentation, summary: ReportReceiptSummary, class_id: str
) -> tuple[str, ...]:
    """Prove every existing explanation claim matches the chosen exact receipt."""
    lines, technical = value.lines, value.technical_lines
    expected_lines = (
        f"Export: {summary.export_id}",
        f"Snapshot: {summary.snapshot_id}",
        f"Export Profile: {summary.profile_id} r{summary.profile_revision}",
        f"Rows: {summary.row_count}",
        f"Destination kind: {summary.destination_kind.replace('_', ' ')}",
        f"Destination file: {summary.destination_name or 'none'}",
        f"Teacher: {summary.actor_id}",
        "Scope: local Meridian export provenance; external acceptance is not claimed.",
    )
    expected_technical = (
        f"class_id: {class_id}",
        f"receipt_sha256: {summary.receipt_sha256}",
        f"preview_sha256: {summary.preview_sha256}",
        f"payload_sha256: {summary.payload_sha256}",
        f"payload_byte_length: {summary.payload_byte_length}",
        f"snapshot_sha256: {summary.snapshot_sha256}",
        f"profile_sha256: {summary.profile_sha256}",
    )
    if (
        value.title != "ExportReceipt Provenance"
        or not isinstance(lines, tuple)
        or not isinstance(technical, tuple)
        or any(not isinstance(v, str) for v in (*lines, *technical))
        or lines != expected_lines
        or any(technical.count(item) != 1 for item in expected_technical)
    ):
        raise _ReportReceiptChanged("Report receipt explanation is outside selection.")
    return (lines[3], lines[4], lines[5], lines[6], lines[7])


def run_named_report_receipt_explanation(
    *,
    navigation: TeacherNavigationContext,
    report_receipt_explainer: ReportReceiptExplainer,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    receipt_catalog: ReportReceiptChoiceCatalog | None = None,
) -> None:
    """Explain a saved local report export by name, without writing records."""
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        catalog = receipt_catalog or ReportReceiptChoiceCatalog(navigation)
        active = _class(
            navigation, classes, input_fn=input_fn, output=output, clear_fn=clear_fn
        )
        if active is None:
            return
        root, class_id = active
        verified = navigation.current_class()
        if (
            verified is None
            or verified.workspace != root
            or verified.class_id != class_id
        ):
            raise _ReportReceiptChanged("Verified class changed.")
        selected = select_teacher_choice(
            catalog=catalog,
            scope="report_export_receipt",
            selected={"class": class_id},
            title="Saved Local Report Exports",
            question="Which local report ExportReceipt should be explained?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if selected is None:
            return

        def check_scope() -> ReportReceiptSummary:
            if navigation.current_class() != verified:
                raise _ReportReceiptChanged("Verified class changed during review.")
            _current_choice(
                catalog,
                scope="report_export_receipt",
                selected={"class": class_id},
                choice=selected,
            )
            summary = catalog.inspect(root, class_id, selected.identity[0])
            if (
                summary.school_year != verified.school_year
                or summary.choice() != selected
            ):
                raise _ReportReceiptChanged("Saved local receipt witness changed.")
            return summary

        summary = check_scope()
        value = report_receipt_explainer(root, class_id, summary.export_id)
        ordinary = _checked_ordinary_lines(value, summary, class_id)
        if check_scope() != summary:
            raise _ReportReceiptChanged("Receipt changed during explanation read.")
        while True:
            if check_scope() != summary:
                raise _ReportReceiptChanged("Receipt changed during display.")
            clear_fn()
            print_menu_header(output, "Local Report ExportReceipt Explanation")
            write_lines(
                output,
                f"Export Profile: {summary.profile_title}",
                f"Academic period: {summary.period_label} ({summary.school_year})",
                f"Exported at: {summary.exported_at}",
                *ordinary,
                "",
                "This receipt is proof of a local export, not SIS/LMS acceptance.",
                "The file may have been moved or deleted after export.",
                "No report, receipt, profile, or academic record was changed.",
                "T. Technical details / provenance",
            )
            print_standard_navigation(output)
            choice = read_choice(input_fn)
            if choice.casefold() == "t":
                if check_scope() != summary:
                    raise _ReportReceiptChanged("Receipt changed before details.")
                clear_fn()
                print_menu_header(output, "Report ExportReceipt — Technical Provenance")
                write_lines(
                    output,
                    f"export_id: {summary.export_id}",
                    f"snapshot_id: {summary.snapshot_id}",
                    f"profile_id: {summary.profile_id}",
                    f"profile_revision: {summary.profile_revision}",
                    *value.technical_lines,
                )
                pause_for_user(input_fn)
                continue
            command = parse_navigation_choice(choice)
            if command is NavigationChoice.BACK or choice == "":
                return
            write_lines(output, "Please choose T, B, M, or Q.")
            pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_ReportReceiptChanged, _ScopeChanged):
        write_lines(
            output,
            "Class or saved ExportReceipt changed during review.",
            "No record was changed. Refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Local ExportReceipt provenance could not be verified safely.",
            "No record was changed. Use Advanced for exact diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = (
    "ReportReceiptChoiceCatalog",
    "ReportReceiptReaders",
    "run_named_report_receipt_explanation",
)
