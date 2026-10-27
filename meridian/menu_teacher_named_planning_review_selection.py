"""Select one immutable Planning Review by its saved, named Preview (#123 10F).

Discover through verified class/preview/review storage contracts. The existing
CAS-bound review selection service is the only mutation authority. Selecting a
review never authors a new decision, exports a Core signal or forms groups.
"""

from __future__ import annotations

import hashlib
import json
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

from meridian.grouping_signal_review_storage import (
    StoredGroupingSignalReview,
    get_current_grouping_signal_review_revision,
    list_grouping_signal_review_revisions,
    load_grouping_signal_review_revision,
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
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.planning_signal_review_selection_workflow import (
        PlanningSignalReviewSelectionPreview,
        PlanningSignalReviewSelectionWorkflowResult,
    )

ReviewSelectionPreparer: TypeAlias = Callable[
    [Path, str, str, str, str, int, str],
    "PlanningSignalReviewSelectionPreview",
]
ReviewSelectionCommitter: TypeAlias = Callable[
    [Path, "PlanningSignalReviewSelectionPreview"],
    "PlanningSignalReviewSelectionWorkflowResult",
]
ReviewHistoryLister: TypeAlias = Callable[[Path, str, str], tuple[int, ...]]
ReviewLoader: TypeAlias = Callable[[Path, str, str, int], StoredGroupingSignalReview]
SelectedRevisionReader: TypeAlias = Callable[[Path, str, str], int | None]
_MAX_REVISIONS = 200


class _SelectionChanged(RuntimeError):
    """The exact chosen review or one of its authority witnesses changed."""


@dataclass(frozen=True, slots=True)
class NamedPlanningReviewSummary:
    """A historical review, bound to a verified saved preview and selector."""

    preview: PlanningPreviewSummary
    revision: int
    sha256: str
    decision: str
    reviewed_at: str
    selected_revision: int | None

    def choice(self) -> TeacherChoice:
        witness = hashlib.sha256(
            b"pds.meridian.review-selection-choice.v1\0"
            + json.dumps(
                (
                    self.preview.preview_id,
                    self.preview.preview_sha256,
                    self.preview.derivation_sha256,
                    self.preview.policy_sha256,
                    self.preview.selected_review_revision,
                    self.preview.selected_review_sha256,
                    self.revision,
                    self.sha256,
                    self.decision,
                    self.reviewed_at,
                    self.selected_revision,
                ),
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return TeacherChoice(
            identity=(self.preview.preview_id, str(self.revision)),
            label=f"Review {self.revision}: {self.decision.replace('_', ' ')}",
            detail=(
                f"{self.preview.title} · {self.preview.period_label} "
                f"({self.preview.school_year}) · {self.preview.standard_id}"
            ),
            status=(
                "Currently selected"
                if self.selected_revision == self.revision
                else f"Saved review · {self.reviewed_at}"
            ),
            witness="sha256:" + witness,
        )


@dataclass(frozen=True, slots=True)
class PlanningReviewSelectionReaders:
    """Read-only public storage injection; no selection/write functions."""

    lister: ReviewHistoryLister = list_grouping_signal_review_revisions
    loader: ReviewLoader = load_grouping_signal_review_revision
    selected: SelectedRevisionReader = get_current_grouping_signal_review_revision


@dataclass(slots=True)
class NamedPlanningReviewCatalog:
    """Bounded historical review choices for one verified saved preview."""

    navigation: TeacherNavigationContext
    previews: PlanningPreviewChoiceCatalog
    readers: PlanningReviewSelectionReaders = field(
        default_factory=PlanningReviewSelectionReaders
    )

    def inspect(
        self,
        root: Path,
        class_id: str,
        preview: PlanningPreviewSummary,
        revision: int,
    ) -> NamedPlanningReviewSummary:
        current = self.previews.inspect(root, class_id, preview.preview_id)
        if current != preview:
            raise TeacherChoiceUnavailable("Saved preview witness changed.")
        if type(revision) is not int or revision < 1:
            raise TeacherChoiceUnavailable("Review revision is invalid.")
        stored = self.readers.loader(root, class_id, preview.derivation_id, revision)
        record = stored.review
        reference = stored.reference
        selected = self.readers.selected(root, class_id, preview.derivation_id)
        if (
            record.class_id != class_id
            or record.review_revision != revision
            or reference.class_id != class_id
            or reference.derivation_id != preview.derivation_id
            or reference.review_revision != revision
            or reference.review_sha256 != stored.review_sha256
            or record.derivation_reference.derivation_id != preview.derivation_id
            or record.derivation_reference.derivation_sha256
            != preview.derivation_sha256
            or record.preview_reference.preview_id != preview.preview_id
            or record.preview_reference.preview_sha256 != preview.preview_sha256
            or record.decision not in {"accepted_for_export", "rejected"}
            or selected != preview.selected_review_revision
            or (selected is None) != (preview.selected_review_sha256 is None)
        ):
            raise TeacherChoiceUnavailable("Historical review provenance changed.")
        return NamedPlanningReviewSummary(
            preview=preview,
            revision=revision,
            sha256=stored.review_sha256,
            decision=record.decision,
            reviewed_at=record.reviewed_at.isoformat(),
            selected_revision=selected,
        )

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "planning_review_selection":
            raise TeacherChoiceUnavailable("Unsupported Planning Review scope.")
        verified = self.navigation.current_class()
        class_id = selected.get("class")
        preview_id = selected.get("preview")
        if (
            verified is None
            or class_id is None
            or class_id != verified.class_id
            or not preview_id
        ):
            raise TeacherChoiceUnavailable("Choose a verified class and preview.")
        try:
            preview = self.previews.inspect(verified.workspace, class_id, preview_id)
            if preview.school_year != verified.school_year:
                raise TeacherChoiceUnavailable("Saved preview is out of school year.")
            revisions = self.readers.lister(
                verified.workspace, class_id, preview.derivation_id
            )
            if (
                len(revisions) > _MAX_REVISIONS
                or len(revisions) != len(set(revisions))
                or any(type(r) is not int or r < 1 for r in revisions)
            ):
                raise TeacherChoiceUnavailable("Review history exceeds safe limits.")
            # Other saved previews may share this derivation's review history.
            # Only exact reviews of the chosen preview appear as options.
            choices: list[TeacherChoice] = []
            for revision in revisions:
                stored = self.readers.loader(
                    verified.workspace, class_id, preview.derivation_id, revision
                )
                if stored.review.preview_reference.preview_id != preview.preview_id:
                    continue
                current = self.inspect(verified.workspace, class_id, preview, revision)
                choices.append(current.choice())
            return tuple(choices)
        except TeacherChoiceUnavailable:
            raise
        except Exception as error:
            raise TeacherChoiceUnavailable(
                "Saved Planning Review history could not be verified."
            ) from error


def _check_intent(
    intent: PlanningSignalReviewSelectionPreview,
    preview: PlanningPreviewSummary,
    selected: NamedPlanningReviewSummary,
    class_id: str,
) -> None:
    """Verify the reviewed CAS target and live applicability before display."""
    _checked_projection(intent.projection, preview, class_id)
    target = intent.target
    record = target.review
    if (
        intent.class_id != class_id
        or intent.derivation_id != preview.derivation_id
        or intent.target_review_revision != selected.revision
        or intent.target_review_sha256 != selected.sha256
        or intent.target_decision != selected.decision
        or intent.expected_current_review_revision != selected.selected_revision
        or intent.projection.preview_reference.preview_id != preview.preview_id
        or record.class_id != class_id
        or record.preview_reference != intent.projection.preview_reference
        or record.derivation_reference != intent.projection.derivation_reference
        or record.review_revision != selected.revision
        or record.decision != selected.decision
        or record.reviewed_at.isoformat() != selected.reviewed_at
        or target.reference.review_sha256 != selected.sha256
        or intent.target_applicability.status
        not in {"current", "stale", "not_accepted"}
    ):
        raise _SelectionChanged("Review-selection intent differs from chosen record.")


def _check_result(
    result: PlanningSignalReviewSelectionWorkflowResult,
    intent: PlanningSignalReviewSelectionPreview,
    selected: NamedPlanningReviewSummary,
) -> None:
    if (
        result.preview != intent
        or result.selected_review_revision != selected.revision
        or result.selected_review_sha256 != selected.sha256
        or result.selected_decision != selected.decision
        or result.previous_current_review_revision != selected.selected_revision
        or result.selection_disposition not in {"created", "updated", "existing"}
        or result.review_selection_action != "performed"
        or result.review_write_action != "not_performed"
        or result.core_export_action != "not_performed"
        or result.csv_export_action != "not_performed"
    ):
        raise _SelectionChanged("Review selection result differs from confirmation.")


def run_named_planning_review_selection(
    *,
    navigation: TeacherNavigationContext,
    selection_preparer: ReviewSelectionPreparer,
    selection_committer: ReviewSelectionCommitter,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    preview_catalog: PlanningPreviewChoiceCatalog | None = None,
    review_catalog: NamedPlanningReviewCatalog | None = None,
) -> None:
    """Select one saved review by named preview/history with exact SELECT/CAS."""
    attempted = False
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        previews = preview_catalog or PlanningPreviewChoiceCatalog(navigation)
        catalog = review_catalog or NamedPlanningReviewCatalog(navigation, previews)
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
            raise _SelectionChanged("Class changed before review selection.")
        chosen_preview = select_teacher_choice(
            catalog=previews,
            scope="planning_preview_review",
            selected={"class": class_id},
            title="Saved Planning Previews",
            question="Which saved preview's teacher reviews should be considered?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen_preview is None:
            return
        if len(chosen_preview.identity) != 1:
            raise _SelectionChanged("Unexpected preview choice identity.")

        def check_preview() -> PlanningPreviewSummary:
            if navigation.current_class() != verified:
                raise _SelectionChanged("Verified class changed.")
            _current_choice(
                previews,
                scope="planning_preview_review",
                selected={"class": class_id},
                choice=chosen_preview,
            )
            current = previews.inspect(root, class_id, chosen_preview.identity[0])
            if (
                current.school_year != verified.school_year
                or current.choice() != chosen_preview
            ):
                raise _SelectionChanged("Chosen preview/review pointer changed.")
            return current

        preview = check_preview()
        chosen_review = select_teacher_choice(
            catalog=catalog,
            scope="planning_review_selection",
            selected={"class": class_id, "preview": preview.preview_id},
            title="Saved Teacher Reviews",
            question="Which historical teacher decision should become selected?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen_review is None:
            return
        if len(chosen_review.identity) != 2:
            raise _SelectionChanged("Unexpected review choice identity.")

        def check_scope() -> NamedPlanningReviewSummary:
            current = check_preview()
            _current_choice(
                catalog,
                scope="planning_review_selection",
                selected={"class": class_id, "preview": preview.preview_id},
                choice=chosen_review,
            )
            if chosen_review.identity[0] != preview.preview_id:
                raise _SelectionChanged("Review selection changed preview.")
            try:
                revision = int(chosen_review.identity[1])
            except ValueError as error:
                raise _SelectionChanged("Review identity changed.") from error
            selected = catalog.inspect(root, class_id, current, revision)
            if selected.choice() != chosen_review:
                raise _SelectionChanged("Saved review currentness changed.")
            return selected

        selected = check_scope()
        intent = selection_preparer(
            root,
            class_id,
            preview.policy_id,
            preview.preview_id,
            preview.preview_sha256,
            selected.revision,
            selected.sha256,
        )
        _check_intent(intent, preview, selected, class_id)
        if check_scope() != selected:
            raise _SelectionChanged("Saved review changed during preparation.")
        while True:
            if check_scope() != selected:
                raise _SelectionChanged("Review changed before confirmation.")
            clear_fn()
            print_menu_header(output, "Review Planning Review Selection")
            write_lines(
                output,
                f"Policy: {preview.title}",
                f"Marking period: {preview.period_label} ({preview.school_year})",
                f"Standard: {preview.standard_id}",
                f"Saved decision: {selected.decision.replace('_', ' ')}",
                f"Historical review revision: {selected.revision}",
                "Live applicability: "
                + intent.target_applicability.status.replace("_", " "),
                "Currently selected revision: "
                + (
                    str(selected.selected_revision)
                    if selected.selected_revision is not None
                    else "none"
                ),
                "",
                "SELECT makes this exact saved review revision current.",
                "It does not authorize a Core export or create any groups.",
                "Type SELECT to apply; B or blank cancels; M or Q navigates.",
                "T. Technical details / provenance",
            )
            answer = read_choice(input_fn, "Confirmation: ")
            if answer.casefold() == "t":
                if check_scope() != selected:
                    raise _SelectionChanged("Review changed before provenance view.")
                clear_fn()
                print_menu_header(output, "Planning Review — Technical Provenance")
                write_lines(
                    output,
                    f"class_id: {class_id}",
                    f"preview_id: {preview.preview_id}",
                    f"preview_sha256: {preview.preview_sha256}",
                    f"derivation_id: {preview.derivation_id}",
                    f"derivation_sha256: {preview.derivation_sha256}",
                    f"policy_id: {preview.policy_id}",
                    f"review_revision: {selected.revision}",
                    f"review_sha256: {selected.sha256}",
                )
                pause_for_user(input_fn)
                continue
            command = parse_navigation_choice(answer)
            if command is NavigationChoice.BACK or not answer:
                write_lines(output, "Selection unchanged; no review was applied.")
                return
            if answer != "SELECT":
                write_lines(output, "Selection unchanged; no review was applied.")
                pause_for_user(input_fn)
                return
            if check_scope() != selected:
                raise _SelectionChanged("Review changed immediately before apply.")
            attempted = True
            result = selection_committer(root, intent)
            _check_result(result, intent, selected)
            clear_fn()
            print_menu_header(output, "Planning Review Selected")
            write_lines(
                output,
                f"Policy: {preview.title}",
                f"Selected revision: {result.selected_review_revision}",
                f"Selected decision: {result.selected_decision.replace('_', ' ')}",
                f"Selection outcome: {result.selection_disposition}",
                "",
                "No Planning Review revision or Core export was created.",
            )
            pause_for_user(input_fn)
            return
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_SelectionChanged, _DiagnosticsChanged, _ScopeChanged):
        write_lines(
            output,
            "Class, saved Planning Preview, or review selection changed.",
            "A selection may have completed; inspect current review before retrying."
            if attempted
            else "No selection was requested; refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Planning Review selection could not be verified or applied safely.",
            "A selection may have completed; inspect current review before retrying."
            if attempted
            else "No selection was requested; use Advanced for diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = (
    "NamedPlanningReviewCatalog",
    "NamedPlanningReviewSummary",
    "PlanningReviewSelectionReaders",
    "run_named_planning_review_selection",
)
