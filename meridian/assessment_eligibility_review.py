"""#125-B: bounded, read-only assessment-level eligibility/roster projection.

The view composes Core roster identity, the existing teacher-readable evidence
labels, and #41's canonical eligibility resolutions from ONE authorized source.
It is not an academic decision, persisted batch, or permission grant.  No
eligibility writes, attempt choices, or grade computations occur here.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pds_core.classes import load_class_roster
from pds_core.rosters import Roster, RosterError, student_display_name
from pds_core.routing_models import ModuleWorkRef

from meridian.evidence import EvidenceInventory
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.guided_projection import GuidedProjectionResult
from meridian.new_evidence_workflow import (
    NewEvidenceReview,
    NewEvidenceRow,
    project_new_evidence_review,
)
from meridian.teacher_evidence_review import (
    TeacherEvidenceReview,
    build_teacher_evidence_review,
)

MAXIMUM_ROSTER_STUDENTS = 500
MAXIMUM_EVIDENCE_ITEMS = 5_000

ExceptionRoute = Literal[
    "review-source",
    "review-roster",
    "grade-items",
    "review-eligibility",
    "review-attempts",
    "review-individual",
    "stop",
]


class AssessmentEligibilityReviewError(RuntimeError):
    """Cannot create a trustworthy read-only assessment eligibility view."""

    code = "teacher_workflow.assessment_eligibility.read_error"


class AssessmentEligibilityReviewScopeError(
    AssessmentEligibilityReviewError, ValueError
):
    """Exact provenance, cardinality, or roster invariants were violated."""

    code = "teacher_workflow.assessment_eligibility.scope_invalid"


@dataclass(frozen=True, slots=True)
class AssessmentEligibilityException:
    """An unresolved condition, never an automatic action or disposition."""

    code: str
    route: ExceptionRoute
    student_id: str | None = None
    source: EvidenceSourceReference | None = None


@dataclass(frozen=True, slots=True)
class AssessmentEligibilityItem:
    """One exact item, with native label and canonical selected status intact."""

    source: EvidenceSourceReference
    student_id: str | None
    evidence_label: str
    target_kind: str
    target_id: str | None
    result_kind: str
    eligibility_status: str | None
    selected_eligibility_revision: int | None
    selected_eligibility_disposition: str | None
    operative_included: bool
    candidate_for_explicit_review: bool
    exceptions: tuple[AssessmentEligibilityException, ...]


@dataclass(frozen=True, slots=True)
class AssessmentEligibilityStudent:
    """One Core roster student, even when no source result was returned."""

    student_id: str
    display_label: str
    period: str
    items: tuple[AssessmentEligibilityItem, ...]
    within_requested_authorization: bool

    @property
    def no_result(self) -> bool:
        return not self.items and self.within_requested_authorization


@dataclass(frozen=True, slots=True)
class AssessmentEligibilityReview:
    """Complete bounded view; counts describe observation, not grades."""

    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    publication_id: str
    cache_key: str
    snapshot_digest: str
    source_status: str
    membership_state: str
    membership_revision: int | None
    academic_period_id: str | None
    academic_period_calendar_revision: int | None
    students: tuple[AssessmentEligibilityStudent, ...]
    shared_items: tuple[AssessmentEligibilityItem, ...]
    unmatched_items: tuple[AssessmentEligibilityItem, ...]
    exceptions: tuple[AssessmentEligibilityException, ...]
    status_counts: tuple[tuple[str, int], ...]
    projected_item_count: int
    candidate_item_count: int
    no_result_student_count: int
    outside_authorization_scope_count: int
    class_label: str | None = None
    assessment_title: str | None = None

    @property
    def exception_count(self) -> int:
        return len(self.exceptions)


def _labels(roster: Roster) -> dict[str, str]:
    """Use Core's display names and #110's name/period disambiguation rules.

    Unlike the older item-only review, disambiguate across ALL roster members,
    including those whose publication contains no evidence.
    """
    names = {
        student.student_id: " ".join(student_display_name(student).split())
        for student in roster.students
    }
    if any(not label for label in names.values()):
        raise AssessmentEligibilityReviewScopeError("Core roster display name missing.")
    counts = Counter(names.values())
    labels: dict[str, str] = {}
    for student in roster.students:
        name = names[student.student_id]
        if counts[name] > 1 and student.period.strip():
            name = f"{name} · Period {student.period.strip()}"
        labels[student.student_id] = name
    if len(labels) != len(roster.students) or len(set(labels.values())) != len(labels):
        raise AssessmentEligibilityReviewScopeError(
            "Roster student names cannot be safely distinguished "
            "by display name and period."
        )
    return labels


def _identity_check(
    evidence: NewEvidenceReview, teacher: TeacherEvidenceReview, roster: Roster
) -> None:
    if not isinstance(evidence, NewEvidenceReview):
        raise AssessmentEligibilityReviewScopeError("Expected a NewEvidenceReview.")
    if not isinstance(teacher, TeacherEvidenceReview):
        raise AssessmentEligibilityReviewScopeError("Expected a TeacherEvidenceReview.")
    if not isinstance(roster, Roster):
        raise AssessmentEligibilityReviewScopeError("Expected a canonical Core Roster.")
    if (
        evidence.class_id != roster.class_id
        or teacher.class_id != roster.class_id
        or evidence.work != teacher.work
        or evidence.publication_id != teacher.publication_id
    ):
        raise AssessmentEligibilityReviewScopeError(
            "Roster, work, or publication identity differs."
        )
    if len(roster.students) > MAXIMUM_ROSTER_STUDENTS:
        raise AssessmentEligibilityReviewScopeError(
            "Roster exceeds bounded review limit."
        )
    if len(evidence.rows) > MAXIMUM_EVIDENCE_ITEMS:
        raise AssessmentEligibilityReviewScopeError(
            "Evidence exceeds bounded review limit."
        )
    for row in evidence.rows:
        source = row.source
        if (
            source.work != evidence.work
            or source.publication_id != evidence.publication_id
            or source.cache_key != evidence.cache_key
            or source.snapshot_digest != evidence.snapshot_digest
        ):
            raise AssessmentEligibilityReviewScopeError(
                "Evidence row has a different exact source."
            )
    if len({row.source.item_id for row in evidence.rows}) != len(evidence.rows):
        raise AssessmentEligibilityReviewScopeError(
            "Duplicate exact item IDs; review source integrity."
        )


def _classify(
    row: NewEvidenceRow,
    *,
    is_known_student: bool,
    source_current: bool,
    duplicate_target: bool,
) -> tuple[AssessmentEligibilityException, ...]:
    issues: list[AssessmentEligibilityException] = []

    def mark(code: str, route: ExceptionRoute) -> None:
        issues.append(
            AssessmentEligibilityException(code, route, row.student_id, row.source)
        )

    if not source_current:
        mark("source_not_current", "review-source")
    if row.membership_state != "included":
        mark("membership_" + row.membership_state, "grade-items")
    if row.student_id is None:
        mark("non_student_evidence", "review-individual")
    elif not is_known_student:
        mark("unknown_roster_student", "review-roster")
    if duplicate_target:
        mark("multiple_items_same_native_target", "review-attempts")

    status = row.eligibility_status
    if row.membership_state == "included":
        if status is None:
            mark("eligibility_resolution_missing", "stop")
        elif status in {"excluded", "pending", "unsupported"}:
            mark("previous_" + status, "review-eligibility")
        elif status not in {"no_decision", "included"}:
            mark("eligibility_" + status, "review-individual")
        if status == "no_decision" and (
            row.selected_eligibility_revision is not None
            or row.selected_eligibility_disposition is not None
        ):
            mark("eligibility_resolution_inconsistent", "stop")
        if status in {"included", "excluded", "pending", "unsupported"} and (
            row.selected_eligibility_revision is None
            or row.selected_eligibility_disposition is None
        ):
            mark("eligibility_selection_unverifiable", "stop")
        if status == "included" and not row.operative_included:
            mark("included_not_operative", "review-individual")
        if row.selected_eligibility_disposition in {"superseded", "withdrawn"}:
            mark("source_lifecycle_decision", "review-source")

    return tuple(issues)


def build_assessment_eligibility_review(
    *,
    evidence: NewEvidenceReview,
    teacher: TeacherEvidenceReview,
    roster: Roster,
    class_label: str | None = None,
    assessment_title: str | None = None,
    requested_student_ids: tuple[str, ...] = (),
) -> AssessmentEligibilityReview:
    """Purely combine already-authorized/read-only projections; NEVER write.

    A represented student's native label comes from TeacherEvidenceReview;
    unknown roster subjects are preserved in an explicit blocked exception group.
    """
    _identity_check(evidence, teacher, roster)
    roster_names = _labels(roster)
    roster_ids = set(roster_names)
    if not isinstance(requested_student_ids, tuple) or any(
        not isinstance(value, str) or not value for value in requested_student_ids
    ):
        raise AssessmentEligibilityReviewScopeError("Invalid requested student scope.")
    if len(set(requested_student_ids)) != len(requested_student_ids):
        raise AssessmentEligibilityReviewScopeError(
            "Duplicate requested student identities."
        )
    allowed_ids = set(requested_student_ids) if requested_student_ids else roster_ids
    if requested_student_ids and not allowed_ids <= roster_ids:
        raise AssessmentEligibilityReviewScopeError(
            "Requested evidence scope contains a student absent from the Core roster."
        )
    if requested_student_ids and any(
        row.student_id in roster_ids and row.student_id not in allowed_ids
        for row in evidence.rows
    ):
        raise AssessmentEligibilityReviewScopeError(
            "Authorized projection includes evidence outside requested student scope."
        )

    native_labels: dict[str, str] = {}
    for student in teacher.students:
        if student.student_id not in roster_ids:
            raise AssessmentEligibilityReviewScopeError(
                "Teacher view references a non-roster student."
            )
        for item in student.items:
            if item.item_id in native_labels or item.student_id != student.student_id:
                raise AssessmentEligibilityReviewScopeError(
                    "Teacher native item identity is ambiguous."
                )
            native_labels[item.item_id] = item.evidence_label
    for item in teacher.shared_items:
        if item.item_id in native_labels or item.student_id is not None:
            raise AssessmentEligibilityReviewScopeError(
                "Teacher shared-item identity is ambiguous."
            )
        native_labels[item.item_id] = item.evidence_label

    expected_teacher_ids = {
        row.source.item_id
        for row in evidence.rows
        if row.student_id is None or row.student_id in roster_ids
    }
    if set(native_labels) != expected_teacher_ids:
        raise AssessmentEligibilityReviewScopeError(
            "Teacher native labels do not cover exactly "
            "the authorized known roster items."
        )

    native_target_counts = Counter(
        (row.student_id, row.target_kind, row.target_id)
        for row in evidence.rows
        if row.target_id is not None and row.student_id is not None
    )
    per_student: dict[str, list[AssessmentEligibilityItem]] = defaultdict(list)
    shared: list[AssessmentEligibilityItem] = []
    unmatched: list[AssessmentEligibilityItem] = []
    exceptions: list[AssessmentEligibilityException] = []
    counts: Counter[str] = Counter()
    candidates = 0
    for row in evidence.rows:
        known = row.student_id is not None and row.student_id in roster_ids
        duplicate = bool(
            row.student_id is not None
            and row.target_id is not None
            and native_target_counts[row.student_id, row.target_kind, row.target_id] > 1
        )
        problems = _classify(
            row,
            is_known_student=known,
            source_current=evidence.projection_source_status == "current",
            duplicate_target=duplicate,
        )
        if known and row.student_id not in allowed_ids:
            problems += (
                AssessmentEligibilityException(
                    "evidence_outside_requested_scope",
                    "stop",
                    row.student_id,
                    row.source,
                ),
            )
        candidate = (
            not problems
            and row.membership_state == "included"
            and row.eligibility_status == "no_decision"
            and row.selected_eligibility_revision is None
            and row.selected_eligibility_disposition is None
            and not row.operative_included
        )
        if candidate:
            candidates += 1
        label = native_labels.get(row.source.item_id)
        if label is None:
            # Unknown roster attribution: retain source identity, not a guessed name.
            label = "Unmatched " + row.target_kind.replace("_", " ").capitalize()
        item = AssessmentEligibilityItem(
            source=row.source,
            student_id=row.student_id,
            evidence_label=label,
            target_kind=row.target_kind,
            target_id=row.target_id,
            result_kind=row.result_kind,
            eligibility_status=row.eligibility_status,
            selected_eligibility_revision=row.selected_eligibility_revision,
            selected_eligibility_disposition=row.selected_eligibility_disposition,
            operative_included=row.operative_included,
            candidate_for_explicit_review=candidate,
            exceptions=problems,
        )
        counts[
            "membership_" + row.membership_state
            if row.membership_state != "included"
            else "eligibility_" + (row.eligibility_status or "unavailable")
        ] += 1
        exceptions.extend(problems)
        if row.student_id is None:
            shared.append(item)
        elif not known:
            unmatched.append(item)
        else:
            per_student[row.student_id].append(item)

    students: list[AssessmentEligibilityStudent] = []
    for record in roster.students:
        items = tuple(
            sorted(per_student[record.student_id], key=lambda x: x.source.item_id)
        )
        students.append(
            AssessmentEligibilityStudent(
                student_id=record.student_id,
                display_label=roster_names[record.student_id],
                period=record.period,
                items=items,
                within_requested_authorization=record.student_id in allowed_ids,
            )
        )
        if record.student_id not in allowed_ids:
            exceptions.append(
                AssessmentEligibilityException(
                    "outside_requested_authorization_scope",
                    "review-source",
                    record.student_id,
                )
            )
        elif not items:
            exceptions.append(
                AssessmentEligibilityException(
                    "no_result_in_publication", "review-source", record.student_id
                )
            )
    if not students:
        exceptions.append(
            AssessmentEligibilityException("empty_core_roster", "review-roster")
        )
    if not evidence.rows:
        exceptions.append(
            AssessmentEligibilityException("no_projected_evidence", "review-source")
        )
    if not evidence.projection_source_status == "current" and not evidence.rows:
        exceptions.append(
            AssessmentEligibilityException("source_not_current", "review-source")
        )
    if evidence.membership_state != "included" and not evidence.rows:
        exceptions.append(
            AssessmentEligibilityException(
                "membership_" + evidence.membership_state, "grade-items"
            )
        )

    return AssessmentEligibilityReview(
        class_id=evidence.class_id,
        grade_item_id=evidence.grade_item_id,
        work=evidence.work,
        publication_id=evidence.publication_id,
        cache_key=evidence.cache_key,
        snapshot_digest=evidence.snapshot_digest,
        source_status=evidence.projection_source_status,
        membership_state=evidence.membership_state,
        membership_revision=evidence.membership_revision,
        academic_period_id=evidence.academic_period_id,
        academic_period_calendar_revision=evidence.academic_period_calendar_revision,
        students=tuple(students),
        shared_items=tuple(sorted(shared, key=lambda x: x.source.item_id)),
        unmatched_items=tuple(sorted(unmatched, key=lambda x: x.source.item_id)),
        exceptions=tuple(exceptions),
        status_counts=tuple(sorted(counts.items())),
        projected_item_count=len(evidence.rows),
        candidate_item_count=candidates,
        no_result_student_count=sum(student.no_result for student in students),
        outside_authorization_scope_count=sum(
            not student.within_requested_authorization for student in students
        ),
        class_label=class_label,
        assessment_title=assessment_title,
    )


def project_assessment_eligibility_review(
    workspace_root: str | Path,
    *,
    grade_item_id: str,
    prepared: GuidedProjectionResult,
    class_label: str | None = None,
    assessment_title: str | None = None,
) -> AssessmentEligibilityReview:
    """Entry point: use an already-authorized exact projection once.

    Source authentication/permission is performed by the existing guided
    projection service *before* this function. A lost or missing Core roster
    blocks the projection; no synthetic roster or access grant is created.
    """
    if not isinstance(prepared, GuidedProjectionResult):
        raise AssessmentEligibilityReviewScopeError(
            "Expected an authorized GuidedProjectionResult."
        )
    authorized = prepared.authorized
    publication = authorized.current_context.publication
    snapshot = authorized.stored.snapshot
    if snapshot.source.publication != publication or not isinstance(
        snapshot.inventory, EvidenceInventory
    ):
        raise AssessmentEligibilityReviewScopeError(
            "Authorized publication/inventory basis differs."
        )
    work = publication.work
    try:
        roster = load_class_roster(workspace_root, work.class_id)
    except (RosterError, OSError, ValueError) as error:
        raise AssessmentEligibilityReviewError(
            "Canonical Core roster unavailable."
        ) from error
    if roster is None:
        raise AssessmentEligibilityReviewError("Canonical Core roster unavailable.")
    if len(roster.students) > MAXIMUM_ROSTER_STUDENTS:
        raise AssessmentEligibilityReviewScopeError(
            "Roster exceeds bounded review limit."
        )
    if len(snapshot.inventory.items) > MAXIMUM_EVIDENCE_ITEMS:
        raise AssessmentEligibilityReviewScopeError(
            "Evidence exceeds bounded review limit."
        )

    eligibility = project_new_evidence_review(
        workspace_root, work.class_id, grade_item_id, authorized
    )
    represented = {student.student_id for student in roster.students}
    known = tuple(
        item
        for item in snapshot.inventory.items
        if item.subject is None or item.subject.student_id in represented
    )
    native = build_teacher_evidence_review(
        inventory=EvidenceInventory(known),
        roster=roster,
        work=work,
        publication_id=publication.publication_id,
    )
    return build_assessment_eligibility_review(
        evidence=eligibility,
        teacher=native,
        roster=roster,
        class_label=class_label,
        assessment_title=assessment_title,
        requested_student_ids=prepared.requested_student_ids,
    )


def render_assessment_eligibility_preview(review: AssessmentEligibilityReview) -> str:
    """Plain-text READ ONLY preview; no Apply, mutation, or implicit selection.

    Display all student and exceptional items within the bounded model; later
    menu/paging support belongs to #125-F. Item IDs appear only in advanced
    models, not in ordinary text.
    """
    if not isinstance(review, AssessmentEligibilityReview):
        raise TypeError("Expected an AssessmentEligibilityReview.")
    lines = [
        "ASSESSMENT ELIGIBILITY — READ-ONLY REVIEW",
        f"Class: {review.class_label or 'Current class'}",
        f"Assessment: {review.assessment_title or 'Selected assessment'}",
        f"Publication: {review.source_status}",
        f"Grade Item membership: {review.membership_state}",
        f"Academic Period: {review.academic_period_id or 'Not assigned'}",
        (
            f"Roster: {len(review.students)} students; "
            f"{review.no_result_student_count} with no published result"
        ),
        (
            "Outside requested evidence scope: "
            f"{review.outside_authorization_scope_count} students "
            "(not counted as missing)"
        ),
        (
            f"Projected evidence: {review.projected_item_count} items; "
            f"{review.candidate_item_count} potential new decisions"
        ),
        (
            f"Exceptions: {review.exception_count} conditions "
            "(not necessarily distinct items)"
        ),
        (
            "No grades, missing-result zeros, or eligibility decisions "
            "are created by this screen."
        ),
        "",
        "EXCEPTIONS — REVIEW BEFORE ANY BATCH ACTION",
    ]
    if not review.exceptions:
        lines.append("None observed in this authorized projection.")
    else:
        names = {
            student.student_id: student.display_label for student in review.students
        }
        for issue in review.exceptions:
            who = names.get(issue.student_id or "", "Unmatched/shared evidence")
            lines.append(f"- {who}: {issue.code.replace('_', ' ')} — {issue.route}")
    lines.extend(("", "ROSTER COVERAGE AND CURRENT ELIGIBILITY"))
    for student in review.students:
        lines.append(f"{student.display_label}: {len(student.items)} native items")
        if not student.within_requested_authorization:
            lines.append("  Outside requested evidence scope (no availability claim).")
        elif student.no_result:
            lines.append("  No result returned in this publication (not a zero).")
        for item in student.items:
            status = item.eligibility_status or "no eligibility resolution"
            if item.operative_included:
                status += " (operative)"
            lines.append(f"  {item.evidence_label}: {status}")
    if review.shared_items:
        lines.append("SHARED / NON-STUDENT EVIDENCE — NOT AUTO-ATTRIBUTABLE")
        for item in review.shared_items:
            lines.append(
                f"  {item.evidence_label}: {item.eligibility_status or 'not resolved'}"
            )
    if review.unmatched_items:
        lines.append("UNMATCHED STUDENT ATTRIBUTION — NOT AUTO-ATTRIBUTABLE")
        for item in review.unmatched_items:
            lines.append(
                f"  {item.evidence_label}: {item.eligibility_status or 'not resolved'}"
            )
    lines.extend(
        ("", "Review only. No confirmation or Apply is available in slice 125-B.")
    )
    return "\n".join(lines)


__all__ = (
    "AssessmentEligibilityException",
    "AssessmentEligibilityItem",
    "AssessmentEligibilityReview",
    "AssessmentEligibilityReviewError",
    "AssessmentEligibilityReviewScopeError",
    "AssessmentEligibilityStudent",
    "build_assessment_eligibility_review",
    "project_assessment_eligibility_review",
    "render_assessment_eligibility_preview",
)
