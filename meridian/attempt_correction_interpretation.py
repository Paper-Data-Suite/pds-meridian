"""#126-C: exact-source, teacher-reviewed attempt-relationship intention.

This is a typed *preview*, never a producer correction certification or an
academic writer. Immutable #30 and, when required, #31 remain authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_attempt_inventory import (
    AssessmentAttemptInventory,
    NativeAttemptInventoryRow,
    StudentAttemptInventoryRow,
)
from meridian.attempt_selection import (
    MAXIMUM_ATTEMPT_SELECTION_RATIONALE_LENGTH,
    AttemptObservationReference,
    AttemptProjectionReference,
)

TeacherTreatment: TypeAlias = Literal[
    "unresolved",
    "teacher_reviewed_correction",
    "teacher_reviewed_reassessment",
]


class AttemptInterpretationError(ValueError):
    """The requested interpretation cannot be justified by this projection."""

    code = "teacher_workflow.correction_interpretation.invalid"


@dataclass(frozen=True, slots=True)
class AttemptOriginFact:
    """Producer-reported native origin; does not establish causal correction."""

    attempt: AttemptObservationReference = field(repr=False)
    result_origin: str | None
    scan_review_failure_reference: bool
    points: tuple[int | float, int | float] | None
    operative_eligible: bool


@dataclass(frozen=True, slots=True)
class AttemptInterpretationPreview:
    """Exact, unsaved teacher intent; no CAS, authorization grant, or write."""

    class_id: str
    grade_item_id: str
    student_id: str = field(repr=False)
    student_label: str
    source_snapshot: AttemptProjectionReference = field(repr=False)
    treatment: TeacherTreatment
    facts: tuple[AttemptOriginFact, ...]
    original_attempt: AttemptObservationReference | None = field(repr=False)
    intended_selected_attempts: tuple[AttemptObservationReference, ...] = field(
        repr=False
    )
    teacher_rationale: str | None = field(repr=False)
    suggested_canonical_rationale: str | None = field(repr=False)
    needs_reassessment_decision: bool
    selection_status_at_preview: str | None
    selected_revision_at_preview: int | None

    @property
    def can_continue_to_reviewed_action(self) -> bool:
        return self.treatment != "unresolved"


def _source(value: AssessmentAttemptInventory) -> AttemptProjectionReference:
    return AttemptProjectionReference(
        work=ModuleWorkRef(value.work_module_id, value.class_id, value.work_id),
        publication_id=value.publication_id,
        cache_key=value.cache_key,
        snapshot_digest=value.snapshot_digest,
    )


def _valid_rationale(value: str | None) -> str:
    if not isinstance(value, str):
        raise AttemptInterpretationError("Teacher rationale is required.")
    reason = value.strip()
    if not reason:
        raise AttemptInterpretationError("Teacher rationale is required.")
    if any(ord(character) < 32 and character not in "\t\n" for character in reason):
        raise AttemptInterpretationError(
            "Rationale contains an unsafe control character."
        )
    if any(ord(character) == 127 for character in reason):
        raise AttemptInterpretationError(
            "Rationale contains an unsafe control character."
        )
    return reason


def _safe_display(value: str) -> str:
    return "".join(character if character.isprintable() else "?" for character in value)


def _label(attempt: AttemptObservationReference) -> str:
    if attempt.native.sequence is not None:
        return f"Attempt {attempt.native.sequence}"
    return "Native attempt (exact identity retained)"


def _student(
    value: AssessmentAttemptInventory, student_id: str
) -> StudentAttemptInventoryRow:
    matching = [row for row in value.students if row.student_id == student_id]
    if len(matching) != 1:
        raise AttemptInterpretationError(
            "Student is not uniquely present in the authorized review."
        )
    return matching[0]


def preview_attempt_interpretation(
    inventory: AssessmentAttemptInventory,
    *,
    student_id: str,
    treatment: TeacherTreatment,
    selected_attempts: tuple[AttemptObservationReference, ...] = (),
    original_attempt: AttemptObservationReference | None = None,
    teacher_rationale: str | None = None,
) -> AttemptInterpretationPreview:
    """Validate typed teacher testimony without authoring or selecting a decision.

    Only explicit in-snapshot, operative eligible attempts can be intended for
    future #30 selection. A teacher's correction account is *never* promoted
    to verified producer provenance. A fresh #30/#31 + #122 check is required
    before any consequential commit.
    """
    if not isinstance(inventory, AssessmentAttemptInventory):
        raise AttemptInterpretationError("Expected an authorized attempt inventory.")
    if treatment not in {
        "unresolved",
        "teacher_reviewed_correction",
        "teacher_reviewed_reassessment",
    }:
        raise AttemptInterpretationError("Unsupported teacher interpretation.")
    row = _student(inventory, student_id)
    source = _source(inventory)
    native_rows: dict[AttemptObservationReference, NativeAttemptInventoryRow] = {
        item.attempt: item for item in row.attempts
    }
    if len(native_rows) != len(row.attempts):
        raise AttemptInterpretationError("Duplicate native attempt identity.")
    facts = tuple(
        AttemptOriginFact(
            attempt=item.attempt,
            result_origin=item.result_origin,
            scan_review_failure_reference=item.scan_review_failure_reference,
            points=item.point_result,
            operative_eligible=item.operative_eligible,
        )
        for item in row.attempts
    )
    if treatment == "unresolved":
        if (
            selected_attempts
            or original_attempt is not None
            or teacher_rationale is not None
        ):
            raise AttemptInterpretationError(
                "Unresolved interpretation cannot silently choose an attempt."
            )
        return AttemptInterpretationPreview(
            class_id=inventory.class_id,
            grade_item_id=inventory.grade_item_id,
            student_id=student_id,
            student_label=row.display_label,
            source_snapshot=source,
            treatment=treatment,
            facts=facts,
            original_attempt=None,
            intended_selected_attempts=(),
            teacher_rationale=None,
            suggested_canonical_rationale=None,
            needs_reassessment_decision=False,
            selection_status_at_preview=row.selection_status,
            selected_revision_at_preview=row.selected_decision_revision,
        )
    if inventory.source_status != "current" or inventory.membership_state != "included":
        raise AttemptInterpretationError("Source or Grade Item is not current.")
    if row.selection_status not in {"no_decision", "selected", "selected_none"}:
        raise AttemptInterpretationError(
            "Current attempt resolution is unavailable or stale."
        )
    if len(native_rows) < 2:
        raise AttemptInterpretationError(
            "Multiple exact native attempts are required to interpret a relationship."
        )
    if (
        not isinstance(selected_attempts, tuple)
        or not selected_attempts
        or any(
            not isinstance(value, AttemptObservationReference)
            for value in selected_attempts
        )
        or len(set(selected_attempts)) != len(selected_attempts)
    ):
        raise AttemptInterpretationError("Choose distinct exact attempts explicitly.")
    if any(
        not isinstance(item, AttemptObservationReference)
        or item.source_snapshot != source
        or item.student_id != student_id
        or item not in native_rows
        or not native_rows[item].operative_eligible
        for item in selected_attempts
    ):
        raise AttemptInterpretationError(
            "An intended selection is not an exact current eligible attempt."
        )
    reason = _valid_rationale(teacher_rationale)
    if treatment == "teacher_reviewed_correction":
        if len(selected_attempts) != 1:
            raise AttemptInterpretationError(
                "A correction-use review must select exactly one operative result."
            )
        if (
            original_attempt is None
            or original_attempt not in native_rows
            or original_attempt == selected_attempts[0]
        ):
            raise AttemptInterpretationError(
                "Identify a distinct, source-reported original attempt explicitly."
            )
        statement = (
            "Teacher-reviewed correction of result representation "
            "(not producer-certified): "
            f"{_label(original_attempt)} treated as original; "
            f"{_label(selected_attempts[0])} intended for current use. "
        )
    else:
        if original_attempt is not None:
            raise AttemptInterpretationError(
                "An original-correction claim is not applicable to reassessment."
            )
        statement = (
            "Teacher-reviewed separate performance/reassessment "
            "(not inferred from score or chronology): "
            + ", ".join(_label(item) for item in selected_attempts)
            + " intended for current use. "
        )
    canonical_rationale = statement + "Teacher explanation: " + reason
    if len(canonical_rationale) > MAXIMUM_ATTEMPT_SELECTION_RATIONALE_LENGTH:
        raise AttemptInterpretationError("Rationale exceeds canonical #30 size limit.")
    return AttemptInterpretationPreview(
        class_id=inventory.class_id,
        grade_item_id=inventory.grade_item_id,
        student_id=student_id,
        student_label=row.display_label,
        source_snapshot=source,
        treatment=treatment,
        facts=facts,
        original_attempt=original_attempt,
        intended_selected_attempts=selected_attempts,
        teacher_rationale=reason,
        suggested_canonical_rationale=canonical_rationale,
        needs_reassessment_decision=len(selected_attempts) > 1,
        selection_status_at_preview=row.selection_status,
        selected_revision_at_preview=row.selected_decision_revision,
    )


def render_attempt_interpretation_preview(value: AttemptInterpretationPreview) -> str:
    """Plain, screen-safe preview with no fake confirmed save or producer claim."""
    if not isinstance(value, AttemptInterpretationPreview):
        raise TypeError("Expected an AttemptInterpretationPreview.")
    lines = [
        "Meridian — Review Correction or Reassessment (NOT SAVED)",
        f"Student: {_safe_display(value.student_label)}",
        f"Interpretation: {value.treatment.replace('_', ' ')}",
        "Producer: native origin facts only; correction relationship NOT certified.",
    ]
    for fact in value.facts:
        origin = fact.result_origin or "origin unavailable"
        detail = (
            "scan-review reference reported"
            if fact.scan_review_failure_reference
            else "no scan-review reference reported"
        )
        lines.append(f"  {_label(fact.attempt)}: {_safe_display(origin)}; {detail}")
    if value.treatment == "unresolved":
        lines.extend(
            (
                "Relationship unresolved; no candidate selected by this preview.",
                "Review the paper/source and current eligibility before deciding.",
            )
        )
    else:
        lines.append(
            "Intended exact selection: "
            + ", ".join(_label(item) for item in value.intended_selected_attempts)
        )
        if value.original_attempt is not None:
            lines.append(
                "Teacher identifies original: " + _label(value.original_attempt)
            )
        lines.append(
            "Teacher statement: " + _safe_display(value.teacher_rationale or "")
        )
        lines.append(
            "Separate #31 reassessment relationship required: "
            + ("yes" if value.needs_reassessment_decision else "no")
        )
    lines.append(
        "Nothing was saved. #30/#31 policy, exact eligibility, CAS and actor "
        "must be revalidated at the later reviewed action."
    )
    return "\n".join(lines)


__all__ = (
    "AttemptInterpretationError",
    "AttemptInterpretationPreview",
    "AttemptOriginFact",
    "TeacherTreatment",
    "preview_attempt_interpretation",
    "render_attempt_interpretation_preview",
)
