"""Immutable teacher final-Grade override decisions and canonical serialization.

Issue #53 v1 overrides only exact persisted final Academic Period Grade results.
The record is an immutable teacher decision layered over a source Grade result;
it never mutates the source calculation.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_from_dict,
    academic_period_ref_to_dict,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.conventional_grade import (
    ConventionalGradeResultReference,
    conventional_grade_result_reference_from_dict,
    conventional_grade_result_reference_to_dict,
)
from meridian.grade_policy import (
    GradeCalculationFamily,
    GradePolicyActor,
    GradePolicyValidationError,
)
from meridian.hybrid_grade_result import (
    HybridGradeResultReference,
    hybrid_grade_result_reference_from_dict,
    hybrid_grade_result_reference_to_dict,
)
from meridian.standards_grade_result import (
    StandardsGradeResultReference,
    standards_grade_result_reference_from_dict,
    standards_grade_result_reference_to_dict,
)

TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION: Final[str] = "1"
TEACHER_GRADE_OVERRIDE_RECORD_TYPE: Final[str] = "meridian_teacher_grade_override"
MAXIMUM_TEACHER_GRADE_OVERRIDE_TEXT_LENGTH: Final[int] = 2000

TeacherGradeOverrideDecisionKind: TypeAlias = Literal["override", "withdraw"]
GradeResultReference: TypeAlias = (
    ConventionalGradeResultReference
    | StandardsGradeResultReference
    | HybridGradeResultReference
)

_FAMILIES: Final[frozenset[str]] = frozenset(
    {"conventional", "standards_based", "hybrid"}
)
_DECISIONS: Final[frozenset[str]] = frozenset({"override", "withdraw"})
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_KEYS: Final[frozenset[str]] = frozenset({"family", "reference"})
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "student_id",
        "school_year",
        "period_id",
        "calendar_revision",
        "calculation_family",
        "override_revision",
        "override_sha256",
    }
)
_DECISION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "student_id",
        "target_period",
        "calendar_revision",
        "calculation_family",
        "override_revision",
        "supersedes_revision",
        "decision",
        "source_result",
        "replacement_grade",
        "withdrawn_override_reference",
        "actor",
        "rationale",
        "decided_at",
    }
)


class TeacherGradeOverrideError(ValueError):
    """Base error for immutable teacher Grade override contracts."""


class TeacherGradeOverrideValidationError(TeacherGradeOverrideError):
    """Raised when override data violates the exact v1 domain contract."""


class TeacherGradeOverrideSerializationError(TeacherGradeOverrideError):
    """Raised when override JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class GradeOverrideSourceResultReference:
    """Exact family-tagged immutable Grade result reference."""

    family: GradeCalculationFamily
    reference: GradeResultReference

    def __post_init__(self) -> None:
        family = _family(self.family, "family")
        reference = _validated_result_reference(family, self.reference)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "reference", reference)


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideReference:
    """Exact immutable teacher Grade override revision and digest."""

    class_id: str
    student_id: str
    school_year: str
    period_id: str
    calendar_revision: int
    calculation_family: GradeCalculationFamily
    override_revision: int
    override_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        try:
            period = AcademicPeriodRef(self.school_year, self.period_id)
        except AcademicPeriodValidationError as error:
            raise TeacherGradeOverrideValidationError(
                f"override reference period is invalid: {error}"
            ) from error
        object.__setattr__(self, "school_year", period.school_year)
        object.__setattr__(self, "period_id", period.period_id)
        object.__setattr__(
            self,
            "calendar_revision",
            _positive_int(self.calendar_revision, "calendar_revision"),
        )
        object.__setattr__(
            self,
            "calculation_family",
            _family(self.calculation_family, "calculation_family"),
        )
        object.__setattr__(
            self,
            "override_revision",
            _positive_int(self.override_revision, "override_revision"),
        )
        object.__setattr__(
            self,
            "override_sha256",
            _sha256(self.override_sha256, "override_sha256"),
        )


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideDecision:
    """One immutable teacher decision over one exact final Grade result."""

    schema_version: str
    record_type: str
    class_id: str
    student_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    calculation_family: GradeCalculationFamily
    override_revision: int
    supersedes_revision: int | None
    decision: TeacherGradeOverrideDecisionKind
    source_result: GradeOverrideSourceResultReference
    replacement_grade: Decimal | None
    withdrawn_override_reference: TeacherGradeOverrideReference | None
    actor: GradePolicyActor
    rationale: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION:
            raise TeacherGradeOverrideValidationError(
                'schema_version must be "1".'
            )
        if self.record_type != TEACHER_GRADE_OVERRIDE_RECORD_TYPE:
            raise TeacherGradeOverrideValidationError(
                'record_type must be "meridian_teacher_grade_override".'
            )

        class_id = _identifier(self.class_id, "class_id")
        student_id = _identifier(self.student_id, "student_id")
        try:
            target_period = validate_academic_period_ref(self.target_period)
        except (AcademicPeriodValidationError, TypeError) as error:
            raise TeacherGradeOverrideValidationError(
                f"target_period is invalid: {error}"
            ) from error
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        calculation_family = _family(
            self.calculation_family,
            "calculation_family",
        )
        override_revision = _positive_int(
            self.override_revision,
            "override_revision",
        )
        supersedes = _optional_positive_int(
            self.supersedes_revision,
            "supersedes_revision",
        )
        _validate_revision_pair(override_revision, supersedes)

        if self.decision not in _DECISIONS:
            raise TeacherGradeOverrideValidationError(
                "decision must be one of: override, withdraw."
            )
        decision = self.decision

        if not isinstance(self.source_result, GradeOverrideSourceResultReference):
            raise TeacherGradeOverrideValidationError(
                "source_result must be a GradeOverrideSourceResultReference."
            )
        source_result = GradeOverrideSourceResultReference(
            self.source_result.family,
            self.source_result.reference,
        )
        if source_result.family != calculation_family:
            raise TeacherGradeOverrideValidationError(
                "source_result family must match calculation_family."
            )
        _require_source_scope(
            source_result.reference,
            class_id=class_id,
            student_id=student_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
        )

        withdrawn_reference = self.withdrawn_override_reference
        if decision == "override":
            if self.replacement_grade is None:
                raise TeacherGradeOverrideValidationError(
                    "override requires replacement_grade."
                )
            replacement_grade = _nonnegative_decimal(
                self.replacement_grade,
                "replacement_grade",
            )
            if withdrawn_reference is not None:
                raise TeacherGradeOverrideValidationError(
                    "override requires withdrawn_override_reference=null."
                )
        else:
            if self.replacement_grade is not None:
                raise TeacherGradeOverrideValidationError(
                    "withdraw requires replacement_grade=null."
                )
            replacement_grade = None
            if not isinstance(withdrawn_reference, TeacherGradeOverrideReference):
                raise TeacherGradeOverrideValidationError(
                    "withdraw requires an exact withdrawn_override_reference."
                )
            withdrawn_reference = TeacherGradeOverrideReference(
                class_id=withdrawn_reference.class_id,
                student_id=withdrawn_reference.student_id,
                school_year=withdrawn_reference.school_year,
                period_id=withdrawn_reference.period_id,
                calendar_revision=withdrawn_reference.calendar_revision,
                calculation_family=withdrawn_reference.calculation_family,
                override_revision=withdrawn_reference.override_revision,
                override_sha256=withdrawn_reference.override_sha256,
            )
            _require_override_reference_scope(
                withdrawn_reference,
                class_id=class_id,
                student_id=student_id,
                target_period=target_period,
                calendar_revision=calendar_revision,
                calculation_family=calculation_family,
            )
            if withdrawn_reference.override_revision >= override_revision:
                raise TeacherGradeOverrideValidationError(
                    "withdrawn override revision must precede the withdrawal revision."
                )

        if not isinstance(self.actor, GradePolicyActor):
            raise TeacherGradeOverrideValidationError(
                "actor must be a GradePolicyActor."
            )
        try:
            actor = GradePolicyActor(self.actor.kind, self.actor.actor_id)
        except GradePolicyValidationError as error:
            raise TeacherGradeOverrideValidationError(
                f"actor is invalid: {error}"
            ) from error
        if actor.kind != "teacher":
            raise TeacherGradeOverrideValidationError(
                "teacher Grade override actor kind must be teacher."
            )

        rationale = _bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_TEACHER_GRADE_OVERRIDE_TEXT_LENGTH,
        )
        decided_at = _aware_utc_datetime(self.decided_at, "decided_at")

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "target_period", target_period)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "calculation_family", calculation_family)
        object.__setattr__(self, "override_revision", override_revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "source_result", source_result)
        object.__setattr__(self, "replacement_grade", replacement_grade)
        object.__setattr__(
            self,
            "withdrawn_override_reference",
            withdrawn_reference,
        )
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "decided_at", decided_at)


def validate_teacher_grade_override_decision(
    value: TeacherGradeOverrideDecision,
) -> TeacherGradeOverrideDecision:
    """Fully revalidate one teacher Grade override decision."""

    if not isinstance(value, TeacherGradeOverrideDecision):
        raise TeacherGradeOverrideValidationError(
            "value must be a TeacherGradeOverrideDecision."
        )
    return TeacherGradeOverrideDecision(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        student_id=value.student_id,
        target_period=value.target_period,
        calendar_revision=value.calendar_revision,
        calculation_family=value.calculation_family,
        override_revision=value.override_revision,
        supersedes_revision=value.supersedes_revision,
        decision=value.decision,
        source_result=value.source_result,
        replacement_grade=value.replacement_grade,
        withdrawn_override_reference=value.withdrawn_override_reference,
        actor=value.actor,
        rationale=value.rationale,
        decided_at=value.decided_at,
    )


def validate_teacher_grade_override_transition(
    previous: TeacherGradeOverrideDecision,
    candidate: TeacherGradeOverrideDecision,
) -> TeacherGradeOverrideDecision:
    """Validate contiguous immutable history for one exact override family."""

    old = validate_teacher_grade_override_decision(previous)
    new = validate_teacher_grade_override_decision(candidate)
    old_scope = (
        old.class_id,
        old.student_id,
        old.target_period,
        old.calendar_revision,
        old.calculation_family,
    )
    new_scope = (
        new.class_id,
        new.student_id,
        new.target_period,
        new.calendar_revision,
        new.calculation_family,
    )
    if new_scope != old_scope:
        raise TeacherGradeOverrideValidationError(
            "teacher Grade override logical identity cannot change."
        )
    if new.override_revision != old.override_revision + 1:
        raise TeacherGradeOverrideValidationError(
            "override revisions must be contiguous."
        )
    if new.supersedes_revision != old.override_revision:
        raise TeacherGradeOverrideValidationError(
            "supersedes_revision must identify the prior override revision."
        )
    if new.decided_at < old.decided_at:
        raise TeacherGradeOverrideValidationError(
            "decided_at must be nondecreasing across override history."
        )
    return new


def teacher_grade_override_reference(
    value: TeacherGradeOverrideDecision,
) -> TeacherGradeOverrideReference:
    """Return an exact digest-bound reference for one override decision."""

    decision = validate_teacher_grade_override_decision(value)
    digest = hashlib.sha256(
        teacher_grade_override_decision_to_json_bytes(decision)
    ).hexdigest()
    return TeacherGradeOverrideReference(
        class_id=decision.class_id,
        student_id=decision.student_id,
        school_year=decision.target_period.school_year,
        period_id=decision.target_period.period_id,
        calendar_revision=decision.calendar_revision,
        calculation_family=decision.calculation_family,
        override_revision=decision.override_revision,
        override_sha256=digest,
    )


def grade_override_source_result_reference_to_dict(
    value: GradeOverrideSourceResultReference,
) -> dict[str, object]:
    """Serialize one exact family-tagged source Grade result reference."""

    if not isinstance(value, GradeOverrideSourceResultReference):
        raise TeacherGradeOverrideValidationError(
            "value must be a GradeOverrideSourceResultReference."
        )
    validated = GradeOverrideSourceResultReference(value.family, value.reference)
    if validated.family == "conventional":
        reference = conventional_grade_result_reference_to_dict(
            cast(ConventionalGradeResultReference, validated.reference)
        )
    elif validated.family == "standards_based":
        reference = standards_grade_result_reference_to_dict(
            cast(StandardsGradeResultReference, validated.reference)
        )
    else:
        reference = hybrid_grade_result_reference_to_dict(
            cast(HybridGradeResultReference, validated.reference)
        )
    return {"family": validated.family, "reference": reference}


def grade_override_source_result_reference_from_dict(
    data: object,
) -> GradeOverrideSourceResultReference:
    """Parse one exact family-tagged source Grade result reference."""

    mapping = _exact_mapping(data, _SOURCE_KEYS, "source Grade result reference")
    family = _family(mapping["family"], "source_result.family")
    try:
        if family == "conventional":
            reference: GradeResultReference = (
                conventional_grade_result_reference_from_dict(
                    mapping["reference"]
                )
            )
        elif family == "standards_based":
            reference = standards_grade_result_reference_from_dict(
                mapping["reference"]
            )
        else:
            reference = hybrid_grade_result_reference_from_dict(
                mapping["reference"]
            )
    except ValueError as error:
        raise TeacherGradeOverrideValidationError(
            f"source_result.reference is invalid: {error}"
        ) from error
    return GradeOverrideSourceResultReference(family, reference)


def teacher_grade_override_reference_to_dict(
    value: TeacherGradeOverrideReference,
) -> dict[str, object]:
    """Serialize one exact override revision reference."""

    if not isinstance(value, TeacherGradeOverrideReference):
        raise TeacherGradeOverrideValidationError(
            "value must be a TeacherGradeOverrideReference."
        )
    validated = TeacherGradeOverrideReference(
        class_id=value.class_id,
        student_id=value.student_id,
        school_year=value.school_year,
        period_id=value.period_id,
        calendar_revision=value.calendar_revision,
        calculation_family=value.calculation_family,
        override_revision=value.override_revision,
        override_sha256=value.override_sha256,
    )
    return {
        "class_id": validated.class_id,
        "student_id": validated.student_id,
        "school_year": validated.school_year,
        "period_id": validated.period_id,
        "calendar_revision": validated.calendar_revision,
        "calculation_family": validated.calculation_family,
        "override_revision": validated.override_revision,
        "override_sha256": validated.override_sha256,
    }


def teacher_grade_override_reference_from_dict(
    data: object,
) -> TeacherGradeOverrideReference:
    """Parse one exact teacher Grade override reference."""

    mapping = _exact_mapping(
        data,
        _REFERENCE_KEYS,
        "teacher Grade override reference",
    )
    return TeacherGradeOverrideReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        student_id=_require_str(mapping["student_id"], "student_id"),
        school_year=_require_str(mapping["school_year"], "school_year"),
        period_id=_require_str(mapping["period_id"], "period_id"),
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
        calculation_family=_family(
            mapping["calculation_family"],
            "calculation_family",
        ),
        override_revision=_require_int(
            mapping["override_revision"],
            "override_revision",
        ),
        override_sha256=_require_str(
            mapping["override_sha256"],
            "override_sha256",
        ),
    )


def teacher_grade_override_decision_to_dict(
    value: TeacherGradeOverrideDecision,
) -> dict[str, object]:
    """Convert one validated override decision to exact JSON-native data."""

    decision = validate_teacher_grade_override_decision(value)
    return {
        "schema_version": decision.schema_version,
        "record_type": decision.record_type,
        "class_id": decision.class_id,
        "student_id": decision.student_id,
        "target_period": academic_period_ref_to_dict(decision.target_period),
        "calendar_revision": decision.calendar_revision,
        "calculation_family": decision.calculation_family,
        "override_revision": decision.override_revision,
        "supersedes_revision": decision.supersedes_revision,
        "decision": decision.decision,
        "source_result": grade_override_source_result_reference_to_dict(
            decision.source_result
        ),
        "replacement_grade": (
            _decimal_text(
                decision.replacement_grade,
                "replacement_grade",
                allow_zero=True,
            )
            if decision.replacement_grade is not None
            else None
        ),
        "withdrawn_override_reference": (
            teacher_grade_override_reference_to_dict(
                decision.withdrawn_override_reference
            )
            if decision.withdrawn_override_reference is not None
            else None
        ),
        "actor": {
            "kind": decision.actor.kind,
            "actor_id": decision.actor.actor_id,
        },
        "rationale": decision.rationale,
        "decided_at": decision.decided_at.isoformat(),
    }


def teacher_grade_override_decision_from_dict(
    data: object,
) -> TeacherGradeOverrideDecision:
    """Parse one exact teacher Grade override decision mapping."""

    mapping = _exact_mapping(
        data,
        _DECISION_KEYS,
        "teacher Grade override decision",
    )
    supersedes = _optional_int(
        mapping["supersedes_revision"],
        "supersedes_revision",
    )
    replacement_data = mapping["replacement_grade"]
    replacement_grade = (
        _decimal_from_text(
            replacement_data,
            "replacement_grade",
            allow_zero=True,
        )
        if replacement_data is not None
        else None
    )
    withdrawn_data = mapping["withdrawn_override_reference"]
    withdrawn_reference = (
        teacher_grade_override_reference_from_dict(withdrawn_data)
        if withdrawn_data is not None
        else None
    )
    actor_mapping = _exact_mapping(mapping["actor"], _ACTOR_KEYS, "actor")
    try:
        actor = GradePolicyActor(
            cast(
                Literal["teacher", "policy"],
                _require_str(actor_mapping["kind"], "actor.kind"),
            ),
            _require_str(actor_mapping["actor_id"], "actor.actor_id"),
        )
    except GradePolicyValidationError as error:
        raise TeacherGradeOverrideValidationError(
            f"actor is invalid: {error}"
        ) from error

    decision_text = _require_str(mapping["decision"], "decision")
    return TeacherGradeOverrideDecision(
        schema_version=_require_str(
            mapping["schema_version"],
            "schema_version",
        ),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        student_id=_require_str(mapping["student_id"], "student_id"),
        target_period=_period_from_dict(mapping["target_period"]),
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
        calculation_family=_family(
            mapping["calculation_family"],
            "calculation_family",
        ),
        override_revision=_require_int(
            mapping["override_revision"],
            "override_revision",
        ),
        supersedes_revision=supersedes,
        decision=cast(TeacherGradeOverrideDecisionKind, decision_text),
        source_result=grade_override_source_result_reference_from_dict(
            mapping["source_result"]
        ),
        replacement_grade=replacement_grade,
        withdrawn_override_reference=withdrawn_reference,
        actor=actor,
        rationale=_require_str(mapping["rationale"], "rationale"),
        decided_at=_datetime_from_text(mapping["decided_at"], "decided_at"),
    )


def teacher_grade_override_decision_to_json_bytes(
    value: TeacherGradeOverrideDecision,
) -> bytes:
    """Return deterministic canonical UTF-8 bytes for one override decision."""

    return _canonical_json_bytes(teacher_grade_override_decision_to_dict(value))


def teacher_grade_override_decision_from_json_bytes(
    data: bytes,
) -> TeacherGradeOverrideDecision:
    """Parse exact canonical override-decision bytes."""

    decoded = _decode_json(data, "teacher Grade override decision")
    value = teacher_grade_override_decision_from_dict(decoded)
    if teacher_grade_override_decision_to_json_bytes(value) != data:
        raise TeacherGradeOverrideSerializationError(
            "teacher Grade override decision bytes are not the canonical encoding."
        )
    return value


def _validated_result_reference(
    family: GradeCalculationFamily,
    value: object,
) -> GradeResultReference:
    try:
        if family == "conventional":
            if not isinstance(value, ConventionalGradeResultReference):
                raise TeacherGradeOverrideValidationError(
                    "conventional source family requires "
                    "ConventionalGradeResultReference."
                )
            return ConventionalGradeResultReference(
                class_id=value.class_id,
                student_id=value.student_id,
                school_year=value.school_year,
                period_id=value.period_id,
                calendar_revision=value.calendar_revision,
                result_revision=value.result_revision,
                result_sha256=value.result_sha256,
            )
        if family == "standards_based":
            if not isinstance(value, StandardsGradeResultReference):
                raise TeacherGradeOverrideValidationError(
                    "standards_based source family requires "
                    "StandardsGradeResultReference."
                )
            return StandardsGradeResultReference(
                class_id=value.class_id,
                student_id=value.student_id,
                school_year=value.school_year,
                period_id=value.period_id,
                calendar_revision=value.calendar_revision,
                result_revision=value.result_revision,
                result_sha256=value.result_sha256,
            )
        if not isinstance(value, HybridGradeResultReference):
            raise TeacherGradeOverrideValidationError(
                "hybrid source family requires HybridGradeResultReference."
            )
        return HybridGradeResultReference(
            class_id=value.class_id,
            student_id=value.student_id,
            school_year=value.school_year,
            period_id=value.period_id,
            calendar_revision=value.calendar_revision,
            result_revision=value.result_revision,
            result_sha256=value.result_sha256,
        )
    except TeacherGradeOverrideValidationError:
        raise
    except ValueError as error:
        raise TeacherGradeOverrideValidationError(
            f"source Grade result reference is invalid: {error}"
        ) from error


def _require_source_scope(
    reference: GradeResultReference,
    *,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> None:
    expected = (
        class_id,
        student_id,
        target_period.school_year,
        target_period.period_id,
        calendar_revision,
    )
    actual = (
        reference.class_id,
        reference.student_id,
        reference.school_year,
        reference.period_id,
        reference.calendar_revision,
    )
    if actual != expected:
        raise TeacherGradeOverrideValidationError(
            "source Grade result reference must match exact override scope."
        )


def _require_override_reference_scope(
    reference: TeacherGradeOverrideReference,
    *,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
) -> None:
    expected = (
        class_id,
        student_id,
        target_period.school_year,
        target_period.period_id,
        calendar_revision,
        calculation_family,
    )
    actual = (
        reference.class_id,
        reference.student_id,
        reference.school_year,
        reference.period_id,
        reference.calendar_revision,
        reference.calculation_family,
    )
    if actual != expected:
        raise TeacherGradeOverrideValidationError(
            "withdrawn override reference must match exact override family."
        )


def _validate_revision_pair(
    revision: int,
    supersedes: int | None,
) -> None:
    if revision == 1:
        if supersedes is not None:
            raise TeacherGradeOverrideValidationError(
                "override revision 1 must use supersedes_revision=null."
            )
    elif supersedes != revision - 1:
        raise TeacherGradeOverrideValidationError(
            "supersedes_revision must equal override_revision - 1."
        )


def _family(value: object, field_name: str) -> GradeCalculationFamily:
    text = _require_str(value, field_name)
    if text not in _FAMILIES:
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be one of: conventional, hybrid, standards_based."
        )
    return cast(GradeCalculationFamily, text)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            separators=(",", ": "),
        )
    except (TypeError, ValueError) as error:
        raise TeacherGradeOverrideSerializationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise TeacherGradeOverrideSerializationError(
            f"{label} data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TeacherGradeOverrideSerializationError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except TeacherGradeOverrideSerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise TeacherGradeOverrideSerializationError(
            f"{label} is not valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TeacherGradeOverrideSerializationError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise TeacherGradeOverrideSerializationError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise TeacherGradeOverrideValidationError(
            f"{label} must be an object."
        )
    if any(not isinstance(key, str) for key in data):
        raise TeacherGradeOverrideValidationError(
            f"{label} keys must be strings."
        )
    actual = frozenset(cast(Mapping[str, object], data).keys())
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise TeacherGradeOverrideValidationError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise TeacherGradeOverrideValidationError(str(error)) from error


def _bounded_text(
    value: object,
    field_name: str,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be a string."
        )
    if not value or value != value.strip():
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be nonblank without surrounding whitespace."
        )
    if len(value) > maximum:
        raise TeacherGradeOverrideValidationError(
            f"{field_name} exceeds maximum length {maximum}."
        )
    if any(
        unicodedata.category(character) in {"Cc", "Zl", "Zp"}
        for character in value
    ):
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be single-line and free of control characters."
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer <= 0:
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be greater than zero."
        )
    return integer


def _optional_positive_int(
    value: object,
    field_name: str,
) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _nonnegative_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be a Decimal."
        )
    if not value.is_finite():
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be finite."
        )
    if value < 0:
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be nonnegative."
        )
    return Decimal(_decimal_text(value, field_name, allow_zero=True))


def _decimal_text(
    value: Decimal,
    field_name: str,
    *,
    allow_zero: bool,
) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be a finite Decimal."
        )
    if value < 0 or (not allow_zero and value == 0):
        requirement = "nonnegative" if allow_zero else "greater than zero"
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be {requirement}."
        )
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"-0", ""}:
        text = "0"
    return text


def _decimal_from_text(
    value: object,
    field_name: str,
    *,
    allow_zero: bool,
) -> Decimal:
    if not isinstance(value, str):
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be decimal text."
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be valid decimal text."
        ) from error
    if not parsed.is_finite():
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be finite."
        )
    if parsed < 0 or (not allow_zero and parsed == 0):
        requirement = "nonnegative" if allow_zero else "greater than zero"
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be {requirement}."
        )
    return Decimal(_decimal_text(parsed, field_name, allow_zero=allow_zero))


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be a datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be a valid ISO datetime string."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _period_from_dict(value: object) -> AcademicPeriodRef:
    try:
        return academic_period_ref_from_dict(value)
    except (AcademicPeriodValidationError, TypeError, ValueError) as error:
        raise TeacherGradeOverrideValidationError(
            f"target_period is invalid: {error}"
        ) from error


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be a string."
        )
    return value


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be an integer."
        )
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise TeacherGradeOverrideValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


__all__ = [
    "GradeOverrideSourceResultReference",
    "GradeResultReference",
    "MAXIMUM_TEACHER_GRADE_OVERRIDE_TEXT_LENGTH",
    "TEACHER_GRADE_OVERRIDE_RECORD_TYPE",
    "TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION",
    "TeacherGradeOverrideDecision",
    "TeacherGradeOverrideDecisionKind",
    "TeacherGradeOverrideError",
    "TeacherGradeOverrideReference",
    "TeacherGradeOverrideSerializationError",
    "TeacherGradeOverrideValidationError",
    "grade_override_source_result_reference_from_dict",
    "grade_override_source_result_reference_to_dict",
    "teacher_grade_override_decision_from_dict",
    "teacher_grade_override_decision_from_json_bytes",
    "teacher_grade_override_decision_to_dict",
    "teacher_grade_override_decision_to_json_bytes",
    "teacher_grade_override_reference",
    "teacher_grade_override_reference_from_dict",
    "teacher_grade_override_reference_to_dict",
    "validate_teacher_grade_override_decision",
    "validate_teacher_grade_override_transition",
]
