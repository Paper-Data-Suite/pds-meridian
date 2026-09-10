"""Immutable Grade-policy activation decisions and canonical serialization."""

from __future__ import annotations

import hashlib
import json
import re
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

from meridian.grade_policy import (
    GradePolicyActor,
    GradePolicyReference,
    GradePolicyValidationError,
    grade_policy_reference_from_dict,
    grade_policy_reference_to_dict,
)

GRADE_POLICY_ACTIVATION_SCHEMA_VERSION: Final[str] = "1"
GRADE_POLICY_ACTIVATION_RECORD_TYPE: Final[str] = "meridian_grade_policy_activation"
MAXIMUM_GRADE_POLICY_ACTIVATION_TEXT_LENGTH: Final[int] = 2000

GradePolicyActivationDecisionKind: TypeAlias = Literal["activate", "deactivate"]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_DECISIONS: Final[frozenset[str]] = frozenset({"activate", "deactivate"})
_ACTIVATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "target_period",
        "calendar_revision",
        "activation_revision",
        "supersedes_revision",
        "decision",
        "policy_reference",
        "actor",
        "rationale",
        "decided_at",
    }
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "school_year",
        "period_id",
        "activation_revision",
        "activation_sha256",
    }
)


class GradePolicyActivationError(ValueError):
    """Base error for Grade-policy activation contracts."""


class GradePolicyActivationValidationError(GradePolicyActivationError):
    """Raised when activation data violates the domain contract."""


class GradePolicyActivationSerializationError(GradePolicyActivationError):
    """Raised when activation JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class GradePolicyActivationDecision:
    """One immutable teacher-controlled Grade-policy activation decision."""

    schema_version: str
    record_type: str
    class_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    activation_revision: int
    supersedes_revision: int | None
    decision: GradePolicyActivationDecisionKind
    policy_reference: GradePolicyReference | None
    actor: GradePolicyActor
    rationale: str | None
    decided_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != GRADE_POLICY_ACTIVATION_SCHEMA_VERSION:
            raise GradePolicyActivationValidationError(
                'schema_version must be "1".'
            )
        if self.record_type != GRADE_POLICY_ACTIVATION_RECORD_TYPE:
            raise GradePolicyActivationValidationError(
                'record_type must be "meridian_grade_policy_activation".'
            )
        class_id = _identifier(self.class_id, "class_id")
        if not isinstance(self.target_period, AcademicPeriodRef):
            raise GradePolicyActivationValidationError(
                "target_period must be an AcademicPeriodRef."
            )
        try:
            target_period = validate_academic_period_ref(self.target_period)
        except AcademicPeriodValidationError as error:
            raise GradePolicyActivationValidationError(
                f"target_period is invalid: {error}"
            ) from error

        calendar_revision = _positive_int(
            self.calendar_revision, "calendar_revision"
        )
        activation_revision = _positive_int(
            self.activation_revision, "activation_revision"
        )
        supersedes = _optional_positive_int(
            self.supersedes_revision, "supersedes_revision"
        )
        if activation_revision == 1:
            if supersedes is not None:
                raise GradePolicyActivationValidationError(
                    "activation revision 1 must use supersedes_revision=null."
                )
        elif supersedes != activation_revision - 1:
            raise GradePolicyActivationValidationError(
                "supersedes_revision must equal activation_revision - 1."
            )

        if self.decision not in _DECISIONS:
            raise GradePolicyActivationValidationError(
                "decision must be one of: activate, deactivate."
            )

        policy_reference = self.policy_reference
        if self.decision == "activate":
            if not isinstance(policy_reference, GradePolicyReference):
                raise GradePolicyActivationValidationError(
                    "activate requires an exact GradePolicyReference."
                )
            try:
                policy_reference = GradePolicyReference(
                    policy_reference.class_id,
                    policy_reference.policy_id,
                    policy_reference.policy_revision,
                    policy_reference.policy_sha256,
                )
            except GradePolicyValidationError as error:
                raise GradePolicyActivationValidationError(
                    f"policy_reference is invalid: {error}"
                ) from error
            if policy_reference.class_id != class_id:
                raise GradePolicyActivationValidationError(
                    "policy_reference.class_id must match class_id."
                )
        elif policy_reference is not None:
            raise GradePolicyActivationValidationError(
                "deactivate must use policy_reference=null."
            )

        if not isinstance(self.actor, GradePolicyActor):
            raise GradePolicyActivationValidationError(
                "actor must be a GradePolicyActor."
            )
        actor = GradePolicyActor(self.actor.kind, self.actor.actor_id)

        rationale = self.rationale
        if rationale is not None:
            rationale = _bounded_text(
                rationale,
                "rationale",
                MAXIMUM_GRADE_POLICY_ACTIVATION_TEXT_LENGTH,
            )

        decided_at = _aware_utc_datetime(self.decided_at, "decided_at")

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "target_period", target_period)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "activation_revision", activation_revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "policy_reference", policy_reference)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "decided_at", decided_at)


@dataclass(frozen=True, slots=True)
class GradePolicyActivationReference:
    """Exact immutable activation decision and canonical-byte digest."""

    class_id: str
    school_year: str
    period_id: str
    activation_revision: int
    activation_sha256: str

    def __post_init__(self) -> None:
        class_id = _identifier(self.class_id, "class_id")
        try:
            period = AcademicPeriodRef(self.school_year, self.period_id)
        except AcademicPeriodValidationError as error:
            raise GradePolicyActivationValidationError(
                f"activation reference period is invalid: {error}"
            ) from error
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "school_year", period.school_year)
        object.__setattr__(self, "period_id", period.period_id)
        object.__setattr__(
            self,
            "activation_revision",
            _positive_int(self.activation_revision, "activation_revision"),
        )
        object.__setattr__(
            self,
            "activation_sha256",
            _sha256(self.activation_sha256, "activation_sha256"),
        )


def validate_grade_policy_activation_decision(
    value: GradePolicyActivationDecision,
) -> GradePolicyActivationDecision:
    """Fully revalidate one activation decision."""

    if not isinstance(value, GradePolicyActivationDecision):
        raise GradePolicyActivationValidationError(
            "activation decision must be a GradePolicyActivationDecision."
        )
    return GradePolicyActivationDecision(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        target_period=value.target_period,
        calendar_revision=value.calendar_revision,
        activation_revision=value.activation_revision,
        supersedes_revision=value.supersedes_revision,
        decision=value.decision,
        policy_reference=value.policy_reference,
        actor=value.actor,
        rationale=value.rationale,
        decided_at=value.decided_at,
    )


def validate_grade_policy_activation_transition(
    previous: GradePolicyActivationDecision,
    candidate: GradePolicyActivationDecision,
) -> GradePolicyActivationDecision:
    """Validate a pure linear activation-history transition."""

    old = validate_grade_policy_activation_decision(previous)
    new = validate_grade_policy_activation_decision(candidate)
    if new.class_id != old.class_id:
        raise GradePolicyActivationValidationError(
            "candidate class_id must match previous."
        )
    if new.target_period != old.target_period:
        raise GradePolicyActivationValidationError(
            "candidate target_period must match previous."
        )
    if new.activation_revision != old.activation_revision + 1:
        raise GradePolicyActivationValidationError(
            "candidate activation_revision must be exactly one greater than previous."
        )
    if new.supersedes_revision != old.activation_revision:
        raise GradePolicyActivationValidationError(
            "candidate supersedes_revision must identify previous revision."
        )
    if new.decided_at < old.decided_at:
        raise GradePolicyActivationValidationError(
            "candidate decided_at must not be earlier than previous decided_at."
        )
    return new


def grade_policy_activation_reference(
    value: GradePolicyActivationDecision,
) -> GradePolicyActivationReference:
    """Return an exact digest-bound reference for one activation decision."""

    decision = validate_grade_policy_activation_decision(value)
    digest = hashlib.sha256(
        grade_policy_activation_decision_to_json_bytes(decision)
    ).hexdigest()
    return GradePolicyActivationReference(
        class_id=decision.class_id,
        school_year=decision.target_period.school_year,
        period_id=decision.target_period.period_id,
        activation_revision=decision.activation_revision,
        activation_sha256=digest,
    )


def grade_policy_activation_reference_to_dict(
    value: GradePolicyActivationReference,
) -> dict[str, object]:
    """Convert an exact activation reference to JSON-native data."""

    if not isinstance(value, GradePolicyActivationReference):
        raise GradePolicyActivationValidationError(
            "activation reference must be a GradePolicyActivationReference."
        )
    validated = GradePolicyActivationReference(
        value.class_id,
        value.school_year,
        value.period_id,
        value.activation_revision,
        value.activation_sha256,
    )
    return {
        "class_id": validated.class_id,
        "school_year": validated.school_year,
        "period_id": validated.period_id,
        "activation_revision": validated.activation_revision,
        "activation_sha256": validated.activation_sha256,
    }


def grade_policy_activation_reference_from_dict(
    data: object,
) -> GradePolicyActivationReference:
    """Parse an exact activation reference."""

    mapping = _exact_mapping(data, _REFERENCE_KEYS, "activation reference")
    return GradePolicyActivationReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        school_year=_require_str(mapping["school_year"], "school_year"),
        period_id=_require_str(mapping["period_id"], "period_id"),
        activation_revision=_require_int(
            mapping["activation_revision"], "activation_revision"
        ),
        activation_sha256=_require_str(
            mapping["activation_sha256"], "activation_sha256"
        ),
    )


def grade_policy_activation_decision_to_dict(
    value: GradePolicyActivationDecision,
) -> dict[str, object]:
    """Convert a validated activation decision to exact JSON-native data."""

    decision = validate_grade_policy_activation_decision(value)
    return {
        "schema_version": decision.schema_version,
        "record_type": decision.record_type,
        "class_id": decision.class_id,
        "target_period": academic_period_ref_to_dict(decision.target_period),
        "calendar_revision": decision.calendar_revision,
        "activation_revision": decision.activation_revision,
        "supersedes_revision": decision.supersedes_revision,
        "decision": decision.decision,
        "policy_reference": (
            grade_policy_reference_to_dict(decision.policy_reference)
            if decision.policy_reference is not None
            else None
        ),
        "actor": {
            "kind": decision.actor.kind,
            "actor_id": decision.actor.actor_id,
        },
        "rationale": decision.rationale,
        "decided_at": decision.decided_at.isoformat(),
    }


def grade_policy_activation_decision_from_dict(
    data: object,
) -> GradePolicyActivationDecision:
    """Parse one exact activation-decision mapping."""

    mapping = _exact_mapping(data, _ACTIVATION_KEYS, "activation decision")
    target_period = academic_period_ref_from_dict(mapping["target_period"])
    policy_data = mapping["policy_reference"]
    policy_reference = (
        grade_policy_reference_from_dict(policy_data)
        if policy_data is not None
        else None
    )
    actor_map = _exact_mapping(mapping["actor"], _ACTOR_KEYS, "actor")
    supersedes = mapping["supersedes_revision"]
    if supersedes is not None and (
        isinstance(supersedes, bool) or not isinstance(supersedes, int)
    ):
        raise GradePolicyActivationValidationError(
            "supersedes_revision must be an integer or null."
        )
    return GradePolicyActivationDecision(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        target_period=target_period,
        calendar_revision=_require_int(
            mapping["calendar_revision"], "calendar_revision"
        ),
        activation_revision=_require_int(
            mapping["activation_revision"], "activation_revision"
        ),
        supersedes_revision=supersedes,
        decision=cast(
            GradePolicyActivationDecisionKind,
            _require_str(mapping["decision"], "decision"),
        ),
        policy_reference=policy_reference,
        actor=GradePolicyActor(
            cast(
                Literal["teacher", "policy"],
                _require_str(actor_map["kind"], "actor.kind"),
            ),
            _require_str(actor_map["actor_id"], "actor.actor_id"),
        ),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        decided_at=_datetime_from_text(mapping["decided_at"], "decided_at"),
    )


def grade_policy_activation_decision_to_json_bytes(
    value: GradePolicyActivationDecision,
) -> bytes:
    """Return deterministic canonical UTF-8 bytes for one activation decision."""

    return _canonical_json_bytes(grade_policy_activation_decision_to_dict(value))


def grade_policy_activation_decision_from_json_bytes(
    data: bytes,
) -> GradePolicyActivationDecision:
    """Parse exact canonical activation-decision bytes."""

    if type(data) is not bytes:
        raise GradePolicyActivationSerializationError(
            "activation decision data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GradePolicyActivationSerializationError(
            "activation decision is not valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except GradePolicyActivationSerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise GradePolicyActivationSerializationError(
            "activation decision is not valid JSON."
        ) from error
    decision = grade_policy_activation_decision_from_dict(decoded)
    if grade_policy_activation_decision_to_json_bytes(decision) != data:
        raise GradePolicyActivationSerializationError(
            "activation decision bytes are not the canonical encoding."
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
        raise GradePolicyActivationSerializationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GradePolicyActivationSerializationError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise GradePolicyActivationSerializationError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise GradePolicyActivationValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise GradePolicyActivationValidationError(
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
        raise GradePolicyActivationValidationError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradePolicyActivationValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GradePolicyActivationValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer <= 0:
        raise GradePolicyActivationValidationError(
            f"{field_name} must be greater than zero."
        )
    return integer


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GradePolicyActivationValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise GradePolicyActivationValidationError(
            f"{field_name} must be a string."
        )
    if not value or value != value.strip():
        raise GradePolicyActivationValidationError(
            f"{field_name} must be nonblank without edge whitespace."
        )
    if len(value) > maximum:
        raise GradePolicyActivationValidationError(
            f"{field_name} exceeds maximum length."
        )
    if any(ord(character) < 32 for character in value):
        raise GradePolicyActivationValidationError(
            f"{field_name} must not contain control characters."
        )
    return value


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise GradePolicyActivationValidationError(
            f"{field_name} must be a datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise GradePolicyActivationValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise GradePolicyActivationValidationError(
            f"{field_name} must be a valid ISO datetime string."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradePolicyActivationValidationError(
            f"{field_name} must be a string."
        )
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GradePolicyActivationValidationError(
            f"{field_name} must be an integer."
        )
    return value
