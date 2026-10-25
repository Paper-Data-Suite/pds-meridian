"""Named, read-only historical ReportingSnapshot / current Grade comparison.

#123 Slice 9B delegates all comparison semantics and protected reads to the
existing Explain provider. Frozen snapshots are selected through the bounded
#123 catalog and reverified against their exact identity and digest.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.grade_policy import GradeCalculationFamily
from meridian.menu_snapshots import _list_snapshots
from meridian.menu_teacher_named_grades import (
    _current_choice,
    _family,
    _marking_period,
    _ScopeChanged,
)
from meridian.menu_teacher_named_review import _class
from meridian.menu_teacher_named_snapshots import FrozenSnapshotChoiceCatalog
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.teacher_navigation_choices import TeacherChoice
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_explain import ExplanationPresentation
    from meridian.menu_snapshots import SnapshotLister, SnapshotListItem

SnapshotComparisonReader: TypeAlias = Callable[
    [Path, str, str, str, str, AcademicPeriodRef, int, GradeCalculationFamily],
    "ExplanationPresentation",
]


class _ComparisonChanged(RuntimeError):
    """A selection or historical comparison changed after review."""


@dataclass(slots=True)
class _PeriodSnapshotCatalog:
    """Filter the existing bounded frozen catalog to an exact verified period."""

    inner: FrozenSnapshotChoiceCatalog
    lister: SnapshotLister
    root: Path
    class_id: str
    school_year: str
    period_id: str
    calendar_revision: int

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "frozen_snapshot" or selected.get("class") != self.class_id:
            raise _ComparisonChanged("Snapshot choice scope changed.")
        all_choices = self.inner.options(scope=scope, selected=selected)
        rows = self.lister(self.root, self.class_id)
        matched = {
            row.snapshot_id
            for row in rows
            if row.school_year == self.school_year
            and row.period_id == self.period_id
            and row.calendar_revision == self.calendar_revision
        }
        return tuple(choice for choice in all_choices if choice.identity[0] in matched)


def _snapshot_item(
    lister: SnapshotLister, root: Path, class_id: str, choice: TeacherChoice
) -> SnapshotListItem:
    rows = lister(root, class_id)
    if len(rows) > 200:
        raise _ComparisonChanged("Snapshot collection exceeds safe browse limit.")
    matches = tuple(row for row in rows if (row.snapshot_id,) == choice.identity)
    if len(matches) != 1:
        raise _ComparisonChanged("Frozen snapshot changed or is not unique.")
    return matches[0]


def _check_comparison(
    value: ExplanationPresentation,
    *,
    class_id: str,
    student_id: str,
    snapshot_id: str,
    snapshot_sha256: str,
    revision: int,
    family: GradeCalculationFamily,
) -> tuple[str, ...]:
    lines, technical = value.lines, value.technical_lines
    if (
        value.title != "Prior / Current Grade Comparison"
        or not isinstance(lines, tuple)
        or len(lines) != 5
        or any(not isinstance(line, str) for line in lines)
        or lines[0] != f"Student: {student_id}"
        or not lines[1].startswith("Relationship: ")
        or lines[1].split(": ", 1)[1] not in {"new", "removed", "comparable"}
        or lines[2] not in {"Changed: yes", "Changed: no"}
        or not lines[3].startswith("Reasons: ")
        or not lines[4].startswith("Effective Grade delta: ")
        or not isinstance(technical, tuple)
        or len(technical) != 6
        or any(not isinstance(line, str) for line in technical)
        or technical[0] != f"snapshot_id: {snapshot_id}"
        or technical[1] != f"snapshot_sha256: {snapshot_sha256}"
        or technical[2] != f"class_id: {class_id}"
        or technical[3] != f"calendar_revision: {revision}"
        or technical[4] != f"calculation_family: {family}"
        or not technical[5].startswith("current_calculation_fingerprint: ")
    ):
        raise _ComparisonChanged("Comparison no longer matches selected scope.")
    return lines[1:]


def run_named_grade_snapshot_comparison(
    *,
    navigation: TeacherNavigationContext,
    snapshot_comparer: SnapshotComparisonReader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    snapshot_lister: SnapshotLister = _list_snapshots,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
    frozen_catalog: FrozenSnapshotChoiceCatalog | None = None,
) -> None:
    """Select a snapshot by report title, then explain exact prior/current delta."""
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        periods = period_catalog or PeriodProficiencyChoiceCatalog(navigation)
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
            raise _ComparisonChanged("Verified class changed.")
        chosen = _marking_period(
            navigation,
            periods,
            class_id=class_id,
            root=root,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen is None:
            return
        period, period_choice = chosen
        student = select_teacher_choice(
            catalog=classes,
            scope="student",
            selected={"class": class_id},
            title="Choose Student",
            question="Whose Grade should be compared with a saved checkpoint?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if student is None:
            return
        family = _family(input_fn=input_fn, output=output, clear_fn=clear_fn)
        if family is None:
            return
        snapshots = _PeriodSnapshotCatalog(
            inner=frozen_catalog
            or FrozenSnapshotChoiceCatalog(navigation, snapshot_lister),
            lister=snapshot_lister,
            root=root,
            class_id=class_id,
            school_year=period.school_year,
            period_id=period.period_id,
            calendar_revision=period.calendar_revision,
        )
        chosen_snapshot = select_teacher_choice(
            catalog=snapshots,
            scope="frozen_snapshot",
            selected={"class": class_id},
            title="Choose Historical Reporting Checkpoint",
            question="Which saved reporting checkpoint should be compared?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen_snapshot is None:
            return

        def check_scope() -> SnapshotListItem:
            current = navigation.current_class()
            if (
                current is None
                or current != verified
                or navigation.current_period() != period
                or period.workspace != root
                or period.class_id != class_id
                or period.school_year != verified.school_year
            ):
                raise _ComparisonChanged("Class or marking period changed.")
            _current_choice(
                classes, scope="student", selected={"class": class_id}, choice=student
            )
            _current_choice(
                periods,
                scope="period",
                selected={"class": class_id},
                choice=period_choice,
            )
            _current_choice(
                snapshots,
                scope="frozen_snapshot",
                selected={"class": class_id},
                choice=chosen_snapshot,
            )
            item = _snapshot_item(snapshot_lister, root, class_id, chosen_snapshot)
            if (
                item.school_year != period.school_year
                or item.period_id != period.period_id
                or item.calendar_revision != period.calendar_revision
                or chosen_snapshot.witness is None
                or chosen_snapshot.witness.split(":", 1)[0] != item.snapshot_sha256
            ):
                raise _ComparisonChanged("Historical checkpoint scope changed.")
            return item

        snapshot = check_scope()
        value = snapshot_comparer(
            root,
            class_id,
            snapshot.snapshot_id,
            snapshot.snapshot_sha256,
            student.identity[0],
            AcademicPeriodRef(period.school_year, period.period_id),
            period.calendar_revision,
            family,
        )
        ordinary = _check_comparison(
            value,
            class_id=class_id,
            student_id=student.identity[0],
            snapshot_id=snapshot.snapshot_id,
            snapshot_sha256=snapshot.snapshot_sha256,
            revision=period.calendar_revision,
            family=family,
        )
        if check_scope() != snapshot:
            raise _ComparisonChanged("Historical checkpoint changed during read.")
        while True:
            if check_scope() != snapshot:
                raise _ComparisonChanged("Historical checkpoint changed during review.")
            clear_fn()
            print_menu_header(output, "Historical / Current Grade Comparison")
            write_lines(
                output,
                f"Student: {student.label}",
                f"Marking period: {period.label}",
                f"Saved checkpoint: {chosen_snapshot.label}",
                f"Frozen: {snapshot.created_at}",
                *ordinary,
                "",
                "A missing or unavailable Grade is not zero.",
                "Read-only comparison; no Grade, snapshot, or evidence was changed.",
                "T. Technical details / provenance",
            )
            print_standard_navigation(output)
            choice = read_choice(input_fn)
            if choice.casefold() == "t":
                if check_scope() != snapshot:
                    raise _ComparisonChanged(
                        "Checkpoint changed before technical view."
                    )
                clear_fn()
                print_menu_header(output, "Grade Comparison — Technical Provenance")
                write_lines(
                    output,
                    f"student_id: {student.identity[0]}",
                    f"school_year: {period.school_year}",
                    f"period_id: {period.period_id}",
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
    except (_ComparisonChanged, _ScopeChanged):
        write_lines(
            output,
            "Class, student, marking period, or saved comparison changed.",
            "No academic record was changed. Refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Historical Grade comparison could not be verified safely.",
            "No academic record was changed. Check evidence access or Advanced.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_grade_snapshot_comparison",)
