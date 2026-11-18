"""#126-B: bounded, authorization-scoped, read-only attempt inventory.

This is a *projection*, not a correction classifier or academic writer. It
keeps producer-public attempt history separate from #29 eligibility, #30
current selection, and #31 reassessment. No score/sequence implies priority.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from meridian.assessment_eligibility_review import (
    AssessmentEligibilityReview,
    project_assessment_eligibility_review,
)
from meridian.attempt_decisions_workflow import (
    AttemptDecisionWorkflowProjection,
    project_attempt_decisions,
)
from meridian.attempt_selection import (
    AttemptNativeIdentity,
    AttemptObservationReference,
    AttemptProjectionReference,
    AttemptTargetReference,
)
from meridian.evidence import (
    EvidenceInventory,
    EvidenceItem,
    EvidenceTarget,
    EvidenceTargetIdentity,
    NativePointValue,
    NativeScalarValue,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.reassessment_storage import resolve_current_reassessment

MAXIMUM_ATTEMPT_INVENTORY_STUDENTS = 500
MAXIMUM_ATTEMPT_INVENTORY_ITEMS = 5_000
PAGE_SIZE = 20

AttentionCode = Literal[
    "publication_not_current",
    "membership_not_included",
    "projection_coverage_unavailable",
    "eligibility_attention",
    "attempt_identity_unsupported",
    "multiple_attempts_relationship_unverified",
    "operative_selection_missing",
    "operative_selection_stale",
    "reassessment_unresolved",
    "selection_integrity_conflict",
]


class AssessmentAttemptInventoryError(RuntimeError):
    """The authorized read-only view cannot be trusted as constructed."""

    code = "teacher_workflow.assessment_attempt_inventory.error"


class AssessmentAttemptInventoryScopeError(AssessmentAttemptInventoryError, ValueError):
    """A roster, source, identity, or current-selection seam does not agree."""

    code = "teacher_workflow.assessment_attempt_inventory.scope_invalid"


@dataclass(frozen=True, slots=True)
class NativeAttemptInventoryRow:
    """One source-reported native attempt, including excluded historical items.

    `attempt` and `item_ids` are exact internal references; ordinary screens
    show a bounded human label instead of IDs. Producer origin is never an
    assertion about the causal relationship to another attempt.
    """

    attempt: AttemptObservationReference = field(repr=False)
    item_ids: tuple[str, ...] = field(repr=False)
    point_result: tuple[int | float, int | float] | None
    result_origin: str | None
    scan_review_failure_reference: bool
    operative_eligible: bool
    current_selected: bool

    @property
    def attempt_label(self) -> str:
        if self.attempt.native.sequence is not None:
            return f"Attempt {self.attempt.native.sequence}"
        if self.attempt.native.identifier is not None:
            return "Native attempt (identifier in Technical Details)"
        return "Native attempt"


@dataclass(frozen=True, slots=True)
class StudentAttemptInventoryRow:
    """One authorized Core-roster student with faithful missing-state labels."""

    student_id: str = field(repr=False)
    display_label: str
    attempts: tuple[NativeAttemptInventoryRow, ...]
    selection_status: str | None
    selection_resolution_status: str | None
    selected_decision_revision: int | None
    reassessment_status: str | None
    projected_item_count: int
    attention: tuple[AttentionCode, ...]

    @property
    def needs_attention(self) -> bool:
        return bool(self.attention)


@dataclass(frozen=True, slots=True)
class AssessmentAttemptInventory:
    """Exact one-publication assessment review, not a mixed-history merge."""

    class_id: str
    grade_item_id: str
    work_module_id: str
    work_id: str
    publication_id: str = field(repr=False)
    cache_key: str = field(repr=False)
    snapshot_digest: str = field(repr=False)
    source_status: str
    membership_state: str
    class_label: str | None
    assessment_title: str | None
    students: tuple[StudentAttemptInventoryRow, ...]
    shared_item_count: int
    unmatched_item_count: int
    outside_requested_authorization_scope_count: int
    unresolved_global_exception_codes: tuple[str, ...]

    @property
    def attention_count(self) -> int:
        return sum(row.needs_attention for row in self.students)


def _attempt_from_public_item(
    item: EvidenceItem,
    source: AttemptProjectionReference,
    student_id: str,
) -> AttemptObservationReference | None:
    """Read explicit producer-native attempt shape; never synthesize an ID.

    This mirrors the *public model* interpretation used by #30's candidate
    derivation. Unlike #30, we do not require Included status to see history.
    """
    target = item.target
    if target.target_kind == "attempt":
        identity: EvidenceTarget | EvidenceTargetIdentity = target
    elif (
        target.parent_target is not None
        and target.parent_target.target_kind == "attempt"
    ):
        identity = target.parent_target
    else:
        return None
    refs = tuple(
        ref for ref in item.provenance.native.references if ref.kind == "attempt"
    )
    if len(refs) != 1:
        raise AssessmentAttemptInventoryScopeError(
            "An attempt-shaped evidence item lacks one exact native attempt reference."
        )
    native = refs[0]
    return AttemptObservationReference(
        source_snapshot=source,
        student_id=student_id,
        target=AttemptTargetReference(
            target_kind="attempt",
            target_id=identity.target_id,
            owning_system=identity.owning_system,
            contract_version=identity.contract_version,
        ),
        native=AttemptNativeIdentity(
            identifier=native.identifier, sequence=native.sequence
        ),
    )


def _native_sort_key(row: NativeAttemptInventoryRow) -> tuple[object, ...]:
    attempt = row.attempt
    return (
        attempt.native.sequence is None,
        attempt.native.sequence or 0,
        attempt.native.identifier or "",
        attempt.target.target_id or "",
    )


def _render_safe(value: str) -> str:
    """Prevent terminal control characters in producer/roster display strings."""
    return "".join(
        character
        if character.isprintable() and character not in {"\x1b", "\x7f"}
        else "?"
        for character in value
    )


def build_assessment_attempt_inventory(
    *,
    review: AssessmentEligibilityReview,
    inventory: EvidenceInventory,
    selection_projections: Mapping[str, AttemptDecisionWorkflowProjection],
    reassessment_statuses: Mapping[str, str] | None = None,
    supports_multiple_attempts: bool,
) -> AssessmentAttemptInventory:
    """Compose previously authorized #125/#30 facts without any IO or writes.

    The caller must pass the *same* authorized projection inventory that built
    `review`, not an independent scan of the producer workspace or other cache.
    Only roster students inside the requested authorization scope are emitted.
    """
    if not isinstance(review, AssessmentEligibilityReview):
        raise AssessmentAttemptInventoryScopeError("Expected a #125 assessment review.")
    if not isinstance(inventory, EvidenceInventory):
        raise AssessmentAttemptInventoryScopeError(
            "Expected an immutable evidence inventory."
        )
    if not isinstance(supports_multiple_attempts, bool):
        raise AssessmentAttemptInventoryScopeError(
            "Attempt capability must be explicit."
        )
    if (
        len(review.students) > MAXIMUM_ATTEMPT_INVENTORY_STUDENTS
        or len(inventory.items) > MAXIMUM_ATTEMPT_INVENTORY_ITEMS
    ):
        raise AssessmentAttemptInventoryScopeError(
            "Assessment inventory exceeds bounded limits."
        )
    expected_ids = {
        item.source.item_id for student in review.students for item in student.items
    } | {item.source.item_id for item in review.shared_items + review.unmatched_items}
    actual_ids = {item.item_id for item in inventory.items}
    if len(expected_ids) != review.projected_item_count or actual_ids != expected_ids:
        raise AssessmentAttemptInventoryScopeError(
            "Authorized inventory does not exactly match the #125 source items."
        )
    for student in review.students:
        for item in student.items:
            if (
                item.source.work != review.work
                or item.source.publication_id != review.publication_id
                or item.source.cache_key != review.cache_key
                or item.source.snapshot_digest != review.snapshot_digest
                or item.student_id != student.student_id
            ):
                raise AssessmentAttemptInventoryScopeError(
                    "Roster evidence and exact authorized publication basis disagree."
                )
    student_map = {student.student_id: student for student in review.students}
    if len(student_map) != len(review.students):
        raise AssessmentAttemptInventoryScopeError(
            "Duplicate Core-roster student identity."
        )
    allowed = {
        student.student_id
        for student in review.students
        if student.within_requested_authorization
    }
    if (
        set(selection_projections) - allowed
        or set(reassessment_statuses or ()) - allowed
    ):
        raise AssessmentAttemptInventoryScopeError(
            "Attempt/reassessment results contain an out-of-scope student."
        )

    source = AttemptProjectionReference(
        work=review.work,
        publication_id=review.publication_id,
        cache_key=review.cache_key,
        snapshot_digest=review.snapshot_digest,
    )
    current_context = (
        review.source_status == "current" and review.membership_state == "included"
    )
    # On stale source or membership, no selected pointer is safe to present as current.
    if not current_context and (selection_projections or reassessment_statuses):
        raise AssessmentAttemptInventoryScopeError(
            "Current-selection projection is not applicable to stale source/membership."
        )
    if current_context and set(selection_projections) != allowed:
        raise AssessmentAttemptInventoryScopeError(
            "Missing exact read-only selection status for an authorized student."
        )

    eligibility_by_item = {
        item.source.item_id: item
        for student in review.students
        for item in student.items
    }
    item_by_student: dict[str, list[EvidenceItem]] = defaultdict(list)
    for source_item in inventory.items:
        if source_item.subject is None:
            continue
        student_id = source_item.subject.student_id
        if student_id in student_map and student_id not in allowed:
            raise AssessmentAttemptInventoryScopeError(
                "Authorized inventory includes evidence outside requested roster scope."
            )
        if student_id in allowed:
            review_item = eligibility_by_item.get(source_item.item_id)
            if review_item is None or review_item.student_id != student_id:
                raise AssessmentAttemptInventoryScopeError(
                    "Source item roster identity disagrees with #125 review."
                )
            item_by_student[student_id].append(source_item)

    rows: list[StudentAttemptInventoryRow] = []
    for student in review.students:
        if not student.within_requested_authorization:
            continue  # never reveal identity/attempts outside the requested scope
        projection = selection_projections.get(student.student_id)
        if projection is not None and (
            projection.student_id != student.student_id
            or projection.work != review.work
            or projection.class_id != review.class_id
            or projection.grade_item_id != review.grade_item_id
            or projection.source_snapshot != source
        ):
            raise AssessmentAttemptInventoryScopeError(
                "#30 selection belongs to a different student or exact source."
            )
        if (
            projection is not None
            and not supports_multiple_attempts
            and projection.status != "not_applicable"
        ):
            raise AssessmentAttemptInventoryScopeError(
                "Producer attempt capability disagrees with canonical #30 resolver."
            )
        if (
            projection is not None
            and supports_multiple_attempts
            and projection.status == "not_applicable"
        ):
            raise AssessmentAttemptInventoryScopeError(
                "Producer declares attempts but #30 reports not applicable."
            )

        attention: list[AttentionCode] = []
        if review.source_status != "current":
            attention.append("publication_not_current")
        if review.membership_state != "included":
            attention.append("membership_not_included")
        if student.coverage_unavailable:
            attention.append("projection_coverage_unavailable")
        if any(
            item.exceptions or not item.operative_included for item in student.items
        ):
            attention.append("eligibility_attention")

        grouped: dict[AttemptObservationReference, list[EvidenceItem]] = defaultdict(
            list
        )
        target_to_native: dict[AttemptTargetReference, AttemptNativeIdentity] = {}
        native_to_target: dict[AttemptNativeIdentity, AttemptTargetReference] = {}
        for source_item in item_by_student[student.student_id]:
            if (
                source_item.item_id not in eligibility_by_item
                or not supports_multiple_attempts
            ):
                continue
            attempt = _attempt_from_public_item(source_item, source, student.student_id)
            if attempt is None:
                continue
            prev_native = target_to_native.get(attempt.target)
            prev_target = native_to_target.get(attempt.native)
            if (prev_native is not None and prev_native != attempt.native) or (
                prev_target is not None and prev_target != attempt.target
            ):
                raise AssessmentAttemptInventoryScopeError(
                    "Contradictory target/native attempt identity; "
                    "no selection is safe."
                )
            target_to_native[attempt.target] = attempt.native
            native_to_target[attempt.native] = attempt.target
            grouped[attempt].append(source_item)

        candidates = (
            {}
            if projection is None
            else {candidate.attempt: candidate for candidate in projection.candidates}
        )
        if len(candidates) != (0 if projection is None else len(projection.candidates)):
            raise AssessmentAttemptInventoryScopeError(
                "Duplicate #30 candidate attempt."
            )
        if not set(candidates) <= set(grouped):
            raise AssessmentAttemptInventoryScopeError(
                "Operative #30 candidate is absent from the "
                "source-reported native attempts."
            )
        selected = (
            set() if projection is None else set(projection.reviewed_selected_attempts)
        )
        if not selected <= set(grouped):
            raise AssessmentAttemptInventoryScopeError(
                "#30 reviewed decision references an unrepresented native attempt."
            )
        if (
            projection is not None
            and projection.status == "selected"
            and (
                not projection.operative_selection
                or not selected
                or not selected <= set(candidates)
            )
        ):
            raise AssessmentAttemptInventoryScopeError(
                "Operative #30 selected attempt is not a current eligible candidate."
            )
        if projection is not None and not projection.operative_selection:
            selected = set()  # history remains; no stale selection shown as current

        native_rows: list[NativeAttemptInventoryRow] = []
        for attempt, items in grouped.items():
            point_values = [
                item.value for item in items if item.result_kind == "attempt_points"
            ]
            origins = [
                item.value for item in items if item.result_kind == "result_origin"
            ]
            point = point_values[0] if point_values else None
            origin = origins[0] if origins else None
            if (
                len(point_values) > 1
                or len(origins) > 1
                or (point is not None and not isinstance(point, NativePointValue))
                or (
                    origin is not None
                    and (
                        not isinstance(origin, NativeScalarValue)
                        or not isinstance(origin.value, str)
                    )
                )
            ):
                raise AssessmentAttemptInventoryScopeError(
                    "Contradictory attempt summary/origin items in public projection."
                )
            point_result = (
                (point.earned, point.possible)
                if isinstance(point, NativePointValue)
                else None
            )
            result_origin = (
                origin.value
                if isinstance(origin, NativeScalarValue)
                and isinstance(origin.value, str)
                else None
            )
            review_failure = any(
                ref.kind == "review_failure"
                for item in items
                for ref in item.provenance.native.references
            )
            native_rows.append(
                NativeAttemptInventoryRow(
                    attempt=attempt,
                    item_ids=tuple(sorted(item.item_id for item in items)),
                    point_result=point_result,
                    result_origin=result_origin,
                    scan_review_failure_reference=review_failure,
                    operative_eligible=attempt in candidates,
                    current_selected=attempt in selected,
                )
            )
        native_rows.sort(key=_native_sort_key)
        if (
            supports_multiple_attempts
            and item_by_student[student.student_id]
            and not grouped
        ):
            attention.append("attempt_identity_unsupported")
        if len(native_rows) > 1:
            attention.append("multiple_attempts_relationship_unverified")
        if projection is not None:
            if projection.status == "no_decision" and candidates:
                attention.append("operative_selection_missing")
            elif projection.status in {"stale", "unsupported_attempt_shape"}:
                attention.append("operative_selection_stale")
            elif (
                projection.status == "selected"
                and len(selected) != projection.reviewed_selected_count
            ):
                attention.append("selection_integrity_conflict")
        reassessment = (reassessment_statuses or {}).get(student.student_id)
        if (
            projection is not None
            and projection.status == "selected"
            and len(selected) > 1
        ):
            if reassessment not in {"resolved"}:
                attention.append("reassessment_unresolved")
        elif reassessment is not None:
            raise AssessmentAttemptInventoryScopeError(
                "#31 status is only applicable when multiple operative "
                "attempts are selected."
            )
        rows.append(
            StudentAttemptInventoryRow(
                student_id=student.student_id,
                display_label=student.display_label,
                attempts=tuple(native_rows),
                selection_status=None if projection is None else projection.status,
                selection_resolution_status=(
                    None if projection is None else projection.resolution_status
                ),
                selected_decision_revision=(
                    None
                    if projection is None
                    else projection.selected_decision_revision
                ),
                reassessment_status=reassessment,
                projected_item_count=len(student.items),
                attention=tuple(dict.fromkeys(attention)),
            )
        )

    return AssessmentAttemptInventory(
        class_id=review.class_id,
        grade_item_id=review.grade_item_id,
        work_module_id=review.work.module_id,
        work_id=review.work.work_id,
        publication_id=review.publication_id,
        cache_key=review.cache_key,
        snapshot_digest=review.snapshot_digest,
        source_status=review.source_status,
        membership_state=review.membership_state,
        class_label=review.class_label,
        assessment_title=review.assessment_title,
        students=tuple(rows),
        shared_item_count=len(review.shared_items),
        unmatched_item_count=len(review.unmatched_items),
        outside_requested_authorization_scope_count=(
            review.outside_authorization_scope_count
        ),
        unresolved_global_exception_codes=tuple(
            sorted(
                {
                    exception.code
                    for exception in review.exceptions
                    if exception.student_id is None
                }
            )
        ),
    )


def project_assessment_attempt_inventory(
    workspace_root: str | Path,
    *,
    grade_item_id: str,
    prepared: GuidedProjectionResult,
    class_label: str | None = None,
    assessment_title: str | None = None,
) -> AssessmentAttemptInventory:
    """Load #125, #30 and necessary #31 truth from one authorized projection.

    This service does not call a producer/private reader, reauthorize evidence,
    author/select revisions, create receipts, or persist any state.
    """
    if not isinstance(prepared, GuidedProjectionResult):
        raise AssessmentAttemptInventoryScopeError(
            "Expected prepared authorized projection."
        )
    review = project_assessment_eligibility_review(
        workspace_root,
        grade_item_id=grade_item_id,
        prepared=prepared,
        class_label=class_label,
        assessment_title=assessment_title,
    )
    authorized = prepared.authorized
    publication = authorized.current_context.publication
    inventory = authorized.stored.snapshot.inventory
    if (
        publication.publication_id != review.publication_id
        or publication.work != review.work
    ):
        raise AssessmentAttemptInventoryScopeError(
            "Publication changed across read-only projections."
        )
    selections: dict[str, AttemptDecisionWorkflowProjection] = {}
    reassessments: dict[str, str] = {}
    if review.source_status == "current" and review.membership_state == "included":
        for student in review.students:
            if not student.within_requested_authorization:
                continue
            selection = project_attempt_decisions(
                workspace_root,
                review.class_id,
                grade_item_id,
                review.work,
                student.student_id,
                authorized_snapshot=authorized,
            )
            selections[student.student_id] = selection
            if selection.status == "selected" and selection.reviewed_selected_count > 1:
                resolution = resolve_current_reassessment(
                    workspace_root,
                    review.class_id,
                    grade_item_id,
                    review.work,
                    student.student_id,
                    authorized_snapshot=authorized,
                )
                reassessments[student.student_id] = resolution.status
    return build_assessment_attempt_inventory(
        review=review,
        inventory=inventory,
        selection_projections=selections,
        reassessment_statuses=reassessments,
        supports_multiple_attempts="multiple_attempts" in publication.capabilities,
    )


def render_assessment_attempt_inventory(
    value: AssessmentAttemptInventory,
    *,
    attention_only: bool = True,
    page: int = 1,
    technical_details: bool = False,
) -> str:
    """Accessible plain-text, exception-first, bounded roster preview.

    `technical_details` reveals exact source/attempt identifiers only when the
    caller has already obtained this authorized view (never an authorization grant).
    """
    if not isinstance(value, AssessmentAttemptInventory):
        raise TypeError("Expected an AssessmentAttemptInventory.")
    if type(page) is not int or page < 1:
        raise ValueError("Page must be a positive integer.")
    students = (
        [student for student in value.students if student.needs_attention]
        if attention_only
        else list(value.students)
    )
    page_count = max(1, (len(students) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > page_count:
        raise ValueError("Page outside the bounded roster view.")
    window = students[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    lines = [
        "Meridian — Review Corrections & Attempts (READ ONLY)",
        f"Class: {_render_safe(value.class_label or 'Current class')}",
        f"Assessment: {_render_safe(value.assessment_title or 'Selected assessment')}",
        (
            f"Publication: {value.source_status}; "
            f"Grade Item membership: {value.membership_state}"
        ),
        (
            f"Authorized students: {len(value.students)}; "
            f"attention: {value.attention_count}"
        ),
        (
            f"Shared evidence items: {value.shared_item_count}; "
            f"unmatched: {value.unmatched_item_count}"
        ),
        (
            "Outside authorized student scope: "
            f"{value.outside_requested_authorization_scope_count} "
            "(identities hidden)"
        ),
        "Native attempt history is NOT an automatic correction or grade decision.",
        (
            f"{'ATTENTION' if attention_only else 'ALL AUTHORIZED STUDENTS'} "
            f"— page {page}/{page_count}"
        ),
    ]
    if value.unresolved_global_exception_codes:
        lines.append(
            "Global source/roster exceptions: "
            + "; ".join(
                code.replace("_", " ")
                for code in value.unresolved_global_exception_codes
            )
        )
    if not window:
        lines.append("No students in this view.")
    for student in window:
        lines.append(
            f"{_render_safe(student.display_label)} — "
            f"{len(student.attempts)} native attempts"
        )
        if student.attention:
            lines.append(
                "  Attention: "
                + "; ".join(code.replace("_", " ") for code in student.attention)
            )
        lines.append(f"  Selection: {student.selection_status or 'unavailable'}")
        if student.reassessment_status is not None:
            lines.append(f"  Reassessment: {student.reassessment_status}")
        if not student.attempts and student.projected_item_count == 0:
            lines.append(
                "  No source projection coverage established (never an inferred zero)."
            )
        for attempt in student.attempts:
            status = (
                "current selected"
                if attempt.current_selected
                else (
                    "eligible, not selected"
                    if attempt.operative_eligible
                    else "historical / not operative"
                )
            )
            facts = []
            if attempt.point_result is not None:
                earned, possible = attempt.point_result
                facts.append(f"source points {earned}/{possible}")
            if attempt.result_origin == "scan_review_manual":
                facts.append("scan-review manual origin")
            elif attempt.result_origin in {"pds2_scan", "plain_paper_manual"}:
                facts.append(attempt.result_origin.replace("_", " ") + " origin")
            if attempt.scan_review_failure_reference:
                facts.append("review-failure reference reported")
            lines.append(
                "  "
                + attempt.attempt_label
                + " — "
                + status
                + ("; " + "; ".join(facts) if facts else "")
            )
            if technical_details:
                lines.append(
                    f"    Native target: {ascii(attempt.attempt.target.target_id)}; "
                    f"sequence: {attempt.attempt.native.sequence!r}"
                )
                lines.append(f"    Item IDs: {ascii(attempt.item_ids)}")
        if technical_details:
            lines.append(f"  Core roster student ID: {ascii(student.student_id)}")
            lines.append(
                "  Canonical #30 resolution: "
                f"{ascii(student.selection_resolution_status)}; "
                f"revision: {student.selected_decision_revision!r}"
            )
    if technical_details:
        lines.extend(
            (
                f"Publication ID: {ascii(value.publication_id)}",
                f"Cache key: {ascii(value.cache_key)}",
                f"Snapshot digest: {ascii(value.snapshot_digest)}",
                "Only exact current authorized source observations may be used "
                "to make a decision.",
            )
        )
    lines.append(
        "No eligibility, selection, reassessment, grade, "
        "or producer records are changed."
    )
    return "\n".join(lines)


__all__ = (
    "AssessmentAttemptInventory",
    "AssessmentAttemptInventoryError",
    "AssessmentAttemptInventoryScopeError",
    "NativeAttemptInventoryRow",
    "StudentAttemptInventoryRow",
    "build_assessment_attempt_inventory",
    "project_assessment_attempt_inventory",
    "render_assessment_attempt_inventory",
)
