"""Read-only named Planning Preview / selected Review explanation (#123 Slice 9F).

A preview is immutable, while its selected review can change.  Exact canonical
preview and review witnesses must remain stable through every displayed screen.
Neither a named choice nor a selected review implies live export eligibility.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.grouping_signal_derivation import GroupingSignalDerivationReference
from meridian.grouping_signal_derivation_storage import (
    StoredGroupingSignalDerivation,
    load_grouping_signal_derivation_reference,
)
from meridian.grouping_signal_preview_storage import (
    StoredGroupingSignalPreview,
    list_grouping_signal_preview_ids,
    load_grouping_signal_preview,
)
from meridian.grouping_signal_review_storage import (
    StoredGroupingSignalReview,
    load_current_grouping_signal_review,
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

PlanningPreviewExplainer: TypeAlias = Callable[
    [Path, str, str], "ExplanationPresentation"
]
_MAX_PREVIEWS = 200


class _PreviewChanged(RuntimeError):
    """A selected canonical preview, its source, or review pointer changed."""


@dataclass(frozen=True, slots=True)
class PlanningPreviewSummary:
    """Exact read witness with bounded, separately derived display metadata."""

    preview_id: str
    preview_sha256: str
    derivation_id: str
    derivation_sha256: str
    policy_id: str
    policy_revision: int
    policy_sha256: str
    title: str
    period_label: str
    school_year: str
    period_id: str
    calendar_revision: int
    standard_id: str
    dimension_id: str
    band_count: int
    roster_count: int
    selected_review_revision: int | None
    selected_review_sha256: str | None

    def choice(self) -> TeacherChoice:
        selected_here = self.selected_review_revision is not None
        review = (
            f"{self.selected_review_revision}:{self.selected_review_sha256}"
            if selected_here
            else "none:none"
        )
        return TeacherChoice(
            identity=(self.preview_id,),
            label=self.title,
            detail=(
                f"{self.period_label} ({self.school_year}) · "
                f"Standard {self.standard_id} · {self.roster_count} students · "
                f"{self.band_count} bands"
            ),
            status="Saved preview · selected review present"
            if selected_here
            else "Saved preview · no selected review",
            witness=f"{self.preview_sha256}:{review}",
        )


@dataclass(frozen=True, slots=True)
class PlanningPreviewReaders:
    """Injected canonical storage readers; never write or authorize operations."""

    lister: Callable[[Path, str], tuple[str, ...]] = list_grouping_signal_preview_ids
    preview_loader: Callable[[Path, str, str], StoredGroupingSignalPreview] = (
        load_grouping_signal_preview
    )
    derivation_loader: Callable[
        [Path, GroupingSignalDerivationReference], StoredGroupingSignalDerivation
    ] = load_grouping_signal_derivation_reference
    selected_review_loader: Callable[
        [Path, str, str], StoredGroupingSignalReview | None
    ] = load_current_grouping_signal_review


@dataclass(slots=True)
class PlanningPreviewChoiceCatalog:
    """Bounded preview discovery with exact source and review-pointer witnesses."""

    navigation: TeacherNavigationContext
    readers: PlanningPreviewReaders = field(default_factory=PlanningPreviewReaders)
    derivation_catalog: PlanningDerivationChoiceCatalog | None = None

    def inspect(
        self, root: Path, class_id: str, preview_id: str
    ) -> PlanningPreviewSummary:
        stored = self.readers.preview_loader(root, class_id, preview_id)
        preview = stored.snapshot
        if (
            preview.preview_id != preview_id
            or stored.reference.class_id != class_id
            or stored.reference.preview_id != preview_id
            or stored.reference.preview_sha256 != stored.preview_sha256
        ):
            raise TeacherChoiceUnavailable("Saved preview identity changed.")
        derivation = self.readers.derivation_loader(root, preview.derivation_reference)
        if derivation.reference != preview.derivation_reference:
            raise TeacherChoiceUnavailable("Saved preview source digest changed.")
        source = derivation.snapshot
        if (
            preview.policy_reference != source.policy_reference
            or preview.roster_basis != source.roster_basis
            or preview.derivation_calculation_fingerprint
            != source.calculation_fingerprint
            or preview.dimension_id != source.dimension_id
            or preview.band_count != source.band_count
            or len(preview.student_rows) != len(source.student_derivations)
        ):
            raise TeacherChoiceUnavailable("Saved preview source lineage changed.")
        catalog = self.derivation_catalog or PlanningDerivationChoiceCatalog(
            self.navigation
        )
        derived = catalog.inspect(
            root, class_id, preview.derivation_reference.derivation_id
        )
        period = preview.academic_basis.target_period
        if (
            derived.derivation_sha256 != preview.derivation_reference.derivation_sha256
            or derived.policy_id != preview.policy_reference.policy_id
            or derived.policy_revision != preview.policy_reference.policy_revision
            or derived.policy_sha256 != preview.policy_reference.policy_sha256
            or derived.title != preview.policy_title
            or derived.standard_id != preview.academic_basis.standard_id
            or derived.school_year != period.period.school_year
            or derived.dimension_id != preview.dimension_id
            or derived.band_count != preview.band_count
            or derived.student_count != preview.coverage.roster_student_count
        ):
            raise TeacherChoiceUnavailable("Saved preview policy scope changed.")
        selected = self.readers.selected_review_loader(
            root, class_id, preview.derivation_reference.derivation_id
        )
        if selected is not None and (
            selected.reference.class_id != class_id
            or selected.reference.derivation_id
            != preview.derivation_reference.derivation_id
            or selected.review.derivation_reference != preview.derivation_reference
        ):
            raise TeacherChoiceUnavailable("Selected review scope changed.")
        return PlanningPreviewSummary(
            preview_id=preview_id,
            preview_sha256=stored.preview_sha256,
            derivation_id=derived.derivation_id,
            derivation_sha256=derived.derivation_sha256,
            policy_id=derived.policy_id,
            policy_revision=derived.policy_revision,
            policy_sha256=derived.policy_sha256,
            title=derived.title,
            period_label=derived.period_label,
            school_year=derived.school_year,
            period_id=period.period.period_id,
            calendar_revision=period.calendar_revision,
            standard_id=derived.standard_id,
            dimension_id=derived.dimension_id,
            band_count=derived.band_count,
            roster_count=derived.student_count,
            selected_review_revision=(
                selected.review.review_revision if selected is not None else None
            ),
            selected_review_sha256=(
                selected.review_sha256 if selected is not None else None
            ),
        )

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "planning_preview_review":
            raise TeacherChoiceUnavailable("Unsupported preview choice scope.")
        current = self.navigation.current_class()
        if current is None or selected.get("class") != current.class_id:
            raise TeacherChoiceUnavailable("Choose a verified class first.")
        try:
            ids = self.readers.lister(current.workspace, current.class_id)
            if len(ids) > _MAX_PREVIEWS or len(ids) != len(set(ids)):
                raise TeacherChoiceUnavailable(
                    "Saved preview catalog exceeds safe limits. Use Advanced."
                )
            choices: list[TeacherChoice] = []
            for preview_id in ids:
                summary = self.inspect(current.workspace, current.class_id, preview_id)
                if summary.school_year == current.school_year:
                    choices.append(summary.choice())
            return tuple(choices)
        except TeacherChoiceUnavailable:
            raise
        except Exception as error:
            raise TeacherChoiceUnavailable(
                "Saved planning previews could not be verified."
            ) from error


def _check_explanation(
    value: ExplanationPresentation,
    summary: PlanningPreviewSummary,
    class_id: str,
) -> tuple[str, ...]:
    """Bind a read-only, live preview/review explanation to exact witnesses."""
    lines, technical = value.lines, value.technical_lines
    review_revision = (
        str(summary.selected_review_revision)
        if summary.selected_review_revision is not None
        else "none"
    )
    review_sha = summary.selected_review_sha256 or "none"
    exact_lines = (
        f"Policy: {summary.title}",
        f"Academic Period: {summary.school_year} / {summary.period_id}",
        f"Standard: {summary.standard_id}",
        f"Dimension: {summary.dimension_id}",
    )
    exact_technical = (
        f"class_id: {class_id}",
        f"preview_id: {summary.preview_id}",
        f"preview_sha256: {summary.preview_sha256}",
        f"derivation_id: {summary.derivation_id}",
        f"derivation_sha256: {summary.derivation_sha256}",
        f"policy_id: {summary.policy_id}",
        f"policy_revision: {summary.policy_revision}",
        f"policy_sha256: {summary.policy_sha256}",
        f"selected_review_revision: {review_revision}",
        f"selected_review_sha256: {review_sha}",
    )
    if (
        value.title != "Planning Preview / Review Explanation"
        or not isinstance(lines, tuple)
        or not isinstance(technical, tuple)
        or len(lines) != 9
        or any(not isinstance(item, str) for item in (*lines, *technical))
        or any(lines.count(item) != 1 for item in exact_lines)
        or any(technical.count(item) != 1 for item in exact_technical)
        or not lines[4].startswith("Path state: ")
        or not lines[5].startswith("Live currentness: ")
        or not lines[6].startswith("Selected review: ")
        or not lines[7].startswith("Coverage: ")
        or not lines[8].startswith("Export eligible: ")
        or lines[8] not in ("Export eligible: yes", "Export eligible: no")
    ):
        raise _PreviewChanged("Planning explanation no longer matches the choice.")
    return lines[4:]


def run_named_planning_preview_review_explanation(
    *,
    navigation: TeacherNavigationContext,
    planning_preview_explainer: PlanningPreviewExplainer,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    preview_catalog: PlanningPreviewChoiceCatalog | None = None,
) -> None:
    """Explain one saved preview and the explicitly selected review, read-only."""
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
            raise _PreviewChanged("Class context changed.")
        selected = select_teacher_choice(
            catalog=catalog,
            scope="planning_preview_review",
            selected={"class": class_id},
            title="Saved Planning Previews",
            question="Which saved planning preview and review should be explained?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if selected is None:
            return

        def check_scope() -> PlanningPreviewSummary:
            if navigation.current_class() != verified:
                raise _PreviewChanged("Class changed while reviewing.")
            _current_choice(
                catalog,
                scope="planning_preview_review",
                selected={"class": class_id},
                choice=selected,
            )
            current = catalog.inspect(root, class_id, selected.identity[0])
            if (
                current.school_year != verified.school_year
                or current.choice() != selected
            ):
                raise _PreviewChanged("Saved preview/review witness changed.")
            return current

        summary = check_scope()
        value = planning_preview_explainer(root, class_id, summary.preview_id)
        ordinary = _check_explanation(value, summary, class_id)
        if check_scope() != summary:
            raise _PreviewChanged("Saved preview or selected review changed.")
        while True:
            if check_scope() != summary:
                raise _PreviewChanged("Saved preview or selected review changed.")
            clear_fn()
            print_menu_header(output, "Planning Preview / Selected Review Explanation")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Academic period: {summary.period_label}",
                f"Standard: {summary.standard_id}",
                f"Dimension: {summary.dimension_id}",
                f"Roster students: {summary.roster_count}",
                *ordinary,
                "",
                "Live currentness and eligibility reflect the explanation read.",
                "No planning, review, export, or academic record was changed.",
                "T. Technical details / provenance",
            )
            print_standard_navigation(output)
            choice = read_choice(input_fn)
            if choice.casefold() == "t":
                if check_scope() != summary:
                    raise _PreviewChanged("Selected review changed before details.")
                clear_fn()
                print_menu_header(output, "Planning Preview — Technical Provenance")
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
    except (_PreviewChanged, _ScopeChanged):
        write_lines(
            output,
            "Class, saved preview, or selected Planning Review changed.",
            "No record was changed. Refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Planning Preview / Review could not be verified safely.",
            "No record was changed. Use Advanced for exact diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = (
    "PlanningPreviewChoiceCatalog",
    "PlanningPreviewReaders",
    "run_named_planning_preview_review_explanation",
)
