"""Use a named, frozen ReportingSnapshot as current reporting selection (#123 7B).

Snapshot choices and remembered scope never authorize selection. The existing
preview and digest-bound CAS committer own the consequential operation. A
failed post-commit observation is an uncertain outcome, not a claimed rollback.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_teacher_named_grades import _marking_period
from meridian.menu_teacher_named_review import _class
from meridian.menu_teacher_named_snapshots import (
    FrozenSnapshotChoiceCatalog,
    _revalidate,
    _SnapshotChanged,
)
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    read_choice,
    write_lines,
)
from meridian.teacher_navigation_choices import load_teacher_choices
from meridian.teacher_navigation_context import (
    TeacherNavigationContext,
    VerifiedPeriodScope,
)
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_snapshots import (
        SnapshotListItem,
        SnapshotPresentation,
        SnapshotSelectionPlan,
    )

SnapshotLister: TypeAlias = Callable[[Path, str], tuple["SnapshotListItem", ...]]
SnapshotInspector: TypeAlias = Callable[[Path, str, str], "SnapshotPresentation"]
SelectionPreviewer: TypeAlias = Callable[
    [Path, str, str, str, str | None, datetime], "SnapshotSelectionPlan"
]
SelectionCommitter: TypeAlias = Callable[[Path, "SnapshotSelectionPlan"], str]
Clock: TypeAlias = Callable[[], datetime]

# The existing teacher-attribution adapter recognizes this exact prompt. It
# supplies the saved/one-action teacher identity when the main menu is composed.
_TEACHER_ATTRIBUTION_PROMPT = "Teacher actor ID: "
_MAX_INVENTORY = 200


def _period_items(
    lister: SnapshotLister,
    period: VerifiedPeriodScope,
    root: Path,
    class_id: str,
) -> tuple["SnapshotListItem", ...]:
    values = lister(root, class_id)
    if len(values) > _MAX_INVENTORY:
        raise _SnapshotChanged("The snapshot catalog is too large for this screen.")
    return tuple(
        item
        for item in values
        if item.school_year == period.school_year
        and item.period_id == period.period_id
        and item.calendar_revision == period.calendar_revision
    )


def _verify_plan(
    plan: "SnapshotSelectionPlan",
    *,
    item: "SnapshotListItem",
    root_class: str,
    actor: str,
    rationale: str | None,
    decided_at: datetime,
) -> None:
    """Bind the teacher preview to one immutable snapshot and CAS scope."""
    reference = plan.target_reference
    current = plan.expected_current
    if (
        plan.class_id != root_class
        or plan.snapshot_id != item.snapshot_id
        or plan.snapshot_sha256 != item.snapshot_sha256
        or plan.definition_id != item.definition_id
        or plan.school_year != item.school_year
        or plan.period_id != item.period_id
        or plan.calendar_revision != item.calendar_revision
        or plan.row_count != item.row_count
        or plan.actor_id != actor
        or plan.rationale != rationale
        or plan.decided_at != decided_at
        or reference.class_id != root_class
        or reference.snapshot_id != item.snapshot_id
        or reference.snapshot_sha256 != item.snapshot_sha256
    ):
        raise _SnapshotChanged("Reporting selector preview changed identity.")
    if current is None:
        if (
            plan.current_snapshot_id is not None
            or plan.current_selection_revision is not None
        ):
            raise _SnapshotChanged("Unexpected current selection without a witness.")
    elif (
        current.class_id != root_class
        or current.definition_id != item.definition_id
        or current.target_period.school_year != item.school_year
        or current.target_period.period_id != item.period_id
        or current.calendar_revision != item.calendar_revision
        or plan.current_selection_revision != current.selection_revision
        or plan.current_snapshot_id is None
    ):
        raise _SnapshotChanged("The current reporting selector is inconsistent.")


def run_named_snapshot_selection(
    *,
    navigation: TeacherNavigationContext,
    lister: SnapshotLister,
    inspector: SnapshotInspector,
    selection_previewer: SelectionPreviewer,
    selection_committer: SelectionCommitter,
    clock: Clock,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
) -> None:
    """Select one verified checkpoint for *local* reporting use, never SIS."""
    attempted = False
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        periods = period_catalog or PeriodProficiencyChoiceCatalog(navigation)
        active = _class(
            navigation, classes, input_fn=input_fn, output=output, clear_fn=clear_fn
        )
        if active is None:
            return
        root, class_id = active
        verified_class = navigation.current_class()
        if (
            verified_class is None
            or verified_class.workspace != root
            or verified_class.class_id != class_id
        ):
            raise _SnapshotChanged("Class scope changed.")
        result = _marking_period(
            navigation,
            periods,
            class_id=class_id,
            root=root,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if result is None:
            return
        period, period_choice = result

        def filtered_lister(path: Path, cid: str) -> tuple["SnapshotListItem", ...]:
            return _period_items(lister, period, path, cid)

        catalog = FrozenSnapshotChoiceCatalog(navigation, filtered_lister)

        def check_scope() -> None:
            current = navigation.current_class()
            if (
                current is None
                or current.workspace != root
                or current.class_id != class_id
                or current.school_year != verified_class.school_year
                or navigation.current_period() != period
                or period_choice
                not in load_teacher_choices(
                    periods, scope="period", selected={"class": class_id}
                )
            ):
                raise _SnapshotChanged("Class or marking period became stale.")

        check_scope()
        choice = select_teacher_choice(
            catalog=catalog,
            scope="frozen_snapshot",
            selected={"class": class_id},
            title="Choose Frozen Reporting Checkpoint",
            question="Which checkpoint should be current for reporting use?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if choice is None:
            return

        def check_choice() -> "SnapshotListItem":
            check_scope()
            _revalidate(
                navigation=navigation,
                root=root,
                class_id=class_id,
                school_year=verified_class.school_year,
                catalog=catalog,
                choice=choice,
            )
            matches = tuple(
                item
                for item in filtered_lister(root, class_id)
                if item.snapshot_id == choice.identity[0]
            )
            if len(matches) != 1:
                raise _SnapshotChanged("The selected checkpoint is not unique.")
            return matches[0]

        item = check_choice()
        first = inspector(root, class_id, item.snapshot_id)
        if first.item != item:
            raise _SnapshotChanged("The immutable checkpoint changed.")
        if first.current_for_scope:
            write_lines(
                output,
                "This checkpoint is already current for reporting use.",
                "No selection was changed.",
            )
            pause_for_user(input_fn)
            return
        rationale_text = read_choice(input_fn, "Rationale (optional): ")
        rationale = rationale_text or None
        actor = read_choice(input_fn, _TEACHER_ATTRIBUTION_PROMPT)
        if not actor:
            write_lines(output, "Teacher attribution unavailable. Nothing changed.")
            pause_for_user(input_fn)
            return
        decided_at = clock()
        check_choice()
        plan = selection_previewer(
            root, class_id, item.snapshot_id, actor, rationale, decided_at
        )
        _verify_plan(
            plan,
            item=item,
            root_class=class_id,
            actor=actor,
            rationale=rationale,
            decided_at=decided_at,
        )
        if (plan.current_snapshot_id == item.snapshot_id) != first.current_for_scope:
            raise _SnapshotChanged("The current checkpoint selection changed.")
        check_choice()
        clear_fn()
        print_menu_header(output, "Use Frozen Reporting Checkpoint")
        write_lines(
            output,
            f"Report: {choice.label}",
            f"Marking period: {period.label}",
            f"Frozen: {item.created_at}",
            f"Rows: {item.row_count}",
            (
                "Current reporting checkpoint: none"
                if plan.current_snapshot_id is None
                else "Another checkpoint is currently selected."
            ),
            "",
            "USE changes Meridian's local reporting-use selection only.",
            "It does not freeze a new report or post to the district/SIS.",
            "Type USE to select this exact frozen checkpoint, or Enter to cancel.",
        )
        if read_choice(input_fn, "Confirmation: ") != "USE":
            write_lines(output, "Canceled. Current reporting selection unchanged.")
            pause_for_user(input_fn)
            return
        check_choice()
        fresh = selection_previewer(
            root, class_id, item.snapshot_id, actor, rationale, decided_at
        )
        _verify_plan(
            fresh,
            item=item,
            root_class=class_id,
            actor=actor,
            rationale=rationale,
            decided_at=decided_at,
        )
        if fresh != plan:
            raise _SnapshotChanged("The reviewed selector authority changed.")
        if inspector(root, class_id, item.snapshot_id) != first:
            raise _SnapshotChanged("The checkpoint selection changed after review.")
        check_choice()
        attempted = True
        disposition = selection_committer(root, plan)
        if disposition not in {"created", "updated", "existing"}:
            raise _SnapshotChanged("Unrecognized selection disposition.")
        confirmed = inspector(root, class_id, item.snapshot_id)
        if confirmed.item != item or not confirmed.current_for_scope:
            raise _SnapshotChanged("The committed selection cannot be verified.")
        write_lines(
            output,
            "",
            f"Checkpoint selected for local reporting use ({disposition}).",
            "No district/SIS Grade or external system was changed.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _SnapshotChanged:
        if attempted:
            write_lines(
                output,
                "Selection outcome is uncertain. The selector may have changed.",
                "Inspect the current reporting checkpoint before retrying.",
            )
        else:
            write_lines(
                output,
                "Class, marking period, or checkpoint changed before selection.",
                "No selection was attempted. Refresh your choices.",
            )
        pause_for_user(input_fn)
    except Exception:
        if attempted:
            write_lines(
                output,
                "Selection outcome could not be verified safely; it may have changed.",
                "Inspect the current reporting checkpoint before retrying.",
            )
        else:
            write_lines(
                output,
                "The reporting checkpoint could not be verified safely.",
                "No selection was attempted. Use Advanced for diagnostics.",
            )
        pause_for_user(input_fn)


__all__ = ("run_named_snapshot_selection",)
