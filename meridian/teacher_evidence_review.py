"""Roster-backed teacher evidence review projection for Issue #110."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.classes import load_class_roster
from pds_core.rosters import (
    Roster,
    RosterError,
    StudentRecord,
    student_display_name,
    student_lookup,
)
from pds_core.routing_models import ModuleWorkRef

from meridian.evidence import (
    EvidenceInventory,
    NativePointValue,
    NativeScalarValue,
    NativeScaledValue,
    NativeStateValue,
)
from meridian.guided_projection import GuidedProjectionResult


class TeacherEvidenceReviewError(RuntimeError):
    """Base failure for teacher-facing evidence review projection."""

    code = "teacher_evidence_review.error"


class TeacherEvidenceReviewValidationError(TeacherEvidenceReviewError, ValueError):
    """Raised when authorized evidence cannot form a valid review projection."""

    code = "teacher_evidence_review.invalid"


class TeacherEvidenceRosterUnavailableError(TeacherEvidenceReviewError):
    """Raised when individualized evidence cannot be matched to a Core roster."""

    code = "teacher_evidence_review.roster_unavailable"


class TeacherEvidenceStudentMissingError(TeacherEvidenceReviewError):
    """Raised when evidence names a student absent from the canonical roster."""

    code = "teacher_evidence_review.student_missing"


class TeacherEvidenceStudentAmbiguityError(TeacherEvidenceReviewError):
    """Raised when roster-backed display context cannot distinguish students."""

    code = "teacher_evidence_review.student_ambiguous"


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TeacherEvidenceReviewValidationError(
            f"{field_name} must be a string."
        )
    if not value or value != value.strip() or "\n" in value or "\r" in value:
        raise TeacherEvidenceReviewValidationError(
            f"{field_name} must be non-empty single-line text."
        )
    return value


def _compact_text(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    compact = " ".join(value.split())
    return compact or fallback


def _humanize(value: str) -> str:
    compact = value.replace("_", " ").strip()
    if not compact:
        return "Evidence"
    return compact[:1].upper() + compact[1:]


def _scalar_text(value: object) -> str:
    if type(value) is bool:
        return "True" if value else "False"
    return str(value)


def _scaled_value_label(value: NativeScaledValue) -> str:
    for level in value.scale.levels:
        if type(level.value) is type(value.value) and level.value == value.value:
            if level.label is not None:
                return _compact_text(level.label, _scalar_text(value.value))
            break
    return _scalar_text(value.value)


def _value_label(value: object) -> str:
    if isinstance(value, NativePointValue):
        return f"{value.earned} / {value.possible}"
    if isinstance(value, NativeScaledValue):
        return _scaled_value_label(value)
    if isinstance(value, NativeStateValue):
        if value.label is not None:
            return _compact_text(value.label, _humanize(value.code))
        return _humanize(value.code)
    if isinstance(value, NativeScalarValue):
        return _scalar_text(value.value)
    raise TeacherEvidenceReviewValidationError(
        "Evidence contains an unsupported value variant."
    )


def _evidence_label(item: object) -> str:
    target = getattr(item, "target", None)
    if target is None:
        raise TeacherEvidenceReviewValidationError(
            "Evidence item is missing target context."
        )
    target_kind = getattr(target, "target_kind", None)
    if not isinstance(target_kind, str) or not target_kind:
        raise TeacherEvidenceReviewValidationError(
            "Evidence target kind is unavailable."
        )
    sequence = getattr(target, "sequence", None)
    if isinstance(sequence, int) and not isinstance(sequence, bool) and sequence > 0:
        return f"{_humanize(target_kind)} {sequence}"

    provenance = getattr(item, "provenance", None)
    native = getattr(provenance, "native", None)
    references = getattr(native, "references", ())
    for reference in reversed(tuple(references)):
        ref_sequence = getattr(reference, "sequence", None)
        ref_kind = getattr(reference, "kind", None)
        if (
            isinstance(ref_sequence, int)
            and not isinstance(ref_sequence, bool)
            and ref_sequence > 0
            and isinstance(ref_kind, str)
            and ref_kind
        ):
            return f"{_humanize(ref_kind)} {ref_sequence}"
    return _humanize(target_kind)


def _result_kind_label(item: object) -> str:
    result_kind = getattr(item, "result_kind", None)
    if not isinstance(result_kind, str) or not result_kind:
        raise TeacherEvidenceReviewValidationError(
            "Evidence result kind is unavailable."
        )
    return _humanize(result_kind)


def _standard_ids(item: object) -> tuple[str, ...]:
    target = getattr(item, "target", None)
    values = getattr(target, "standard_ids", ())
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise TeacherEvidenceReviewValidationError(
            "Evidence Standard identities are invalid."
        )
    return values


def _student_id(item: object) -> str | None:
    subject = getattr(item, "subject", None)
    if subject is None:
        return None
    value = getattr(subject, "student_id", None)
    return _identifier(value, "student_id")


def _item_id(item: object) -> str:
    return _identifier(getattr(item, "item_id", None), "item_id")


@dataclass(frozen=True, slots=True)
class TeacherEvidenceReviewItem:
    """One teacher-readable row carrying exact hidden evidence identity."""

    item_id: str
    student_id: str | None
    evidence_label: str
    value_label: str
    result_kind_label: str
    standard_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _identifier(self.item_id, "item_id"))
        if self.student_id is not None:
            object.__setattr__(
                self,
                "student_id",
                _identifier(self.student_id, "student_id"),
            )
        object.__setattr__(
            self,
            "evidence_label",
            _identifier(self.evidence_label, "evidence_label"),
        )
        object.__setattr__(
            self,
            "value_label",
            _identifier(self.value_label, "value_label"),
        )
        object.__setattr__(
            self,
            "result_kind_label",
            _identifier(self.result_kind_label, "result_kind_label"),
        )
        standards = tuple(self.standard_ids)
        if any(not isinstance(value, str) or not value.strip() for value in standards):
            raise TeacherEvidenceReviewValidationError(
                "standard_ids must contain non-blank strings."
            )
        object.__setattr__(self, "standard_ids", standards)


@dataclass(frozen=True, slots=True)
class TeacherEvidenceStudent:
    """One roster-backed student plus hidden exact identity and evidence rows."""

    student_id: str
    display_label: str
    period: str
    items: tuple[TeacherEvidenceReviewItem, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        object.__setattr__(
            self,
            "display_label",
            _identifier(self.display_label, "display_label"),
        )
        if not isinstance(self.period, str):
            raise TeacherEvidenceReviewValidationError(
                "period must be a string."
            )
        if not self.items:
            raise TeacherEvidenceReviewValidationError(
                "represented student must contain evidence."
            )
        if any(item.student_id != self.student_id for item in self.items):
            raise TeacherEvidenceReviewValidationError(
                "student evidence rows must preserve exact roster identity."
            )


@dataclass(frozen=True, slots=True)
class TeacherEvidenceReview:
    """Read-only roster-backed view over one exact authorized projection."""

    class_id: str
    work: ModuleWorkRef
    publication_id: str
    students: tuple[TeacherEvidenceStudent, ...]
    shared_items: tuple[TeacherEvidenceReviewItem, ...]

    def __post_init__(self) -> None:
        class_id = _identifier(self.class_id, "class_id")
        if not isinstance(self.work, ModuleWorkRef):
            raise TeacherEvidenceReviewValidationError(
                "work must be a ModuleWorkRef."
            )
        if self.work.class_id != class_id:
            raise TeacherEvidenceReviewValidationError(
                "review class must match exact work identity."
            )
        object.__setattr__(
            self,
            "publication_id",
            _identifier(self.publication_id, "publication_id"),
        )
        if any(
            not isinstance(student, TeacherEvidenceStudent)
            for student in self.students
        ):
            raise TeacherEvidenceReviewValidationError(
                "students must contain TeacherEvidenceStudent values."
            )
        if any(
            not isinstance(item, TeacherEvidenceReviewItem)
            for item in self.shared_items
        ):
            raise TeacherEvidenceReviewValidationError(
                "shared_items must contain TeacherEvidenceReviewItem values."
            )
        student_ids = tuple(student.student_id for student in self.students)
        if len(set(student_ids)) != len(student_ids):
            raise TeacherEvidenceReviewValidationError(
                "review students must not contain duplicate identities."
            )
        if any(item.student_id is not None for item in self.shared_items):
            raise TeacherEvidenceReviewValidationError(
                "shared evidence rows must not carry student identity."
            )

    @property
    def student_count(self) -> int:
        return len(self.students)

    @property
    def evidence_count(self) -> int:
        return sum(len(student.items) for student in self.students) + len(
            self.shared_items
        )

    @property
    def shared_evidence_count(self) -> int:
        return len(self.shared_items)


def _project_item(item: object) -> TeacherEvidenceReviewItem:
    value = getattr(item, "value", None)
    return TeacherEvidenceReviewItem(
        item_id=_item_id(item),
        student_id=_student_id(item),
        evidence_label=_evidence_label(item),
        value_label=_value_label(value),
        result_kind_label=_result_kind_label(item),
        standard_ids=_standard_ids(item),
    )


def _display_labels(
    records: tuple[StudentRecord, ...],
) -> dict[str, str]:
    base = {
        record.student_id: _compact_text(
            student_display_name(record),
            "Student",
        )
        for record in records
    }
    counts: dict[str, int] = {}
    for label in base.values():
        counts[label] = counts.get(label, 0) + 1

    labels: dict[str, str] = {}
    for record in records:
        label = base[record.student_id]
        if counts[label] > 1:
            period = _compact_text(record.period, "")
            if period:
                label = f"{label} · Period {period}"
        labels[record.student_id] = label

    if len(set(labels.values())) != len(labels):
        raise TeacherEvidenceStudentAmbiguityError(
            "Roster students cannot be safely distinguished for evidence review."
        )
    return labels


def build_teacher_evidence_review(
    *,
    inventory: EvidenceInventory,
    roster: Roster | None,
    work: ModuleWorkRef,
    publication_id: str,
) -> TeacherEvidenceReview:
    """Project validated evidence and optional roster into teacher-facing groups."""

    if not isinstance(work, ModuleWorkRef):
        raise TeacherEvidenceReviewValidationError(
            "work must be a ModuleWorkRef."
        )

    raw_items = tuple(getattr(inventory, "items", ()))
    projected = tuple(_project_item(item) for item in raw_items)

    represented_list: list[str] = []
    for item in projected:
        student_id = item.student_id
        if student_id is not None and student_id not in represented_list:
            represented_list.append(student_id)
    represented_ids = tuple(represented_list)

    students: tuple[TeacherEvidenceStudent, ...] = ()
    if represented_ids:
        if roster is None:
            raise TeacherEvidenceRosterUnavailableError(
                "Individualized evidence requires the canonical class roster."
            )
        if roster.class_id != work.class_id:
            raise TeacherEvidenceReviewValidationError(
                "Canonical roster class does not match evidence work."
            )
        lookup = student_lookup(roster)
        missing = tuple(
            student_id
            for student_id in represented_ids
            if student_id not in lookup
        )
        if missing:
            raise TeacherEvidenceStudentMissingError(
                "Evidence references a student absent from the current class roster."
            )

        represented = set(represented_ids)
        records = tuple(
            student
            for student in roster.students
            if student.student_id in represented
        )
        labels = _display_labels(records)
        students = tuple(
            TeacherEvidenceStudent(
                student_id=record.student_id,
                display_label=labels[record.student_id],
                period=record.period,
                items=tuple(
                    item
                    for item in projected
                    if item.student_id == record.student_id
                ),
            )
            for record in records
        )

    shared_items = tuple(item for item in projected if item.student_id is None)
    return TeacherEvidenceReview(
        class_id=work.class_id,
        work=work,
        publication_id=publication_id,
        students=students,
        shared_items=shared_items,
    )


def project_teacher_evidence_review(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
) -> TeacherEvidenceReview:
    """Build a roster-backed teacher view from one authorized projection."""

    if not isinstance(prepared, GuidedProjectionResult):
        raise TeacherEvidenceReviewValidationError(
            "prepared must be a GuidedProjectionResult."
        )

    authorized = prepared.authorized
    publication = authorized.current_context.publication
    inventory = authorized.stored.snapshot.inventory
    represented = any(
        getattr(item, "subject", None) is not None
        for item in inventory.items
    )

    roster: Roster | None = None
    if represented:
        try:
            roster = load_class_roster(workspace_root, publication.work.class_id)
        except (RosterError, OSError, ValueError) as error:
            raise TeacherEvidenceRosterUnavailableError(
                "Canonical class roster could not be loaded safely."
            ) from error

    return build_teacher_evidence_review(
        inventory=inventory,
        roster=roster,
        work=publication.work,
        publication_id=publication.publication_id,
    )


__all__ = (
    "TeacherEvidenceReview",
    "TeacherEvidenceReviewError",
    "TeacherEvidenceReviewItem",
    "TeacherEvidenceReviewValidationError",
    "TeacherEvidenceRosterUnavailableError",
    "TeacherEvidenceStudent",
    "TeacherEvidenceStudentAmbiguityError",
    "TeacherEvidenceStudentMissingError",
    "build_teacher_evidence_review",
    "project_teacher_evidence_review",
)
