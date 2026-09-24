"""Low-density teacher menu for Meridian Grade Item review."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.routing_models import ModuleWorkRef
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.grade_item_authoring_workflow import (
    GradeItemAuthoringOperation,
    GradeItemAuthoringPreview,
    GradeItemAuthoringResult,
    GradeItemAuthoringWorkflowError,
    GradeItemWeightingAction,
    commit_grade_item_authoring_preview,
    preview_grade_item_authoring,
)
from meridian.grade_item_membership_authoring_workflow import (
    GradeItemMembershipAuthoringError,
    GradeItemMembershipAuthoringOperation,
    GradeItemMembershipAuthoringPreview,
    GradeItemMembershipAuthoringResult,
    commit_grade_item_membership_authoring_preview,
    preview_grade_item_membership_authoring,
)
from meridian.grade_item_membership_selection_workflow import (
    GradeItemMembershipSelectionPreview,
    GradeItemMembershipSelectionWorkflowError,
    GradeItemMembershipSelectionWorkflowResult,
    commit_grade_item_membership_selection_preview,
    preview_grade_item_membership_selection,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDisposition,
)
from meridian.grade_item_selection_workflow import (
    GradeItemSelectionPreview,
    GradeItemSelectionWorkflowError,
    GradeItemSelectionWorkflowResult,
    commit_grade_item_selection_preview,
    preview_grade_item_selection,
)
from meridian.grade_item_storage import GradeItemStorageError
from meridian.grade_items import GradeItemPurpose, GradeItemWeightingMetadata
from meridian.grade_items_workflow import (
    GradeItemsReview,
    GradeItemsWorkflowError,
    project_grade_items_review,
)
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

WorkspaceResolver: TypeAlias = Callable[[], Path]
GradeItemsReviewLoader: TypeAlias = Callable[[Path, str], GradeItemsReview]
Clock: TypeAlias = Callable[[], datetime]
GradeItemAuthoringPreviewer: TypeAlias = Callable[
    [
        Path,
        str,
        str,
        GradeItemAuthoringOperation,
        str,
        datetime,
        str | None,
        GradeItemPurpose | None,
        GradeItemWeightingMetadata | None,
        GradeItemWeightingAction | None,
    ],
    GradeItemAuthoringPreview,
]
GradeItemAuthoringCommitter: TypeAlias = Callable[
    [Path, GradeItemAuthoringPreview],
    GradeItemAuthoringResult,
]
GradeItemSelectionPreviewer: TypeAlias = Callable[
    [Path, str, str, int],
    GradeItemSelectionPreview,
]
GradeItemSelectionCommitter: TypeAlias = Callable[
    [Path, GradeItemSelectionPreview],
    GradeItemSelectionWorkflowResult,
]
MembershipAuthoringPreviewer: TypeAlias = Callable[
    [
        Path,
        str,
        str,
        ModuleWorkRef,
        GradeItemMembershipAuthoringOperation,
        int,
        int,
        GradeItemMembershipDisposition,
        str,
        datetime,
        GradeItemAcademicPeriodAssignment | None,
        str | None,
    ],
    GradeItemMembershipAuthoringPreview,
]
MembershipAuthoringCommitter: TypeAlias = Callable[
    [Path, GradeItemMembershipAuthoringPreview],
    GradeItemMembershipAuthoringResult,
]
MembershipSelectionPreviewer: TypeAlias = Callable[
    [Path, str, str, ModuleWorkRef, int],
    GradeItemMembershipSelectionPreview,
]
MembershipSelectionCommitter: TypeAlias = Callable[
    [Path, GradeItemMembershipSelectionPreview],
    GradeItemMembershipSelectionWorkflowResult,
]

_PAGE_SIZE = 10


@dataclass(frozen=True, slots=True)
class GradeItemsMenuDependencies:
    """Injected read services for deterministic menu testing and composition."""

    workspace_resolver: WorkspaceResolver
    review_loader: GradeItemsReviewLoader


@dataclass(frozen=True, slots=True)
class GradeItemsWriteDependencies:
    """Existing preview/commit services used by consequential menu actions."""

    clock: Clock
    authoring_previewer: GradeItemAuthoringPreviewer
    authoring_committer: GradeItemAuthoringCommitter
    selection_previewer: GradeItemSelectionPreviewer
    selection_committer: GradeItemSelectionCommitter
    membership_authoring_previewer: MembershipAuthoringPreviewer
    membership_authoring_committer: MembershipAuthoringCommitter
    membership_selection_previewer: MembershipSelectionPreviewer
    membership_selection_committer: MembershipSelectionCommitter


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _preview_authoring(
    root: Path,
    class_id: str,
    grade_item_id: str,
    operation: GradeItemAuthoringOperation,
    actor_id: str,
    revised_at: datetime,
    title: str | None,
    purpose: GradeItemPurpose | None,
    weighting: GradeItemWeightingMetadata | None,
    weighting_action: GradeItemWeightingAction | None,
) -> GradeItemAuthoringPreview:
    return preview_grade_item_authoring(
        root,
        class_id,
        grade_item_id,
        operation=operation,
        actor_id=actor_id,
        revised_at=revised_at,
        title=title,
        purpose=purpose,
        weighting=weighting,
        weighting_action=weighting_action,
    )


def _preview_membership_authoring(
    root: Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    operation: GradeItemMembershipAuthoringOperation,
    grade_item_revision: int,
    registration_revision: int,
    decision: GradeItemMembershipDisposition,
    actor_id: str,
    decided_at: datetime,
    academic_period: GradeItemAcademicPeriodAssignment | None,
    rationale: str | None,
) -> GradeItemMembershipAuthoringPreview:
    return preview_grade_item_membership_authoring(
        root,
        class_id,
        grade_item_id,
        work,
        operation=operation,
        grade_item_revision=grade_item_revision,
        registration_revision=registration_revision,
        decision=decision,
        actor_id=actor_id,
        decided_at=decided_at,
        academic_period=academic_period,
        rationale=rationale,
    )


def default_grade_items_write_dependencies() -> GradeItemsWriteDependencies:
    return GradeItemsWriteDependencies(
        clock=_utc_now,
        authoring_previewer=_preview_authoring,
        authoring_committer=commit_grade_item_authoring_preview,
        selection_previewer=preview_grade_item_selection,
        selection_committer=commit_grade_item_selection_preview,
        membership_authoring_previewer=_preview_membership_authoring,
        membership_authoring_committer=commit_grade_item_membership_authoring_preview,
        membership_selection_previewer=preview_grade_item_membership_selection,
        membership_selection_committer=commit_grade_item_membership_selection_preview,
    )


def default_grade_items_menu_dependencies() -> GradeItemsMenuDependencies:
    """Return production read dependencies without creating workspace state."""

    def load_review(root: Path, class_id: str) -> GradeItemsReview:
        return project_grade_items_review(root, class_id)

    return GradeItemsMenuDependencies(
        workspace_resolver=resolve_workspace_root,
        review_loader=load_review,
    )


def _humanize(value: str) -> str:
    return value.replace("_", " ")


def _render_review(output: TextIO, review: GradeItemsReview) -> None:
    print_menu_header(output, "Grade Items")
    write_lines(
        output,
        f"Class: {review.class_id}",
        (
            f"Grade Items: {len(review.items)} "
            f"({review.active_count} active, {review.archived_count} archived)"
        ),
        f"Without a current revision: {review.unselected_count}",
        f"Work relationships: {review.membership_relationship_count}",
        "",
    )
    if not review.items:
        write_lines(
            output,
            "No Grade Items have been created for this class.",
            "Nothing was inferred from publications, dates, or evidence.",
        )
        return

    for index, row in enumerate(review.items[:_PAGE_SIZE], start=1):
        title = row.title or "Grade Item without a current revision"
        status = _humanize(row.status or row.selection_state)
        print(f"{index}. {title} — {status}", file=output)
        if row.purpose:
            print(f"   Purpose: {row.purpose}", file=output)
        if row.memberships:
            print(f"   Work relationships: {len(row.memberships)}", file=output)

    remaining = len(review.items) - _PAGE_SIZE
    if remaining > 0:
        print(
            f"... {remaining} more Grade Items not shown on this screen.",
            file=output,
        )


def _render_technical(output: TextIO, review: GradeItemsReview) -> None:
    print_menu_header(output, "Grade Items — Technical details / provenance")
    print(f"class_id: {review.class_id}", file=output)
    if not review.items:
        print("No canonical Grade Item histories.", file=output)
        return
    for row in review.items:
        selected = (
            row.selected_revision
            if row.selected_revision is not None
            else "none"
        )
        print(
            f"{row.grade_item_id}: selected={selected}; "
            f"latest={row.latest_persisted_revision}; "
            f"selection={row.selection_state}",
            file=output,
        )
        for membership in row.memberships:
            membership_selected = (
                membership.selected_revision
                if membership.selected_revision is not None
                else "none"
            )
            print(
                "  "
                f"{membership.work.module_id}/{membership.work.work_id}: "
                f"selected={membership_selected}; "
                f"latest={membership.latest_persisted_revision}; "
                f"decision={membership.decision or 'none'}; "
                f"basis={membership.grade_item_basis_state}",
                file=output,
            )


def _show_review(
    *,
    review: GradeItemsReview,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    while True:
        clear_fn()
        _render_review(output, review)
        write_lines(output, "", "T. Technical details / provenance")
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if choice.casefold() == "t":
            clear_fn()
            _render_technical(output, review)
            write_lines(output, "")
            pause_for_user(input_fn)
            continue
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or choice == "":
            return
        write_lines(output, "", "Please choose T, B, M, or Q.")
        pause_for_user(input_fn)


def _review_grade_items(
    *,
    dependencies: GradeItemsMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Review Grade Items")
    class_id = read_choice(input_fn, "Class ID (leave blank to cancel): ")
    if not class_id:
        return
    navigation = parse_navigation_choice(class_id)
    if navigation is NavigationChoice.BACK:
        return

    try:
        root = dependencies.workspace_resolver()
        review = dependencies.review_loader(root, class_id)
    except WorkspaceRootError as error:
        write_lines(
            output,
            "",
            "The Paper Data Suite workspace could not be resolved.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    except (GradeItemsWorkflowError, GradeItemStorageError, ValueError) as error:
        write_lines(
            output,
            "",
            "Grade Item state could not be reviewed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    _show_review(
        review=review,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )



def _positive_int(value: str, label: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f"{label} must be a positive integer") from error
    if result < 1:
        raise ValueError(f"{label} must be a positive integer")
    return result


def _operation(value: str) -> GradeItemAuthoringOperation:
    choices: dict[str, GradeItemAuthoringOperation] = {
        "1": "create",
        "2": "revise",
        "3": "archive",
        "4": "reactivate",
    }
    if value not in choices:
        raise ValueError("operation must be 1, 2, 3, or 4")
    return choices[value]


def _purpose(value: str) -> GradeItemPurpose:
    choices: dict[str, GradeItemPurpose] = {
        "1": "standards_proficiency",
        "2": "conventional_grade",
        "3": "standards_and_conventional",
        "4": "reporting_only",
    }
    if value not in choices:
        raise ValueError("purpose must be 1, 2, 3, or 4")
    return choices[value]


def _weighting(
    input_fn: InputFunction,
    output: TextIO,
    *,
    operation: GradeItemAuthoringOperation,
) -> tuple[GradeItemWeightingMetadata | None, GradeItemWeightingAction | None]:
    if operation in {"archive", "reactivate"}:
        return None, "preserve"
    if operation == "create":
        write_lines(
            output,
            "Weighting metadata is optional and is not an executable Grade policy.",
        )
        choice = read_choice(
            input_fn,
            "Add reserved weighting metadata? (yes/no): ",
        ).casefold()
        if choice in {"n", "no"}:
            return None, "preserve"
        if choice not in {"y", "yes"}:
            raise ValueError("weighting choice must be yes or no")
        action: GradeItemWeightingAction = "replace"
    else:
        print("1. Preserve current weighting metadata", file=output)
        print("2. Clear weighting metadata", file=output)
        print("3. Replace weighting metadata", file=output)
        choice = read_choice(input_fn, "Weighting action: ")
        actions: dict[str, GradeItemWeightingAction] = {
            "1": "preserve",
            "2": "clear",
            "3": "replace",
        }
        if choice not in actions:
            raise ValueError("weighting action must be 1, 2, or 3")
        action = actions[choice]
        if action != "replace":
            return None, action

    category = read_choice(input_fn, "Weighting category ID (optional): ")
    relative_text = read_choice(input_fn, "Relative weight (optional): ")
    relative: Decimal | None = None
    if relative_text:
        try:
            relative = Decimal(relative_text)
        except InvalidOperation as error:
            raise ValueError("relative weight must be a decimal number") from error
    return (
        GradeItemWeightingMetadata(
            category_id=category or None,
            relative_weight=relative,
        ),
        action,
    )


def _membership_operation(value: str) -> GradeItemMembershipAuthoringOperation:
    if value == "1":
        return "create"
    if value == "2":
        return "revise"
    raise ValueError("membership operation must be 1 or 2")


def _membership_decision(value: str) -> GradeItemMembershipDisposition:
    if value == "1":
        return "included"
    if value == "2":
        return "excluded"
    raise ValueError("membership decision must be 1 or 2")


def _review_one_grade_item(
    *,
    dependencies: GradeItemsMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Grade Item and Work Relationships")
    class_id = read_choice(input_fn, "Class ID: ")
    grade_item_id = read_choice(input_fn, "Grade Item ID: ")
    try:
        review = dependencies.review_loader(
            dependencies.workspace_resolver(),
            class_id,
        )
        row = next(
            item for item in review.items if item.grade_item_id == grade_item_id
        )
    except StopIteration:
        write_lines(output, "", "That Grade Item is not present in the class review.")
        pause_for_user(input_fn)
        return
    except (
        WorkspaceRootError,
        GradeItemsWorkflowError,
        GradeItemStorageError,
    ) as error:
        write_lines(output, "", f"Grade Item review failed safely: {error}")
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Grade Item and Work Relationships")
    write_lines(
        output,
        f"Grade Item: {row.title or row.grade_item_id}",
        f"Status: {_humanize(row.status or row.selection_state)}",
        f"Purpose: {_humanize(row.purpose or 'not selected')}",
        (
            "Current revision: none"
            if row.selected_revision is None
            else f"Current revision: {row.selected_revision}"
        ),
        f"Latest authored revision: {row.latest_persisted_revision}",
        "",
        "Work relationships:",
    )
    if not row.memberships:
        print("  None.", file=output)
    for membership in row.memberships:
        assignment = "none"
        if membership.academic_period_id is not None:
            assignment = (
                f"{membership.academic_period_school_year} / "
                f"{membership.academic_period_id} "
                f"(calendar r{membership.academic_period_calendar_revision})"
            )
        print(
            f"  {membership.work.module_id}/{membership.work.work_id}"
            f" — {_humanize(membership.decision or membership.selection_state)}",
            file=output,
        )
        print(f"     Academic Period: {assignment}", file=output)
        selected = (
            "none"
            if membership.selected_revision is None
            else str(membership.selected_revision)
        )
        print(
            f"     Current membership revision: {selected}",
            file=output,
        )
    write_lines(output, "")
    pause_for_user(input_fn)


def _author_grade_item(
    *,
    dependencies: GradeItemsMenuDependencies,
    writes: GradeItemsWriteDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Author Grade Item Revision")
    class_id = read_choice(input_fn, "Class ID: ")
    grade_item_id = read_choice(input_fn, "Grade Item ID: ")
    print("1. Create", file=output)
    print("2. Revise", file=output)
    print("3. Archive", file=output)
    print("4. Reactivate", file=output)
    try:
        operation = _operation(read_choice(input_fn, "Operation: "))
        actor_id = read_choice(input_fn, "Teacher actor ID: ")
        title: str | None = None
        purpose: GradeItemPurpose | None = None
        if operation in {"create", "revise"}:
            title = read_choice(input_fn, "Title: ")
            print("1. Standards proficiency", file=output)
            print("2. Conventional Grade", file=output)
            print("3. Standards and conventional", file=output)
            print("4. Reporting only", file=output)
            purpose = _purpose(read_choice(input_fn, "Purpose: "))
        weighting, weighting_action = _weighting(
            input_fn,
            output,
            operation=operation,
        )
        preview = writes.authoring_previewer(
            dependencies.workspace_resolver(),
            class_id,
            grade_item_id,
            operation,
            actor_id,
            writes.clock(),
            title,
            purpose,
            weighting,
            weighting_action,
        )
    except (
        WorkspaceRootError,
        GradeItemAuthoringWorkflowError,
        ValueError,
    ) as error:
        write_lines(output, "", f"Grade Item preview failed safely: {error}")
        pause_for_user(input_fn)
        return

    candidate = preview.candidate
    clear_fn()
    print_menu_header(output, "Review Grade Item Before Write")
    write_lines(
        output,
        f"Operation: {_humanize(preview.operation)}",
        f"Grade Item: {candidate.title}",
        f"Purpose: {_humanize(candidate.purpose)}",
        f"Status: {_humanize(candidate.status)}",
        f"Revision: {candidate.grade_item_revision}",
        f"Candidate sha256: {preview.candidate_sha256}",
        f"Teacher: {preview.actor_id}",
        "",
        "Writing this immutable revision will NOT select it as current.",
        "Type WRITE to create this exact revision.",
    )
    if read_choice(input_fn, "Confirmation: ") != "WRITE":
        write_lines(output, "", "No Grade Item revision was written.")
        pause_for_user(input_fn)
        return

    try:
        result = writes.authoring_committer(
            dependencies.workspace_resolver(),
            preview,
        )
    except (WorkspaceRootError, GradeItemAuthoringWorkflowError) as error:
        write_lines(output, "", f"Grade Item write failed safely: {error}")
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Grade Item revision: {result.write_disposition}.",
        (
            "Current selected revision: none"
            if result.selected_revision_after is None
            else f"Current selected revision: {result.selected_revision_after}"
        ),
        "Selection was not changed by this write.",
    )
    pause_for_user(input_fn)


def _select_grade_item(
    *,
    dependencies: GradeItemsMenuDependencies,
    writes: GradeItemsWriteDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Select Grade Item Revision")
    class_id = read_choice(input_fn, "Class ID: ")
    grade_item_id = read_choice(input_fn, "Grade Item ID: ")
    try:
        revision = _positive_int(
            read_choice(input_fn, "Revision to select: "),
            "revision",
        )
        preview = writes.selection_previewer(
            dependencies.workspace_resolver(),
            class_id,
            grade_item_id,
            revision,
        )
    except (
        WorkspaceRootError,
        GradeItemSelectionWorkflowError,
        ValueError,
    ) as error:
        write_lines(output, "", f"Selection preview failed safely: {error}")
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review Grade Item Selection")
    write_lines(
        output,
        f"Grade Item: {preview.target.revision.title}",
        f"Target revision: {preview.target_revision}",
        f"Target status: {_humanize(preview.target_status)}",
        f"Target sha256: {preview.target.revision_sha256}",
        (
            "Current revision: none"
            if preview.expected_current_revision is None
            else f"Current revision: {preview.expected_current_revision}"
        ),
        f"Latest authored revision: {preview.latest_revision}",
        "",
        "Type SELECT to make this exact revision current.",
    )
    if read_choice(input_fn, "Confirmation: ") != "SELECT":
        write_lines(output, "", "Current Grade Item selection was not changed.")
        pause_for_user(input_fn)
        return

    try:
        result = writes.selection_committer(
            dependencies.workspace_resolver(),
            preview,
        )
    except (WorkspaceRootError, GradeItemSelectionWorkflowError) as error:
        write_lines(output, "", f"Grade Item selection failed safely: {error}")
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Grade Item selection: {result.selection_disposition}.",
        f"Selected revision: {result.selected_revision}.",
    )
    pause_for_user(input_fn)


def _work_ref(
    input_fn: InputFunction,
    class_id: str,
) -> ModuleWorkRef:
    module_id = read_choice(input_fn, "Producer module ID: ")
    work_id = read_choice(input_fn, "Work ID: ")
    return ModuleWorkRef(
        module_id=module_id,
        class_id=class_id,
        work_id=work_id,
    )


def _author_membership(
    *,
    dependencies: GradeItemsMenuDependencies,
    writes: GradeItemsWriteDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Author Work Membership Revision")
    class_id = read_choice(input_fn, "Class ID: ")
    grade_item_id = read_choice(input_fn, "Grade Item ID: ")
    try:
        work = _work_ref(input_fn, class_id)
        print("1. Create membership history", file=output)
        print("2. Revise membership history", file=output)
        operation = _membership_operation(read_choice(input_fn, "Operation: "))
        grade_item_revision = _positive_int(
            read_choice(input_fn, "Current Grade Item revision: "),
            "Grade Item revision",
        )
        registration_revision = _positive_int(
            read_choice(input_fn, "Core registration revision: "),
            "registration revision",
        )
        print("1. Included", file=output)
        print("2. Excluded", file=output)
        decision = _membership_decision(read_choice(input_fn, "Decision: "))
        academic_period: GradeItemAcademicPeriodAssignment | None = None
        if decision == "included":
            school_year = read_choice(input_fn, "School year (YYYY-YYYY): ")
            period_id = read_choice(input_fn, "Academic Period ID: ")
            calendar_revision = _positive_int(
                read_choice(input_fn, "Calendar revision: "),
                "calendar revision",
            )
            academic_period = GradeItemAcademicPeriodAssignment(
                period=AcademicPeriodRef(school_year, period_id),
                calendar_revision=calendar_revision,
            )
        actor_id = read_choice(input_fn, "Teacher actor ID: ")
        rationale_text = read_choice(input_fn, "Rationale (optional): ")
        preview = writes.membership_authoring_previewer(
            dependencies.workspace_resolver(),
            class_id,
            grade_item_id,
            work,
            operation,
            grade_item_revision,
            registration_revision,
            decision,
            actor_id,
            writes.clock(),
            academic_period,
            rationale_text or None,
        )
    except (
        WorkspaceRootError,
        GradeItemMembershipAuthoringError,
        ValueError,
    ) as error:
        write_lines(output, "", f"Membership preview failed safely: {error}")
        pause_for_user(input_fn)
        return

    candidate = preview.candidate
    assignment = "none"
    if candidate.academic_period is not None:
        assignment = (
            f"{candidate.academic_period.period.school_year} / "
            f"{candidate.academic_period.period.period_id} "
            f"(calendar r{candidate.academic_period.calendar_revision})"
        )
    clear_fn()
    print_menu_header(output, "Review Work Membership Before Write")
    write_lines(
        output,
        (
            f"Work: {candidate.work_reference.work.module_id}/"
            f"{candidate.work_reference.work.work_id}"
        ),
        f"Decision: {_humanize(candidate.decision)}",
        f"Membership revision: {candidate.membership_revision}",
        f"Grade Item revision basis: {candidate.grade_item_revision}",
        (
            "Core registration revision: "
            f"{candidate.work_reference.registration_revision}"
        ),
        f"Academic Period: {assignment}",
        f"Teacher: {candidate.actor_id}",
        "",
        "Writing this immutable decision will NOT select it as current.",
        "Type WRITE to create this exact membership revision.",
    )
    if read_choice(input_fn, "Confirmation: ") != "WRITE":
        write_lines(output, "", "No membership revision was written.")
        pause_for_user(input_fn)
        return

    try:
        result = writes.membership_authoring_committer(
            dependencies.workspace_resolver(),
            preview,
        )
    except (WorkspaceRootError, GradeItemMembershipAuthoringError) as error:
        write_lines(output, "", f"Membership write failed safely: {error}")
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Membership revision: {result.write_disposition}.",
        f"Written revision: {result.written_revision}.",
        "Current membership selection was not changed.",
    )
    pause_for_user(input_fn)


def _select_membership(
    *,
    dependencies: GradeItemsMenuDependencies,
    writes: GradeItemsWriteDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Select Work Membership Revision")
    class_id = read_choice(input_fn, "Class ID: ")
    grade_item_id = read_choice(input_fn, "Grade Item ID: ")
    try:
        work = _work_ref(input_fn, class_id)
        revision = _positive_int(
            read_choice(input_fn, "Membership revision to select: "),
            "membership revision",
        )
        preview = writes.membership_selection_previewer(
            dependencies.workspace_resolver(),
            class_id,
            grade_item_id,
            work,
            revision,
        )
    except (
        WorkspaceRootError,
        GradeItemMembershipSelectionWorkflowError,
        ValueError,
    ) as error:
        write_lines(output, "", f"Membership selection preview failed: {error}")
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review Work Membership Selection")
    write_lines(
        output,
        f"Work: {preview.work.module_id}/{preview.work.work_id}",
        f"Target revision: {preview.target_revision}",
        f"Decision: {_humanize(preview.target_decision)}",
        f"Grade Item revision basis: {preview.target_grade_item_revision}",
        f"Core registration revision: {preview.target_registration_revision}",
        f"Target sha256: {preview.target.decision_sha256}",
        (
            "Current membership revision: none"
            if preview.expected_current_membership_revision is None
            else (
                "Current membership revision: "
                f"{preview.expected_current_membership_revision}"
            )
        ),
        "",
        "Type SELECT to make this exact membership decision current.",
    )
    if read_choice(input_fn, "Confirmation: ") != "SELECT":
        write_lines(output, "", "Current membership selection was not changed.")
        pause_for_user(input_fn)
        return

    try:
        result = writes.membership_selection_committer(
            dependencies.workspace_resolver(),
            preview,
        )
    except (
        WorkspaceRootError,
        GradeItemMembershipSelectionWorkflowError,
    ) as error:
        write_lines(output, "", f"Membership selection failed safely: {error}")
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Membership selection: {result.selection_disposition}.",
        f"Selected revision: {result.selected_revision}.",
        f"Decision: {_humanize(result.selected_decision)}.",
    )
    pause_for_user(input_fn)


def run_grade_items_menu(
    *,
    dependencies: GradeItemsMenuDependencies | None = None,
    write_dependencies: GradeItemsWriteDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    """Run the Grade Item review/author/select teacher menu."""

    stream = sys.stdout if output is None else output
    active = dependencies or default_grade_items_menu_dependencies()
    writes = write_dependencies or default_grade_items_write_dependencies()
    while True:
        clear_fn()
        print_menu_header(stream, "Manage Grade Items")
        write_lines(
            stream,
            "1. Review Grade Items",
            "2. Review one Grade Item and work relationships",
            "3. Author Grade Item revision",
            "4. Select Grade Item revision",
            "5. Author work membership revision",
            "6. Select work membership revision",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or choice == "":
            return
        if choice == "1":
            _review_grade_items(
                dependencies=active,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "2":
            _review_one_grade_item(
                dependencies=active,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "3":
            _author_grade_item(
                dependencies=active,
                writes=writes,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "4":
            _select_grade_item(
                dependencies=active,
                writes=writes,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "5":
            _author_membership(
                dependencies=active,
                writes=writes,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "6":
            _select_membership(
                dependencies=active,
                writes=writes,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        write_lines(stream, "", "Please choose 1-6, B, M, or Q.")
        pause_for_user(input_fn)
