"""Teacher-first, read-only scope selection for Meridian reports (Issue #111).

Slice 12.1 deliberately separates a transient selection from an authoritative
report request. It does not discover records, compute reports, or save anything.
Only an injected catalog may supply verified, teacher-readable choices.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Literal, Protocol, TextIO, TypeAlias

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

ReportScope: TypeAlias = Literal[
    "class", "period", "student", "grade_item", "checkpoint", "mapping"
]

SCOPE_PROMPTS: Final[dict[ReportScope, str]] = {
    "class": "Which class?",
    "period": "Which marking period?",
    "student": "Which student?",
    "grade_item": "Which assignment or assessment?",
    "checkpoint": "Which earlier reporting checkpoint?",
    "mapping": "Which external gradebook mapping?",
}


@dataclass(frozen=True, slots=True)
class ReportGuide:
    report_kind: str
    question: str
    explanation: str
    scopes: tuple[ReportScope, ...]
    advanced_command: str


REPORT_GUIDES: Final[tuple[ReportGuide, ...]] = (
    ReportGuide(
        "sis_gradebook_reconciliation",
        "What do I need to update in my gradebook?",
        "See which reporting judgments are new, changed, or need review. "
        "Works with a teacher-configured external gradebook mapping, not one SIS.",
        ("class", "period", "mapping"),
        "meridian reports reconciliation --help",
    ),
    ReportGuide(
        "student_current_grade_justification",
        "Why does this student have this grade?",
        "Explain an existing Grade using its selected evidence, policy, "
        "and any teacher override.",
        ("class", "period", "student"),
        "meridian reports justify --help",
    ),
    ReportGuide(
        "class_standards_profile",
        "How is my class doing on each standard?",
        "See selected proficiency judgments by student and standard, "
        "including gaps where no judgment exists.",
        ("class", "period"),
        "meridian reports standards profile --help",
    ),
    ReportGuide(
        "student_proficiency_growth",
        "How has a student progressed?",
        "Review recorded proficiency changes without assuming every "
        "change is an improvement.",
        ("class", "period", "student"),
        "meridian reports standards growth --help",
    ),
    ReportGuide(
        "evidence_coverage",
        "Who needs more evidence?",
        "Find missing, pending, or unresolved evidence without "
        "automatically treating it as low proficiency.",
        ("class", "period"),
        "meridian reports evidence --help",
    ),
    ReportGuide(
        "grade_checkpoint_comparison",
        "What changed since our last grade checkpoint?",
        "Compare an exact earlier reporting checkpoint with the "
        "current Grade picture.",
        ("class", "period", "checkpoint"),
        "meridian reports checkpoint --help",
    ),
    ReportGuide(
        "marking_period_readiness",
        "Am I ready to close the marking period?",
        "Review unresolved Meridian reporting conditions before "
        "an external marking-period close.",
        ("class", "period"),
        "meridian reports readiness --help",
    ),
    ReportGuide(
        "assessment_impact",
        "What did this assessment contribute?",
        "Review which results included an assignment; participation "
        "does not prove that it caused a Grade change.",
        ("class", "period", "grade_item"),
        "meridian reports impact --help",
    ),
)


class ReportSelectionUnavailable(RuntimeError):
    """The catalog cannot safely provide a required set of choices."""


def _readable(value: str, field: str, *, limit: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError(f"{field} must be a bounded, single-line value.")
    return value


@dataclass(frozen=True, slots=True)
class ReportOption:
    """Exact catalog identity and a bounded teacher-readable label."""

    value: str
    label: str
    detail: str | None = None

    def __post_init__(self) -> None:
        _readable(self.value, "option value", limit=256)
        _readable(self.label, "option label")
        if self.detail is not None:
            _readable(self.detail, "option detail")

    @property
    def display(self) -> str:
        if self.detail is not None:
            return f"{self.label} - {self.detail}"
        return self.label


@dataclass(frozen=True, slots=True)
class ReportPreparedSelection:
    """A transient plan; never a canonical academic or report record."""

    report_kind: str
    choices: tuple[tuple[ReportScope, ReportOption], ...]

    def identifiers(self) -> dict[ReportScope, str]:
        return {scope: option.value for scope, option in self.choices}


class ReportChoiceCatalog(Protocol):
    """Read-only provider of canonical, displayable options for one scope."""

    def options(
        self,
        *,
        report_kind: str,
        scope: ReportScope,
        selected: Mapping[ReportScope, str],
    ) -> tuple[ReportOption, ...]: ...


InputFunction: TypeAlias = Callable[[str], str]
ClearFunction: TypeAlias = Callable[[], None]


def _available_options(
    catalog: ReportChoiceCatalog,
    guide: ReportGuide,
    scope: ReportScope,
    current: Mapping[ReportScope, str],
) -> tuple[ReportOption, ...]:
    try:
        options = catalog.options(
            report_kind=guide.report_kind,
            scope=scope,
            selected=current,
        )
    except Exception as error:
        raise ReportSelectionUnavailable(
            "Could not safely enumerate report choices."
        ) from error
    if not isinstance(options, tuple) or any(
        not isinstance(option, ReportOption) for option in options
    ):
        raise ReportSelectionUnavailable("Invalid selection catalog response.")
    keys = [option.value for option in options]
    if len(keys) != len(set(keys)):
        raise ReportSelectionUnavailable("Ambiguous catalog identities.")
    display = [option.display.casefold() for option in options]
    if len(display) != len(set(display)):
        raise ReportSelectionUnavailable("Selections need distinct display labels.")
    return tuple(
        sorted(options, key=lambda item: (item.display.casefold(), item.value))
    )


def collect_guided_report_selection(
    guide: ReportGuide,
    *,
    catalog: ReportChoiceCatalog,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> ReportPreparedSelection | None:
    """Choose catalog-backed identities, confirming each; B reverses one step.

    Core-owned M/Q navigation exceptions propagate to the top-level menu.
    Empty/unsupported catalogs fail closed and do not produce a selection.
    """
    selected: list[tuple[ReportScope, ReportOption]] = []
    while len(selected) < len(guide.scopes):
        scope = guide.scopes[len(selected)]
        current: dict[ReportScope, str] = {
            key: item.value for key, item in selected
        }
        try:
            options = _available_options(catalog, guide, scope, current)
        except ReportSelectionUnavailable:
            print("The available choices could not be verified safely.", file=output)
            print("No report was generated or changed.", file=output)
            input_fn("Press Enter to return to this report...")
            return None
        if not options:
            print(
                f"No verified choices are available for: {SCOPE_PROMPTS[scope]}",
                file=output,
            )
            print("No report was generated or changed.", file=output)
            input_fn("Press Enter to return to this report...")
            return None
        clear_fn()
        print("Meridian / Reports", file=output)
        print(guide.question, file=output)
        print(f"Step {len(selected) + 1} of {len(guide.scopes)}", file=output)
        print(file=output)
        print(SCOPE_PROMPTS[scope], file=output)
        for number, item in enumerate(options, start=1):
            print(f"{number}. {item.display}", file=output)
        print(file=output)
        print("B. Back", file=output)
        print("M. Main Menu", file=output)
        print("Q. Quit", file=output)
        choice = input_fn("Choice: ").strip()
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or not choice:
            if selected:
                selected.pop()
                continue
            return None
        if not choice.isascii() or not choice.isdecimal():
            print("Choose a number from the list, or B to go back.", file=output)
            input_fn("Press Enter to try again...")
            continue
        number = int(choice)
        if number < 1 or number > len(options):
            print("Choose a number from the list, or B to go back.", file=output)
            input_fn("Press Enter to try again...")
            continue
        chosen = options[number - 1]
        try:
            refreshed = _available_options(catalog, guide, scope, current)
        except ReportSelectionUnavailable:
            print("The choices changed and could not be rechecked.", file=output)
            input_fn("Press Enter to return to this report...")
            return None
        if chosen not in refreshed:
            print("The choices changed. Please select again.", file=output)
            input_fn("Press Enter to try again...")
            continue
        selected.append((scope, chosen))
    return ReportPreparedSelection(guide.report_kind, tuple(selected))


__all__ = (
    "REPORT_GUIDES",
    "ReportChoiceCatalog",
    "ReportGuide",
    "ReportOption",
    "ReportPreparedSelection",
    "ReportScope",
    "ReportSelectionUnavailable",
    "collect_guided_report_selection",
)
