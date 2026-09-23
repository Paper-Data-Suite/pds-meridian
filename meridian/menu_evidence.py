"""Low-density protected-evidence review menu for Meridian issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.diagnostics import (
    DiagnosticsAuthorizationProviderRequiredError,
    DiagnosticsDependencies,
    DiagnosticsError,
    EvidenceFilters,
    default_diagnostics_dependencies,
    inspect_evidence_diagnostic,
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
from meridian.new_evidence_workflow import (
    NewEvidenceReview,
    NewEvidenceWorkflowError,
    project_new_evidence_review,
)
from meridian.projection_cache import ProjectionCacheError

WorkspaceResolver: TypeAlias = Callable[[], Path]
EvidenceReviewLoader: TypeAlias = Callable[
    [Path, str, str, str, str, tuple[str, ...]],
    NewEvidenceReview,
]

_PAGE_SIZE = 10


@dataclass(frozen=True, slots=True)
class EvidenceMenuDependencies:
    """Explicit protected-evidence dependencies for the interactive boundary."""

    workspace_resolver: WorkspaceResolver
    diagnostics: DiagnosticsDependencies
    review_loader: EvidenceReviewLoader


def _load_review(
    root: Path,
    publication_id: str,
    cache_key: str,
    grade_item_id: str,
    purpose_id: str,
    student_ids: tuple[str, ...],
    *,
    diagnostics: DiagnosticsDependencies,
) -> NewEvidenceReview:
    inspection = inspect_evidence_diagnostic(
        root,
        publication_id,
        cache_key,
        authorization_purpose_id=purpose_id,
        requested_student_ids=student_ids,
        filters=EvidenceFilters(),
        dependencies=diagnostics,
    )
    authorized = inspection.authorized
    class_id = authorized.stored.snapshot.source.publication.work.class_id
    return project_new_evidence_review(
        root,
        class_id,
        grade_item_id,
        authorized,
    )


def default_evidence_menu_dependencies(
    *,
    diagnostics: DiagnosticsDependencies | None = None,
) -> EvidenceMenuDependencies:
    """Build normal dependencies while preserving fail-closed authorization."""

    active = diagnostics or default_diagnostics_dependencies()

    def load(
        root: Path,
        publication_id: str,
        cache_key: str,
        grade_item_id: str,
        purpose_id: str,
        student_ids: tuple[str, ...],
    ) -> NewEvidenceReview:
        return _load_review(
            root,
            publication_id,
            cache_key,
            grade_item_id,
            purpose_id,
            student_ids,
            diagnostics=active,
        )

    return EvidenceMenuDependencies(
        workspace_resolver=resolve_workspace_root,
        diagnostics=active,
        review_loader=load,
    )


def _humanize(value: str) -> str:
    return value.replace("_", " ")


def _visible_row_status(review: NewEvidenceReview, index: int) -> str:
    row = review.rows[index]
    if row.attention_required and row.recommended_task is not None:
        return f"needs review — next: {_humanize(row.recommended_task)}"
    if row.eligibility_status is not None:
        return _humanize(row.eligibility_status)
    return _humanize(row.membership_state)


def _render_review(output: TextIO, review: NewEvidenceReview) -> None:
    print_menu_header(output, "New Evidence")
    write_lines(
        output,
        f"Grade Item: {review.grade_item_id}",
        f"Evidence rows: {len(review.rows)}",
        f"Need attention: {review.attention_count}",
        "",
    )
    if review.status_summary:
        print("Current status:", file=output)
        for summary in review.status_summary:
            print(f"  {_humanize(summary.status)}: {summary.count}", file=output)
        print(file=output)

    if not review.rows:
        print("No evidence rows are present in this authorized review.", file=output)
        return

    for index, row in enumerate(review.rows[:_PAGE_SIZE], start=1):
        student = row.student_id or "shared / nonstudent evidence"
        print(
            f"{index}. Student: {student} — {_visible_row_status(review, index - 1)}",
            file=output,
        )
        print(f"   Result kind: {_humanize(row.result_kind)}", file=output)

    remaining = len(review.rows) - _PAGE_SIZE
    if remaining > 0:
        print(
            f"... {remaining} more evidence rows not shown on this screen.",
            file=output,
        )


def _render_technical(output: TextIO, review: NewEvidenceReview) -> None:
    print_menu_header(output, "New Evidence — Technical details / provenance")
    write_lines(
        output,
        f"class_id: {review.class_id}",
        f"grade_item_id: {review.grade_item_id}",
        (
            "work: "
            f"{review.work.module_id}/{review.work.class_id}/{review.work.work_id}"
        ),
        f"publication_id: {review.publication_id}",
        f"cache_key: {review.cache_key}",
        f"snapshot_sha256: {review.snapshot_digest}",
        f"source_status: {review.projection_source_status}",
        f"membership_state: {review.membership_state}",
        (
            "membership_revision: "
            + (
                str(review.membership_revision)
                if review.membership_revision is not None
                else "none"
            )
        ),
    )
    for row in review.rows:
        print(
            "  "
            f"item={row.source.item_id}; "
            f"student={row.student_id or 'none'}; "
            f"membership={row.membership_state}; "
            f"eligibility={row.eligibility_status or 'not_evaluated'}",
            file=output,
        )


def _show_review(
    *,
    review: NewEvidenceReview,
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


def _student_ids(raw: str) -> tuple[str, ...]:
    if not raw.strip():
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _review_prepared_evidence(
    *,
    dependencies: EvidenceMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Review Prepared Evidence")
    write_lines(
        output,
        "Protected evidence remains behind Meridian's authorization boundary.",
        "This path opens one exact already-prepared projection.",
        "",
    )
    publication_id = read_choice(input_fn, "Publication ID (blank to cancel): ")
    if not publication_id:
        return
    navigation = parse_navigation_choice(publication_id)
    if navigation is NavigationChoice.BACK:
        return
    cache_key = read_choice(input_fn, "Projection cache key: ")
    grade_item_id = read_choice(input_fn, "Grade Item ID: ")
    purpose_id = read_choice(input_fn, "Authorization purpose ID: ")
    raw_students = read_choice(
        input_fn,
        "Student IDs, comma-separated (blank for requested full scope): ",
    )

    try:
        root = dependencies.workspace_resolver()
        review = dependencies.review_loader(
            root,
            publication_id,
            cache_key,
            grade_item_id,
            purpose_id,
            _student_ids(raw_students),
        )
    except DiagnosticsAuthorizationProviderRequiredError:
        write_lines(
            output,
            "",
            "Protected evidence review is unavailable in this Meridian process.",
            "No evidence was opened.",
            "A deployment-provided authorization capability is required.",
        )
        pause_for_user(input_fn)
        return
    except WorkspaceRootError as error:
        write_lines(
            output,
            "",
            "The Paper Data Suite workspace could not be resolved.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    except (
        DiagnosticsError,
        ProjectionCacheError,
        NewEvidenceWorkflowError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "The selected evidence could not be reviewed safely.",
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


def run_new_evidence_menu(
    *,
    dependencies: EvidenceMenuDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    """Run the read-only protected New Evidence menu for the current slice."""

    stream = sys.stdout if output is None else output
    active = dependencies or default_evidence_menu_dependencies()
    while True:
        clear_fn()
        print_menu_header(stream, "Review New Evidence")
        write_lines(
            stream,
            "1. Review prepared protected evidence",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or choice == "":
            return
        if choice == "1":
            _review_prepared_evidence(
                dependencies=active,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        write_lines(stream, "", "Please choose 1, B, M, or Q.")
        pause_for_user(input_fn)
