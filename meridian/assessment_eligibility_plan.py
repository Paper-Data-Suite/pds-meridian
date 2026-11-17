"""#125-C: immutable, read-only plans for explicitly selected eligibility items.

A plan is not a persisted decision, authorization token, receipt, or executor.
The #125-D executor must re-fetch the source, permission, membership, roster,
actor profile, policy, per-item selected pointer and revision history before it
uses the existing #122 per-item action bridge.  No academic writes occur here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_eligibility_review import (
    MAXIMUM_EVIDENCE_ITEMS,
    AssessmentEligibilityItem,
    AssessmentEligibilityReview,
)
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.evidence_eligibility_storage import (
    load_current_evidence_eligibility_decision,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
)
from meridian.guided_eligibility import (
    DEFAULT_GUIDED_ELIGIBILITY_POLICIES,
    GuidedEligibilityPolicyChoice,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.teacher_action_contract import TeacherActionActor

TeacherDisposition: TypeAlias = Literal[
    "included", "excluded", "pending", "unsupported"
]
PlanItemStatus: TypeAlias = Literal["action", "unchanged", "deferred", "blocked"]
DispositionOrDefer: TypeAlias = TeacherDisposition | None

_ALLOWED = frozenset({"included", "excluded", "pending", "unsupported"})
_REASON = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAXIMUM_RATIONALE = 2000


class AssessmentEligibilityPlanError(ValueError):
    """The requested batch is not a bounded, exact, reviewed selection."""

    code = "teacher_workflow.assessment_eligibility.plan_invalid"


class AssessmentEligibilityPlanStaleError(AssessmentEligibilityPlanError):
    """A read-only CAS/source witness no longer matches the reviewed view."""

    code = "teacher_workflow.assessment_eligibility.plan_stale"


def _identifier(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise AssessmentEligibilityPlanError(f"{label} must be a bounded identifier.")
    return value


def _reasons(values: tuple[str, ...], disposition: DispositionOrDefer) -> None:
    if not isinstance(values, tuple) or len(values) > 16:
        raise AssessmentEligibilityPlanError("Reason codes must be a bounded tuple.")
    if len(set(values)) != len(values) or any(
        not isinstance(code, str) or len(code) > 128 or _REASON.fullmatch(code) is None
        for code in values
    ):
        raise AssessmentEligibilityPlanError("Reason codes are invalid or repeated.")
    if disposition == "included" and values:
        raise AssessmentEligibilityPlanError(
            "Include must not carry exclusion reasons."
        )
    if disposition in {"excluded", "pending", "unsupported"} and not values:
        raise AssessmentEligibilityPlanError(
            "Exclude, Pending and Unsupported each require a reason code."
        )
    if disposition is None and values:
        raise AssessmentEligibilityPlanError("Deferred items must not carry reasons.")


def _rationale(value: str | None) -> None:
    if value is not None and (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > MAXIMUM_RATIONALE
        or any(ord(char) < 32 and char not in "\n\t" for char in value)
    ):
        raise AssessmentEligibilityPlanError(
            "Rationale must be bounded, readable text."
        )


def _disposition(value: DispositionOrDefer) -> None:
    if value is not None and value not in _ALLOWED:
        raise AssessmentEligibilityPlanError("Unpermitted teacher disposition.")


@dataclass(frozen=True, slots=True)
class BatchStudentException:
    """One deliberate exception, expanded only to reviewed selected source IDs."""

    student_id: str
    disposition: DispositionOrDefer
    reason_codes: tuple[str, ...] = ()
    rationale: str | None = None
    replace_existing: bool = False

    def __post_init__(self) -> None:
        _identifier(self.student_id, "student_id")
        _disposition(self.disposition)
        _reasons(self.reason_codes, self.disposition)
        _rationale(self.rationale)
        if type(self.replace_existing) is not bool:
            raise AssessmentEligibilityPlanError("replace_existing must be boolean.")
        if self.disposition is None and (
            self.rationale is not None or self.replace_existing
        ):
            raise AssessmentEligibilityPlanError(
                "Defer cannot replace an existing record."
            )


@dataclass(frozen=True, slots=True)
class BatchItemException:
    """Explicit item override wins over the student and common decision."""

    item_id: str
    disposition: DispositionOrDefer
    reason_codes: tuple[str, ...] = ()
    rationale: str | None = None
    replace_existing: bool = False

    def __post_init__(self) -> None:
        _identifier(self.item_id, "item_id")
        _disposition(self.disposition)
        _reasons(self.reason_codes, self.disposition)
        _rationale(self.rationale)
        if type(self.replace_existing) is not bool:
            raise AssessmentEligibilityPlanError("replace_existing must be boolean.")
        if self.disposition is None and (
            self.rationale is not None or self.replace_existing
        ):
            raise AssessmentEligibilityPlanError(
                "Defer cannot replace an existing record."
            )


@dataclass(frozen=True, slots=True)
class BatchEligibilitySelection:
    """Exact selected IDs; no wildcard, implicit roster expansion or auto-accept."""

    selected_item_ids: tuple[str, ...]
    disposition: TeacherDisposition
    reason_codes: tuple[str, ...] = ()
    rationale: str | None = None
    student_exceptions: tuple[BatchStudentException, ...] = ()
    item_exceptions: tuple[BatchItemException, ...] = ()

    def __post_init__(self) -> None:
        _disposition(self.disposition)
        _reasons(self.reason_codes, self.disposition)
        _rationale(self.rationale)
        if not isinstance(self.selected_item_ids, tuple) or (
            len(self.selected_item_ids) > MAXIMUM_EVIDENCE_ITEMS
        ):
            raise AssessmentEligibilityPlanError("Selected source IDs are not bounded.")
        for item_id in self.selected_item_ids:
            _identifier(item_id, "selected item_id")
        if len(set(self.selected_item_ids)) != len(self.selected_item_ids):
            raise AssessmentEligibilityPlanError("Duplicate selected source item.")
        if not isinstance(self.student_exceptions, tuple) or not isinstance(
            self.item_exceptions, tuple
        ):
            raise AssessmentEligibilityPlanError("Exceptions must be immutable tuples.")
        if any(
            not isinstance(x, BatchStudentException) for x in self.student_exceptions
        ):
            raise AssessmentEligibilityPlanError("Invalid student exception.")
        if any(not isinstance(x, BatchItemException) for x in self.item_exceptions):
            raise AssessmentEligibilityPlanError("Invalid item exception.")
        if len(set(x.student_id for x in self.student_exceptions)) != len(
            self.student_exceptions
        ) or len(set(x.item_id for x in self.item_exceptions)) != len(
            self.item_exceptions
        ):
            raise AssessmentEligibilityPlanError("Conflicting duplicate exceptions.")


@dataclass(frozen=True, slots=True)
class BatchEligibilityPointerWitness:
    """One read-only #122-style CAS observation, not a permission or lease."""

    source: EvidenceSourceReference
    selected_revision: int | None
    selected_sha256: str | None
    membership_revision: int
    membership_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, EvidenceSourceReference):
            raise AssessmentEligibilityPlanError(
                "Pointer witness requires exact source."
            )
        if (self.selected_revision is None) != (self.selected_sha256 is None):
            raise AssessmentEligibilityPlanError(
                "Pointer revision and digest must pair."
            )
        if self.selected_revision is not None and (
            type(self.selected_revision) is not int or self.selected_revision < 1
        ):
            raise AssessmentEligibilityPlanError("Invalid selected revision.")
        if (
            not isinstance(self.membership_sha256, str)
            or _SHA256.fullmatch(self.membership_sha256) is None
            or type(self.membership_revision) is not int
            or self.membership_revision < 1
        ):
            raise AssessmentEligibilityPlanError("Invalid membership CAS witness.")
        if self.selected_sha256 is not None and (
            not isinstance(self.selected_sha256, str)
            or _SHA256.fullmatch(self.selected_sha256) is None
        ):
            raise AssessmentEligibilityPlanError("Invalid pointer digest.")


@dataclass(frozen=True, slots=True)
class BatchEligibilityPlanItem:
    """Fixed per-source proposed action and reviewed current-state witness."""

    source: EvidenceSourceReference
    student_id: str | None
    student_label: str
    evidence_label: str
    disposition: DispositionOrDefer
    reason_codes: tuple[str, ...]
    rationale: str | None
    replace_existing: bool
    status: PlanItemStatus
    status_reason: str | None
    witness: BatchEligibilityPointerWitness
    reviewed_eligibility_status: str | None
    reviewed_disposition: str | None
    reviewed_operative_included: bool

    def __post_init__(self) -> None:
        if self.source != self.witness.source:
            raise AssessmentEligibilityPlanError("Plan item/witness identity mismatch.")
        _disposition(self.disposition)
        _reasons(self.reason_codes, self.disposition)
        _rationale(self.rationale)
        if self.status not in {"action", "unchanged", "deferred", "blocked"}:
            raise AssessmentEligibilityPlanError("Unrecognized plan item status.")
        if self.status == "action" and self.disposition is None:
            raise AssessmentEligibilityPlanError("Action requires a disposition.")
        if self.status == "deferred" and self.disposition is not None:
            raise AssessmentEligibilityPlanError("Deferred means no action.")


@dataclass(frozen=True, slots=True)
class BatchEligibilityReviewPlan:
    """In-memory, exact immutable proposal; no commit authority without #125-D."""

    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    publication_id: str
    cache_key: str
    snapshot_digest: str
    membership_revision: int
    membership_sha256: str
    academic_period_id: str
    academic_period_calendar_revision: int
    roster_and_source_sha256: str
    actor: TeacherActionActor
    policy: GuidedEligibilityPolicyChoice
    items: tuple[BatchEligibilityPlanItem, ...]
    plan_sha256: str
    class_label: str | None = None
    assessment_title: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.work, ModuleWorkRef)
            or self.work.class_id != self.class_id
        ):
            raise AssessmentEligibilityPlanError("Plan work/class does not match.")
        if (
            type(self.membership_revision) is not int
            or self.membership_revision < 1
            or type(self.academic_period_calendar_revision) is not int
            or self.academic_period_calendar_revision < 1
        ):
            raise AssessmentEligibilityPlanError("Plan has invalid academic revisions.")
        for name, digest in (
            ("membership", self.membership_sha256),
            ("review", self.roster_and_source_sha256),
            ("plan", self.plan_sha256),
        ):
            if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
                raise AssessmentEligibilityPlanError(f"Invalid {name} digest.")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > MAXIMUM_EVIDENCE_ITEMS
            or any(
                not isinstance(item, BatchEligibilityPlanItem) for item in self.items
            )
        ):
            raise AssessmentEligibilityPlanError("Plan item collection is invalid.")
        if len({item.source.item_id for item in self.items}) != len(self.items):
            raise AssessmentEligibilityPlanError(
                "Plan contains repeated item identities."
            )

    @property
    def action_count(self) -> int:
        return sum(item.status == "action" for item in self.items)

    @property
    def blocked_count(self) -> int:
        return sum(item.status == "blocked" for item in self.items)

    @property
    def unchanged_count(self) -> int:
        return sum(item.status == "unchanged" for item in self.items)

    @property
    def deferred_count(self) -> int:
        return sum(item.status == "deferred" for item in self.items)


def _exact_items(
    review: AssessmentEligibilityReview,
) -> dict[str, AssessmentEligibilityItem]:
    if not isinstance(review, AssessmentEligibilityReview):
        raise AssessmentEligibilityPlanError("Expected a #125-B assessment review.")
    if (
        len(review.students) > 500
        or review.projected_item_count > MAXIMUM_EVIDENCE_ITEMS
    ):
        raise AssessmentEligibilityPlanError("Assessment review exceeds safe bounds.")
    result: dict[str, AssessmentEligibilityItem] = {}
    seen_students: set[str] = set()
    for student in review.students:
        if student.student_id in seen_students:
            raise AssessmentEligibilityPlanError("Duplicated Core roster student.")
        seen_students.add(student.student_id)
        for item in student.items:
            if item.student_id != student.student_id:
                raise AssessmentEligibilityPlanError("Misattributed student evidence.")
            if not student.within_requested_authorization:
                raise AssessmentEligibilityPlanError(
                    "Out-of-scope evidence is present."
                )
            _insert_reviewed_item(result, item, review)
    for item in (*review.shared_items, *review.unmatched_items):
        _insert_reviewed_item(result, item, review)
    if len(result) != review.projected_item_count:
        raise AssessmentEligibilityPlanError(
            "Projected coverage count is inconsistent."
        )
    if review.candidate_item_count != sum(
        item.candidate_for_explicit_review for item in result.values()
    ):
        raise AssessmentEligibilityPlanError("Candidate count is inconsistent.")
    return result


def _insert_reviewed_item(
    result: dict[str, AssessmentEligibilityItem],
    item: AssessmentEligibilityItem,
    review: AssessmentEligibilityReview,
) -> None:
    if not isinstance(item, AssessmentEligibilityItem):
        raise AssessmentEligibilityPlanError("Unrecognized assessment item.")
    if (
        item.source.work != review.work
        or item.source.publication_id != review.publication_id
        or item.source.cache_key != review.cache_key
        or item.source.snapshot_digest != review.snapshot_digest
    ):
        raise AssessmentEligibilityPlanError("Item source differs from reviewed scope.")
    if item.source.item_id in result:
        raise AssessmentEligibilityPlanError("Duplicated exact evidence item.")
    result[item.source.item_id] = item


def _json_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


def review_witness_sha256(review: AssessmentEligibilityReview) -> str:
    """Witness all roster/evidence facts, not just the selected subset."""
    indexed = _exact_items(review)
    return _json_digest(
        {
            "class": review.class_id,
            "grade_item": review.grade_item_id,
            "work": (
                review.work.module_id,
                review.work.class_id,
                review.work.work_id,
            ),
            "source": (
                review.publication_id,
                review.cache_key,
                review.snapshot_digest,
                review.source_status,
            ),
            "membership": (
                review.membership_state,
                review.membership_revision,
                review.academic_period_id,
                review.academic_period_calendar_revision,
            ),
            "roster": [
                (
                    s.student_id,
                    s.display_label,
                    s.period,
                    s.within_requested_authorization,
                )
                for s in review.students
            ],
            "items": [
                (
                    key,
                    item.student_id,
                    item.evidence_label,
                    item.target_kind,
                    item.target_id,
                    item.result_kind,
                    item.eligibility_status,
                    item.selected_eligibility_revision,
                    item.selected_eligibility_disposition,
                    item.operative_included,
                    item.candidate_for_explicit_review,
                    tuple((e.code, e.route) for e in item.exceptions),
                )
                for key, item in sorted(indexed.items())
            ],
            "exceptions": [
                (e.code, e.route, e.student_id, e.source.item_id if e.source else None)
                for e in review.exceptions
            ],
        }
    )


def capture_batch_pointer_witnesses(
    workspace_root: str | Path,
    review: AssessmentEligibilityReview,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    selected_item_ids: tuple[str, ...],
) -> tuple[BatchEligibilityPointerWitness, ...]:
    """Read only current CAS digests from canonical Meridian stores.

    Requires an already-authorized exact snapshot. Fresh authorization and source
    checks remain the executor's responsibility; a witness is not an access grant.
    """
    indexed = _exact_items(review)
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise AssessmentEligibilityPlanError(
            "An authorized exact snapshot is required."
        )
    source = authorized_snapshot.stored.snapshot.source.publication
    if (
        source.work != review.work
        or source.publication_id != review.publication_id
        or authorized_snapshot.stored.cache_key != review.cache_key
        or authorized_snapshot.stored.snapshot_digest != review.snapshot_digest
        or authorized_snapshot.assessment.source_status != review.source_status
    ):
        raise AssessmentEligibilityPlanStaleError("Authorized snapshot changed.")
    if (
        not isinstance(selected_item_ids, tuple)
        or len(selected_item_ids) > MAXIMUM_EVIDENCE_ITEMS
    ):
        raise AssessmentEligibilityPlanError("Selected IDs are not bounded.")
    if len(set(selected_item_ids)) != len(selected_item_ids) or (
        set(selected_item_ids) - set(indexed)
    ):
        raise AssessmentEligibilityPlanError(
            "Selected IDs are duplicated or unavailable."
        )
    membership = load_current_grade_item_membership_decision(
        workspace_root, review.class_id, review.grade_item_id, review.work
    )
    if (
        membership is None
        or membership.decision.decision != "included"
        or membership.decision.membership_revision != review.membership_revision
    ):
        raise AssessmentEligibilityPlanStaleError("Grade Item membership changed.")
    assignment = membership.decision.academic_period
    if (
        assignment is None
        or assignment.period.period_id != review.academic_period_id
        or assignment.calendar_revision != review.academic_period_calendar_revision
    ):
        raise AssessmentEligibilityPlanStaleError("Academic Period basis changed.")
    result: list[BatchEligibilityPointerWitness] = []
    for item_id in sorted(selected_item_ids):
        item = indexed[item_id]
        stored = load_current_evidence_eligibility_decision(
            workspace_root, review.class_id, review.grade_item_id, item.source
        )
        revision = None if stored is None else stored.decision.eligibility_revision
        digest = None if stored is None else stored.decision_sha256
        disposition = None if stored is None else stored.decision.disposition
        if (
            revision != item.selected_eligibility_revision
            or disposition != item.selected_eligibility_disposition
        ):
            raise AssessmentEligibilityPlanStaleError(
                "Selected eligibility changed after roster review."
            )
        result.append(
            BatchEligibilityPointerWitness(
                item.source,
                revision,
                digest,
                membership.decision.membership_revision,
                membership.decision_sha256,
            )
        )
    return tuple(result)


def _classify_action(
    item: AssessmentEligibilityItem,
    disposition: DispositionOrDefer,
    replace_existing: bool,
    review: AssessmentEligibilityReview,
) -> tuple[PlanItemStatus, str | None]:
    if disposition is None:
        return "deferred", "explicitly_deferred"
    if review.source_status != "current":
        return "blocked", "source_not_current"
    if review.membership_state != "included":
        return "blocked", "grade_item_membership_not_included"
    if any(
        issue.code
        not in {
            "previous_included",
            "previous_excluded",
            "previous_pending",
            "previous_unsupported",
        }
        for issue in item.exceptions
    ):
        return "blocked", item.exceptions[0].code if item.exceptions else "unsafe_item"
    if item.eligibility_status in {"included", "excluded", "pending", "unsupported"}:
        if item.selected_eligibility_disposition == disposition and (
            disposition != "included" or item.operative_included
        ):
            return "unchanged", "existing_matching_selection"
        if not replace_existing:
            return "blocked", "replacement_requires_item_or_student_override"
        return "action", None
    if item.candidate_for_explicit_review:
        return "action", None
    return "blocked", "not_a_safe_new_decision"


def build_batch_eligibility_plan(
    review: AssessmentEligibilityReview,
    selection: BatchEligibilitySelection,
    *,
    actor: TeacherActionActor,
    policy: GuidedEligibilityPolicyChoice,
    witnesses: tuple[BatchEligibilityPointerWitness, ...],
    qualified_policies: tuple[GuidedEligibilityPolicyChoice, ...] = (
        DEFAULT_GUIDED_ELIGIBILITY_POLICIES
    ),
) -> BatchEligibilityReviewPlan:
    """Build a deterministic pre-Apply proposal; zero IO, zero side effects."""
    indexed = _exact_items(review)
    if not isinstance(selection, BatchEligibilitySelection):
        raise AssessmentEligibilityPlanError("Expected explicit batch selection.")
    if not isinstance(actor, TeacherActionActor):
        raise AssessmentEligibilityPlanError("Expected verified #121 actor binding.")
    if (
        not isinstance(policy, GuidedEligibilityPolicyChoice)
        or not isinstance(qualified_policies, tuple)
        or policy not in qualified_policies
    ):
        raise AssessmentEligibilityPlanError("Unqualified eligibility policy choice.")
    if not isinstance(witnesses, tuple) or any(
        not isinstance(x, BatchEligibilityPointerWitness) for x in witnesses
    ):
        raise AssessmentEligibilityPlanError(
            "Missing typed selected-pointer witnesses."
        )
    selected = set(selection.selected_item_ids)
    if selected - set(indexed):
        raise AssessmentEligibilityPlanError("Selected item absent from exact review.")
    witness_map = {w.source.item_id: w for w in witnesses}
    if len(witness_map) != len(witnesses) or set(witness_map) != selected:
        raise AssessmentEligibilityPlanError(
            "CAS witnesses do not cover selection exactly."
        )
    if (
        review.membership_revision is None
        or review.academic_period_id is None
        or review.academic_period_calendar_revision is None
    ):
        raise AssessmentEligibilityPlanError("Included membership/period is required.")
    if any(
        w.membership_revision != review.membership_revision
        or w.source != indexed[w.source.item_id].source
        or w.selected_revision
        != indexed[w.source.item_id].selected_eligibility_revision
        for w in witnesses
    ):
        raise AssessmentEligibilityPlanStaleError("Current CAS witnesses differ.")
    membership_hashes = {w.membership_sha256 for w in witnesses}
    if len(membership_hashes) > 1:
        raise AssessmentEligibilityPlanStaleError("Membership CAS witness diverged.")
    if not witnesses:
        raise AssessmentEligibilityPlanError("No exact item witnesses were provided.")
    student_map = {student.student_id: student for student in review.students}
    student_exceptions = {x.student_id: x for x in selection.student_exceptions}
    item_exceptions = {x.item_id: x for x in selection.item_exceptions}
    if set(item_exceptions) - selected:
        raise AssessmentEligibilityPlanError("Item override is outside selected set.")
    for student_id in student_exceptions:
        if student_id not in student_map or not any(
            indexed[item_id].student_id == student_id for item_id in selected
        ):
            raise AssessmentEligibilityPlanError(
                "Student exception has no selected exact source items."
            )
    rows: list[BatchEligibilityPlanItem] = []
    for item_id in sorted(selected):
        item = indexed[item_id]
        override: BatchItemException | BatchStudentException | None = (
            item_exceptions.get(item_id)
        )
        if override is None and item.student_id is not None:
            override = student_exceptions.get(item.student_id)
        disposition: DispositionOrDefer = (
            selection.disposition if override is None else override.disposition
        )
        reasons = selection.reason_codes if override is None else override.reason_codes
        rationale = selection.rationale
        if override is not None:
            if override.rationale is not None:
                rationale = override.rationale
            elif override.disposition != selection.disposition:
                # A common rationale for another disposition is not inherited.
                rationale = None
        replace_existing = False if override is None else override.replace_existing
        if disposition is None:
            rationale = None
        _reasons(reasons, disposition)
        _rationale(rationale)
        status, status_reason = _classify_action(
            item, disposition, replace_existing, review
        )
        label = "Unmatched or shared evidence"
        if item.student_id is not None and item.student_id in student_map:
            label = student_map[item.student_id].display_label
        rows.append(
            BatchEligibilityPlanItem(
                source=item.source,
                student_id=item.student_id,
                student_label=label,
                evidence_label=item.evidence_label,
                disposition=disposition,
                reason_codes=reasons,
                rationale=rationale,
                replace_existing=replace_existing,
                status=status,
                status_reason=status_reason,
                witness=witness_map[item_id],
                reviewed_eligibility_status=item.eligibility_status,
                reviewed_disposition=item.selected_eligibility_disposition,
                reviewed_operative_included=item.operative_included,
            )
        )
    witness = review_witness_sha256(review)
    digest = _json_digest(
        {
            "review": witness,
            "actor": (actor.actor_id, actor.profile_sha256, actor.source),
            "policy": (policy.policy_id, policy.policy_version),
            "membership_sha256": next(iter(membership_hashes)),
            "items": [
                (
                    item.source.item_id,
                    item.witness.selected_revision,
                    item.witness.selected_sha256,
                    item.disposition,
                    item.reason_codes,
                    item.rationale,
                    item.replace_existing,
                    item.status,
                )
                for item in rows
            ],
        }
    )
    return BatchEligibilityReviewPlan(
        class_id=review.class_id,
        grade_item_id=review.grade_item_id,
        work=review.work,
        publication_id=review.publication_id,
        cache_key=review.cache_key,
        snapshot_digest=review.snapshot_digest,
        membership_revision=review.membership_revision,
        membership_sha256=next(iter(membership_hashes)),
        academic_period_id=review.academic_period_id,
        academic_period_calendar_revision=review.academic_period_calendar_revision,
        roster_and_source_sha256=witness,
        actor=actor,
        policy=policy,
        items=tuple(rows),
        plan_sha256=digest,
        class_label=review.class_label,
        assessment_title=review.assessment_title,
    )


def assert_batch_plan_review_current(
    plan: BatchEligibilityReviewPlan, fresh_review: AssessmentEligibilityReview
) -> None:
    """Read-only comparison; not a substitute for fresh domain authorization/CAS."""
    if not isinstance(plan, BatchEligibilityReviewPlan):
        raise AssessmentEligibilityPlanError("Expected typed batch plan.")
    if review_witness_sha256(fresh_review) != plan.roster_and_source_sha256:
        raise AssessmentEligibilityPlanStaleError(
            "Assessment, roster, or evidence changed; review the batch again."
        )


def render_batch_eligibility_plan(plan: BatchEligibilityReviewPlan) -> str:
    """Teacher-facing text; NEVER prints raw identities or becomes confirmation."""
    if not isinstance(plan, BatchEligibilityReviewPlan):
        raise AssessmentEligibilityPlanError("Expected typed batch plan.")
    counts = {
        disposition: sum(
            item.status == "action" and item.disposition == disposition
            for item in plan.items
        )
        for disposition in _ALLOWED
    }
    lines = [
        "BATCH ELIGIBILITY — REVIEW ONLY (NOT APPLIED)",
        f"Class: {plan.class_label or 'Current class'}",
        f"Assessment: {plan.assessment_title or 'Selected assessment'}",
        f"Academic Period: {plan.academic_period_id}",
        f"Teacher actor: {plan.actor.actor_id} ({plan.actor.source})",
        (
            f"Policy: {plan.policy.title} — {plan.policy.policy_id} "
            f"v{plan.policy.policy_version}"
        ),
        (
            f"Exact selected items: {len(plan.items)}; "
            f"proposed Include {counts['included']}, "
            f"Exclude {counts['excluded']}, Pending {counts['pending']}, "
            f"Unsupported {counts['unsupported']}"
        ),
        (
            f"Already current: {plan.unchanged_count}; "
            f"explicitly deferred: {plan.deferred_count}; blocked: {plan.blocked_count}"
        ),
        (
            "Each proposed action would produce its own canonical "
            "per-item eligibility decision."
        ),
        "Nothing has been written or selected. This screen cannot confirm actions.",
    ]
    for item in plan.items:
        outcome = item.status.upper()
        if item.status_reason:
            outcome += f" ({item.status_reason.replace('_', ' ')})"
        label = item.disposition or "no action"
        lines.append(
            f"- {item.student_label} / {item.evidence_label}: {label} — {outcome}"
        )
    return "\n".join(lines)


__all__ = (
    "AssessmentEligibilityPlanError",
    "AssessmentEligibilityPlanStaleError",
    "BatchEligibilitySelection",
    "BatchStudentException",
    "BatchItemException",
    "BatchEligibilityPointerWitness",
    "BatchEligibilityPlanItem",
    "BatchEligibilityReviewPlan",
    "build_batch_eligibility_plan",
    "capture_batch_pointer_witnesses",
    "assert_batch_plan_review_current",
    "render_batch_eligibility_plan",
    "review_witness_sha256",
)
