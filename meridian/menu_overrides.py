"""Teacher-facing Grade override workflows for Meridian issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.grade_policy import GradeCalculationFamily
from meridian.menu_grades import WorkEvidenceProvider
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    clear_screen,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.teacher_grade_override_lifecycle import (
    TeacherGradeOverrideSelectionPreview,
    TeacherGradeOverrideWithdrawalPreview,
    commit_teacher_grade_override_selection_preview,
    commit_teacher_grade_override_withdrawal_preview,
    preview_teacher_grade_override_selection,
    preview_teacher_grade_override_withdrawal,
)
from meridian.teacher_grade_override_storage import (
    TeacherGradeOverrideStorageError,
    list_teacher_grade_override_revisions,
    load_current_teacher_grade_override,
    load_teacher_grade_override_revision,
)
from meridian.teacher_grade_override_workflow import (
    TeacherGradeOverrideAuthoringPreview,
    TeacherGradeOverrideWorkflowError,
    commit_teacher_grade_override_authoring_preview,
    preview_teacher_grade_override_authoring,
)

WorkspaceResolver: TypeAlias = Callable[[], Path]
Clock: TypeAlias = Callable[[], datetime]


class OverrideMenuEvidenceUnavailableError(RuntimeError):
    """Raised when override freshness needs explicit authorized work evidence."""


@dataclass(frozen=True, slots=True)
class OverrideScope:
    class_id: str
    student_id: str
    period: AcademicPeriodRef
    calendar_revision: int
    family: GradeCalculationFamily


@dataclass(frozen=True, slots=True)
class OverrideReviewPresentation:
    scope: OverrideScope
    selected: bool
    decision: str | None
    override_revision: int | None
    override_sha256: str | None
    replacement_grade: str | None
    actor_id: str | None
    rationale: str | None
    source_result_revision: int | None
    source_result_sha256: str | None


@dataclass(frozen=True, slots=True)
class OverrideAuthoringPlan:
    scope: OverrideScope
    replacement_grade: str
    source_status: str
    source_grade: str | None
    source_freshness: str
    candidate_revision: int
    candidate_sha256: str
    actor_id: str
    rationale: str
    preview: TeacherGradeOverrideAuthoringPreview = field(repr=False)


@dataclass(frozen=True, slots=True)
class OverrideSelectionPlan:
    scope: OverrideScope
    target_revision: int
    target_sha256: str
    target_decision: str
    replacement_grade: str | None
    current_revision: int | None
    current_sha256: str | None
    preview: TeacherGradeOverrideSelectionPreview = field(repr=False)


@dataclass(frozen=True, slots=True)
class OverrideWithdrawalPlan:
    scope: OverrideScope
    selected_revision: int
    selected_sha256: str
    source_status: str
    source_grade: str | None
    candidate_revision: int
    candidate_sha256: str
    actor_id: str
    rationale: str
    preview: TeacherGradeOverrideWithdrawalPreview = field(repr=False)


OverrideReviewLoader: TypeAlias = Callable[
    [Path, OverrideScope],
    OverrideReviewPresentation,
]
OverrideAuthoringPreviewer: TypeAlias = Callable[
    [Path, OverrideScope, Decimal, str, str, datetime],
    OverrideAuthoringPlan,
]
OverrideAuthoringCommitter: TypeAlias = Callable[
    [Path, OverrideAuthoringPlan],
    str,
]
OverrideSelectionPreviewer: TypeAlias = Callable[
    [Path, OverrideScope],
    OverrideSelectionPlan,
]
OverrideSelectionCommitter: TypeAlias = Callable[
    [Path, OverrideSelectionPlan],
    str,
]
OverrideWithdrawalPreviewer: TypeAlias = Callable[
    [Path, OverrideScope, str, str, datetime],
    OverrideWithdrawalPlan,
]
OverrideWithdrawalCommitter: TypeAlias = Callable[
    [Path, OverrideWithdrawalPlan],
    str,
]


@dataclass(frozen=True, slots=True)
class OverrideMenuDependencies:
    workspace_resolver: WorkspaceResolver
    clock: Clock
    review_loader: OverrideReviewLoader
    authoring_previewer: OverrideAuthoringPreviewer
    authoring_committer: OverrideAuthoringCommitter
    selection_previewer: OverrideSelectionPreviewer
    selection_committer: OverrideSelectionCommitter
    withdrawal_previewer: OverrideWithdrawalPreviewer
    withdrawal_committer: OverrideWithdrawalCommitter


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _decimal_text(value: object | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _work_evidence(
    provider: WorkEvidenceProvider | None,
    root: Path,
    scope: OverrideScope,
) -> tuple[ConventionalGradeWorkEvidenceSpec, ...] | None:
    if scope.family == "standards_based":
        return None
    if provider is None:
        family = scope.family.replace("_", " ")
        raise OverrideMenuEvidenceUnavailableError(
            f"{family} override authoring requires an explicit authorized "
            "work-evidence provider. No protected evidence was opened."
        )
    return provider(
        root,
        scope.class_id,
        scope.student_id,
        scope.period,
        scope.calendar_revision,
        scope.family,
    )


def _review_override(
    root: Path,
    scope: OverrideScope,
) -> OverrideReviewPresentation:
    stored = load_current_teacher_grade_override(
        root,
        scope.class_id,
        scope.student_id,
        scope.period,
        scope.calendar_revision,
        scope.family,
    )
    if stored is None:
        return OverrideReviewPresentation(
            scope=scope,
            selected=False,
            decision=None,
            override_revision=None,
            override_sha256=None,
            replacement_grade=None,
            actor_id=None,
            rationale=None,
            source_result_revision=None,
            source_result_sha256=None,
        )
    decision = stored.decision
    source = decision.source_result.reference
    return OverrideReviewPresentation(
        scope=scope,
        selected=True,
        decision=decision.decision,
        override_revision=decision.override_revision,
        override_sha256=stored.override_sha256,
        replacement_grade=_decimal_text(decision.replacement_grade),
        actor_id=decision.actor.actor_id,
        rationale=decision.rationale,
        source_result_revision=source.result_revision,
        source_result_sha256=source.result_sha256,
    )


def _preview_authoring(
    root: Path,
    scope: OverrideScope,
    replacement_grade: Decimal,
    actor_id: str,
    rationale: str,
    decided_at: datetime,
    *,
    provider: WorkEvidenceProvider | None,
) -> OverrideAuthoringPlan:
    work_evidence = _work_evidence(provider, root, scope)
    preview = preview_teacher_grade_override_authoring(
        root,
        scope.class_id,
        scope.student_id,
        scope.period,
        scope.calendar_revision,
        scope.family,
        replacement_grade=replacement_grade,
        actor_id=actor_id,
        rationale=rationale,
        decided_at=decided_at,
        work_evidence=work_evidence,
    )
    return OverrideAuthoringPlan(
        scope=scope,
        replacement_grade=format(replacement_grade, "f"),
        source_status=preview.source.source_status,
        source_grade=_decimal_text(preview.source.base_grade),
        source_freshness=preview.source.freshness_status,
        candidate_revision=preview.candidate.override_revision,
        candidate_sha256=preview.candidate_sha256,
        actor_id=preview.candidate.actor.actor_id,
        rationale=preview.candidate.rationale,
        preview=preview,
    )


def _commit_authoring(
    root: Path,
    plan: OverrideAuthoringPlan,
) -> str:
    result = commit_teacher_grade_override_authoring_preview(root, plan.preview)
    return result.write_disposition


def _preview_selection(
    root: Path,
    scope: OverrideScope,
) -> OverrideSelectionPlan:
    revisions = list_teacher_grade_override_revisions(
        root,
        scope.class_id,
        scope.student_id,
        scope.period,
        scope.calendar_revision,
        scope.family,
    )
    if not revisions:
        raise TeacherGradeOverrideWorkflowError(
            "No authored override decisions exist for this Grade scope."
        )
    stored = load_teacher_grade_override_revision(
        root,
        scope.class_id,
        scope.student_id,
        scope.period,
        scope.calendar_revision,
        scope.family,
        revisions[-1],
    )
    preview = preview_teacher_grade_override_selection(root, stored.reference)
    current = preview.expected_current
    return OverrideSelectionPlan(
        scope=scope,
        target_revision=preview.target_reference.override_revision,
        target_sha256=preview.target_reference.override_sha256,
        target_decision=preview.target_decision.decision,
        replacement_grade=_decimal_text(
            preview.target_decision.replacement_grade
        ),
        current_revision=(
            None if current is None else current.override_revision
        ),
        current_sha256=(
            None if current is None else current.override_sha256
        ),
        preview=preview,
    )


def _commit_selection(
    root: Path,
    plan: OverrideSelectionPlan,
) -> str:
    result = commit_teacher_grade_override_selection_preview(
        root,
        plan.preview,
    )
    return result.selection_disposition


def _preview_withdrawal(
    root: Path,
    scope: OverrideScope,
    actor_id: str,
    rationale: str,
    decided_at: datetime,
) -> OverrideWithdrawalPlan:
    preview = preview_teacher_grade_override_withdrawal(
        root,
        scope.class_id,
        scope.student_id,
        scope.period,
        scope.calendar_revision,
        scope.family,
        actor_id=actor_id,
        rationale=rationale,
        decided_at=decided_at,
    )
    selected = preview.selected_override_reference
    return OverrideWithdrawalPlan(
        scope=scope,
        selected_revision=selected.override_revision,
        selected_sha256=selected.override_sha256,
        source_status=preview.source.source_status,
        source_grade=_decimal_text(preview.source.base_grade),
        candidate_revision=preview.candidate.override_revision,
        candidate_sha256=preview.candidate_sha256,
        actor_id=preview.candidate.actor.actor_id,
        rationale=preview.candidate.rationale,
        preview=preview,
    )


def _commit_withdrawal(
    root: Path,
    plan: OverrideWithdrawalPlan,
) -> str:
    result = commit_teacher_grade_override_withdrawal_preview(
        root,
        plan.preview,
    )
    return result.write_disposition


def default_override_menu_dependencies(
    *,
    work_evidence_provider: WorkEvidenceProvider | None = None,
) -> OverrideMenuDependencies:
    def preview_authoring(
        root: Path,
        scope: OverrideScope,
        replacement_grade: Decimal,
        actor_id: str,
        rationale: str,
        decided_at: datetime,
    ) -> OverrideAuthoringPlan:
        return _preview_authoring(
            root,
            scope,
            replacement_grade,
            actor_id,
            rationale,
            decided_at,
            provider=work_evidence_provider,
        )

    return OverrideMenuDependencies(
        workspace_resolver=resolve_workspace_root,
        clock=_utc_now,
        review_loader=_review_override,
        authoring_previewer=preview_authoring,
        authoring_committer=_commit_authoring,
        selection_previewer=_preview_selection,
        selection_committer=_commit_selection,
        withdrawal_previewer=_preview_withdrawal,
        withdrawal_committer=_commit_withdrawal,
    )


def _family(value: str) -> GradeCalculationFamily | None:
    values: dict[str, GradeCalculationFamily] = {
        "1": "conventional",
        "2": "standards_based",
        "3": "hybrid",
    }
    return values.get(value)


def _positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise ValueError("calendar revision must be a positive integer")
    return result


def _scope(input_fn: InputFunction, output: TextIO) -> OverrideScope:
    class_id = read_choice(input_fn, "Class ID: ")
    student_id = read_choice(input_fn, "Student ID: ")
    school_year = read_choice(input_fn, "School year (YYYY-YYYY): ")
    period_id = read_choice(input_fn, "Academic Period ID: ")
    calendar_revision = _positive_int(
        read_choice(input_fn, "Calendar revision: ")
    )
    write_lines(
        output,
        "",
        "1. Conventional",
        "2. Standards based",
        "3. Hybrid",
    )
    family = _family(read_choice(input_fn, "Calculation family: "))
    if family is None:
        raise ValueError("calculation family must be 1, 2, or 3")
    return OverrideScope(
        class_id=class_id,
        student_id=student_id,
        period=AcademicPeriodRef(school_year, period_id),
        calendar_revision=calendar_revision,
        family=family,
    )


def _show_review(
    value: OverrideReviewPresentation,
    *,
    output: TextIO,
) -> None:
    print_menu_header(output, "Current Grade Override")
    write_lines(
        output,
        f"Student: {value.scope.student_id}",
        (
            "Academic Period: "
            f"{value.scope.period.school_year} / {value.scope.period.period_id}"
        ),
        f"Calculation family: {value.scope.family.replace('_', ' ')}",
    )
    if not value.selected:
        write_lines(output, "", "Selected override: none")
        return
    write_lines(
        output,
        f"Decision: {value.decision}",
        f"Replacement Grade: {value.replacement_grade or 'not applicable'}",
        f"Teacher: {value.actor_id or 'unavailable'}",
        f"Rationale: {value.rationale or 'none'}",
    )


def _show_review_technical(
    value: OverrideReviewPresentation,
    *,
    output: TextIO,
) -> None:
    print_menu_header(
        output,
        "Current Grade Override — Technical details / provenance",
    )
    write_lines(
        output,
        f"class_id: {value.scope.class_id}",
        f"student_id: {value.scope.student_id}",
        f"calendar_revision: {value.scope.calendar_revision}",
        f"override_revision: {value.override_revision or 'none'}",
        f"override_sha256: {value.override_sha256 or 'none'}",
        f"source_result_revision: {value.source_result_revision or 'none'}",
        f"source_result_sha256: {value.source_result_sha256 or 'none'}",
    )


def _review_current(
    *,
    deps: OverrideMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Review Current Override")
    try:
        scope = _scope(input_fn, output)
        value = deps.review_loader(deps.workspace_resolver(), scope)
    except (
        WorkspaceRootError,
        TeacherGradeOverrideStorageError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Current override state could not be reviewed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    while True:
        clear_fn()
        _show_review(value, output=output)
        write_lines(output, "", "T. Technical details / provenance")
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if choice.casefold() == "t":
            clear_fn()
            _show_review_technical(value, output=output)
            write_lines(output, "")
            pause_for_user(input_fn)
            continue
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        write_lines(output, "", "Please choose T, B, M, or Q.")
        pause_for_user(input_fn)


def _author_override(
    *,
    deps: OverrideMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Author Grade Override")
    try:
        scope = _scope(input_fn, output)
        replacement = Decimal(
            read_choice(input_fn, "Replacement Grade: ")
        )
        actor_id = read_choice(input_fn, "Teacher actor ID: ")
        rationale = read_choice(input_fn, "Rationale: ")
        plan = deps.authoring_previewer(
            deps.workspace_resolver(),
            scope,
            replacement,
            actor_id,
            rationale,
            deps.clock(),
        )
    except (
        WorkspaceRootError,
        OverrideMenuEvidenceUnavailableError,
        TeacherGradeOverrideWorkflowError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Override authoring preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review Override Before Write")
    write_lines(
        output,
        f"Student: {plan.scope.student_id}",
        f"Replacement Grade: {plan.replacement_grade}",
        f"Selected base result: {plan.source_status}",
        f"Base Grade: {plan.source_grade or 'not numeric'}",
        f"Base freshness: {plan.source_freshness}",
        f"Teacher: {plan.actor_id}",
        f"Rationale: {plan.rationale}",
        f"New immutable override revision: {plan.candidate_revision}",
        "",
        "Writing this revision will NOT select it for effective Grade use.",
        "Type WRITE to create the exact reviewed revision.",
    )
    confirmation = read_choice(input_fn, "Confirmation: ")
    if confirmation != "WRITE":
        write_lines(output, "", "No override revision was written.")
        pause_for_user(input_fn)
        return
    try:
        disposition = deps.authoring_committer(
            deps.workspace_resolver(),
            plan,
        )
    except (WorkspaceRootError, TeacherGradeOverrideWorkflowError) as error:
        write_lines(
            output,
            "",
            "The reviewed override could not be committed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Override revision: {disposition}.",
        "It is not current until explicitly selected.",
    )
    pause_for_user(input_fn)


def _select_latest(
    *,
    deps: OverrideMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Select Latest Authored Override")
    try:
        scope = _scope(input_fn, output)
        plan = deps.selection_previewer(
            deps.workspace_resolver(),
            scope,
        )
    except (
        WorkspaceRootError,
        TeacherGradeOverrideStorageError,
        TeacherGradeOverrideWorkflowError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Override selection preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review Override Selection")
    write_lines(
        output,
        f"Student: {plan.scope.student_id}",
        f"Decision: {plan.target_decision}",
        f"Target revision: {plan.target_revision}",
        f"Target sha256: {plan.target_sha256}",
        (
            "Replacement Grade: "
            f"{plan.replacement_grade or 'not applicable'}"
        ),
        (
            "Currently selected revision: "
            f"{plan.current_revision or 'none'}"
        ),
        "",
        "Type SELECT to make this exact revision current.",
    )
    confirmation = read_choice(input_fn, "Confirmation: ")
    if confirmation != "SELECT":
        write_lines(output, "", "Current override selection was not changed.")
        pause_for_user(input_fn)
        return
    try:
        disposition = deps.selection_committer(
            deps.workspace_resolver(),
            plan,
        )
    except (WorkspaceRootError, TeacherGradeOverrideWorkflowError) as error:
        write_lines(
            output,
            "",
            "The reviewed override selection could not be committed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Override selection: {disposition}.",
    )
    pause_for_user(input_fn)


def _withdraw_override(
    *,
    deps: OverrideMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Withdraw Current Override")
    try:
        scope = _scope(input_fn, output)
        actor_id = read_choice(input_fn, "Teacher actor ID: ")
        rationale = read_choice(input_fn, "Withdrawal rationale: ")
        plan = deps.withdrawal_previewer(
            deps.workspace_resolver(),
            scope,
            actor_id,
            rationale,
            deps.clock(),
        )
    except (
        WorkspaceRootError,
        TeacherGradeOverrideStorageError,
        TeacherGradeOverrideWorkflowError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Override withdrawal preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review Override Withdrawal")
    write_lines(
        output,
        f"Student: {plan.scope.student_id}",
        f"Selected override revision: {plan.selected_revision}",
        f"Selected override sha256: {plan.selected_sha256}",
        f"Base result: {plan.source_status}",
        f"Base Grade: {plan.source_grade or 'not numeric'}",
        f"New withdrawal revision: {plan.candidate_revision}",
        f"Withdrawal sha256: {plan.candidate_sha256}",
        f"Teacher: {plan.actor_id}",
        f"Rationale: {plan.rationale}",
        "",
        "Type WITHDRAW to write this exact immutable withdrawal revision.",
    )
    if read_choice(input_fn, "Confirmation: ") != "WITHDRAW":
        write_lines(output, "", "No withdrawal revision was written.")
        pause_for_user(input_fn)
        return

    try:
        disposition = deps.withdrawal_committer(
            deps.workspace_resolver(),
            plan,
        )
    except (WorkspaceRootError, TeacherGradeOverrideWorkflowError) as error:
        write_lines(
            output,
            "",
            "The reviewed withdrawal could not be committed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    write_lines(
        output,
        "",
        f"Withdrawal revision: {disposition}.",
        "The prior override remains current until the withdrawal is selected.",
    )

    try:
        selection = deps.selection_previewer(
            deps.workspace_resolver(),
            plan.scope,
        )
    except (WorkspaceRootError, TeacherGradeOverrideWorkflowError) as error:
        write_lines(
            output,
            "",
            "The withdrawal was written, but selection preview is unavailable.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    write_lines(
        output,
        "",
        f"Latest authored decision: {selection.target_decision}",
        f"Target revision: {selection.target_revision}",
        f"Target sha256: {selection.target_sha256}",
        "Type SELECT to make the withdrawal current now.",
    )
    if read_choice(input_fn, "Confirmation: ") != "SELECT":
        write_lines(
            output,
            "",
            "Withdrawal revision is stored; current override selection is unchanged.",
        )
        pause_for_user(input_fn)
        return
    try:
        selection_disposition = deps.selection_committer(
            deps.workspace_resolver(),
            selection,
        )
    except (WorkspaceRootError, TeacherGradeOverrideWorkflowError) as error:
        write_lines(
            output,
            "",
            "Withdrawal was written, but current selection was not changed.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Withdrawal selection: {selection_disposition}.",
        "Effective Grade precedence can now return to the selected base result.",
    )
    pause_for_user(input_fn)


def run_overrides_menu(
    *,
    dependencies: OverrideMenuDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    stream = sys.stdout if output is None else output
    deps = dependencies or default_override_menu_dependencies()
    while True:
        clear_fn()
        print_menu_header(stream, "Overrides")
        write_lines(
            stream,
            "1. Review current override",
            "2. Author a new override revision",
            "3. Select the latest authored override",
            "4. Withdraw the current override",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        if choice == "1":
            _review_current(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "2":
            _author_override(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "3":
            _select_latest(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "4":
            _withdraw_override(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        write_lines(stream, "", "Please choose 1-4, B, M, or Q.")
        pause_for_user(input_fn)
