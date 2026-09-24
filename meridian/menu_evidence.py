"""Low-density protected-evidence review menu for Meridian issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.routing_models import ModuleWorkRef
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.attempt_decision_authoring_workflow import (
    AttemptDecisionAuthoringPreview,
    AttemptDecisionAuthoringResult,
    AttemptDecisionAuthoringWorkflowError,
    commit_attempt_decision_authoring_preview,
    preview_attempt_decision_authoring,
)
from meridian.attempt_decision_selection_workflow import (
    AttemptDecisionSelectionPreview,
    AttemptDecisionSelectionWorkflowError,
    AttemptDecisionSelectionWorkflowResult,
    commit_attempt_decision_selection_preview,
    preview_attempt_decision_selection,
)
from meridian.attempt_selection import AttemptObservationReference
from meridian.attempt_selection_storage import (
    AttemptCandidateDerivation,
    AttemptSelectionStorageError,
    derive_attempt_candidates,
)
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
AttemptCandidateLoader: TypeAlias = Callable[
    [Path, AuthorizedEvidenceContext, str],
    AttemptCandidateDerivation,
]
AttemptAuthoringPreviewer: TypeAlias = Callable[
    [
        Path,
        AuthorizedEvidenceContext,
        str,
        str,
        tuple[AttemptObservationReference, ...],
        str,
        str | None,
        datetime,
    ],
    AttemptDecisionAuthoringPreview,
]
AttemptAuthoringCommitter: TypeAlias = Callable[
    [Path, AuthorizedEvidenceContext, AttemptDecisionAuthoringPreview],
    AttemptDecisionAuthoringResult,
]
AttemptSelectionPreviewer: TypeAlias = Callable[
    [Path, AuthorizedEvidenceContext, str, int],
    AttemptDecisionSelectionPreview,
]
AttemptSelectionCommitter: TypeAlias = Callable[
    [Path, AuthorizedEvidenceContext, AttemptDecisionSelectionPreview],
    AttemptDecisionSelectionWorkflowResult,
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


@dataclass(frozen=True, slots=True)
class AttemptActionDependencies:
    """Explicit authorized services for student attempt-decision actions."""

    clock: Clock
    context_loader: EvidenceContextLoader
    candidate_loader: AttemptCandidateLoader
    authoring_previewer: AttemptAuthoringPreviewer
    authoring_committer: AttemptAuthoringCommitter
    selection_previewer: AttemptSelectionPreviewer
    selection_committer: AttemptSelectionCommitter


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


def _attempt_work(context: AuthorizedEvidenceContext) -> ModuleWorkRef:
    return context.authorized.stored.snapshot.source.publication.work


def _load_attempt_candidates(
    root: Path,
    context: AuthorizedEvidenceContext,
    student_id: str,
) -> AttemptCandidateDerivation:
    work = _attempt_work(context)
    return derive_attempt_candidates(
        root,
        work.class_id,
        context.review.grade_item_id,
        student_id,
        context.authorized,
    )


def _preview_attempt_authoring(
    root: Path,
    context: AuthorizedEvidenceContext,
    student_id: str,
    policy_id: str,
    selected_attempts: tuple[AttemptObservationReference, ...],
    actor_id: str,
    rationale: str | None,
    decided_at: datetime,
) -> AttemptDecisionAuthoringPreview:
    work = _attempt_work(context)
    return preview_attempt_decision_authoring(
        root,
        work.class_id,
        context.review.grade_item_id,
        work,
        student_id,
        policy_id,
        authorized_snapshot=context.authorized,
        selected_attempts=selected_attempts,
        actor_id=actor_id,
        decided_at=decided_at,
        rationale=rationale,
    )


def _commit_attempt_authoring(
    root: Path,
    context: AuthorizedEvidenceContext,
    preview: AttemptDecisionAuthoringPreview,
) -> AttemptDecisionAuthoringResult:
    return commit_attempt_decision_authoring_preview(
        root,
        preview,
        authorized_snapshot=context.authorized,
    )


def _preview_attempt_selection(
    root: Path,
    context: AuthorizedEvidenceContext,
    student_id: str,
    decision_revision: int,
) -> AttemptDecisionSelectionPreview:
    work = _attempt_work(context)
    return preview_attempt_decision_selection(
        root,
        work.class_id,
        context.review.grade_item_id,
        work,
        student_id,
        decision_revision,
        authorized_snapshot=context.authorized,
    )


def _commit_attempt_selection(
    root: Path,
    context: AuthorizedEvidenceContext,
    preview: AttemptDecisionSelectionPreview,
) -> AttemptDecisionSelectionWorkflowResult:
    return commit_attempt_decision_selection_preview(
        root,
        preview,
        authorized_snapshot=context.authorized,
    )


def default_attempt_action_dependencies(
    *,
    diagnostics: DiagnosticsDependencies | None = None,
) -> AttemptActionDependencies:
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

    return AttemptActionDependencies(
        clock=_utc_now,
        context_loader=load,
        candidate_loader=_load_attempt_candidates,
        authoring_previewer=_preview_attempt_authoring,
        authoring_committer=_commit_attempt_authoring,
        selection_previewer=_preview_attempt_selection,
        selection_committer=_commit_attempt_selection,
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


def _attempt_scope(
    *,
    dependencies: EvidenceMenuDependencies,
    attempts: AttemptActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
) -> tuple[Path, AuthorizedEvidenceContext, str] | None:
    write_lines(
        output,
        "Attempt decisions are student-scoped and use one exact authorized projection.",
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
    student_id = read_choice(input_fn, "Student ID: ")
    root = dependencies.workspace_resolver()
    context = attempts.context_loader(
        root,
        publication_id,
        cache_key,
        grade_item_id,
        purpose_id,
        (student_id,),
    )
    return root, context, student_id


def _candidate_label(attempt: AttemptObservationReference) -> str:
    native = attempt.native
    if native.sequence is not None and native.identifier is not None:
        return f"sequence {native.sequence}; identifier {native.identifier}"
    if native.sequence is not None:
        return f"sequence {native.sequence}"
    return f"identifier {native.identifier}"


def _parse_sequences(raw: str) -> tuple[int, ...]:
    if not raw.strip():
        return ()
    values: list[int] = []
    for part in raw.split(","):
        value = _positive_int(part.strip(), "attempt sequence")
        if value in values:
            raise ValueError("attempt sequences must not contain duplicates")
        values.append(value)
    return tuple(values)


def _parse_identifiers(raw: str) -> tuple[str, ...]:
    if not raw.strip():
        return ()
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    if len(set(values)) != len(values):
        raise ValueError("attempt identifiers must not contain duplicates")
    return values


def _resolve_attempt_selection(
    derivation: AttemptCandidateDerivation,
    sequences: tuple[int, ...],
    identifiers: tuple[str, ...],
) -> tuple[AttemptObservationReference, ...]:
    if derivation.status != "applicable":
        raise ValueError(
            "Current attempt candidates are not applicable; "
            f"status is {derivation.status}."
        )
    selected: list[AttemptObservationReference] = []
    for field_name, values in (
        ("sequence", sequences),
        ("identifier", identifiers),
    ):
        for value in values:
            matches = tuple(
                candidate.attempt
                for candidate in derivation.candidates
                if getattr(candidate.attempt.native, field_name) == value
            )
            if len(matches) != 1:
                raise ValueError(
                    f"Attempt {field_name} {value!r} must match exactly one "
                    "current candidate."
                )
            if matches[0] in selected:
                raise ValueError(
                    "Multiple selectors resolved to the same attempt candidate."
                )
            selected.append(matches[0])
    return tuple(
        candidate.attempt
        for candidate in derivation.candidates
        if candidate.attempt in selected
    )


def _author_attempt_decision(
    *,
    dependencies: EvidenceMenuDependencies,
    attempts: AttemptActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Author Attempt / Reassessment Decision")
    try:
        loaded = _attempt_scope(
            dependencies=dependencies,
            attempts=attempts,
            input_fn=input_fn,
            output=output,
        )
        if loaded is None:
            return
        root, context, student_id = loaded
        derivation = attempts.candidate_loader(root, context, student_id)
        if derivation.status != "applicable":
            raise ValueError(
                "Current attempt candidates are not applicable; "
                f"status is {derivation.status}."
            )
        write_lines(output, "", "Current eligible attempt candidates:")
        if not derivation.candidates:
            print("  None.", file=output)
        for index, attempt_candidate in enumerate(
            derivation.candidates,
            start=1,
        ):
            print(
                f"  {index}. {_candidate_label(attempt_candidate.attempt)}",
                file=output,
            )
        write_lines(
            output,
            "",
            "Select exact native attempts. Leave both selectors blank for none.",
        )
        sequences = _parse_sequences(
            read_choice(
                input_fn,
                "Selected attempt sequences, comma-separated (optional): ",
            )
        )
        identifiers = _parse_identifiers(
            read_choice(
                input_fn,
                "Selected attempt identifiers, comma-separated (optional): ",
            )
        )
        selected = _resolve_attempt_selection(
            derivation,
            sequences,
            identifiers,
        )
        policy_id = read_choice(input_fn, "Attempt-selection policy ID: ")
        actor_id = read_choice(input_fn, "Teacher actor ID: ")
        rationale_text = read_choice(input_fn, "Rationale (optional): ")
        preview = attempts.authoring_previewer(
            root,
            context,
            student_id,
            policy_id,
            selected,
            actor_id,
            rationale_text or None,
            attempts.clock(),
        )
    except DiagnosticsAuthorizationProviderRequiredError:
        write_lines(
            output,
            "",
            "Protected attempt evidence is unavailable in this Meridian process.",
            "No attempt decision was written.",
            "A deployment-provided authorization capability is required.",
        )
        pause_for_user(input_fn)
        return
    except (
        WorkspaceRootError,
        DiagnosticsError,
        ProjectionCacheError,
        AttemptSelectionStorageError,
        AttemptDecisionAuthoringWorkflowError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Attempt decision preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    candidate = preview.candidate
    clear_fn()
    print_menu_header(output, "Review Attempt Decision Before Write")
    write_lines(
        output,
        f"Student: {candidate.student_id}",
        f"Candidate attempts: {preview.candidate_count}",
        f"Selected attempts: {preview.selected_count}",
        f"Policy: {candidate.policy.policy_id}",
        f"Policy revision: {candidate.policy.policy_revision}",
        f"Decision revision: {candidate.decision_revision}",
        (
            "Currently selected decision revision: none"
            if preview.reviewed_current_decision_revision is None
            else (
                "Currently selected decision revision: "
                f"{preview.reviewed_current_decision_revision}"
            )
        ),
        "",
        "This writes one explicit student attempt/reassessment decision.",
        "It does not mutate producer attempt history.",
        "Writing this revision will NOT select it.",
        "Type WRITE to create this exact decision revision.",
    )
    for attempt in candidate.selected_attempts:
        print(f"  Selected: {_candidate_label(attempt)}", file=output)
    if read_choice(input_fn, "Confirmation: ") != "WRITE":
        write_lines(output, "", "No attempt decision revision was written.")
        pause_for_user(input_fn)
        return

    try:
        result = attempts.authoring_committer(root, context, preview)
    except AttemptDecisionAuthoringWorkflowError as error:
        write_lines(
            output,
            "",
            "The reviewed attempt decision could not be written safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    write_lines(
        output,
        "",
        f"Attempt decision revision: {result.write_disposition}.",
        f"Written revision: {result.written_revision}.",
        "Current attempt-decision selection was not changed.",
    )
    pause_for_user(input_fn)


def _select_attempt_decision(
    *,
    dependencies: EvidenceMenuDependencies,
    attempts: AttemptActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Select Attempt / Reassessment Decision")
    try:
        loaded = _attempt_scope(
            dependencies=dependencies,
            attempts=attempts,
            input_fn=input_fn,
            output=output,
        )
        if loaded is None:
            return
        root, context, student_id = loaded
        revision = _positive_int(
            read_choice(input_fn, "Decision revision to select: "),
            "decision revision",
        )
        preview = attempts.selection_previewer(
            root,
            context,
            student_id,
            revision,
        )
    except DiagnosticsAuthorizationProviderRequiredError:
        write_lines(
            output,
            "",
            "Protected attempt evidence is unavailable in this Meridian process.",
            "No attempt-decision selection was changed.",
            "A deployment-provided authorization capability is required.",
        )
        pause_for_user(input_fn)
        return
    except (
        WorkspaceRootError,
        DiagnosticsError,
        ProjectionCacheError,
        AttemptSelectionStorageError,
        AttemptDecisionSelectionWorkflowError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Attempt decision selection preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    decision = preview.target.decision
    clear_fn()
    print_menu_header(output, "Review Attempt Decision Selection")
    write_lines(
        output,
        f"Student: {decision.student_id}",
        f"Target revision: {preview.target_revision}",
        f"Target sha256: {preview.target_sha256}",
        f"Selected attempts: {len(decision.selected_attempts)}",
        f"Candidate attempts: {len(decision.candidates)}",
        f"Policy: {decision.policy.policy_id}",
        f"Policy revision: {decision.policy.policy_revision}",
        (
            "Current decision revision: none"
            if preview.expected_current_decision_revision is None
            else (
                "Current decision revision: "
                f"{preview.expected_current_decision_revision}"
            )
        ),
        "",
        "Type SELECT to make this exact decision revision current.",
    )
    if read_choice(input_fn, "Confirmation: ") != "SELECT":
        write_lines(output, "", "Current attempt-decision selection was not changed.")
        pause_for_user(input_fn)
        return

    try:
        result = attempts.selection_committer(root, context, preview)
    except AttemptDecisionSelectionWorkflowError as error:
        write_lines(
            output,
            "",
            "The reviewed attempt decision could not be selected safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    write_lines(
        output,
        "",
        f"Attempt-decision selection: {result.selection_disposition}.",
        f"Selected revision: {result.selected_revision}.",
    )
    pause_for_user(input_fn)


def run_new_evidence_menu(
    *,
    dependencies: EvidenceMenuDependencies | None = None,
    action_dependencies: EvidenceActionDependencies | None = None,
    attempt_dependencies: AttemptActionDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    """Run protected evidence review and explicit teacher follow-up actions."""

    stream = sys.stdout if output is None else output
    active = dependencies or default_evidence_menu_dependencies()
    actions = action_dependencies or default_evidence_action_dependencies(
        diagnostics=active.diagnostics,
    )
    attempts = attempt_dependencies or default_attempt_action_dependencies(
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
            "4. Author attempt / reassessment decision",
            "5. Select attempt / reassessment decision",
            "",
            "Grade Item and standards follow-up remain separate tasks.",
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
        if choice == "4":
            _author_attempt_decision(
                dependencies=active,
                attempts=attempts,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "5":
            _select_attempt_decision(
                dependencies=active,
                attempts=attempts,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        write_lines(stream, "", "Please choose 1-5, B, M, or Q.")
        pause_for_user(input_fn)
