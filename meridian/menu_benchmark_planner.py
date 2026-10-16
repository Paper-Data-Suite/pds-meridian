"""Teacher-first benchmark planning from the authorized Report 9 preview.

Issue #117 Slice 7. Source report construction and authorization belong to the
existing live report executor; this controller does not read producer manifests,
repair evidence, open viewers, or create SIS/gradebook state.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, TextIO, TypeAlias, cast

from pds_core.classes import load_class_roster
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.rosters import Roster, RosterError
from pds_core.workspace import resolve_workspace_root

from meridian.benchmark_analysis import (
    BenchmarkInstructionalGroup,
    InstructionalResponse,
    TargetedInstructionResult,
)
from meridian.benchmark_plan_authoring import (
    BenchmarkPlanAuthoringError,
    BenchmarkPlanSourceChangedError,
    BenchmarkTeacherAnnotations,
    TeacherStandardAssessment,
    TeacherStandardJudgment,
    _evidence_rows,
    compose_teacher_benchmark_plan,
    save_teacher_benchmark_plan,
)
from meridian.benchmark_plan_notes import (
    BenchmarkPlanNotesError,
    load_benchmark_plan_notes,
    save_benchmark_plan_notes,
)
from meridian.benchmark_plan_storage import (
    BenchmarkPlanNotFoundError,
    BenchmarkPlanStorageError,
    BenchmarkPlanWriteResult,
    StoredBenchmarkPlanRevision,
    list_benchmark_plan_revisions,
    load_benchmark_plan_revision,
    load_latest_benchmark_plan_revision,
)
from meridian.report_guided_selection import ReportPreparedSelection
from meridian.teacher_report import TeacherReportPreview

Input: TypeAlias = Callable[[str], str]
Revalidator: TypeAlias = Callable[
    [ReportPreparedSelection, TeacherReportPreview | None], None
]


class BenchmarkPlannerMenuError(RuntimeError):
    """Current verified authorization or academic authority is unavailable."""


class _Cancelled(Exception):
    """The teacher deliberately cancelled this unsaved draft."""


@dataclass(frozen=True, slots=True)
class BenchmarkPlannerMenuServices:
    workspace_resolver: Callable[[], Path] = resolve_workspace_root
    roster_loader: Callable[[str | Path, str], Roster] = load_class_roster
    latest_loader: Callable[
        [str | Path, str, str], StoredBenchmarkPlanRevision
    ] = load_latest_benchmark_plan_revision
    history_lister: Callable[[str | Path, str, str], tuple[int, ...]] = (
        list_benchmark_plan_revisions
    )
    revision_loader: Callable[
        [str | Path, str, str, int], StoredBenchmarkPlanRevision
    ] = load_benchmark_plan_revision
    plan_writer: Callable[..., BenchmarkPlanWriteResult] = save_teacher_benchmark_plan
    notes_loader: Callable[
        [str | Path, StoredBenchmarkPlanRevision],
        BenchmarkTeacherAnnotations | None,
    ] = load_benchmark_plan_notes
    notes_writer: Callable[
        [str | Path, StoredBenchmarkPlanRevision, BenchmarkTeacherAnnotations],
        None,
    ] = save_benchmark_plan_notes


def _answer(input_fn: Input, prompt: str) -> str:
    value = input_fn(prompt).strip()
    if parse_navigation_choice(value) is NavigationChoice.BACK:
        raise _Cancelled
    return value


def _yes(input_fn: Input, prompt: str) -> bool:
    return _answer(input_fn, prompt).casefold() in {"y", "yes"}


def _date(input_fn: Input, prompt: str, *, required: bool = False) -> date | None:
    value = _answer(input_fn, prompt)
    if not value and not required:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise BenchmarkPlanAuthoringError(
            "Dates must use YYYY-MM-DD. The draft was not saved."
        ) from error


def _students(
    input_fn: Input,
    output: TextIO,
    students: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    if not students:
        return ()
    print("Select students by number (comma separated; blank for none):", file=output)
    for index, (_, label) in enumerate(students, 1):
        print(f"  {index}. {label}", file=output)
    raw = _answer(input_fn, "Student numbers: ")
    if not raw:
        return ()
    try:
        indexes = tuple(int(part.strip()) for part in raw.split(","))
    except ValueError as error:
        raise BenchmarkPlanAuthoringError(
            "Student selection must use displayed numbers."
        ) from error
    if not indexes or len(indexes) != len(set(indexes)) or any(
        number < 1 or number > len(students) for number in indexes
    ):
        raise BenchmarkPlanAuthoringError(
            "Student selections must be distinct and valid."
        )
    return tuple(sorted(students[number - 1][0] for number in indexes))


def _standards(
    input_fn: Input,
    output: TextIO,
    report: TeacherReportPreview,
) -> tuple[TeacherStandardAssessment, ...]:
    raw_choices = {
        row.values[1]
        for row in report.rows
        if row.values[0] == "2. Standards and Item Analysis"
        and row.values[2] not in {"Difficult item", "Patterns and observations"}
        and not (row.values[2] or "").startswith("Teacher judgment:")
    }
    choices = tuple(sorted(item for item in raw_choices if item is not None))
    if not choices:
        print("No producer-supported standard summaries available.", file=output)
        return ()
    judgments: dict[str, TeacherStandardJudgment] = {
        "s": "strong", "c": "challenging", "u": "unclassified"
    }
    selected: list[TeacherStandardAssessment] = []
    while len(selected) < len(choices) and _yes(
        input_fn, "Add a teacher judgment for a standard? (y/N): "
    ):
        used = {item.standard_id for item in selected}
        for index, name in enumerate(choices, 1):
            if name not in used:
                print(f"  {index}. {name}", file=output)
        value = _answer(input_fn, "Standard number: ")
        if not value.isdigit() or not 1 <= int(value) <= len(choices):
            raise BenchmarkPlanAuthoringError("Choose a displayed standard number.")
        standard_id = choices[int(value) - 1]
        if standard_id in used:
            raise BenchmarkPlanAuthoringError("This standard was already selected.")
        judgment_choice = _answer(
            input_fn, "Classification (S=strong, C=challenging, U=unclassified): "
        ).casefold()
        judgment = judgments.get(judgment_choice)
        if judgment is None:
            raise BenchmarkPlanAuthoringError("Choose S, C, or U.")
        basis = _answer(input_fn, "Evidence basis (blank if unclassified): ")
        comparable = False
        if judgment != "unclassified":
            comparable = _answer(
                input_fn, "Confirm this is comparable evidence (type YES): "
            ) == "YES"
        selected.append(
            TeacherStandardAssessment(standard_id, judgment, basis, comparable)
        )
    return tuple(selected)


def _groups(
    input_fn: Input,
    output: TextIO,
    students: tuple[tuple[str, str], ...],
) -> tuple[BenchmarkInstructionalGroup, ...]:
    groups: list[BenchmarkInstructionalGroup] = []
    while len(groups) < 10 and _yes(input_fn, "Add an instructional group? (y/N): "):
        label = _answer(input_fn, "Group name: ")
        selected = _students(input_fn, output, students)
        rationale = _answer(input_fn, "Why this group? ")
        groups.append(
            BenchmarkInstructionalGroup(
                f"group_{len(groups) + 1}", label, selected, rationale
            )
        )
    return tuple(groups)


def _comma_items(input_fn: Input, prompt: str) -> tuple[str, ...]:
    raw = _answer(input_fn, prompt)
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    return tuple(sorted(set(values)))


def _responses(
    input_fn: Input,
    output: TextIO,
    students: tuple[tuple[str, str], ...],
) -> tuple[InstructionalResponse, ...]:
    choices = ("reteach", "revisit", "small_group", "enrichment", "extension")
    responses: list[InstructionalResponse] = []
    while len(responses) < 10 and _yes(input_fn, "Add a teaching response? (y/N): "):
        print(
            "Response: 1 Reteach, 2 Revisit, 3 Small group, "
            "4 Enrichment, 5 Extension",
            file=output,
        )
        selected = _answer(input_fn, "Response number: ")
        if selected not in {"1", "2", "3", "4", "5"}:
            raise BenchmarkPlanAuthoringError("Choose response 1–5.")
        kind = choices[int(selected) - 1]
        target = _answer(input_fn, "Skill, standard, or item to address: ")
        selected_students = _students(input_fn, output, students)
        strategy = _answer(input_fn, "Instructional strategy or resource: ")
        planned = _date(input_fn, "Planned date (YYYY-MM-DD, optional): ")
        reassess = _date(input_fn, "Reassessment date (optional): ")
        rework = _comma_items(input_fn, "Rework item(s), if any (comma separated): ")
        retest = _comma_items(input_fn, "Retest target(s), if any (comma separated): ")
        status = _answer(
            input_fn,
            "Status (planned/in_progress/completed/paused/cancelled; blank=planned): ",
        ) or "planned"
        if status not in {
            "planned", "in_progress", "completed", "paused", "cancelled"
        }:
            raise BenchmarkPlanAuthoringError("Unsupported response status.")
        reflection = _answer(input_fn, "Teacher reflection (optional): ")
        responses.append(
            InstructionalResponse(
                response_id=f"response_{len(responses) + 1}",
                response_kind=cast(
                    Literal[
                        "reteach", "revisit", "small_group", "enrichment",
                        "extension",
                    ],
                    kind,
                ),
                target=target,
                student_ids=selected_students,
                strategy_resource=strategy,
                planned_date=planned,
                reevaluation_date=reassess,
                rework_items=rework,
                retest_targets=retest,
                status=cast(
                    Literal[
                        "planned", "in_progress", "completed", "paused",
                        "cancelled",
                    ],
                    status,
                ),
                teacher_reflection=reflection,
            )
        )
    return tuple(responses)


def _follow_up(
    input_fn: Input,
    output: TextIO,
    students: tuple[tuple[str, str], ...],
) -> TargetedInstructionResult | None:
    if not _yes(input_fn, "Record observed reassessment results? (y/N): "):
        return None
    tool = _answer(input_fn, "Reassessment tool: ")
    reassess_date = _date(input_fn, "Reassessment date (YYYY-MM-DD): ", required=True)
    if reassess_date is None:
        raise BenchmarkPlanAuthoringError("Reassessment date is required.")
    results = _answer(input_fn, "What did the follow-up show? ")
    remaining = _students(input_fn, output, students)
    standards_raw = _answer(
        input_fn, "Standards still needing attention (comma separated): "
    )
    standards = tuple(sorted(set(
        part.strip() for part in standards_raw.split(",") if part.strip()
    )))
    strategy = _answer(input_fn, "Additional support strategy: ")
    observations = _answer(input_fn, "Teacher observations: ")
    source = _answer(
        input_fn, "Follow-up evidence source ID (optional; blank=teacher observation): "
    )
    comparison = (
        _answer(input_fn, "Explicit comparison basis for this evidence: ")
        if source else None
    )
    return TargetedInstructionResult(
        tool, reassess_date, results, remaining, standards, strategy, observations,
        source or None, comparison,
    )


def _keep_saved(input_fn: Input, section: str) -> bool:
    """Default to keeping an existing section unless explicitly replaced."""
    answer = _answer(
        input_fn, f"Keep saved {section}? (Y/n, blank keeps): "
    ).casefold()
    if answer not in {"", "y", "yes", "n", "no"}:
        raise BenchmarkPlanAuthoringError("Choose Y or N for saved notes.")
    return answer in {"", "y", "yes"}


def _draft(
    input_fn: Input,
    output: TextIO,
    report: TeacherReportPreview,
    students: tuple[tuple[str, str], ...],
    *,
    existing: BenchmarkTeacherAnnotations | None = None,
) -> BenchmarkTeacherAnnotations:
    print(
        "Teacher planning notes do not change Grades, evidence, or proficiency.",
        file=output,
    )
    if existing is not None:
        print(
            "Existing teacher entries can be kept by pressing Enter. "
            "Choose N to replace or clear an entire section.",
            file=output,
        )
        print(
            f"Saved interpretation: {existing.interpretation or '(none)'}",
            file=output,
        )
        print(
            f"Saved judgments: {len(existing.standards)}; "
            f"groups: {len(existing.groups)}; "
            f"responses: {len(existing.responses)}; "
            f"reassessment: {'recorded' if existing.follow_up else 'none'}.",
            file=output,
        )
    interpretation = (
        existing.interpretation
        if existing is not None and _keep_saved(input_fn, "interpretation")
        else _answer(input_fn, "What patterns do you notice? (optional): ")
    )
    standards = (
        existing.standards
        if existing is not None and _keep_saved(input_fn, "standard judgments")
        else _standards(input_fn, output, report)
    )
    groups = (
        existing.groups
        if existing is not None and _keep_saved(input_fn, "instructional groups")
        else _groups(input_fn, output, students)
    )
    responses = (
        existing.responses
        if existing is not None and _keep_saved(input_fn, "teaching responses")
        else _responses(input_fn, output, students)
    )
    follow_up = (
        existing.follow_up
        if existing is not None and _keep_saved(input_fn, "reassessment notes")
        else _follow_up(input_fn, output, students)
    )
    return BenchmarkTeacherAnnotations(
        interpretation=interpretation,
        standards=standards,
        groups=groups,
        responses=responses,
        follow_up=follow_up,
    )


def _same_source(
    current: TeacherReportPreview,
    previous: TeacherReportPreview,
) -> bool:
    return (
        current.class_id == previous.class_id
        and current.target_period == previous.target_period
        and current.calendar_revision == previous.calendar_revision
        and current.title == previous.title
        and current.source_references == previous.source_references
        and current.columns == previous.columns
        and current.summary == previous.summary
        and current.diagnostics == previous.diagnostics
        and _evidence_rows(current) == _evidence_rows(previous)
    )


def _show_saved(
    output: TextIO,
    saved: StoredBenchmarkPlanRevision,
) -> None:
    print(
        f"Saved revision {saved.revision.plan_revision} "
        f"({saved.revision.currentness}; local teacher plan)",
        file=output,
    )
    print(
        "This is NOT an official gradebook or approved instructional plan.",
        file=output,
    )
    for row in saved.revision.report.rows:
        if row.row_id.startswith("zz_plan_"):
            print(
                f"  {row.values[1]}: {row.values[2]} — {row.values[3] or 'no entry'}",
                file=output,
            )
    print("Previous revisions remain unchanged.", file=output)


def run_benchmark_planner_menu(
    *,
    report: TeacherReportPreview,
    prepared: ReportPreparedSelection,
    revalidate: Revalidator | None,
    input_fn: Input = input,
    output: TextIO | None = None,
    services: BenchmarkPlannerMenuServices | None = None,
) -> None:
    """Create fresh plans or safely restore complete saved typed annotations.

    Legacy revisions lacking verified editable notes remain readable but may
    only be revised using a fresh, explicitly complete draft.
    """
    stream = sys.stdout if output is None else output
    if revalidate is None:
        print(
            "Live authorization checks are required for benchmark planning.",
            file=stream,
        )
        return
    if report.report_kind != "benchmark_analysis_instructional_response":
        raise BenchmarkPlannerMenuError("Only Report 9 supports planning.")
    identifiers = prepared.identifiers()
    class_id = identifiers.get("class")
    assessment_id = identifiers.get("grade_item")
    period_id = identifiers.get("period")
    if (
        class_id is None
        or assessment_id is None
        or period_id is None
        or class_id != report.class_id
        or period_id != report.target_period.period_id
    ):
        raise BenchmarkPlannerMenuError("The selected benchmark context is incomplete.")
    try:
        # Each segment is a canonical selection ID, not a filesystem path.
        for segment in (assessment_id, period_id):
            validate_identifier(segment)
    except IdentifierValidationError as error:
        raise BenchmarkPlannerMenuError(
            "Invalid canonical benchmark selection."
        ) from error
    plan_id = f"benchmark_{period_id}_{assessment_id}"
    active = services or BenchmarkPlannerMenuServices()
    try:
        root = active.workspace_resolver().resolve(strict=True)
        revalidate(prepared, report)
        roster = active.roster_loader(root, class_id)
        students = tuple(
            sorted(
                (
                    (student.student_id, f"{student.first_name} {student.last_name}")
                    for student in roster.students
                ),
                key=lambda pair: pair[1].casefold(),
            )
        )
        if len({student_id for student_id, _ in students}) != len(students):
            raise BenchmarkPlannerMenuError("The canonical roster is ambiguous.")
    except (OSError, RuntimeError, ValueError, RosterError):
        print(
            "Verified report and class roster are unavailable. No plan changed.",
            file=stream,
        )
        return

    while True:
        try:
            revalidate(prepared, report)
            try:
                latest = active.latest_loader(root, class_id, plan_id)
            except BenchmarkPlanNotFoundError:
                latest = None
        except (OSError, RuntimeError, ValueError):
            print(
                "Current authority could not be verified. No plan changed.",
                file=stream,
            )
            return
        print("", "Benchmark Analysis — Teacher Plan", sep="\n", file=stream)
        print(f"Assessment: {report.title}", file=stream)
        print(
            "1. Create plan" if latest is None else "1. Replace all planning notes",
            file=stream,
        )
        if latest is not None:
            print("2. Read the latest saved plan", file=stream)
            print("3. Browse earlier revisions", file=stream)
            print("4. Edit latest plan (keep saved sections by default)", file=stream)
        print("B. Return to report preview", file=stream)
        try:
            choice = _answer(input_fn, "Choice: ")
        except _Cancelled:
            return
        if choice in {"1", "4"} and (choice == "1" or latest is not None):
            existing_notes: BenchmarkTeacherAnnotations | None = None
            if choice == "4" and latest is not None:
                try:
                    revalidate(prepared, report)
                    if not _same_source(report, latest.revision.report):
                        raise BenchmarkPlanSourceChangedError(
                            "Saved benchmark source is stale."
                        )
                    existing_notes = active.notes_loader(root, latest)
                    revalidate(prepared, report)
                except (OSError, RuntimeError, ValueError):
                    print(
                        "Saved editing draft failed verification; no changes made.",
                        file=stream,
                    )
                    continue
                if existing_notes is None:
                    print(
                        "This legacy revision has no complete editable notes. "
                        "Choose 1 to author a new complete revision; stored "
                        "history remains available.",
                        file=stream,
                    )
                    continue
            if latest is not None and choice == "1":
                print(
                    "New revisions replace earlier teacher annotations. Re-enter "
                    "all groups, strategies and follow-up you want to retain; "
                    "earlier revisions remain available.",
                    file=stream,
                )
            try:
                teacher_id = (
                    latest.revision.teacher_id if latest is not None else _answer(
                        input_fn,
                        "Your local teacher identifier (letters/numbers/_/-): ",
                    )
                )
                validate_identifier(teacher_id)
                annotations = _draft(
                    input_fn, stream, report, students, existing=existing_notes
                )
                planned = compose_teacher_benchmark_plan(
                    report, annotations,
                    roster_student_ids=tuple(value for value, _ in students),
                )
                print("", "Unsaved teacher planning preview:", sep="\n", file=stream)
                for row in planned.rows:
                    if row.row_id.startswith("zz_plan_"):
                        print(
                            f"  {row.values[1]} / {row.values[2]}: "
                            f"{row.values[3] or 'not supplied'}",
                            file=stream,
                        )
                print(
                    "Native assessment results have not changed. No SIS update or "
                    "official approval is implied.", file=stream,
                )
                confirmation = _answer(
                    input_fn, "Type SAVE PLAN to append, or B to cancel: "
                )
                if confirmation != "SAVE PLAN":
                    print("Draft discarded. Nothing was saved.", file=stream)
                    continue
                # Require an up-to-date authorization/source check immediately
                # before writing. The storage layer independently verifies
                # the exact latest revision digest and baseline evidence.
                revalidate(prepared, report)
                result = active.plan_writer(
                    root,
                    report=report,
                    annotations=annotations,
                    roster_student_ids=tuple(value for value, _ in students),
                    plan_id=plan_id,
                    teacher_id=teacher_id,
                    assessment_id=assessment_id,
                    confirmation=confirmation,
                    expected_previous_revision_sha256=(
                        None if latest is None else latest.revision_sha256
                    ),
                )
                try:
                    active.notes_writer(root, result.stored, annotations)
                except (BenchmarkPlanNotesError, OSError):
                    print(
                        f"Revision {result.stored.revision.plan_revision} was "
                        "saved, but its editable draft could not be retained. "
                        "The saved report remains available in history.",
                        file=stream,
                    )
                    continue
                print(
                    f"Local benchmark plan revision "
                    f"{result.stored.revision.plan_revision} "
                    "saved. Earlier revisions remain unchanged.",
                    file=stream,
                )
            except _Cancelled:
                print("Draft cancelled. Nothing was saved.", file=stream)
            except (
                BenchmarkPlanAuthoringError,
                BenchmarkPlanStorageError,
                IdentifierValidationError,
                OSError,
                RuntimeError,
                ValueError,
            ):
                print(
                    "Plan could not be saved. Check the entries and refresh "
                    "current report authority before retrying.",
                    file=stream,
                )
            continue
        if choice == "2" and latest is not None:
            try:
                revalidate(prepared, report)
                if not _same_source(report, latest.revision.report):
                    raise BenchmarkPlanSourceChangedError("Report source changed.")
                _show_saved(stream, latest)
            except (OSError, RuntimeError, ValueError):
                print(
                    "Saved plan is not available under current authority.",
                    file=stream,
                )
            continue
        if choice == "3" and latest is not None:
            try:
                revalidate(prepared, report)
                revisions = active.history_lister(root, class_id, plan_id)
                print("Historical saved revisions:", file=stream)
                print(", ".join(str(item) for item in revisions), file=stream)
                selected = _answer(input_fn, "Revision number (blank to return): ")
                if selected:
                    if not selected.isdigit() or int(selected) not in revisions:
                        raise BenchmarkPlanAuthoringError("Choose a listed revision.")
                    historical = active.revision_loader(
                        root, class_id, plan_id, int(selected)
                    )
                    revalidate(prepared, report)
                    if not _same_source(report, historical.revision.report):
                        raise BenchmarkPlanSourceChangedError("Report source changed.")
                    _show_saved(stream, historical)
            except _Cancelled:
                pass
            except (OSError, RuntimeError, ValueError):
                print("History cannot be opened under current authority.", file=stream)
            continue
        print("Choose a displayed option, or B to return.", file=stream)


__all__ = ("BenchmarkPlannerMenuServices", "run_benchmark_planner_menu")
