"""Named, read-only explanation of an immutable planning derivation (#123 9E).

Human-readable choices come from verified Meridian #38 derivation and #37
policy snapshots plus Core's exact academic-period calendar.  An opaque choice
never implies current academic authority, data access, or a grouping decision.
"""

from __future__ import annotations

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

from meridian.grouping_signal_derivation_storage import (
    StoredGroupingSignalDerivation,
    list_grouping_signal_derivation_ids,
    load_grouping_signal_derivation,
)
from meridian.grouping_signal_policy_storage import (
    StoredGroupingSignalDerivationPolicy,
    load_grouping_signal_policy_revision,
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

PlanningDerivationExplainer: TypeAlias = Callable[
    [Path, str, str], "ExplanationPresentation"
]
_MAX_DERIVATIONS = 200


class _DerivationChanged(RuntimeError):
    """The exact named planning derivation or verified class changed."""


@dataclass(frozen=True, slots=True)
class PlanningDerivationSummary:
    """Read-only verified display metadata and exact immutable witnesses."""

    derivation_id: str
    derivation_sha256: str
    title: str
    period_label: str
    school_year: str
    standard_id: str
    dimension_id: str
    band_count: int
    student_count: int
    policy_id: str
    policy_revision: int
    policy_sha256: str
    calculation_fingerprint: str
    revised_at: str

    def choice(self) -> TeacherChoice:
        return TeacherChoice(
            identity=(self.derivation_id,),
            label=self.title,
            detail=(
                f"{self.period_label} ({self.school_year}) · "
                f"Standard {self.standard_id} · "
                f"{self.student_count} students · {self.band_count} bands"
            ),
            status=f"Saved planning derivation · Policy revised {self.revised_at}",
            witness=f"{self.derivation_sha256}:{self.policy_sha256}",
        )


@dataclass(frozen=True, slots=True)
class PlanningDerivationReaders:
    """Injected public read dependencies; no independent academic truth cache."""

    lister: Callable[[Path, str], tuple[str, ...]] = list_grouping_signal_derivation_ids
    derivation_loader: Callable[[Path, str, str], StoredGroupingSignalDerivation] = (
        load_grouping_signal_derivation
    )
    policy_loader: Callable[
        [Path, str, str, int], StoredGroupingSignalDerivationPolicy
    ] = load_grouping_signal_policy_revision
    calendar_loader: Callable[[Path, str, int], AcademicPeriodCalendar] = (
        load_academic_period_calendar_revision
    )
    period_lookup: Callable[[AcademicPeriodCalendar, str], AcademicPeriod] = (
        get_academic_period
    )


@dataclass(slots=True)
class PlanningDerivationChoiceCatalog:
    """Bounded saved-derivation choices, without any 'latest' inference."""

    navigation: TeacherNavigationContext
    readers: PlanningDerivationReaders = field(
        default_factory=PlanningDerivationReaders
    )

    def inspect(
        self, root: Path, class_id: str, derivation_id: str
    ) -> PlanningDerivationSummary:
        stored = self.readers.derivation_loader(root, class_id, derivation_id)
        snapshot = stored.snapshot
        if (
            snapshot.class_id != class_id
            or snapshot.derivation_id != derivation_id
            or stored.reference.class_id != class_id
            or stored.reference.derivation_id != derivation_id
            or stored.reference.derivation_sha256 != stored.derivation_sha256
        ):
            raise TeacherChoiceUnavailable("Saved derivation identity changed.")
        policy_ref = snapshot.policy_reference
        if policy_ref.class_id != class_id:
            raise TeacherChoiceUnavailable("Saved derivation policy is out of scope.")
        linked = self.readers.policy_loader(
            root, class_id, policy_ref.policy_id, policy_ref.policy_revision
        )
        if linked.reference != policy_ref:
            raise TeacherChoiceUnavailable("Saved derivation policy changed.")
        policy = linked.policy
        period_target = policy.academic_basis.target_period
        period_ref = period_target.period
        calendar = self.readers.calendar_loader(
            root, period_ref.school_year, period_target.calendar_revision
        )
        period = self.readers.period_lookup(calendar, period_ref.period_id)
        if (
            policy.class_id != class_id
            or policy.policy_id != policy_ref.policy_id
            or policy.policy_revision != policy_ref.policy_revision
            or policy.dimension_id != snapshot.dimension_id
            or policy.band_count != snapshot.band_count
            or period.period_id != period_ref.period_id
        ):
            raise TeacherChoiceUnavailable("Saved derivation dependency changed.")
        return PlanningDerivationSummary(
            derivation_id=derivation_id,
            derivation_sha256=stored.derivation_sha256,
            title=policy.title,
            period_label=period.label,
            school_year=period_ref.school_year,
            standard_id=policy.academic_basis.standard_id,
            dimension_id=snapshot.dimension_id,
            band_count=snapshot.band_count,
            student_count=len(snapshot.student_derivations),
            policy_id=policy_ref.policy_id,
            policy_revision=policy_ref.policy_revision,
            policy_sha256=policy_ref.policy_sha256,
            calculation_fingerprint=snapshot.calculation_fingerprint,
            revised_at=policy.revised_at.isoformat(),
        )

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "planning_derivation":
            raise TeacherChoiceUnavailable("Unsupported planning-choice scope.")
        current = self.navigation.current_class()
        if current is None or selected.get("class") != current.class_id:
            raise TeacherChoiceUnavailable("Choose a verified class first.")
        try:
            ids = self.readers.lister(current.workspace, current.class_id)
            if len(ids) > _MAX_DERIVATIONS or len(ids) != len(set(ids)):
                raise TeacherChoiceUnavailable(
                    "Saved derivation catalog exceeds safe limits. Use Advanced."
                )
            choices = []
            for derivation_id in ids:
                item = self.inspect(current.workspace, current.class_id, derivation_id)
                if item.school_year == current.school_year:
                    choices.append(item.choice())
            return tuple(choices)
        except TeacherChoiceUnavailable:
            raise
        except Exception as error:
            raise TeacherChoiceUnavailable(
                "Saved planning derivations could not be verified."
            ) from error


def _check_explanation(
    value: ExplanationPresentation,
    summary: PlanningDerivationSummary,
    class_id: str,
) -> tuple[str, ...]:
    """Prove the explanation is for the exact choice before displaying content."""
    lines = value.lines
    technical = value.technical_lines
    expected_lines = (
        f"Policy: {summary.title}",
        f"Academic Period: {summary.period_label}",
        f"Standard: {summary.standard_id}",
        f"Dimension: {summary.dimension_id}",
        f"Bands: {summary.band_count}",
        f"Roster students: {summary.student_count}",
    )
    expected_technical = (
        f"class_id: {class_id}",
        f"derivation_id: {summary.derivation_id}",
        f"derivation_sha256: {summary.derivation_sha256}",
        f"policy_id: {summary.policy_id}",
        f"policy_revision: {summary.policy_revision}",
        f"policy_sha256: {summary.policy_sha256}",
        f"calculation_fingerprint: {summary.calculation_fingerprint}",
    )
    if (
        value.title != "Planning Derivation Explanation"
        or not isinstance(lines, tuple)
        or not isinstance(technical, tuple)
        or any(not isinstance(text, str) for text in (*lines, *technical))
        or len(lines) != 8
        or any(lines.count(text) != 1 for text in expected_lines)
        or any(technical.count(text) != 1 for text in expected_technical)
        or not lines[6].startswith("Contributing students: ")
        or not lines[7].startswith("Noncontributing students: ")
    ):
        raise _DerivationChanged("Explanation scope or provenance changed.")
    counts = (lines[6].partition(": ")[2], lines[7].partition(": ")[2])
    if (
        any(
            not n.isascii() or not n.isdecimal() or (n.startswith("0") and n != "0")
            for n in counts
        )
        or sum(int(n) for n in counts) != summary.student_count
    ):
        raise _DerivationChanged("Planning participation totals changed.")
    return lines[6:]


def run_named_planning_derivation_explanation(
    *,
    navigation: TeacherNavigationContext,
    planning_derivation_explainer: PlanningDerivationExplainer,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    derivation_catalog: PlanningDerivationChoiceCatalog | None = None,
) -> None:
    """Explain an exact saved derivation without technical identifier entry."""
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        catalog = derivation_catalog or PlanningDerivationChoiceCatalog(navigation)
        active = _class(
            navigation, classes, input_fn=input_fn, output=output, clear_fn=clear_fn
        )
        if active is None:
            return
        root, class_id = active
        initial_class = navigation.current_class()
        if (
            initial_class is None
            or initial_class.workspace != root
            or initial_class.class_id != class_id
        ):
            raise _DerivationChanged("Class scope changed.")
        chosen = select_teacher_choice(
            catalog=catalog,
            scope="planning_derivation",
            selected={"class": class_id},
            title="Saved Planning Derivations",
            question="Which saved planning derivation should be explained?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen is None:
            return

        def check_scope() -> PlanningDerivationSummary:
            if navigation.current_class() != initial_class:
                raise _DerivationChanged("Class changed before explanation.")
            _current_choice(
                catalog,
                scope="planning_derivation",
                selected={"class": class_id},
                choice=chosen,
            )
            current = catalog.inspect(root, class_id, chosen.identity[0])
            if (
                current.school_year != initial_class.school_year
                or current.choice() != chosen
            ):
                raise _DerivationChanged("Saved derivation witness changed.")
            return current

        summary = check_scope()
        value = planning_derivation_explainer(root, class_id, summary.derivation_id)
        counts = _check_explanation(value, summary, class_id)
        if check_scope() != summary:
            raise _DerivationChanged("Saved derivation changed during read.")
        while True:
            if check_scope() != summary:
                raise _DerivationChanged("Saved derivation changed during review.")
            clear_fn()
            print_menu_header(output, "Saved Planning Derivation Explanation")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Academic period: {summary.period_label}",
                f"Standard: {summary.standard_id}",
                f"Dimension: {summary.dimension_id}",
                f"Bands: {summary.band_count}",
                f"Roster students: {summary.student_count}",
                *counts,
                "",
                "A saved derivation is not a current grouping decision.",
                "Read-only explanation; no planning or academic record changed.",
                "T. Technical details / provenance",
            )
            print_standard_navigation(output)
            choice = read_choice(input_fn)
            if choice.casefold() == "t":
                if check_scope() != summary:
                    raise _DerivationChanged("Saved derivation changed before details.")
                clear_fn()
                print_menu_header(output, "Planning Derivation — Technical Provenance")
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
    except (_DerivationChanged, _ScopeChanged):
        write_lines(
            output,
            "Class or saved planning derivation changed.",
            "No record was changed. Refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Saved planning derivation could not be verified safely.",
            "No record was changed. Use Advanced for exact diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = (
    "PlanningDerivationChoiceCatalog",
    "PlanningDerivationReaders",
    "run_named_planning_derivation_explanation",
)
