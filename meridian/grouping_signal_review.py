"""Immutable teacher review contracts for #39 grouping-signal previews.

A review binds one exact #38 derivation and one exact #39 preview. Reviews are
human workflow state, not deterministic calculation state, so ``reviewed_at``
is intentionally persisted. This module does not select reviews, export Core
grouping signals/CSV, or invoke Concord.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, NoReturn, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationReference,
    grouping_signal_derivation_reference_from_dict,
    grouping_signal_derivation_reference_to_dict,
)
from meridian.grouping_signal_preview import (
    GroupingSignalPreviewCurrentness,
    GroupingSignalPreviewReference,
    GroupingSignalPreviewSnapshot,
    grouping_signal_preview_reference,
    grouping_signal_preview_reference_from_dict,
    grouping_signal_preview_reference_to_dict,
    validate_grouping_signal_preview_snapshot,
)

GROUPING_SIGNAL_REVIEW_SCHEMA_VERSION: Final[str] = "1"
GROUPING_SIGNAL_REVIEW_RECORD_TYPE: Final[str] = "meridian_grouping_signal_review"
MAXIMUM_GROUPING_SIGNAL_REVIEW_BYTES: Final[int] = 512 * 1024
MAXIMUM_GROUPING_SIGNAL_REVIEW_ACTOR_ID_LENGTH: Final[int] = 256

GroupingSignalReviewDecisionValue: TypeAlias = Literal[
    "accepted_for_export",
    "rejected",
]
GroupingSignalReviewActorKind: TypeAlias = Literal["teacher"]
GroupingSignalReviewApplicabilityStatus: TypeAlias = Literal[
    "current",
    "stale",
    "not_accepted",
]

_DECISIONS: Final[tuple[GroupingSignalReviewDecisionValue, ...]] = (
    "accepted_for_export",
    "rejected",
)
_ACTOR_KINDS: Final[tuple[GroupingSignalReviewActorKind, ...]] = ("teacher",)
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_DIAGNOSTIC_ID: Final[re.Pattern[str]] = re.compile(r"^gpd_[0-9a-f]{64}$")
_DERIVATION_ID: Final[re.Pattern[str]] = re.compile(r"^gsd_[0-9a-f]{64}$")

_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_REVIEW_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "derivation_reference",
        "preview_reference",
        "review_revision",
        "supersedes_revision",
        "decision",
        "acknowledged_warning_ids",
        "actor",
        "reviewed_at",
    }
)
_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "derivation_id",
        "review_revision",
        "review_sha256",
    }
)


class GroupingSignalReviewError(ValueError):
    """Base error for grouping-signal preview review contracts."""


class GroupingSignalReviewValidationError(GroupingSignalReviewError):
    """Raised when one review violates its contract."""


class GroupingSignalReviewSerializationError(GroupingSignalReviewError):
    """Raised when review JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class GroupingSignalReviewActor:
    """Teacher identity for one deliberate review decision."""

    kind: GroupingSignalReviewActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in _ACTOR_KINDS:
            raise GroupingSignalReviewValidationError(
                "review actor kind must be teacher."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_GROUPING_SIGNAL_REVIEW_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class GroupingSignalReviewDecision:
    """One immutable deliberate teacher decision over an exact preview."""

    schema_version: str
    record_type: str
    class_id: str
    derivation_reference: GroupingSignalDerivationReference
    preview_reference: GroupingSignalPreviewReference
    review_revision: int
    supersedes_revision: int | None
    decision: GroupingSignalReviewDecisionValue
    acknowledged_warning_ids: tuple[str, ...]
    actor: GroupingSignalReviewActor
    reviewed_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != GROUPING_SIGNAL_REVIEW_SCHEMA_VERSION:
            raise GroupingSignalReviewValidationError(
                "unsupported grouping-signal review schema_version."
            )
        if self.record_type != GROUPING_SIGNAL_REVIEW_RECORD_TYPE:
            raise GroupingSignalReviewValidationError(
                "record_type must identify a grouping-signal review."
            )
        class_id = _identifier(self.class_id, "class_id")
        if not isinstance(
            self.derivation_reference,
            GroupingSignalDerivationReference,
        ):
            raise GroupingSignalReviewValidationError(
                "derivation_reference must be an exact #38 reference."
            )
        self.derivation_reference.__post_init__()
        if not isinstance(self.preview_reference, GroupingSignalPreviewReference):
            raise GroupingSignalReviewValidationError(
                "preview_reference must be an exact #39 preview reference."
            )
        self.preview_reference.__post_init__()
        if (
            self.derivation_reference.class_id != class_id
            or self.preview_reference.class_id != class_id
        ):
            raise GroupingSignalReviewValidationError(
                "review references must share one class scope."
            )
        revision = _positive_int(self.review_revision, "review_revision")
        supersedes = _optional_positive_int(
            self.supersedes_revision,
            "supersedes_revision",
        )
        _validate_revision_pair(revision, supersedes)
        if self.decision not in _DECISIONS:
            raise GroupingSignalReviewValidationError(
                "decision must be accepted_for_export or rejected."
            )
        acknowledgments = _diagnostic_ids(
            self.acknowledged_warning_ids,
            "acknowledged_warning_ids",
        )
        if self.decision == "rejected" and acknowledgments:
            raise GroupingSignalReviewValidationError(
                "rejected review must not record warning acknowledgments."
            )
        if not isinstance(self.actor, GroupingSignalReviewActor):
            raise GroupingSignalReviewValidationError(
                "actor must be a GroupingSignalReviewActor."
            )
        actor = GroupingSignalReviewActor(self.actor.kind, self.actor.actor_id)
        reviewed_at = _aware_utc_datetime(self.reviewed_at, "reviewed_at")

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "review_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "acknowledged_warning_ids", acknowledgments)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "reviewed_at", reviewed_at)


@dataclass(frozen=True, slots=True)
class GroupingSignalReviewReference:
    """Exact immutable review revision and canonical-byte digest."""

    class_id: str
    derivation_id: str
    review_revision: int
    review_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "derivation_id",
            _derivation_id(self.derivation_id),
        )
        object.__setattr__(
            self,
            "review_revision",
            _positive_int(self.review_revision, "review_revision"),
        )
        object.__setattr__(
            self,
            "review_sha256",
            _sha256(self.review_sha256, "review_sha256"),
        )


@dataclass(frozen=True, slots=True)
class GroupingSignalReviewApplicability:
    """Read-only applicability of a review to current derivation state."""

    status: GroupingSignalReviewApplicabilityStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in {"current", "stale", "not_accepted"}:
            raise GroupingSignalReviewValidationError(
                "review applicability status is invalid."
            )
        reasons = _codes(self.reason_codes, "reason_codes")
        if self.status in {"current", "not_accepted"} and reasons:
            raise GroupingSignalReviewValidationError(
                f"{self.status} applicability must not carry stale reasons."
            )
        if self.status == "stale" and not reasons:
            raise GroupingSignalReviewValidationError(
                "stale applicability requires at least one reason code."
            )
        object.__setattr__(self, "reason_codes", reasons)


def create_grouping_signal_review_decision(
    preview: GroupingSignalPreviewSnapshot,
    preview_reference: GroupingSignalPreviewReference,
    *,
    review_revision: int,
    supersedes_revision: int | None,
    decision: GroupingSignalReviewDecisionValue,
    acknowledged_warning_ids: tuple[str, ...],
    actor_id: str,
    reviewed_at: datetime,
) -> GroupingSignalReviewDecision:
    """Create one review and enforce exact acceptance/acknowledgment semantics."""

    exact_preview = validate_grouping_signal_preview_snapshot(preview)
    expected_preview_reference = grouping_signal_preview_reference(exact_preview)
    if preview_reference != expected_preview_reference:
        raise GroupingSignalReviewValidationError(
            "preview_reference must bind the exact reviewed preview bytes."
        )

    candidate = GroupingSignalReviewDecision(
        schema_version=GROUPING_SIGNAL_REVIEW_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_REVIEW_RECORD_TYPE,
        class_id=exact_preview.derivation_reference.class_id,
        derivation_reference=exact_preview.derivation_reference,
        preview_reference=preview_reference,
        review_revision=review_revision,
        supersedes_revision=supersedes_revision,
        decision=decision,
        acknowledged_warning_ids=acknowledged_warning_ids,
        actor=GroupingSignalReviewActor("teacher", actor_id),
        reviewed_at=reviewed_at,
    )
    return validate_grouping_signal_review_against_preview(
        candidate,
        exact_preview,
    )


def validate_grouping_signal_review_against_preview(
    review: GroupingSignalReviewDecision,
    preview: GroupingSignalPreviewSnapshot,
) -> GroupingSignalReviewDecision:
    """Require review provenance and acceptance semantics to match one preview."""

    exact_review = validate_grouping_signal_review_decision(review)
    exact_preview = validate_grouping_signal_preview_snapshot(preview)
    expected_preview_reference = grouping_signal_preview_reference(exact_preview)

    if exact_review.class_id != exact_preview.derivation_reference.class_id:
        raise GroupingSignalReviewValidationError(
            "review class_id must match preview class scope."
        )
    if exact_review.derivation_reference != exact_preview.derivation_reference:
        raise GroupingSignalReviewValidationError(
            "review must bind the exact derivation reviewed by the preview."
        )
    if exact_review.preview_reference != expected_preview_reference:
        raise GroupingSignalReviewValidationError(
            "review must bind the exact canonical preview reference."
        )

    if exact_review.decision == "rejected":
        return exact_review

    if exact_preview.currentness.state != "current":
        raise GroupingSignalReviewValidationError(
            "accepted_for_export requires a current derivation preview."
        )

    blocking = tuple(
        item.diagnostic_id
        for item in exact_preview.diagnostics
        if item.severity == "blocking"
    )
    if blocking:
        raise GroupingSignalReviewValidationError(
            "accepted_for_export is unavailable while blocking diagnostics exist."
        )

    required_warnings = tuple(
        sorted(
            item.diagnostic_id
            for item in exact_preview.diagnostics
            if item.severity == "warning"
        )
    )
    if exact_review.acknowledged_warning_ids != required_warnings:
        raise GroupingSignalReviewValidationError(
            "accepted_for_export must acknowledge exactly every warning "
            "diagnostic ID."
        )
    return exact_review


def validate_grouping_signal_review_transition(
    previous: GroupingSignalReviewDecision,
    candidate: GroupingSignalReviewDecision,
) -> GroupingSignalReviewDecision:
    """Require one contiguous immutable successor within a derivation family."""

    before = validate_grouping_signal_review_decision(previous)
    after = validate_grouping_signal_review_decision(candidate)
    if (
        before.class_id != after.class_id
        or before.derivation_reference != after.derivation_reference
    ):
        raise GroupingSignalReviewValidationError(
            "review transition cannot change exact derivation identity."
        )
    if after.review_revision != before.review_revision + 1:
        raise GroupingSignalReviewValidationError(
            "review revisions must be contiguous."
        )
    if after.supersedes_revision != before.review_revision:
        raise GroupingSignalReviewValidationError(
            "supersedes_revision must identify the immediately prior review."
        )
    if after.reviewed_at < before.reviewed_at:
        raise GroupingSignalReviewValidationError(
            "reviewed_at must be nondecreasing across review revisions."
        )
    return after


def assess_grouping_signal_review_applicability(
    review: GroupingSignalReviewDecision,
    currentness: GroupingSignalPreviewCurrentness,
) -> GroupingSignalReviewApplicability:
    """Assess whether one accepted review still applies to current #38 state."""

    exact_review = validate_grouping_signal_review_decision(review)
    if not isinstance(currentness, GroupingSignalPreviewCurrentness):
        raise GroupingSignalReviewValidationError(
            "currentness must be GroupingSignalPreviewCurrentness."
        )
    currentness.__post_init__()

    if exact_review.decision != "accepted_for_export":
        return GroupingSignalReviewApplicability("not_accepted", ())

    if (
        currentness.state == "current"
        and currentness.current_derivation_reference
        == exact_review.derivation_reference
    ):
        return GroupingSignalReviewApplicability("current", ())

    reasons = currentness.reason_codes
    if not reasons:
        reasons = ("derivation_not_current",)
    return GroupingSignalReviewApplicability("stale", reasons)


def validate_grouping_signal_review_decision(
    value: GroupingSignalReviewDecision,
) -> GroupingSignalReviewDecision:
    """Revalidate one immutable review revision."""

    if not isinstance(value, GroupingSignalReviewDecision):
        raise GroupingSignalReviewValidationError(
            "value must be GroupingSignalReviewDecision."
        )
    value.__post_init__()
    return value


def grouping_signal_review_sha256(
    value: GroupingSignalReviewDecision,
) -> str:
    """Return SHA-256 over exact canonical review JSON bytes."""

    return hashlib.sha256(
        grouping_signal_review_to_json_bytes(value)
    ).hexdigest()


def grouping_signal_review_reference(
    value: GroupingSignalReviewDecision,
) -> GroupingSignalReviewReference:
    """Return exact digest-bound reference to one review revision."""

    review = validate_grouping_signal_review_decision(value)
    return GroupingSignalReviewReference(
        class_id=review.class_id,
        derivation_id=review.derivation_reference.derivation_id,
        review_revision=review.review_revision,
        review_sha256=grouping_signal_review_sha256(review),
    )


def grouping_signal_review_to_dict(
    value: GroupingSignalReviewDecision,
) -> dict[str, object]:
    """Convert one validated review to exact JSON-native data."""

    review = validate_grouping_signal_review_decision(value)
    return {
        "schema_version": review.schema_version,
        "record_type": review.record_type,
        "class_id": review.class_id,
        "derivation_reference": grouping_signal_derivation_reference_to_dict(
            review.derivation_reference
        ),
        "preview_reference": grouping_signal_preview_reference_to_dict(
            review.preview_reference
        ),
        "review_revision": review.review_revision,
        "supersedes_revision": review.supersedes_revision,
        "decision": review.decision,
        "acknowledged_warning_ids": list(review.acknowledged_warning_ids),
        "actor": _actor_to_dict(review.actor),
        "reviewed_at": _datetime_to_text(review.reviewed_at),
    }


def grouping_signal_review_from_dict(
    data: object,
) -> GroupingSignalReviewDecision:
    """Parse one exact review mapping with a closed field set."""

    mapping = _exact_mapping(data, _REVIEW_KEYS, "grouping-signal review")
    decision = _require_str(mapping["decision"], "decision")
    return GroupingSignalReviewDecision(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        derivation_reference=grouping_signal_derivation_reference_from_dict(
            mapping["derivation_reference"]
        ),
        preview_reference=grouping_signal_preview_reference_from_dict(
            mapping["preview_reference"]
        ),
        review_revision=_require_int(
            mapping["review_revision"],
            "review_revision",
        ),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"],
            "supersedes_revision",
        ),
        decision=cast(GroupingSignalReviewDecisionValue, decision),
        acknowledged_warning_ids=tuple(
            _require_str(item, "diagnostic_id")
            for item in _require_list(
                mapping["acknowledged_warning_ids"],
                "acknowledged_warning_ids",
            )
        ),
        actor=_actor_from_dict(mapping["actor"]),
        reviewed_at=_datetime_from_text(
            _require_str(mapping["reviewed_at"], "reviewed_at"),
            "reviewed_at",
        ),
    )


def grouping_signal_review_to_json_bytes(
    value: GroupingSignalReviewDecision,
) -> bytes:
    """Serialize one review as deterministic canonical JSON bytes."""

    payload = _canonical_json_bytes(grouping_signal_review_to_dict(value))
    if len(payload) > MAXIMUM_GROUPING_SIGNAL_REVIEW_BYTES:
        raise GroupingSignalReviewSerializationError(
            "grouping-signal review exceeds bounded canonical JSON size."
        )
    return payload


def grouping_signal_review_from_json_bytes(
    data: bytes,
) -> GroupingSignalReviewDecision:
    """Load only canonical UTF-8 JSON bytes for one review revision."""

    if not isinstance(data, bytes):
        raise GroupingSignalReviewSerializationError(
            "grouping-signal review JSON must be bytes."
        )
    if len(data) > MAXIMUM_GROUPING_SIGNAL_REVIEW_BYTES:
        raise GroupingSignalReviewSerializationError(
            "grouping-signal review exceeds bounded canonical JSON size."
        )
    parsed = _parse_json_bytes(data)
    value = grouping_signal_review_from_dict(parsed)
    if grouping_signal_review_to_json_bytes(value) != data:
        raise GroupingSignalReviewSerializationError(
            "grouping-signal review is not canonical JSON."
        )
    return value


def grouping_signal_review_reference_to_dict(
    value: GroupingSignalReviewReference,
) -> dict[str, object]:
    """Convert one exact review reference to JSON-native data."""

    if not isinstance(value, GroupingSignalReviewReference):
        raise GroupingSignalReviewValidationError(
            "value must be GroupingSignalReviewReference."
        )
    value.__post_init__()
    return {
        "class_id": value.class_id,
        "derivation_id": value.derivation_id,
        "review_revision": value.review_revision,
        "review_sha256": value.review_sha256,
    }


def grouping_signal_review_reference_from_dict(
    data: object,
) -> GroupingSignalReviewReference:
    """Parse one exact review-reference mapping."""

    mapping = _exact_mapping(
        data,
        _REFERENCE_KEYS,
        "grouping-signal review reference",
    )
    return GroupingSignalReviewReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        derivation_id=_require_str(mapping["derivation_id"], "derivation_id"),
        review_revision=_require_int(
            mapping["review_revision"],
            "review_revision",
        ),
        review_sha256=_require_str(
            mapping["review_sha256"],
            "review_sha256",
        ),
    )


def _actor_to_dict(value: GroupingSignalReviewActor) -> dict[str, object]:
    if not isinstance(value, GroupingSignalReviewActor):
        raise GroupingSignalReviewValidationError(
            "value must be GroupingSignalReviewActor."
        )
    value.__post_init__()
    return {"kind": value.kind, "actor_id": value.actor_id}


def _actor_from_dict(data: object) -> GroupingSignalReviewActor:
    mapping = _exact_mapping(data, _ACTOR_KEYS, "grouping-signal review actor")
    kind = _require_str(mapping["kind"], "kind")
    return GroupingSignalReviewActor(
        cast(GroupingSignalReviewActorKind, kind),
        _require_str(mapping["actor_id"], "actor_id"),
    )


def _validate_revision_pair(
    revision: int,
    supersedes: int | None,
) -> None:
    if revision == 1:
        if supersedes is not None:
            raise GroupingSignalReviewValidationError(
                "review revision 1 must not supersede another revision."
            )
    elif supersedes != revision - 1:
        raise GroupingSignalReviewValidationError(
            "review revision must supersede the immediately prior revision."
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalReviewValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GroupingSignalReviewValidationError(str(error)) from error


def _derivation_id(value: object) -> str:
    derivation_id = _identifier(value, "derivation_id")
    if _DERIVATION_ID.fullmatch(derivation_id) is None:
        raise GroupingSignalReviewValidationError(
            "derivation_id must be gsd_ followed by a lowercase SHA-256 digest."
        )
    return derivation_id


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise GroupingSignalReviewValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _diagnostic_ids(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalReviewValidationError(
            f"{field_name} must be a tuple."
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or _DIAGNOSTIC_ID.fullmatch(item) is None:
            raise GroupingSignalReviewValidationError(
                f"{field_name} must contain exact gpd_ diagnostic IDs."
            )
        items.append(item)
    if len(set(items)) != len(items):
        raise GroupingSignalReviewValidationError(
            f"{field_name} must not contain duplicate diagnostic IDs."
        )
    return tuple(sorted(items))


def _codes(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalReviewValidationError(
            f"{field_name} must be a tuple."
        )
    items: list[str] = []
    for item in value:
        if (
            not isinstance(item, str)
            or not item
            or len(item) > 128
            or not item.replace("_", "").isalnum()
        ):
            raise GroupingSignalReviewValidationError(
                f"{field_name} must contain bounded stable codes."
            )
        items.append(item)
    if len(set(items)) != len(items):
        raise GroupingSignalReviewValidationError(
            f"{field_name} must not contain duplicates."
        )
    return tuple(sorted(items))


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise GroupingSignalReviewValidationError(
            f"{field_name} must be nonempty text of at most {maximum} characters."
        )
    if "\n" in value or "\r" in value:
        raise GroupingSignalReviewValidationError(
            f"{field_name} must be one line."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GroupingSignalReviewValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise GroupingSignalReviewValidationError(
            f"{field_name} must be timezone-aware."
        )
    normalized = value.astimezone(UTC)
    if normalized.microsecond != 0:
        raise GroupingSignalReviewValidationError(
            f"{field_name} must use whole-second precision."
        )
    return normalized


def _datetime_to_text(value: datetime) -> str:
    exact = _aware_utc_datetime(value, "reviewed_at")
    return exact.isoformat().replace("+00:00", "Z")


def _datetime_from_text(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise GroupingSignalReviewSerializationError(
            f"{field_name} must be canonical UTC text ending in Z."
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise GroupingSignalReviewSerializationError(
            f"{field_name} is not a valid UTC datetime."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(data, dict):
        raise GroupingSignalReviewSerializationError(
            f"{label} must be a JSON object."
        )
    if set(data) != keys:
        raise GroupingSignalReviewSerializationError(
            f"{label} keys do not match the exact contract."
        )
    if not all(isinstance(key, str) for key in data):
        raise GroupingSignalReviewSerializationError(
            f"{label} keys must be strings."
        )
    return cast(dict[str, object], data)


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise GroupingSignalReviewSerializationError(
            f"{field_name} must be a JSON array."
        )
    return cast(list[object], value)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalReviewSerializationError(
            f"{field_name} must be a string."
        )
    return value


def _require_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise GroupingSignalReviewSerializationError(
            f"{field_name} must be an integer."
        )
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise GroupingSignalReviewSerializationError(
            "grouping-signal review is not JSON serializable."
        ) from error


def _parse_json_bytes(data: bytes) -> object:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GroupingSignalReviewSerializationError(
            "grouping-signal review JSON must be UTF-8."
        ) from error

    def reject_duplicate(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise GroupingSignalReviewSerializationError(
                    "grouping-signal review JSON contains duplicate keys."
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> NoReturn:
        raise GroupingSignalReviewSerializationError(
            f"nonfinite JSON value {value!r} is not allowed."
        )

    try:
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except GroupingSignalReviewSerializationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise GroupingSignalReviewSerializationError(
            "grouping-signal review JSON is invalid."
        ) from error
