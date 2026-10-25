"""Read-only, named discovery of immutable local ExportReceipts (#123 Slice 8C).

The receipt ID and digest stay in transient choice authority, not teacher prompts.
Every displayed receipt is reloaded and checked after the choice is refreshed.
This module never replays a payload, creates an artifact, or claims SIS import.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    write_lines,
)
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
    load_teacher_choices,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_export import ExportReceiptPresentation

ReceiptLister: TypeAlias = Callable[[Path, str], tuple[str, ...]]
ReceiptLoader: TypeAlias = Callable[[Path, str, str], "ExportReceiptPresentation"]
_MAX_RECEIPTS = 200
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class _ReceiptChanged(RuntimeError):
    """A chosen receipt or its verified class is no longer current."""


def _verified_receipt(
    loader: ReceiptLoader, root: Path, class_id: str, export_id: str
) -> "ExportReceiptPresentation":
    receipt = loader(root, class_id, export_id)
    if (
        receipt.export_id != export_id
        or not _SHA256.fullmatch(receipt.receipt_sha256)
        or not _SHA256.fullmatch(receipt.payload_sha256)
        or not receipt.snapshot_id
        or not receipt.profile_id
        or type(receipt.profile_revision) is not int
        or receipt.profile_revision < 1
        or type(receipt.row_count) is not int
        or receipt.row_count < 0
        or receipt.destination_kind not in {"file", "copyable_text"}
        or (receipt.destination_kind == "file")
        != (receipt.destination_name is not None)
    ):
        raise _ReceiptChanged("Receipt metadata changed or is inconsistent.")
    exported = datetime.fromisoformat(receipt.exported_at)
    if exported.utcoffset() is None:
        raise _ReceiptChanged("Receipt timestamp is not timezone-aware.")
    return receipt


def _label(receipt: "ExportReceiptPresentation") -> str:
    if receipt.destination_kind == "file":
        return f"Local file — {receipt.destination_name}"
    return "Copyable report text"


@dataclass(slots=True)
class NamedExportReceiptCatalog:
    """Bounded, per-class catalog; labels never confer immutable identity."""

    navigation: TeacherNavigationContext
    lister: ReceiptLister
    loader: ReceiptLoader

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "export_receipt":
            raise TeacherChoiceUnavailable("Unsupported ExportReceipt choice scope.")
        verified = self.navigation.current_class()
        if verified is None or selected.get("class") != verified.class_id:
            raise TeacherChoiceUnavailable("Choose a verified class first.")
        try:
            ids = self.lister(verified.workspace, verified.class_id)
            if len(ids) > _MAX_RECEIPTS or len(ids) != len(set(ids)):
                raise TeacherChoiceUnavailable("Receipt inventory cannot be verified.")
            receipts = tuple(
                _verified_receipt(
                    self.loader, verified.workspace, verified.class_id, export_id
                )
                for export_id in ids
            )
            return tuple(
                TeacherChoice(
                    identity=(receipt.export_id,),
                    label=_label(receipt),
                    detail=(
                        f"Exported {receipt.exported_at} · "
                        f"{receipt.row_count} rows · profile version "
                        f"{receipt.profile_revision}"
                    ),
                    status="Local receipt — not proof of external import",
                    witness=receipt.receipt_sha256,
                )
                for receipt in receipts
            )
        except TeacherChoiceUnavailable:
            raise
        except Exception as error:
            raise TeacherChoiceUnavailable(
                "Local ExportReceipt records could not be verified."
            ) from error


def _revalidate(
    *,
    navigation: TeacherNavigationContext,
    root: Path,
    class_id: str,
    school_year: str,
    catalog: NamedExportReceiptCatalog,
    choice: TeacherChoice,
) -> "ExportReceiptPresentation":
    current = navigation.current_class()
    if (
        current is None
        or current.workspace != root
        or current.class_id != class_id
        or current.school_year != school_year
        or choice
        not in load_teacher_choices(
            catalog, scope="export_receipt", selected={"class": class_id}
        )
    ):
        raise _ReceiptChanged("Class or receipt choice changed.")
    return _verified_receipt(catalog.loader, root, class_id, choice.identity[0])


def run_named_export_receipt_browse(
    *,
    navigation: TeacherNavigationContext,
    receipt_lister: ReceiptLister,
    receipt_loader: ReceiptLoader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    receipt_catalog: NamedExportReceiptCatalog | None = None,
) -> None:
    """Inspect an existing local receipt by recognizable metadata; no writes."""
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        receipts = receipt_catalog or NamedExportReceiptCatalog(
            navigation=navigation, lister=receipt_lister, loader=receipt_loader
        )
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
            raise _ReceiptChanged("Verified class changed.")
        year = verified.school_year
        choice = select_teacher_choice(
            catalog=receipts,
            scope="export_receipt",
            selected={"class": class_id},
            title="Past Local Exports",
            question="Which saved local export would you like to inspect?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if choice is None:
            return
        first = _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            school_year=year,
            catalog=receipts,
            choice=choice,
        )
        second = _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            school_year=year,
            catalog=receipts,
            choice=choice,
        )
        if second != first or first.receipt_sha256 != choice.witness:
            raise _ReceiptChanged("Receipt details changed during review.")
        clear_fn()
        print_menu_header(output, "Saved Local Export Receipt")
        write_lines(
            output,
            f"Exported: {first.exported_at}",
            f"Destination: {_label(first)}",
            f"Rows: {first.row_count}",
            f"Profile version: {first.profile_revision}",
            f"Recorded teacher: {first.actor_id}",
            "",
            "This receipt verifies a local Meridian export only.",
            "It does not establish that the exported file still exists.",
            "It does not prove a district/SIS accepted or imported any Grades.",
            "Read-only: no file, receipt, or selection was changed.",
            "Advanced contains exact record identities and provenance.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _ReceiptChanged:
        write_lines(
            output,
            "Class or local export receipt changed during review.",
            "Nothing changed. Refresh the list before inspecting again.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Local ExportReceipt records could not be verified safely.",
            "Nothing changed. Use Advanced for technical diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = (
    "NamedExportReceiptCatalog",
    "ReceiptLister",
    "ReceiptLoader",
    "run_named_export_receipt_browse",
)
