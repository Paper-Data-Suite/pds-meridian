"""Low-density protected-evidence review menu for Meridian issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
from meridian.new_evidence_eligibility_selection_workflow import (
    NewEvidenceEligibilitySelectionError,
    NewEvidenceEligibilitySelectionPreview,
    NewEvidenceEligibilitySelectionWorkflowResult,
    commit_new_evidence_eligibility_selection_preview,
    preview_new_evidence_eligibility_selection,
)
from meridian.new_evidence_eligibility_workflow import (
    NewEvidenceEligibilityAuthoringError,
    NewEvidenceEligibilityAuthoringPreview,
    NewEvidenceEligibilityAuthoringResult,
    TeacherEligibilityDisposition,
    commit_new_evidence_eligibility_preview,
    preview_new_evidence_eligibility_revision,
)
from meridian.new_evidence_workflow import (
    NewEvidenceReview,
    NewEvidenceWorkflowError,
    project_new_evidence_review,
)
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    ProjectionCacheError,
)

WorkspaceResolver: TypeAlias = Callable[[], Path]
EvidenceReviewLoader: TypeAlias = Callable[
    [Path, str, str, str, str, tuple[str, ...]],
    NewEvidenceReview,
]
Clock: TypeAlias = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class AuthorizedEvidenceContext:
    review: NewEvidenceReview
    authorized: AuthorizedProjectionSnapshot


EvidenceContextLoader: TypeAlias = Callable[
    [Path, str, str, str, str, tuple[str, ...]],
    AuthorizedEvidenceContext,
]
EligibilityAuthoringPreviewer: TypeAlias = Callable[
    [
        Path,
        AuthorizedEvidenceContext,
        str,
        TeacherEligibilityDisposition,
        str,
        str,
        str,
        tuple[str, ...],
        str | None,
        datetime,
    ],
    NewEvidenceEligibilityAuthoringPreview,
]
EligibilityAuthoringCommitter: TypeAlias = Callable[
    [Path, AuthorizedEvidenceContext, NewEvidenceEligibilityAuthoringPreview],
    NewEvidenceEligibilityAuthoringResult,
]
EligibilitySelectionPreviewer: TypeAlias = Callable[
    [Path, AuthorizedEvidenceContext, str, int],
    NewEvidenceEligibilitySelectionPreview,
]
EligibilitySelectionCommitter: TypeAlias = Callable[
    [Path, AuthorizedEvidenceContext, NewEvidenceEligibilitySelectionPreview],
    NewEvidenceEligibilitySelectionWorkflowResult,
]

_PAGE_SIZE = 10


@dataclass(frozen=True, slots=True)
class EvidenceMenuDependencies:
    """Explicit protected-evidence dependencies for the interactive boundary."""

    workspace_resolver: WorkspaceResolver
    diagnostics: DiagnosticsDependencies
    review_loader: EvidenceReviewLoader


@dataclass(frozen=True, slots=True)
class EvidenceActionDependencies:
    """Explicit authorized dependencies for consequential evidence actions."""

    clock: Clock
    context_loader: EvidenceContextLoader
    authoring_previewer: EligibilityAuthoringPreviewer
    authoring_committer: EligibilityAuthoringCommitter
    selection_previewer: EligibilitySelectionPreviewer
    selection_committer: EligibilitySelectionCommitter


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


def _load_context(
    root: Path,
    publication_id: str,
    cache_key: str,
    grade_item_id: str,
    purpose_id: str,
    student_ids: tuple[str, ...],
    *,
    diagnostics: DiagnosticsDependencies,
) -> AuthorizedEvidenceContext:
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
    review = project_new_evidence_review(
        root,
        class_id,
        grade_item_id,
        authorized,
    )
    return AuthorizedEvidenceContext(review=review, authorized=authorized)


def _preview_eligibility_authoring(
    root: Path,
    context: AuthorizedEvidenceContext,
    item_id: str,
    disposition: TeacherEligibilityDisposition,
    actor_id: str,
    policy_id: str,
    policy_version: str,
    reason_codes: tuple[str, ...],
    rationale: str | None,
    decided_at: datetime,
) -> NewEvidenceEligibilityAuthoringPreview:
    return preview_new_evidence_eligibility_revision(
        root,
        context.review,
        context.authorized,
        item_id=item_id,
        disposition=disposition,
        actor_id=actor_id,
        policy_id=policy_id,
        policy_version=policy_version,
        reason_codes=reason_codes,
        rationale=rationale,
        decided_at=decided_at,
    )


def _commit_eligibility_authoring(
    root: Path,
    context: AuthorizedEvidenceContext,
    preview: NewEvidenceEligibilityAuthoringPreview,
) -> NewEvidenceEligibilityAuthoringResult:
    return commit_new_evidence_eligibility_preview(
        root,
        preview,
        context.authorized,
    )


def _preview_eligibility_selection(
    root: Path,
    context: AuthorizedEvidenceContext,
    item_id: str,
    revision: int,
) -> NewEvidenceEligibilitySelectionPreview:
    return preview_new_evidence_eligibility_selection(
        root,
        context.review,
        context.authorized,
        item_id=item_id,
        eligibility_revision=revision,
    )


def _commit_eligibility_selection(
    root: Path,
    context: AuthorizedEvidenceContext,
    preview: NewEvidenceEligibilitySelectionPreview,
) -> NewEvidenceEligibilitySelectionWorkflowResult:
    return commit_new_evidence_eligibility_selection_preview(
        root,
        preview,
        context.authorized,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def default_evidence_action_dependencies(
    *,
    diagnostics: DiagnosticsDependencies | None = None,
) -> EvidenceActionDependencies:
    active = diagnostics or default_diagnostics_dependencies()

    def load(
        root: Path,
        publication_id: str,
        cache_key: str,
        grade_item_id: str,
        purpose_id: str,
        student_ids: tuple[str, ...],
    ) -> AuthorizedEvidenceContext:
        return _load_context(
            root,
            publication_id,
            cache_key,
            grade_item_id,
            purpose_id,
            student_ids,
            diagnostics=active,
        )

    return EvidenceActionDependencies(
        clock=_utc_now,
        context_loader=load,
        authoring_previewer=_preview_eligibility_authoring,
        authoring_committer=_commit_eligibility_authoring,
        selection_previewer=_preview_eligibility_selection,
        selection_committer=_commit_eligibility_selection,
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


def _positive_int(value: str, label: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f"{label} must be a positive integer") from error
    if result < 1:
        raise ValueError(f"{label} must be a positive integer")
    return result


def _reason_codes(raw: str) -> tuple[str, ...]:
    if not raw.strip():
        return ()
    return tuple(
        value.strip()
        for value in raw.split(",")
        if value.strip()
    )


def _teacher_disposition(value: str) -> TeacherEligibilityDisposition:
    choices: dict[str, TeacherEligibilityDisposition] = {
        "1": "included",
        "2": "excluded",
        "3": "pending",
        "4": "unsupported",
    }
    if value not in choices:
        raise ValueError("eligibility disposition must be 1, 2, 3, or 4")
    return choices[value]


def _authorized_scope(
    *,
    dependencies: EvidenceMenuDependencies,
    actions: EvidenceActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
) -> tuple[Path, AuthorizedEvidenceContext] | None:
    write_lines(
        output,
        "Protected evidence remains behind Meridian's authorization boundary.",
        "Open one exact prepared projection for this teacher action.",
        "",
    )
    publication_id = read_choice(input_fn, "Publication ID (blank to cancel): ")
    if not publication_id:
        return None
    navigation = parse_navigation_choice(publication_id)
    if navigation is NavigationChoice.BACK:
        return None
    cache_key = read_choice(input_fn, "Projection cache key: ")
    grade_item_id = read_choice(input_fn, "Grade Item ID: ")
    purpose_id = read_choice(input_fn, "Authorization purpose ID: ")
    raw_students = read_choice(
        input_fn,
        "Student IDs, comma-separated (blank for requested full scope): ",
    )
    root = dependencies.workspace_resolver()
    context = actions.context_loader(
        root,
        publication_id,
        cache_key,
        grade_item_id,
        purpose_id,
        _student_ids(raw_students),
    )
    return root, context


def _reviewed_student(review: NewEvidenceReview, item_id: str) -> str:
    for row in review.rows:
        if row.source.item_id == item_id:
            return row.student_id or "shared / nonstudent evidence"
    return "unknown"


def _author_eligibility(
    *,
    dependencies: EvidenceMenuDependencies,
    actions: EvidenceActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Author Evidence Eligibility Revision")
    try:
        loaded = _authorized_scope(
            dependencies=dependencies,
            actions=actions,
            input_fn=input_fn,
            output=output,
        )
        if loaded is None:
            return
        root, context = loaded
        item_id = read_choice(input_fn, "Evidence item ID: ")
        print("1. Included", file=output)
        print("2. Excluded", file=output)
        print("3. Pending", file=output)
        print("4. Unsupported", file=output)
        disposition = _teacher_disposition(
            read_choice(input_fn, "Eligibility disposition: ")
        )
        actor_id = read_choice(input_fn, "Teacher actor ID: ")
        policy_id = read_choice(input_fn, "Policy ID: ")
        policy_version = read_choice(input_fn, "Policy version: ")
        reason_codes = _reason_codes(
            read_choice(
                input_fn,
                "Reason codes, comma-separated (optional): ",
            )
        )
        rationale_text = read_choice(input_fn, "Rationale (optional): ")
        preview = actions.authoring_previewer(
            root,
            context,
            item_id,
            disposition,
            actor_id,
            policy_id,
            policy_version,
            reason_codes,
            rationale_text or None,
            actions.clock(),
        )
    except DiagnosticsAuthorizationProviderRequiredError:
        write_lines(
            output,
            "",
            "Protected evidence action is unavailable in this Meridian process.",
            "No evidence was opened and no eligibility revision was written.",
            "A deployment-provided authorization capability is required.",
        )
        pause_for_user(input_fn)
        return
    except (
        WorkspaceRootError,
        DiagnosticsError,
        ProjectionCacheError,
        NewEvidenceWorkflowError,
        NewEvidenceEligibilityAuthoringError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Eligibility preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    decision = preview.decision
    policy = decision.policy
    policy_label = (
        "none"
        if policy is None
        else f"{policy.policy_id} / {policy.policy_version}"
    )
    clear_fn()
    print_menu_header(output, "Review Eligibility Before Write")
    write_lines(
        output,
        f"Evidence item: {decision.source.item_id}",
        f"Student: {_reviewed_student(context.review, decision.source.item_id)}",
        f"Disposition: {_humanize(decision.disposition)}",
        f"Policy: {policy_label}",
        f"Candidate revision: {preview.candidate_revision}",
        f"Teacher: {decision.actor.actor_id}",
        (
            "Currently selected revision: none"
            if preview.selected_revision is None
            else f"Currently selected revision: {preview.selected_revision}"
        ),
        "",
        "This changes Meridian academic eligibility only.",
        "Core supersession/withdrawal state remains authoritative.",
        "Writing this revision will NOT select it.",
        "Type WRITE to create this exact eligibility revision.",
    )
    if read_choice(input_fn, "Confirmation: ") != "WRITE":
        write_lines(output, "", "No eligibility revision was written.")
        pause_for_user(input_fn)
        return

    try:
        result = actions.authoring_committer(root, context, preview)
    except NewEvidenceEligibilityAuthoringError as error:
        write_lines(
            output,
            "",
            "The reviewed eligibility revision could not be written safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    write_lines(
        output,
        "",
        f"Eligibility revision written: {result.written_revision}.",
        f"Disposition: {_humanize(result.written_disposition)}.",
        "Current eligibility selection was not changed.",
    )
    pause_for_user(input_fn)


def _select_eligibility(
    *,
    dependencies: EvidenceMenuDependencies,
    actions: EvidenceActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Select Evidence Eligibility Revision")
    try:
        loaded = _authorized_scope(
            dependencies=dependencies,
            actions=actions,
            input_fn=input_fn,
            output=output,
        )
        if loaded is None:
            return
        root, context = loaded
        item_id = read_choice(input_fn, "Evidence item ID: ")
        revision = _positive_int(
            read_choice(input_fn, "Eligibility revision to select: "),
            "eligibility revision",
        )
        preview = actions.selection_previewer(
            root,
            context,
            item_id,
            revision,
        )
    except DiagnosticsAuthorizationProviderRequiredError:
        write_lines(
            output,
            "",
            "Protected evidence action is unavailable in this Meridian process.",
            "No evidence was opened and no eligibility selection was changed.",
            "A deployment-provided authorization capability is required.",
        )
        pause_for_user(input_fn)
        return
    except (
        WorkspaceRootError,
        DiagnosticsError,
        ProjectionCacheError,
        NewEvidenceWorkflowError,
        NewEvidenceEligibilitySelectionError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Eligibility selection preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    decision = preview.target.decision
    clear_fn()
    print_menu_header(output, "Review Eligibility Selection")
    write_lines(
        output,
        f"Evidence item: {decision.source.item_id}",
        f"Target revision: {preview.target_revision}",
        f"Disposition: {_humanize(preview.target_disposition)}",
        f"Target sha256: {preview.target.decision_sha256}",
        (
            "Current revision: none"
            if preview.expected_current_revision is None
            else f"Current revision: {preview.expected_current_revision}"
        ),
        f"Membership revision basis: {preview.membership_revision}",
        f"Core source state: {_humanize(preview.source_state.state)}",
        "",
        "Type SELECT to make this exact eligibility revision current.",
    )
    if read_choice(input_fn, "Confirmation: ") != "SELECT":
        write_lines(output, "", "Current eligibility selection was not changed.")
        pause_for_user(input_fn)
        return

    try:
        result = actions.selection_committer(root, context, preview)
    except NewEvidenceEligibilitySelectionError as error:
        write_lines(
            output,
            "",
            "The reviewed eligibility revision could not be selected safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    write_lines(
        output,
        "",
        f"Eligibility selection: {result.selection_disposition}.",
        f"Selected revision: {result.selected_revision}.",
        f"Disposition: {_humanize(result.selected_disposition)}.",
    )
    pause_for_user(input_fn)


def run_new_evidence_menu(
    *,
    dependencies: EvidenceMenuDependencies | None = None,
    action_dependencies: EvidenceActionDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    """Run protected evidence review plus explicit eligibility follow-up."""

    stream = sys.stdout if output is None else output
    active = dependencies or default_evidence_menu_dependencies()
    actions = action_dependencies or default_evidence_action_dependencies(
        diagnostics=active.diagnostics,
    )
    while True:
        clear_fn()
        print_menu_header(stream, "Review New Evidence")
        write_lines(
            stream,
            "1. Review prepared protected evidence",
            "2. Author academic eligibility revision",
            "3. Select academic eligibility revision",
            "",
            "Grade Item, attempt, and standards follow-up remain separate tasks.",
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
        if choice == "2":
            _author_eligibility(
                dependencies=active,
                actions=actions,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "3":
            _select_eligibility(
                dependencies=active,
                actions=actions,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        write_lines(stream, "", "Please choose 1-3, B, M, or Q.")
        pause_for_user(input_fn)
