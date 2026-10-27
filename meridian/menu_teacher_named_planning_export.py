"""Deliberate name-based Core Planning Signal export (#123 Slice 10G).

Discovery is read-only. Core/receipt and optional CSV writes remain entirely in
#40/#41 canonical exporters. Exact saved preview, current selected review and
live authorization are all revalidated; no Concord state is created.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias
from uuid import uuid4

from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.menu_teacher_named_explain_preview_review import (
    PlanningPreviewChoiceCatalog,
    PlanningPreviewSummary,
)
from meridian.menu_teacher_named_grades import _current_choice, _ScopeChanged
from meridian.menu_teacher_named_planning_diagnostics import (
    _checked_projection,
    _DiagnosticsChanged,
)
from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    read_choice,
    write_lines,
)
from meridian.planning_signal_core_export_commit_workflow import (
    PlanningSignalCoreExportCommitResult,
)
from meridian.planning_signal_export_commit_workflow import (
    PlanningSignalExportCommitResult,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.planning_signal_core_export_preview_workflow import (
        PlanningSignalCoreExportPreview,
    )

ExportPreviewer: TypeAlias = Callable[
    [Path, str, str, str, str, str, datetime], "PlanningSignalCoreExportPreview"
]
ExportCommitter: TypeAlias = Callable[
    [Path, "PlanningSignalCoreExportPreview", Path | None],
    PlanningSignalCoreExportCommitResult | PlanningSignalExportCommitResult,
]
Clock: TypeAlias = Callable[[], datetime]
SignalIdFactory: TypeAlias = Callable[[], str]


class _ExportChanged(RuntimeError):
    """Exact export authorization, source or committed result does not match."""


def _new_signal_set_id() -> str:
    """Private opaque identifier, never teacher-entered or used as a label."""
    return "meridian_signal_" + uuid4().hex


def _checked_prepared(
    plan: PlanningSignalCoreExportPreview,
    summary: PlanningPreviewSummary,
    class_id: str,
    signal_set_id: str,
    created_at: datetime,
) -> tuple[int, int]:
    """Bind Core candidate to the exact selected, current accepted review."""
    projection = plan.projection
    _checked_projection(projection, summary, class_id)
    signal = plan.signal_set
    eligibility = plan.eligibility
    selected = projection.review_status
    coverage = projection.coverage
    source = signal.source
    if (
        selected.decision != "accepted_for_export"
        or selected.applicability is None
        or selected.applicability.status != "current"
        or projection.live_currentness.state != "current"
        or selected.selected_review_reference is None
        or summary.selected_review_revision is None
        or summary.selected_review_sha256 is None
        or eligibility.preview_reference != projection.preview_reference
        or eligibility.derivation_reference != projection.derivation_reference
        or eligibility.review_reference != selected.selected_review_reference
        or eligibility.review_reference.review_revision
        != summary.selected_review_revision
        or eligibility.review_reference.review_sha256 != summary.selected_review_sha256
        or eligibility.currentness.state != "current"
        or eligibility.currentness.current_derivation_reference
        != projection.derivation_reference
        or signal.class_id != class_id
        or signal.signal_set_id != signal_set_id
        or signal.created_at != created_at
        or source.kind != "module_generated"
        or source.module_id != "meridian"
        or source.snapshot_id != summary.derivation_id
        or source.snapshot_digest != summary.derivation_sha256
        or not plan.final_core_revalidation_required
        or len(plan.contributing_student_ids) != coverage.contributing_student_count
        or len(plan.noncontributing_student_ids)
        != coverage.noncontributing_student_count
        or coverage.contributing_student_count < 1
        or len(signal.dimensions) != 1
        or signal.dimensions[0].dimension_id != summary.dimension_id
        or signal.dimensions[0].band_count != summary.band_count
    ):
        raise _ExportChanged("Core export candidate is not this accepted review.")
    return coverage.contributing_student_count, coverage.noncontributing_student_count


def _checked_result(
    result: PlanningSignalCoreExportCommitResult | PlanningSignalExportCommitResult,
    plan: PlanningSignalCoreExportPreview,
    csv_destination: Path | None,
) -> tuple[PlanningSignalCoreExportCommitResult, str | None]:
    """Report success only when canonical Core/receipt/CSV receipts agree."""
    if isinstance(result, PlanningSignalExportCommitResult):
        core = result.core
        csv = result.csv
    elif isinstance(result, PlanningSignalCoreExportCommitResult):
        core = result
        csv = None
    else:
        raise _ExportChanged("Unexpected Core export result type.")
    if (
        core.preview != plan
        or core.core_write_disposition not in {"created", "existing"}
        or core.receipt_write_disposition not in {"created", "existing"}
        or not isinstance(core.core_signal_digest, str)
        or len(core.core_signal_digest) != 64
        or not isinstance(core.receipt_sha256, str)
        or len(core.receipt_sha256) != 64
        or core.core_export_action != "performed"
        or core.export_receipt_action != "performed"
        or core.review_write_action != "not_performed"
        or core.review_selection_action != "not_performed"
        or core.csv_export_action != "not_performed"
        or core.concord_action != "not_performed"
    ):
        raise _ExportChanged("Core export result did not verify this candidate.")
    if csv_destination is None:
        if csv is not None:
            raise _ExportChanged("Unexpected local CSV export result.")
        return core, None
    if (
        csv is None
        or csv.class_id != plan.signal_set.class_id
        or csv.signal_set_id != plan.signal_set.signal_set_id
        or csv.destination != csv_destination
        or csv.disposition not in {"created", "existing"}
    ):
        raise _ExportChanged("Local CSV result did not verify this Core signal.")
    return core, csv.disposition


def run_named_planning_core_export(
    *,
    navigation: TeacherNavigationContext,
    export_previewer: ExportPreviewer,
    export_committer: ExportCommitter,
    clock: Clock,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    preview_catalog: PlanningPreviewChoiceCatalog | None = None,
    id_factory: SignalIdFactory = _new_signal_set_id,
) -> None:
    """Review an accepted selected preview and explicitly EXPORT to Core."""
    attempted = False
    signal_set_id: str | None = None
    created_at: datetime | None = None
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        catalog = preview_catalog or PlanningPreviewChoiceCatalog(navigation)
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
            raise _ExportChanged("Verified class changed before export selection.")
        chosen = select_teacher_choice(
            catalog=catalog,
            scope="planning_preview_review",
            selected={"class": class_id},
            title="Saved Planning Previews",
            question="Which accepted and selected Planning Preview should be exported?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen is None:
            return
        if len(chosen.identity) != 1:
            raise _ExportChanged("Saved preview choice identity changed.")

        def check_scope() -> PlanningPreviewSummary:
            if navigation.current_class() != verified:
                raise _ExportChanged("Verified class changed.")
            _current_choice(
                catalog,
                scope="planning_preview_review",
                selected={"class": class_id},
                choice=chosen,
            )
            current = catalog.inspect(root, class_id, chosen.identity[0])
            if (
                current.school_year != verified.school_year
                or current.choice() != chosen
            ):
                raise _ExportChanged("Saved preview or selected review changed.")
            return current

        summary = check_scope()
        if summary.selected_review_revision is None:
            write_lines(
                output,
                "No Planning Review is selected for this saved preview.",
                "Select an accepted review by name before exporting.",
                "No Core signal, receipt, or CSV was written.",
            )
            pause_for_user(input_fn)
            return
        clear_fn()
        print_menu_header(output, "Choose Planning Signal Output")
        write_lines(
            output,
            f"Policy: {summary.title}",
            f"Marking period: {summary.period_label} ({summary.school_year})",
            f"Standard: {summary.standard_id}",
            "1. Core grouping signal and Meridian receipt",
            "2. Core grouping signal, Meridian receipt, and local CSV",
            "B. Cancel | M. Main Menu | Q. Quit",
        )
        destination_choice = read_choice(input_fn, "Output: ")
        command = parse_navigation_choice(destination_choice)
        if command is NavigationChoice.BACK or not destination_choice:
            return
        if destination_choice not in {"1", "2"}:
            write_lines(output, "Invalid output choice. No export was requested.")
            pause_for_user(input_fn)
            return
        csv_destination: Path | None = None
        if destination_choice == "2":
            destination_text = read_choice(input_fn, "Local CSV destination: ")
            command = parse_navigation_choice(destination_text)
            if command is NavigationChoice.BACK or not destination_text:
                return
            if (
                len(destination_text) > 2048
                or "\x00" in destination_text
                or Path(destination_text).suffix.casefold() != ".csv"
            ):
                write_lines(output, "Choose a local .csv file destination.")
                pause_for_user(input_fn)
                return
            csv_destination = Path(os.path.abspath(destination_text))
        if check_scope() != summary:
            raise _ExportChanged("Selected review changed before export preview.")
        signal_set_id = id_factory()
        if (
            not isinstance(signal_set_id, str)
            or not signal_set_id.startswith("meridian_signal_")
            or len(signal_set_id) != len("meridian_signal_") + 32
            or any(
                char not in "0123456789abcdef"
                for char in signal_set_id[len("meridian_signal_") :]
            )
        ):
            raise _ExportChanged("Generated Core identity is invalid.")
        created_at = clock()
        if (
            not isinstance(created_at, datetime)
            or created_at.tzinfo is None
            or created_at.utcoffset() is None
        ):
            raise _ExportChanged("Export timestamp is invalid.")
        plan = export_previewer(
            root,
            class_id,
            summary.policy_id,
            summary.preview_id,
            summary.preview_sha256,
            signal_set_id,
            created_at,
        )
        contributing, noncontributing = _checked_prepared(
            plan, summary, class_id, signal_set_id, created_at
        )
        if check_scope() != summary:
            raise _ExportChanged("Review changed during export preview.")
        while True:
            if check_scope() != summary:
                raise _ExportChanged("Selected review changed before confirmation.")
            clear_fn()
            print_menu_header(output, "Review Planning Signal Export")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Marking period: {summary.period_label} ({summary.school_year})",
                f"Standard: {summary.standard_id}",
                "Selected teacher decision: accepted for export",
                f"Contributing students: {contributing}",
                f"Noncontributing students: {noncontributing}",
                "Destination: Core and Meridian receipt"
                if csv_destination is None
                else f"Destination: Core, Meridian receipt and {csv_destination}",
                "",
                "A final live authorization check runs before Core persistence.",
                "A local CSV is separate from Core/receipt persistence.",
                "No Concord groups or academic Grade records are created.",
                "Type EXPORT to commit; B or blank cancels; M or Q navigates.",
                "T. Technical candidate identity and provenance",
            )
            answer = read_choice(input_fn, "Confirmation: ")
            if answer.casefold() == "t":
                if check_scope() != summary:
                    raise _ExportChanged("Selected review changed before details.")
                clear_fn()
                print_menu_header(output, "Core Export — Technical Candidate")
                write_lines(
                    output,
                    f"class_id: {class_id}",
                    f"signal_set_id: {signal_set_id}",
                    f"created_at: {created_at.isoformat()}",
                    f"policy_id: {summary.policy_id}",
                    f"preview_id: {summary.preview_id}",
                    f"preview_sha256: {summary.preview_sha256}",
                    f"derivation_id: {summary.derivation_id}",
                    f"derivation_sha256: {summary.derivation_sha256}",
                    "selected_review_revision: "
                    + str(summary.selected_review_revision),
                    "selected_review_sha256: " + str(summary.selected_review_sha256),
                )
                pause_for_user(input_fn)
                continue
            command = parse_navigation_choice(answer)
            if command is NavigationChoice.BACK or not answer:
                write_lines(output, "No Core signal, receipt, or CSV was written.")
                return
            if answer != "EXPORT":
                write_lines(output, "No export was requested.")
                pause_for_user(input_fn)
                return
            if check_scope() != summary:
                raise _ExportChanged("Selected review changed before Core export.")
            attempted = True
            committed = export_committer(root, plan, csv_destination)
            core, csv_disposition = _checked_result(committed, plan, csv_destination)
            clear_fn()
            print_menu_header(output, "Planning Signal Export Completed")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Marking period: {summary.period_label}",
                f"Core write: {core.core_write_disposition}",
                f"Meridian receipt: {core.receipt_write_disposition}",
                "Local CSV: not requested"
                if csv_disposition is None
                else f"Local CSV: {csv_disposition}",
                "",
                "Export is local/Core provenance, not a Concord cluster.",
                "No SIS or external system import is claimed.",
            )
            pause_for_user(input_fn)
            return
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_ExportChanged, _DiagnosticsChanged, _ScopeChanged):
        write_lines(
            output,
            "Class, selected Planning Review, or export authorization changed.",
            "Core/receipt/CSV may be partially written; inspect saved exports."
            if attempted
            else "No export requested; refresh named choices.",
        )
        if attempted and signal_set_id is not None and created_at is not None:
            write_lines(
                output,
                f"Recovery identity: {signal_set_id}",
                f"Original export timestamp: {created_at.isoformat()}",
            )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Planning Signal export could not be completed or verified safely.",
            "Core/receipt may be durable even if CSV failed; inspect saved exports "
            "before retrying the exact request."
            if attempted
            else "No export requested; select an accepted, current review.",
        )
        if attempted and signal_set_id is not None and created_at is not None:
            write_lines(
                output,
                f"Recovery identity: {signal_set_id}",
                f"Original export timestamp: {created_at.isoformat()}",
            )
        pause_for_user(input_fn)


__all__ = ("run_named_planning_core_export",)
