"""Immutable Meridian Grade Item membership decisions and serialization."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_from_dict,
    academic_period_ref_to_dict,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.grade_items import (
    GradeItemValidationError,
    GradeItemWorkReference,
    grade_item_work_reference_from_dict,
    grade_item_work_reference_to_dict,
)

GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION: Final[str] = "1"
GRADE_ITEM_MEMBERSHIP_RECORD_TYPE: Final[str] = "meridian_grade_item_membership"
MAXIMUM_MEMBERSHIP_ACTOR_ID_LENGTH: Final[int] = 256
MAXIMUM_MEMBERSHIP_RATIONALE_LENGTH: Final[int] = 2000

GradeItemMembershipDisposition: TypeAlias = Literal["included", "excluded"]
GRADE_ITEM_MEMBERSHIP_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {"included", "excluded"}
)

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_ASSIGNMENT_KEYS: Final[frozenset[str]] = frozenset(
    {"period", "calendar_revision"}
)
_MEMBERSHIP_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
        "grade_item_revision",
        "grade_item_revision_sha256",
        "work_reference",
        "membership_revision",
        "supersedes_revision",
        "decision",
        "academic_period",
        "actor_id",
        "rationale",
        "decided_at",
    }
)


class GradeItemMembershipError(ValueError):
    """Base error for Grade Item membership model and serialization failures."""


class GradeItemMembershipValidationError(GradeItemMembershipError):
    """Raised when Grade Item membership data violates the contract."""


class GradeItemMembershipSerializationError(GradeItemMembershipError):
    """Raised when membership JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class GradeItemAcademicPeriodAssignment:
    """Exact Core Academic Period Calendar revision and period reference."""

    period: AcademicPeriodRef
    calendar_revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.period, AcademicPeriodRef):
            raise GradeItemMembershipValidationError(
                "period must be an AcademicPeriodRef."
            )
        try:
            period = validate_academic_period_ref(self.period)
        except AcademicPeriodValidationError as error:
            raise GradeItemMembershipValidationError(
                f"period is invalid: {error}"
            ) from error
        object.__setattr__(self, "period", period)
        object.__setattr__(
            self,
            "calendar_revision",
            _positive_int(self.calendar_revision, "calendar_revision"),
        )


@dataclass(frozen=True, slots=True)
class GradeItemMembershipDecision:
    """One immutable teacher-controlled Grade Item/work membership decision."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    grade_item_revision: int
    grade_item_revision_sha256: str
    work_reference: GradeItemWorkReference
    membership_revision: int
    supersedes_revision: int | None
    decision: GradeItemMembershipDisposition
    academic_period: GradeItemAcademicPeriodAssignment | None
    actor_id: str
    rationale: str | None
    decided_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION:
            raise GradeItemMembershipValidationError('schema_version must be "1".')
        if self.record_type != GRADE_ITEM_MEMBERSHIP_RECORD_TYPE:
            raise GradeItemMembershipValidationError(
                'record_type must be "meridian_grade_item_membership".'
            )
        class_id = _identifier(self.class_id, "class_id")
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        object.__setattr__(
            self,
            "grade_item_revision",
            _positive_int(self.grade_item_revision, "grade_item_revision"),
        )
        object.__setattr__(
            self,
            "grade_item_revision_sha256",
            _sha256(self.grade_item_revision_sha256, "grade_item_revision_sha256"),
        )
        if not isinstance(self.work_reference, GradeItemWorkReference):
            raise GradeItemMembershipValidationError(
                "work_reference must be a GradeItemWorkReference."
            )
        try:
            work_reference = GradeItemWorkReference(
                work=self.work_reference.work,
                registration_revision=self.work_reference.registration_revision,
            )
        except GradeItemValidationError as error:
            raise GradeItemMembershipValidationError(
                f"work_reference is invalid: {error}"
            ) from error
        if work_reference.work.class_id != class_id:
            raise GradeItemMembershipValidationError(
                "work_reference.work.class_id must match class_id."
            )
        object.__setattr__(self, "work_reference", work_reference)

        revision = _positive_int(self.membership_revision, "membership_revision")
        object.__setattr__(self, "membership_revision", revision)
        supersedes = self.supersedes_revision
        if revision == 1:
            if supersedes is not None:
                raise GradeItemMembershipValidationError(
                    "membership revision 1 must use supersedes_revision=null."
                )
        elif supersedes != revision - 1:
            raise GradeItemMembershipValidationError(
                "supersedes_revision must equal membership_revision - 1."
            )

        if self.decision not in GRADE_ITEM_MEMBERSHIP_DISPOSITIONS:
            raise GradeItemMembershipValidationError(
                "decision must be one of: "
                + ", ".join(sorted(GRADE_ITEM_MEMBERSHIP_DISPOSITIONS))
                + "."
            )
        assignment = self.academic_period
        if self.decision == "included":
            if not isinstance(assignment, GradeItemAcademicPeriodAssignment):
                raise GradeItemMembershipValidationError(
                    "included membership requires an academic_period assignment."
                )
            assignment = GradeItemAcademicPeriodAssignment(
                period=assignment.period,
                calendar_revision=assignment.calendar_revision,
            )
        elif assignment is not None:
            raise GradeItemMembershipValidationError(
                "excluded membership must use academic_period=null."
            )
        object.__setattr__(self, "academic_period", assignment)
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_MEMBERSHIP_ACTOR_ID_LENGTH,
            ),
        )
        rationale = self.rationale
        if rationale is not None:
            rationale = _bounded_text(
                rationale,
                "rationale",
                MAXIMUM_MEMBERSHIP_RATIONALE_LENGTH,
            )
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(
            self,
            "decided_at",
            _aware_utc_datetime(self.decided_at, "decided_at"),
        )


def validate_grade_item_academic_period_assignment(
    value: GradeItemAcademicPeriodAssignment,
) -> GradeItemAcademicPeriodAssignment:
    """Fully revalidate one exact Academic Period assignment."""
    if not isinstance(value, GradeItemAcademicPeriodAssignment):
        raise GradeItemMembershipValidationError(
            "academic period assignment must be GradeItemAcademicPeriodAssignment."
        )
    return GradeItemAcademicPeriodAssignment(
        period=value.period,
        calendar_revision=value.calendar_revision,
    )


def validate_grade_item_membership_decision(
    value: GradeItemMembershipDecision,
) -> GradeItemMembershipDecision:
    """Fully revalidate one Grade Item membership decision."""
    if not isinstance(value, GradeItemMembershipDecision):
        raise GradeItemMembershipValidationError(
            "membership decision must be a GradeItemMembershipDecision."
        )
    assignment = value.academic_period
    if assignment is not None:
        assignment = validate_grade_item_academic_period_assignment(assignment)
    return GradeItemMembershipDecision(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        grade_item_id=value.grade_item_id,
        grade_item_revision=value.grade_item_revision,
        grade_item_revision_sha256=value.grade_item_revision_sha256,
        work_reference=value.work_reference,
        membership_revision=value.membership_revision,
        supersedes_revision=value.supersedes_revision,
        decision=value.decision,
        academic_period=assignment,
        actor_id=value.actor_id,
        rationale=value.rationale,
        decided_at=value.decided_at,
    )


def validate_grade_item_membership_transition(
    previous: GradeItemMembershipDecision,
    candidate: GradeItemMembershipDecision,
) -> GradeItemMembershipDecision:
    """Validate a pure contiguous transition in one logical membership history."""
    old = validate_grade_item_membership_decision(previous)
    new = validate_grade_item_membership_decision(candidate)
    if new.class_id != old.class_id:
        raise GradeItemMembershipValidationError(
            "candidate class_id must match previous."
        )
    if new.grade_item_id != old.grade_item_id:
        raise GradeItemMembershipValidationError(
            "candidate grade_item_id must match previous."
        )
    if new.work_reference.work != old.work_reference.work:
        raise GradeItemMembershipValidationError(
            "candidate logical work reference must match previous."
        )
    if new.membership_revision != old.membership_revision + 1:
        raise GradeItemMembershipValidationError(
            "candidate membership_revision must be exactly one greater than previous."
        )
    if new.supersedes_revision != old.membership_revision:
        raise GradeItemMembershipValidationError(
            "candidate supersedes_revision must identify previous revision."
        )
    if new.decided_at < old.decided_at:
        raise GradeItemMembershipValidationError(
            "candidate decided_at must not be earlier than previous decided_at."
        )
    return new


def grade_item_academic_period_assignment_to_dict(
    value: GradeItemAcademicPeriodAssignment,
) -> dict[str, object]:
    """Convert one exact Academic Period assignment to JSON-native data."""
    assignment = validate_grade_item_academic_period_assignment(value)
    return {
        "period": academic_period_ref_to_dict(assignment.period),
        "calendar_revision": assignment.calendar_revision,
    }


def grade_item_academic_period_assignment_from_dict(
    data: object,
) -> GradeItemAcademicPeriodAssignment:
    """Parse one exact Academic Period assignment mapping."""
    mapping = _exact_mapping(data, _ASSIGNMENT_KEYS, "academic period assignment")
    try:
        period = academic_period_ref_from_dict(mapping["period"])
    except AcademicPeriodValidationError as error:
        raise GradeItemMembershipValidationError(
            f"academic period assignment is invalid: {error}"
        ) from error
    return GradeItemAcademicPeriodAssignment(
        period=period,
        calendar_revision=_require_int(
            mapping["calendar_revision"], "calendar_revision"
        ),
    )


def grade_item_membership_decision_to_dict(
    value: GradeItemMembershipDecision,
) -> dict[str, object]:
    """Convert one membership decision to its exact JSON-native shape."""
    decision = validate_grade_item_membership_decision(value)
    return {
        "schema_version": decision.schema_version,
        "record_type": decision.record_type,
        "class_id": decision.class_id,
        "grade_item_id": decision.grade_item_id,
        "grade_item_revision": decision.grade_item_revision,
        "grade_item_revision_sha256": decision.grade_item_revision_sha256,
        "work_reference": grade_item_work_reference_to_dict(
            decision.work_reference
        ),
        "membership_revision": decision.membership_revision,
        "supersedes_revision": decision.supersedes_revision,
        "decision": decision.decision,
        "academic_period": (
            grade_item_academic_period_assignment_to_dict(decision.academic_period)
            if decision.academic_period is not None
            else None
        ),
        "actor_id": decision.actor_id,
        "rationale": decision.rationale,
        "decided_at": decision.decided_at.isoformat(),
    }


def grade_item_membership_decision_from_dict(
    data: object,
) -> GradeItemMembershipDecision:
    """Parse one exact membership decision mapping."""
    mapping = _exact_mapping(data, _MEMBERSHIP_KEYS, "membership decision")
    assignment_data = mapping["academic_period"]
    assignment = (
        grade_item_academic_period_assignment_from_dict(assignment_data)
        if assignment_data is not None
        else None
    )
    supersedes = mapping["supersedes_revision"]
    if supersedes is not None and (
        isinstance(supersedes, bool) or not isinstance(supersedes, int)
    ):
        raise GradeItemMembershipValidationError(
            "supersedes_revision must be an integer or null."
        )
    try:
        work_reference = grade_item_work_reference_from_dict(
            mapping["work_reference"]
        )
    except GradeItemValidationError as error:
        raise GradeItemMembershipValidationError(
            f"work_reference is invalid: {error}"
        ) from error
    return GradeItemMembershipDecision(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        grade_item_revision=_require_int(
            mapping["grade_item_revision"], "grade_item_revision"
        ),
        grade_item_revision_sha256=_require_str(
            mapping["grade_item_revision_sha256"],
            "grade_item_revision_sha256",
        ),
        work_reference=work_reference,
        membership_revision=_require_int(
            mapping["membership_revision"], "membership_revision"
        ),
        supersedes_revision=supersedes,
        decision=cast(
            GradeItemMembershipDisposition,
            _require_str(mapping["decision"], "decision"),
        ),
        academic_period=assignment,
        actor_id=_require_str(mapping["actor_id"], "actor_id"),
        rationale=(
            None
            if mapping["rationale"] is None
            else _require_str(mapping["rationale"], "rationale")
        ),
        decided_at=_datetime_from_text(mapping["decided_at"], "decided_at"),
    )


def grade_item_membership_decision_to_json_bytes(
    value: GradeItemMembershipDecision,
) -> bytes:
    """Return deterministic canonical UTF-8 bytes for one decision."""
    return _canonical_json_bytes(grade_item_membership_decision_to_dict(value))


def grade_item_membership_decision_from_json_bytes(
    data: bytes,
) -> GradeItemMembershipDecision:
    """Parse exact canonical membership-decision bytes."""
    if type(data) is not bytes:
        raise GradeItemMembershipSerializationError(
            "membership decision data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GradeItemMembershipSerializationError(
            "membership decision is not valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except GradeItemMembershipSerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise GradeItemMembershipSerializationError(
            "membership decision is not valid JSON."
        ) from error
    decision = grade_item_membership_decision_from_dict(decoded)
    if grade_item_membership_decision_to_json_bytes(decision) != data:
        raise GradeItemMembershipSerializationError(
            "membership decision bytes are not the canonical encoding."
        )
    return decision


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
        raise GradeItemMembershipSerializationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GradeItemMembershipSerializationError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise GradeItemMembershipSerializationError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    expected: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise GradeItemMembershipValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise GradeItemMembershipValidationError(
            f"{label} keys must all be strings."
        )
    keys = frozenset(cast(Mapping[str, object], data))
    if keys != expected:
        missing = sorted(expected - keys)
        unknown = sorted(keys - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing={missing!r}")
        if unknown:
            details.append(f"unknown={unknown!r}")
        raise GradeItemMembershipValidationError(
            f"{label} must use the exact schema ({', '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradeItemMembershipValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GradeItemMembershipValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GradeItemMembershipValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GradeItemMembershipValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _bounded_text(value: object, field_name: str, maximum_length: int) -> str:
    if not isinstance(value, str):
        raise GradeItemMembershipValidationError(
            f"{field_name} must be a string."
        )
    if not value or value != value.strip():
        raise GradeItemMembershipValidationError(
            f"{field_name} must be nonblank without surrounding whitespace."
        )
    if len(value) > maximum_length:
        raise GradeItemMembershipValidationError(
            f"{field_name} must be at most {maximum_length} characters."
        )
    if any(_is_control_character(character) for character in value):
        raise GradeItemMembershipValidationError(
            f"{field_name} must not contain control characters."
        )
    return value


def _is_control_character(value: str) -> bool:
    return unicodedata.category(value).startswith("C") or value in {"\u2028", "\u2029"}


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise GradeItemMembershipValidationError(
            f"{field_name} must be a datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise GradeItemMembershipValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise GradeItemMembershipValidationError(
            f"{field_name} must be a valid ISO datetime string."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GradeItemMembershipValidationError(
            f"{field_name} must be an integer."
        )
    return value


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradeItemMembershipValidationError(
            f"{field_name} must be a string."
        )
    return value
