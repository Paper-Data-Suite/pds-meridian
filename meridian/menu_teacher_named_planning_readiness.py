"""Named, read-only Planning Signal policy/readiness workflow (#123 Slice 10A).

Select an explicitly current #37 policy by real title and verified academic
period, not by canonical ID. A choice is only a read witness; the existing
planning-readiness service owns academic calculations and authorization.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.academic_period_queries import get_academic_period
from pds_core.academic_period_storage import load_academic_period_calendar_revision
from pds_core.academic_periods import AcademicPeriod, AcademicPeriodCalendar
from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.grouping_signal_policy_storage import (
    StoredGroupingSignalDerivationPolicy,
    list_grouping_signal_policy_ids,
    load_current_grouping_signal_policy,
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
from meridian.planning_signal_workflow import PlanningSignalReadinessProjection
from meridian.teacher_navigation_choices import TeacherChoice, TeacherChoiceUnavailable
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

PlanningReadinessReader: TypeAlias = Callable[
    [Path, str, str], PlanningSignalReadinessProjection
]
_MAX_POLICIES = 200


class _PlanningPolicyChanged(RuntimeError):
    """A verified class, selected planning policy or presentation changed."""


@dataclass(frozen=True, slots=True)
class PlanningReadinessPolicySummary:
    """The exact current-policy witness and its teacher-readable context."""

    policy_id: str
    policy_revision: int
    policy_sha256: str
    title: str
    school_year: str
    period_label: str
    period_id: str
    calendar_revision: int
    standard_id: str
    dimension_id: str
    band_count: int
    revised_at: str

    def choice(self) -> TeacherChoice:
        return TeacherChoice(
            identity=(self.policy_id,),
            label=self.title,
            detail=(
                f"{self.period_label} ({self.school_year}) · "
                f"Standard {self.standard_id} · {self.band_count} bands"
            ),
            status=f"Selected Planning Signal policy · Revised {self.revised_at}",
            witness=f"{self.policy_revision}:{self.policy_sha256}",
        )


@dataclass(frozen=True, slots=True)
class PlanningReadinessPolicyReaders:
    """Strict public readers; no policy authoring, mutation or inference."""

    lister: Callable[[Path, str], tuple[str, ...]] = list_grouping_signal_policy_ids
    current_loader: Callable[
        [Path, str, str], StoredGroupingSignalDerivationPolicy | None
    ] = load_current_grouping_signal_policy
    calendar_loader: Callable[[Path, str, int], AcademicPeriodCalendar] = (
        load_academic_period_calendar_revision
    )
    period_lookup: Callable[[AcademicPeriodCalendar, str], AcademicPeriod] = (
        get_academic_period
    )


@dataclass(slots=True)
class PlanningReadinessPolicyCatalog:
    """Select only explicitly current policy revisions for a verified class."""

    navigation: TeacherNavigationContext
    readers: PlanningReadinessPolicyReaders = field(
        default_factory=PlanningReadinessPolicyReaders
    )

    def inspect(
        self, root: Path, class_id: str, policy_id: str
    ) -> PlanningReadinessPolicySummary | None:
        stored = self.readers.current_loader(root, class_id, policy_id)
        if stored is None:
            return None
        policy = stored.policy
        reference = stored.reference
        if (
            reference.class_id != class_id
            or reference.policy_id != policy_id
            or reference.policy_revision != policy.policy_revision
            or reference.policy_sha256 != stored.policy_sha256
            or policy.class_id != class_id
            or policy.policy_id != policy_id
        ):
            raise TeacherChoiceUnavailable("Selected planning policy identity changed.")
        target = policy.academic_basis.target_period
        ref = target.period
        calendar = self.readers.calendar_loader(
            root, ref.school_year, target.calendar_revision
        )
        period = self.readers.period_lookup(calendar, ref.period_id)
        if period.period_id != ref.period_id:
            raise TeacherChoiceUnavailable("Planning academic period identity changed.")
        return PlanningReadinessPolicySummary(
            policy_id=policy_id,
            policy_revision=policy.policy_revision,
            policy_sha256=stored.policy_sha256,
            title=policy.title,
            school_year=ref.school_year,
            period_label=period.label,
            period_id=ref.period_id,
            calendar_revision=target.calendar_revision,
            standard_id=policy.academic_basis.standard_id,
            dimension_id=policy.dimension_id,
            band_count=policy.band_count,
            revised_at=policy.revised_at.isoformat(),
        )

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "planning_readiness_policy":
            raise TeacherChoiceUnavailable("Unsupported planning policy choice scope.")
        current = self.navigation.current_class()
        if current is None or selected.get("class") != current.class_id:
            raise TeacherChoiceUnavailable("Choose a verified class first.")
        try:
            ids = self.readers.lister(current.workspace, current.class_id)
            if len(ids) > _MAX_POLICIES or len(ids) != len(set(ids)):
                raise TeacherChoiceUnavailable(
                    "Too many planning policies or ambiguous identities. Use Advanced."
                )
            choices: list[TeacherChoice] = []
            for policy_id in ids:
                info = self.inspect(current.workspace, current.class_id, policy_id)
                if info is not None and info.school_year == current.school_year:
                    choices.append(info.choice())
            return tuple(choices)
        except TeacherChoiceUnavailable:
            raise
        except Exception as error:
            raise TeacherChoiceUnavailable(
                "Selected Planning Signal policies could not be verified."
            ) from error


def _safe_text(value: str) -> str:
    """A bounded plain-text diagnostic, never a raw exception or private path."""
    if (
        not isinstance(value, str)
        or len(value) > 80
        or not value
        or not all(c.isascii() and (c.isalnum() or c in "_-.") for c in value)
    ):
        raise _PlanningPolicyChanged("Readiness diagnostic cannot be displayed.")
    return value.replace("_", " ")


def _checked_readiness(
    value: PlanningSignalReadinessProjection,
    summary: PlanningReadinessPolicySummary,
    class_id: str,
) -> tuple[str, ...]:
    policy = value.policy
    if (
        value.class_id != class_id
        or value.policy_id != summary.policy_id
        or policy is None
        or policy.reference.class_id != class_id
        or policy.reference.policy_id != summary.policy_id
        or policy.reference.policy_revision != summary.policy_revision
        or policy.reference.policy_sha256 != summary.policy_sha256
        or policy.title != summary.title
        or policy.standard_id != summary.standard_id
        or policy.dimension_id != summary.dimension_id
        or policy.band_count != summary.band_count
        or policy.target_period.period.school_year != summary.school_year
        or policy.target_period.period.period_id != summary.period_id
        or policy.target_period.calendar_revision != summary.calendar_revision
    ):
        raise _PlanningPolicyChanged("Readiness policy provenance changed.")
    status = _safe_text(value.generation_status)
    blockers = value.blocker_codes
    if not isinstance(blockers, tuple) or len(blockers) > 30:
        raise _PlanningPolicyChanged("Readiness blocker inventory changed.")
    safe_blockers = tuple(_safe_text(blocker) for blocker in blockers)
    lines = [f"Readiness: {status}"]
    roster = value.roster_student_count
    contributing = value.contributing_student_count
    noncontributing = value.noncontributing_student_count
    if roster is not None:
        if (
            not isinstance(roster, int)
            or isinstance(roster, bool)
            or not isinstance(contributing, int)
            or isinstance(contributing, bool)
            or not isinstance(noncontributing, int)
            or isinstance(noncontributing, bool)
            or roster < 0
            or contributing < 0
            or noncontributing < 0
        ):
            raise _PlanningPolicyChanged("Invalid readiness student counts.")
        if contributing + noncontributing != roster:
            raise _PlanningPolicyChanged("Readiness student counts changed.")
        lines.append(
            f"Students: {roster} rostered, {contributing} contributing, "
            f"{noncontributing} noncontributing"
        )
    elif contributing is not None or noncontributing is not None:
        raise _PlanningPolicyChanged("Partial readiness counts are unavailable.")
    if safe_blockers:
        lines.append("Needs attention:")
        lines.extend(f"  - {code}" for code in safe_blockers)
    return tuple(lines)


def run_named_planning_readiness(
    *,
    navigation: TeacherNavigationContext,
    readiness_projector: PlanningReadinessReader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    policy_catalog: PlanningReadinessPolicyCatalog | None = None,
) -> None:
    """Read one selected planning policy's readiness, without writing state."""
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        catalog = policy_catalog or PlanningReadinessPolicyCatalog(navigation)
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
            raise _PlanningPolicyChanged("Class scope changed.")
        selected = select_teacher_choice(
            catalog=catalog,
            scope="planning_readiness_policy",
            selected={"class": class_id},
            title="Selected Planning Signal Policies",
            question="Which selected grouping policy should be checked for readiness?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if selected is None:
            return

        def check_scope() -> PlanningReadinessPolicySummary:
            if navigation.current_class() != verified:
                raise _PlanningPolicyChanged("Verified class changed.")
            _current_choice(
                catalog,
                scope="planning_readiness_policy",
                selected={"class": class_id},
                choice=selected,
            )
            current = catalog.inspect(root, class_id, selected.identity[0])
            if (
                current is None
                or current.school_year != verified.school_year
                or current.choice() != selected
            ):
                raise _PlanningPolicyChanged("Selected planning policy changed.")
            return current

        summary = check_scope()
        value = readiness_projector(root, class_id, summary.policy_id)
        ordinary = _checked_readiness(value, summary, class_id)
        if check_scope() != summary:
            raise _PlanningPolicyChanged("Policy changed during readiness projection.")
        while True:
            if check_scope() != summary:
                raise _PlanningPolicyChanged("Policy changed during display.")
            clear_fn()
            print_menu_header(output, "Planning Signal — Readiness by Policy Name")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Marking period: {summary.period_label}",
                f"Standard: {summary.standard_id}",
                f"Dimension: {summary.dimension_id}",
                f"Bands: {summary.band_count}",
                *ordinary,
                "",
                "Only explicitly selected policies are listed.",
                "Read-only: no derivation, review, or Core export was performed.",
                "T. Technical policy provenance",
            )
            print_standard_navigation(output)
            choice = read_choice(input_fn)
            if choice.casefold() == "t":
                if check_scope() != summary:
                    raise _PlanningPolicyChanged(
                        "Policy changed before technical view."
                    )
                clear_fn()
                print_menu_header(output, "Planning Readiness — Technical Provenance")
                write_lines(
                    output,
                    f"class_id: {class_id}",
                    f"policy_id: {summary.policy_id}",
                    f"policy_revision: {summary.policy_revision}",
                    f"policy_sha256: {summary.policy_sha256}",
                    f"school_year: {summary.school_year}",
                    f"period_id: {summary.period_id}",
                    f"calendar_revision: {summary.calendar_revision}",
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
    except (_PlanningPolicyChanged, _ScopeChanged):
        write_lines(
            output,
            "Class or selected Planning Signal policy changed.",
            "No record was changed. Refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Planning Signal readiness could not be verified safely.",
            "No record was changed. Check policy selection or use Advanced.",
        )
        pause_for_user(input_fn)


__all__ = (
    "PlanningReadinessPolicyCatalog",
    "PlanningReadinessPolicyReaders",
    "run_named_planning_readiness",
)
