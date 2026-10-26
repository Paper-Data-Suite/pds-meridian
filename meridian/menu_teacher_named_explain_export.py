"""Name-based, read-only explanation of one exact historical Planning Export.

#123 Slice 9G. Core owns the exported signal; Meridian owns an immutable
receipt. A selected review is NOT consulted when explaining an older export.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.grouping_signal_storage import (
    StoredGroupingSignal,
    list_grouping_signal_ids,
    load_grouping_signal,
)
from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.grouping_signal_export_storage import (
    StoredGroupingSignalExportReceipt,
    load_grouping_signal_export_receipt,
)
from meridian.grouping_signal_preview import GroupingSignalPreviewReference
from meridian.grouping_signal_preview_storage import (
    StoredGroupingSignalPreview,
    load_grouping_signal_preview_reference,
)
from meridian.grouping_signal_review_storage import (
    StoredGroupingSignalReview,
    load_grouping_signal_review_revision,
)
from meridian.menu_teacher_named_explain_derivation import (
    PlanningDerivationChoiceCatalog,
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
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_explain import ExplanationPresentation

PlanningExportExplainer: TypeAlias = Callable[
    [Path, str, str], "ExplanationPresentation"
]
_MAX_EXPORTS = 200


class _ExportChanged(RuntimeError):
    """The verified Core export, receipt, or academic source changed."""


@dataclass(frozen=True, slots=True)
class PlanningExportSummary:
    """Display metadata plus immutable exact receipt/lineage witnesses."""

    signal_set_id: str
    core_signal_digest: str
    receipt_sha256: str
    derivation_id: str
    derivation_sha256: str
    preview_id: str
    preview_sha256: str
    review_revision: int
    review_sha256: str
    title: str
    period_label: str
    school_year: str
    standard_id: str
    dimension_id: str
    band_count: int
    exported_count: int
    omitted_count: int
    review_decision: str
    preview_currentness: str
    created_at: str

    def choice(self) -> TeacherChoice:
        return TeacherChoice(
            identity=(self.signal_set_id,),
            label=self.title,
            detail=(
                f"{self.period_label} ({self.school_year}) · "
                f"Standard {self.standard_id} · "
                f"{self.exported_count} exported, {self.omitted_count} omitted"
            ),
            status=f"Saved Core export · {self.created_at}",
            witness="sha256:"
            + hashlib.sha256(
                b"pds.meridian.planning-export-choice.v1\0"
                + json.dumps(
                    (
                        self.signal_set_id,
                        self.core_signal_digest,
                        self.receipt_sha256,
                        self.derivation_sha256,
                        self.preview_sha256,
                        self.review_revision,
                        self.review_sha256,
                    ),
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class PlanningExportReaders:
    """Public, replaceable storage readers. No export or selection functions."""

    lister: Callable[[Path, str], tuple[str, ...]] = list_grouping_signal_ids
    signal_loader: Callable[[Path, str, str], StoredGroupingSignal] = (
        load_grouping_signal
    )
    receipt_loader: Callable[[Path, str, str], StoredGroupingSignalExportReceipt] = (
        load_grouping_signal_export_receipt
    )
    preview_loader: Callable[
        [Path, GroupingSignalPreviewReference], StoredGroupingSignalPreview
    ] = load_grouping_signal_preview_reference
    review_loader: Callable[[Path, str, str, int], StoredGroupingSignalReview] = (
        load_grouping_signal_review_revision
    )


@dataclass(slots=True)
class PlanningExportChoiceCatalog:
    """Bounded Core signal inventory, restricted to Meridian-receipted exports."""

    navigation: TeacherNavigationContext
    readers: PlanningExportReaders = field(default_factory=PlanningExportReaders)
    derivation_catalog: PlanningDerivationChoiceCatalog | None = None

    def inspect(
        self, root: Path, class_id: str, signal_set_id: str
    ) -> PlanningExportSummary:
        core = self.readers.signal_loader(root, class_id, signal_set_id)
        signal = core.signal
        if (
            signal.class_id != class_id
            or signal.signal_set_id != signal_set_id
            or core.digest_algorithm != "sha256"
            or signal.source.kind != "module_generated"
            or signal.source.module_id != "meridian"
        ):
            raise TeacherChoiceUnavailable("Core signal is not a Meridian export.")
        stored = self.readers.receipt_loader(root, class_id, signal_set_id)
        receipt = stored.receipt
        if (
            receipt.class_id != class_id
            or receipt.signal_set_id != signal_set_id
            or stored.reference.class_id != class_id
            or stored.reference.signal_set_id != signal_set_id
            or stored.reference.receipt_sha256 != stored.receipt_sha256
            or receipt.core_contract != "grouping_signal_set_v1"
            or receipt.core_digest_algorithm != "sha256"
            or receipt.core_signal_digest != core.digest
            or signal.source.snapshot_digest_algorithm != "sha256"
            or signal.source.snapshot_id != receipt.derivation_reference.derivation_id
            or signal.source.snapshot_digest
            != receipt.derivation_reference.derivation_sha256
        ):
            raise TeacherChoiceUnavailable("Export receipt or Core source changed.")
        derived = (
            self.derivation_catalog or PlanningDerivationChoiceCatalog(self.navigation)
        ).inspect(root, class_id, receipt.derivation_reference.derivation_id)
        current = self.navigation.current_class()
        if (
            current is None
            or current.workspace != root
            or current.class_id != class_id
            or (
                derived.derivation_sha256
                != receipt.derivation_reference.derivation_sha256
            )
            or derived.school_year != current.school_year
        ):
            raise TeacherChoiceUnavailable("Saved export's derivation changed.")
        preview = self.readers.preview_loader(root, receipt.preview_reference)
        snapshot = preview.snapshot
        if (
            preview.reference != receipt.preview_reference
            or snapshot.derivation_reference != receipt.derivation_reference
            or snapshot.policy_reference.policy_id != derived.policy_id
            or snapshot.policy_reference.policy_revision != derived.policy_revision
            or snapshot.policy_reference.policy_sha256 != derived.policy_sha256
            or snapshot.dimension_id != derived.dimension_id
            or snapshot.band_count != derived.band_count
        ):
            raise TeacherChoiceUnavailable("Export preview lineage changed.")
        review = self.readers.review_loader(
            root,
            class_id,
            receipt.derivation_reference.derivation_id,
            receipt.review_reference.review_revision,
        )
        if (
            review.reference != receipt.review_reference
            or review.review.derivation_reference != receipt.derivation_reference
            or review.review.preview_reference != receipt.preview_reference
        ):
            raise TeacherChoiceUnavailable("Exact export review changed.")
        exported = len(signal.student_bands)
        cohort = len(snapshot.student_rows)
        if exported > cohort or cohort != derived.student_count:
            raise TeacherChoiceUnavailable("Export cohort counts disagree.")
        return PlanningExportSummary(
            signal_set_id=signal_set_id,
            core_signal_digest=core.digest,
            receipt_sha256=stored.receipt_sha256,
            derivation_id=derived.derivation_id,
            derivation_sha256=derived.derivation_sha256,
            preview_id=receipt.preview_reference.preview_id,
            preview_sha256=receipt.preview_reference.preview_sha256,
            review_revision=receipt.review_reference.review_revision,
            review_sha256=receipt.review_reference.review_sha256,
            title=derived.title,
            period_label=derived.period_label,
            school_year=derived.school_year,
            standard_id=derived.standard_id,
            dimension_id=derived.dimension_id,
            band_count=derived.band_count,
            exported_count=exported,
            omitted_count=cohort - exported,
            review_decision=review.review.decision,
            preview_currentness=snapshot.currentness.state,
            created_at=signal.created_at.isoformat(),
        )

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "planning_export":
            raise TeacherChoiceUnavailable("Unsupported Planning Export scope.")
        current = self.navigation.current_class()
        if current is None or selected.get("class") != current.class_id:
            raise TeacherChoiceUnavailable("Choose a verified class first.")
        try:
            ids = self.readers.lister(current.workspace, current.class_id)
            if len(ids) > _MAX_EXPORTS or len(ids) != len(set(ids)):
                raise TeacherChoiceUnavailable(
                    "Core export collection exceeds safe limits. Use Advanced."
                )
            choices: list[TeacherChoice] = []
            for signal_set_id in ids:
                core = self.readers.signal_loader(
                    current.workspace, current.class_id, signal_set_id
                )
                # Core can store other producers' signals; those are not Meridian
                # exports and must never be assumed to carry Meridian receipts.
                source = core.signal.source
                if source.kind != "module_generated" or source.module_id != "meridian":
                    continue
                item = self.inspect(current.workspace, current.class_id, signal_set_id)
                if item.school_year == current.school_year:
                    choices.append(item.choice())
            return tuple(choices)
        except TeacherChoiceUnavailable:
            raise
        except Exception as error:
            raise TeacherChoiceUnavailable(
                "Saved Planning Exports could not be verified."
            ) from error


def _check_explanation(
    value: ExplanationPresentation,
    summary: PlanningExportSummary,
    class_id: str,
) -> tuple[str, ...]:
    """Bind every displayed historical claim to its exact saved export."""
    lines, technical = value.lines, value.technical_lines
    required = (
        f"Signal set: {summary.signal_set_id}",
        f"Dimension: {summary.dimension_id}",
        f"Bands: {summary.band_count}",
        f"Students exported: {summary.exported_count}",
        f"Students omitted: {summary.omitted_count}",
        f"Review decision: {summary.review_decision.replace('_', ' ')}",
        f"Preview currentness: {summary.preview_currentness.replace('_', ' ')}",
    )
    provenance = (
        f"class_id: {class_id}",
        "core_contract: grouping_signal_set_v1",
        f"core_signal_digest: {summary.core_signal_digest}",
        f"receipt_sha256: {summary.receipt_sha256}",
        f"derivation_id: {summary.derivation_id}",
        f"derivation_sha256: {summary.derivation_sha256}",
        f"preview_id: {summary.preview_id}",
        f"preview_sha256: {summary.preview_sha256}",
        f"review_revision: {summary.review_revision}",
        f"review_sha256: {summary.review_sha256}",
    )
    if (
        value.title != "Planning Export Explanation"
        or not isinstance(lines, tuple)
        or not isinstance(technical, tuple)
        or len(lines) != len(required)
        or any(not isinstance(v, str) for v in (*lines, *technical))
        or tuple(lines) != required
        or any(technical.count(p) != 1 for p in provenance)
    ):
        raise _ExportChanged("Export explanation no longer matches exact receipt.")
    return lines[3:]


def run_named_planning_export_explanation(
    *,
    navigation: TeacherNavigationContext,
    planning_export_explainer: PlanningExportExplainer,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    export_catalog: PlanningExportChoiceCatalog | None = None,
) -> None:
    """Explain an exact exported Core signal by name without canonical-ID entry."""
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        catalog = export_catalog or PlanningExportChoiceCatalog(navigation)
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
            raise _ExportChanged("Verified class changed.")
        selected = select_teacher_choice(
            catalog=catalog,
            scope="planning_export",
            selected={"class": class_id},
            title="Saved Planning Exports",
            question="Which exported Planning Signal should be explained?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if selected is None:
            return

        def check_scope() -> PlanningExportSummary:
            if navigation.current_class() != verified:
                raise _ExportChanged("Class changed during explanation.")
            _current_choice(
                catalog,
                scope="planning_export",
                selected={"class": class_id},
                choice=selected,
            )
            current = catalog.inspect(root, class_id, selected.identity[0])
            if (
                current.school_year != verified.school_year
                or current.choice() != selected
            ):
                raise _ExportChanged("Immutable export witness changed.")
            return current

        summary = check_scope()
        value = planning_export_explainer(root, class_id, summary.signal_set_id)
        ordinary = _check_explanation(value, summary, class_id)
        if check_scope() != summary:
            raise _ExportChanged("Export changed during provenance read.")
        while True:
            if check_scope() != summary:
                raise _ExportChanged("Export changed during display.")
            clear_fn()
            print_menu_header(output, "Saved Planning Export Explanation")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Academic period: {summary.period_label}",
                f"Standard: {summary.standard_id}",
                f"Dimension: {summary.dimension_id}",
                f"Bands: {summary.band_count}",
                f"Students exported: {summary.exported_count}",
                *ordinary,
                "",
                "This is a historical export, not a current grouping decision.",
                "No Planning Signal, review, or academic record was changed.",
                "T. Technical details / provenance",
            )
            print_standard_navigation(output)
            choice = read_choice(input_fn)
            if choice.casefold() == "t":
                if check_scope() != summary:
                    raise _ExportChanged("Export changed before technical view.")
                clear_fn()
                print_menu_header(output, "Planning Export — Technical Provenance")
                write_lines(output, f"signal_set_id: {summary.signal_set_id}")
                write_lines(output, *value.technical_lines)
                pause_for_user(input_fn)
                continue
            command = parse_navigation_choice(choice)
            if command is NavigationChoice.BACK or choice == "":
                return
            write_lines(output, "Please choose T, B, M, or Q.")
            pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_ExportChanged, _ScopeChanged):
        write_lines(
            output,
            "Class or saved Planning Export changed.",
            "No record was changed. Refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Saved Planning Export could not be verified safely.",
            "No record was changed. Use Advanced for exact diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = (
    "PlanningExportChoiceCatalog",
    "PlanningExportReaders",
    "run_named_planning_export_explanation",
)
