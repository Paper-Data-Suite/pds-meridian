"""Current academic-period proficiency choices for issue #123 Slice 4B.

Only Core's verified marking-period catalog and Meridian's selected-result
reader can supply a candidate. Display is never proof of selected authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias

from meridian.academic_period_proficiency_storage import (
    StoredAcademicPeriodProficiencyResult,
    list_academic_period_proficiency_result_standard_ids,
    load_current_academic_period_proficiency_result,
)
from meridian.teacher_navigation_choices import TeacherChoice, TeacherChoiceUnavailable
from meridian.teacher_navigation_context import (
    NavigationScopeUnavailable,
    TeacherNavigationContext,
    VerifiedPeriodScope,
)

StandardLister: TypeAlias = Callable[[Path, str, str, str, str], tuple[str, ...]]
SelectedResultLoader: TypeAlias = Callable[
    [Path, str, str, str, str, str], StoredAcademicPeriodProficiencyResult | None
]


@dataclass(frozen=True, slots=True)
class PeriodChoiceReaders:
    """Replaceable canonical read adapters, never write or projection services."""

    standard_lister: StandardLister = (
        list_academic_period_proficiency_result_standard_ids
    )
    result_loader: SelectedResultLoader = (
        load_current_academic_period_proficiency_result
    )


@dataclass(slots=True)
class PeriodProficiencyChoiceCatalog:
    """Scoped period and selected-standard options, reloaded at each call."""

    navigation: TeacherNavigationContext
    readers: PeriodChoiceReaders = field(default_factory=PeriodChoiceReaders)

    def _class(self, selected: Mapping[str, str]) -> tuple[Path, str, str]:
        chosen_id = selected.get("class")
        scope = self.navigation.current_class()
        if scope is None or chosen_id != scope.class_id:
            raise TeacherChoiceUnavailable("Class must remain selected and current.")
        return scope.workspace, scope.class_id, scope.school_year

    def _period(self, selected: Mapping[str, str]) -> VerifiedPeriodScope:
        period_id = selected.get("period")
        if not period_id:
            raise TeacherChoiceUnavailable("Choose a marking period first.")
        active = self.navigation.current_period()
        if active is None or active.period_id != period_id:
            raise TeacherChoiceUnavailable("Marking period must be selected again.")
        return active

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        root, class_id, year = self._class(selected)
        try:
            if scope == "period":
                periods = self.navigation.readers.period_lister(root, year)
                if len(periods) > 500:
                    raise TeacherChoiceUnavailable("Marking-period list exceeds bound.")
                choices: list[TeacherChoice] = []
                for entry in periods:
                    calendar_period = entry.period
                    if (
                        not entry.is_current_calendar
                        or entry.school_year != year
                        or calendar_period.period_type != "marking_period"
                        or calendar_period.lifecycle == "cancelled"
                    ):
                        continue
                    exact = self.navigation.verify_period(calendar_period.period_id)
                    if exact.calendar_revision != entry.calendar_revision:
                        raise TeacherChoiceUnavailable("Period catalog changed.")
                    choices.append(
                        TeacherChoice(
                            identity=(calendar_period.period_id,),
                            label=calendar_period.label,
                            detail=(
                                f"{calendar_period.start_date.isoformat()} to "
                                f"{calendar_period.end_date.isoformat()} · {year}"
                            ),
                            status=calendar_period.lifecycle.replace("_", " "),
                            witness=(
                                f"{year}:{entry.calendar_revision}:"
                                f"{entry.calendar_updated_at.isoformat()}"
                            ),
                        )
                    )
                return tuple(choices)

            if scope != "period_standard":
                raise TeacherChoiceUnavailable("Unsupported period choice scope.")
            period = self._period(selected)
            if (period.workspace, period.class_id, period.school_year) != (
                root,
                class_id,
                year,
            ):
                raise TeacherChoiceUnavailable("Class or marking period changed.")
            student_id = selected.get("student")
            if not student_id:
                raise TeacherChoiceUnavailable("Choose a roster student first.")
            roster = self.navigation.readers.roster_loader(root, class_id)
            if roster.class_id != class_id or student_id not in {
                record.student_id for record in roster.students
            }:
                raise TeacherChoiceUnavailable("Student is not in the current roster.")
            standards = self.readers.standard_lister(
                root, class_id, year, period.period_id, student_id
            )
            if len(standards) > 500 or len(standards) != len(set(standards)):
                raise TeacherChoiceUnavailable("Result list exceeds bound or repeats.")
            choices = []
            for standard_id in standards:
                current = self.readers.result_loader(
                    root, class_id, year, period.period_id, student_id, standard_id
                )
                if current is None:
                    continue
                result = current.snapshot
                target = result.target_period
                if (
                    result.class_id != class_id
                    or result.student_id != student_id
                    or result.standard_id != standard_id
                    or target.period.school_year != year
                    or target.period.period_id != period.period_id
                    or target.calendar_revision != period.calendar_revision
                ):
                    raise TeacherChoiceUnavailable(
                        "Current result does not match the selected period."
                    )
                choices.append(
                    TeacherChoice(
                        identity=(standard_id,),
                        label=f"Standard {standard_id}",
                        status="Current selected period result",
                        witness=f"{result.result_revision}:{current.result_sha256}",
                    )
                )
            return tuple(choices)
        except (TeacherChoiceUnavailable, NavigationScopeUnavailable):
            raise
        except Exception as error:
            raise TeacherChoiceUnavailable(
                "Current period choices could not be verified."
            ) from error


__all__ = ("PeriodChoiceReaders", "PeriodProficiencyChoiceCatalog")
