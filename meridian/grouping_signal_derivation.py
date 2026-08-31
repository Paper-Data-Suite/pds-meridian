"""Deterministic Meridian derivation of contextual grouping-signal bands.

This module owns only the pure, immutable #38 derivation contract. It does not
resolve workspace state, assess #35 freshness, persist derivations, preview a
class distribution, create a Core grouping signal, export CSV, or form groups.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal, NoReturn, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
    AcademicPeriodProficiencyResultSnapshot,
    academic_period_proficiency_result_reference,
    academic_period_proficiency_result_reference_from_dict,
    academic_period_proficiency_result_reference_to_dict,
)
from meridian.grouping_signal_policy import (
    GroupingSignalDerivationPolicy,
    GroupingSignalDerivationPolicyReference,
    grouping_signal_derivation_policy_reference,
    grouping_signal_derivation_policy_reference_from_dict,
    grouping_signal_derivation_policy_reference_to_dict,
    validate_grouping_signal_derivation_policy_against_scale,
)
from meridian.proficiency_mapping import (
    ProficiencyScale,
    proficiency_scale_reference,
    validate_proficiency_scale,
)

GROUPING_SIGNAL_DERIVATION_SCHEMA_VERSION: Final[str] = "1"
GROUPING_SIGNAL_DERIVATION_RECORD_TYPE: Final[str] = (
    "meridian_grouping_signal_derivation"
)
GROUPING_SIGNAL_DERIVATION_ALGORITHM_VERSION: Final[str] = (
    "academic_period_proficiency_band_v1"
)
GROUPING_SIGNAL_DERIVATION_ID_PREFIX: Final[str] = "gsd_"
MAXIMUM_GROUPING_SIGNAL_DERIVATION_BYTES: Final[int] = 8 * 1024 * 1024

GroupingSignalDerivationSourceState: TypeAlias = Literal[
    "calculated",
    "missing",
    "insufficient_evidence",
]
GroupingSignalDerivationDisposition: TypeAlias = Literal[
    "contributing",
    "noncontributing",
]

_SOURCE_STATES: Final[tuple[GroupingSignalDerivationSourceState, ...]] = (
    "calculated",
    "missing",
    "insufficient_evidence",
)
_DISPOSITIONS: Final[tuple[GroupingSignalDerivationDisposition, ...]] = (
    "contributing",
    "noncontributing",
)
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_DERIVATION_ID: Final[re.Pattern[str]] = re.compile(r"^gsd_[0-9a-f]{64}$")

_ROSTER_BASIS_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "student_ids", "membership_sha256"}
)
_STUDENT_DERIVATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "student_id",
        "source_state",
        "disposition",
        "source_result",
        "proficiency_level_id",
        "scale_position",
        "band",
    }
)
_DERIVATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "derivation_id",
        "class_id",
        "algorithm_version",
        "policy_reference",
        "roster_basis",
        "dimension_id",
        "band_count",
        "student_derivations",
        "calculation_fingerprint",
    }
)
_DERIVATION_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "derivation_id", "derivation_sha256"}
)


class GroupingSignalDerivationError(ValueError):
    """Base error for deterministic grouping-signal derivation contracts."""


class GroupingSignalDerivationValidationError(GroupingSignalDerivationError):
    """Raised when grouping-signal derivation data violates its contract."""


class GroupingSignalDerivationSerializationError(GroupingSignalDerivationError):
    """Raised when grouping-signal derivation JSON is invalid/noncanonical."""


class GroupingSignalDerivationBlockedError(GroupingSignalDerivationError):
    """Raised when selected policy semantics block a pure class derivation."""

    blocking_students: tuple[
        tuple[str, GroupingSignalDerivationSourceState], ...
    ]

    def __init__(
        self,
        blocking_students: Iterable[
            tuple[str, GroupingSignalDerivationSourceState]
        ],
    ) -> None:
        blockers = tuple(sorted(blocking_students, key=lambda item: item[0]))
        if not blockers:
            raise ValueError("blocking_students must not be empty.")
        self.blocking_students = blockers
        summary = ", ".join(
            f"{student_id}:{state}" for student_id, state in blockers
        )
        super().__init__(f"grouping-signal derivation is blocked: {summary}")


@dataclass(frozen=True, slots=True)
class GroupingSignalRosterBasis:
    """Privacy-minimal exact Core roster membership used by one derivation."""

    class_id: str
    student_ids: tuple[str, ...]
    membership_sha256: str

    def __post_init__(self) -> None:
        class_id = _identifier(self.class_id, "class_id")
        if not isinstance(self.student_ids, tuple):
            raise GroupingSignalDerivationValidationError(
                "student_ids must be a tuple."
            )
        student_ids = tuple(
            _identifier(item, "student_id") for item in self.student_ids
        )
        if not student_ids:
            raise GroupingSignalDerivationValidationError(
                "student_ids must not be empty."
            )
        if len(set(student_ids)) != len(student_ids):
            raise GroupingSignalDerivationValidationError(
                "student_ids must not contain duplicates."
            )
        student_ids = tuple(sorted(student_ids))
        membership_sha256 = _sha256(
            self.membership_sha256,
            "membership_sha256",
        )
        expected = _roster_membership_sha256(class_id, student_ids)
        if membership_sha256 != expected:
            raise GroupingSignalDerivationValidationError(
                "membership_sha256 must bind the exact canonical roster membership."
            )
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "student_ids", student_ids)
        object.__setattr__(self, "membership_sha256", membership_sha256)


@dataclass(frozen=True, slots=True)
class GroupingSignalResolvedStudentResult:
    """One roster student plus the exact selected/current #35 result, if any."""

    student_id: str
    result: AcademicPeriodProficiencyResultSnapshot | None

    def __post_init__(self) -> None:
        student_id = _identifier(self.student_id, "student_id")
        result = self.result
        if result is not None:
            if not isinstance(result, AcademicPeriodProficiencyResultSnapshot):
                raise GroupingSignalDerivationValidationError(
                    "result must be an AcademicPeriodProficiencyResultSnapshot "
                    "or None."
                )
            try:
                reference = academic_period_proficiency_result_reference(result)
            except ValueError as error:
                raise GroupingSignalDerivationValidationError(str(error)) from error
            if reference.student_id != student_id:
                raise GroupingSignalDerivationValidationError(
                    "resolved result student_id must match the roster student."
                )
        object.__setattr__(self, "student_id", student_id)


@dataclass(frozen=True, slots=True)
class GroupingSignalStudentDerivation:
    """Rich privacy-minimal provenance for one exact roster student."""

    student_id: str
    source_state: GroupingSignalDerivationSourceState
    disposition: GroupingSignalDerivationDisposition
    source_result: AcademicPeriodProficiencyResultReference | None
    proficiency_level_id: str | None
    scale_position: int | None
    band: int | None

    def __post_init__(self) -> None:
        student_id = _identifier(self.student_id, "student_id")
        source_state = _source_state(self.source_state)
        disposition = _disposition(self.disposition)
        source_result = self.source_result
        if source_result is not None:
            if not isinstance(
                source_result,
                AcademicPeriodProficiencyResultReference,
            ):
                raise GroupingSignalDerivationValidationError(
                    "source_result must be an exact #35 result reference or None."
                )
            if source_result.student_id != student_id:
                raise GroupingSignalDerivationValidationError(
                    "source_result student_id must match student_id."
                )

        level_id = self.proficiency_level_id
        if level_id is not None:
            level_id = _identifier(level_id, "proficiency_level_id")
        scale_position = _optional_positive_int(
            self.scale_position,
            "scale_position",
        )
        band = _optional_positive_int(self.band, "band")

        if source_state == "calculated":
            if (
                disposition != "contributing"
                or source_result is None
                or level_id is None
                or scale_position is None
                or band is None
            ):
                raise GroupingSignalDerivationValidationError(
                    "calculated student derivation requires contributing exact "
                    "result, level, scale position, and band."
                )
        elif source_state == "missing":
            if (
                disposition != "noncontributing"
                or source_result is not None
                or level_id is not None
                or scale_position is not None
                or band is not None
            ):
                raise GroupingSignalDerivationValidationError(
                    "missing student derivation must be noncontributing and carry "
                    "no result, level, scale position, or band."
                )
        elif (
            disposition != "noncontributing"
            or source_result is None
            or level_id is not None
            or scale_position is not None
            or band is not None
        ):
            raise GroupingSignalDerivationValidationError(
                "insufficient student derivation requires exact result provenance "
                "and no level, scale position, or band."
            )

        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "source_state", source_state)
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "proficiency_level_id", level_id)
        object.__setattr__(self, "scale_position", scale_position)
        object.__setattr__(self, "band", band)


@dataclass(frozen=True, slots=True)
class GroupingSignalDerivationSnapshot:
    """One immutable content-addressed deterministic Meridian derivation."""

    schema_version: str
    record_type: str
    derivation_id: str
    class_id: str
    algorithm_version: str
    policy_reference: GroupingSignalDerivationPolicyReference
    roster_basis: GroupingSignalRosterBasis
    dimension_id: str
    band_count: int
    student_derivations: tuple[GroupingSignalStudentDerivation, ...]
    calculation_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema_version != GROUPING_SIGNAL_DERIVATION_SCHEMA_VERSION:
            raise GroupingSignalDerivationValidationError(
                "unsupported grouping-signal derivation schema_version."
            )
        if self.record_type != GROUPING_SIGNAL_DERIVATION_RECORD_TYPE:
            raise GroupingSignalDerivationValidationError(
                "record_type must identify a grouping-signal derivation."
            )
        class_id = _identifier(self.class_id, "class_id")
        if self.algorithm_version != GROUPING_SIGNAL_DERIVATION_ALGORITHM_VERSION:
            raise GroupingSignalDerivationValidationError(
                "unsupported grouping-signal derivation algorithm_version."
            )
        if not isinstance(
            self.policy_reference,
            GroupingSignalDerivationPolicyReference,
        ):
            raise GroupingSignalDerivationValidationError(
                "policy_reference must be an exact #37 policy reference."
            )
        if self.policy_reference.class_id != class_id:
            raise GroupingSignalDerivationValidationError(
                "policy_reference class_id must match derivation class_id."
            )
        if not isinstance(self.roster_basis, GroupingSignalRosterBasis):
            raise GroupingSignalDerivationValidationError(
                "roster_basis must be a GroupingSignalRosterBasis."
            )
        self.roster_basis.__post_init__()
        if self.roster_basis.class_id != class_id:
            raise GroupingSignalDerivationValidationError(
                "roster_basis class_id must match derivation class_id."
            )
        dimension_id = _identifier(self.dimension_id, "dimension_id")
        band_count = _positive_int(self.band_count, "band_count")
        if band_count < 2:
            raise GroupingSignalDerivationValidationError(
                "band_count must be at least 2."
            )
        derivations = _student_derivations(
            self.student_derivations,
            self.roster_basis,
            class_id,
            band_count,
        )
        fingerprint = _sha256(
            self.calculation_fingerprint,
            "calculation_fingerprint",
        )
        expected_fingerprint = grouping_signal_derivation_calculation_fingerprint(
            self.policy_reference,
            self.roster_basis,
            derivations,
        )
        if fingerprint != expected_fingerprint:
            raise GroupingSignalDerivationValidationError(
                "calculation_fingerprint must bind the exact semantic inputs."
            )
        derivation_id = _derivation_id(self.derivation_id)
        expected_id = grouping_signal_derivation_id(fingerprint)
        if derivation_id != expected_id:
            raise GroupingSignalDerivationValidationError(
                "derivation_id must be content-addressed from calculation_fingerprint."
            )

        object.__setattr__(self, "derivation_id", derivation_id)
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "dimension_id", dimension_id)
        object.__setattr__(self, "band_count", band_count)
        object.__setattr__(self, "student_derivations", derivations)
        object.__setattr__(self, "calculation_fingerprint", fingerprint)


@dataclass(frozen=True, slots=True)
class GroupingSignalDerivationReference:
    """Exact immutable Meridian derivation identity and canonical-byte digest."""

    class_id: str
    derivation_id: str
    derivation_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "derivation_id",
            _derivation_id(self.derivation_id),
        )
        object.__setattr__(
            self,
            "derivation_sha256",
            _sha256(self.derivation_sha256, "derivation_sha256"),
        )


def grouping_signal_roster_basis(
    class_id: str,
    student_ids: Iterable[str],
) -> GroupingSignalRosterBasis:
    """Build one canonical privacy-minimal roster membership basis."""
    exact_class_id = _identifier(class_id, "class_id")
    try:
        exact_student_ids = tuple(student_ids)
    except TypeError as error:
        raise GroupingSignalDerivationValidationError(
            "student_ids must be an iterable of exact student identifiers."
        ) from error
    exact_student_ids = tuple(
        _identifier(item, "student_id") for item in exact_student_ids
    )
    if not exact_student_ids:
        raise GroupingSignalDerivationValidationError(
            "student_ids must not be empty."
        )
    if len(set(exact_student_ids)) != len(exact_student_ids):
        raise GroupingSignalDerivationValidationError(
            "student_ids must not contain duplicates."
        )
    ordered = tuple(sorted(exact_student_ids))
    return GroupingSignalRosterBasis(
        class_id=exact_class_id,
        student_ids=ordered,
        membership_sha256=_roster_membership_sha256(exact_class_id, ordered),
    )


def grouping_signal_derivation_calculation_fingerprint(
    policy_reference: GroupingSignalDerivationPolicyReference,
    roster_basis: GroupingSignalRosterBasis,
    student_derivations: tuple[GroupingSignalStudentDerivation, ...],
) -> str:
    """Digest the exact semantic inputs, excluding derived band output fields."""
    if not isinstance(
        policy_reference,
        GroupingSignalDerivationPolicyReference,
    ):
        raise GroupingSignalDerivationValidationError(
            "policy_reference must be an exact #37 policy reference."
        )
    if not isinstance(roster_basis, GroupingSignalRosterBasis):
        raise GroupingSignalDerivationValidationError(
            "roster_basis must be a GroupingSignalRosterBasis."
        )
    roster_basis.__post_init__()
    if policy_reference.class_id != roster_basis.class_id:
        raise GroupingSignalDerivationValidationError(
            "policy_reference and roster_basis must use one class scope."
        )
    derivations = _student_derivations(
        student_derivations,
        roster_basis,
        policy_reference.class_id,
        band_count=None,
    )
    source_resolution = [
        {
            "student_id": item.student_id,
            "source_state": item.source_state,
            "source_result": (
                academic_period_proficiency_result_reference_to_dict(
                    item.source_result
                )
                if item.source_result is not None
                else None
            ),
            "proficiency_level_id": item.proficiency_level_id,
        }
        for item in derivations
    ]
    payload = {
        "algorithm_version": GROUPING_SIGNAL_DERIVATION_ALGORITHM_VERSION,
        "policy_reference": grouping_signal_derivation_policy_reference_to_dict(
            policy_reference
        ),
        "roster_basis": grouping_signal_roster_basis_to_dict(roster_basis),
        "source_resolution": source_resolution,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def grouping_signal_derivation_id(calculation_fingerprint: str) -> str:
    """Return the deterministic content-addressed identity for a fingerprint."""
    fingerprint = _sha256(calculation_fingerprint, "calculation_fingerprint")
    derivation_id = GROUPING_SIGNAL_DERIVATION_ID_PREFIX + fingerprint
    try:
        validate_identifier(derivation_id, "derivation_id")
    except IdentifierValidationError as error:
        raise GroupingSignalDerivationValidationError(str(error)) from error
    return derivation_id


def derive_grouping_signal_snapshot(
    policy: GroupingSignalDerivationPolicy,
    policy_reference: GroupingSignalDerivationPolicyReference,
    target_scale: ProficiencyScale,
    roster_basis: GroupingSignalRosterBasis,
    resolved_students: tuple[GroupingSignalResolvedStudentResult, ...],
) -> GroupingSignalDerivationSnapshot:
    """Purely derive one immutable contextual-band snapshot from exact inputs."""
    try:
        exact_policy = validate_grouping_signal_derivation_policy_against_scale(
            policy,
            target_scale,
        )
        exact_scale = validate_proficiency_scale(target_scale)
        expected_policy_reference = grouping_signal_derivation_policy_reference(
            exact_policy
        )
        exact_scale_reference = proficiency_scale_reference(exact_scale)
    except ValueError as error:
        raise GroupingSignalDerivationValidationError(str(error)) from error
    if not isinstance(
        policy_reference,
        GroupingSignalDerivationPolicyReference,
    ):
        raise GroupingSignalDerivationValidationError(
            "policy_reference must be an exact #37 policy reference."
        )
    if policy_reference != expected_policy_reference:
        raise GroupingSignalDerivationValidationError(
            "policy_reference must bind the exact selected #37 policy revision."
        )
    if exact_policy.academic_basis.target_scale != exact_scale_reference:
        raise GroupingSignalDerivationValidationError(
            "selected #37 policy must bind the exact target scale."
        )
    if not isinstance(roster_basis, GroupingSignalRosterBasis):
        raise GroupingSignalDerivationValidationError(
            "roster_basis must be a GroupingSignalRosterBasis."
        )
    roster_basis.__post_init__()
    if roster_basis.class_id != exact_policy.class_id:
        raise GroupingSignalDerivationValidationError(
            "roster_basis class_id must match selected #37 policy class_id."
        )

    resolved = _resolved_students(resolved_students, roster_basis)
    level_positions = {
        level.level_id: level.position for level in exact_scale.levels
    }
    student_derivations: list[GroupingSignalStudentDerivation] = []
    blockers: list[tuple[str, GroupingSignalDerivationSourceState]] = []

    for item in resolved:
        if item.result is None:
            if exact_policy.missing_result_handling == "blocking":
                blockers.append((item.student_id, "missing"))
                continue
            student_derivations.append(
                GroupingSignalStudentDerivation(
                    student_id=item.student_id,
                    source_state="missing",
                    disposition="noncontributing",
                    source_result=None,
                    proficiency_level_id=None,
                    scale_position=None,
                    band=None,
                )
            )
            continue

        result = item.result
        reference = _validate_exact_source_result(
            result,
            item.student_id,
            exact_policy,
        )
        if result.outcome.status == "insufficient_evidence":
            if exact_policy.insufficient_result_handling == "blocking":
                blockers.append((item.student_id, "insufficient_evidence"))
                continue
            student_derivations.append(
                GroupingSignalStudentDerivation(
                    student_id=item.student_id,
                    source_state="insufficient_evidence",
                    disposition="noncontributing",
                    source_result=reference,
                    proficiency_level_id=None,
                    scale_position=None,
                    band=None,
                )
            )
            continue

        level_id = result.outcome.proficiency_level_id
        if level_id is None or level_id not in level_positions:
            raise GroupingSignalDerivationValidationError(
                "calculated #35 result must identify a level on the exact target "
                "scale."
            )
        scale_position = level_positions[level_id]
        band = _band_for_position(exact_policy, scale_position)
        student_derivations.append(
            GroupingSignalStudentDerivation(
                student_id=item.student_id,
                source_state="calculated",
                disposition="contributing",
                source_result=reference,
                proficiency_level_id=level_id,
                scale_position=scale_position,
                band=band,
            )
        )

    if blockers:
        raise GroupingSignalDerivationBlockedError(blockers)

    exact_student_derivations = tuple(student_derivations)
    fingerprint = grouping_signal_derivation_calculation_fingerprint(
        policy_reference,
        roster_basis,
        exact_student_derivations,
    )
    return GroupingSignalDerivationSnapshot(
        schema_version=GROUPING_SIGNAL_DERIVATION_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_DERIVATION_RECORD_TYPE,
        derivation_id=grouping_signal_derivation_id(fingerprint),
        class_id=exact_policy.class_id,
        algorithm_version=GROUPING_SIGNAL_DERIVATION_ALGORITHM_VERSION,
        policy_reference=policy_reference,
        roster_basis=roster_basis,
        dimension_id=exact_policy.dimension_id,
        band_count=exact_policy.band_count,
        student_derivations=exact_student_derivations,
        calculation_fingerprint=fingerprint,
    )


def validate_grouping_signal_derivation_snapshot(
    value: GroupingSignalDerivationSnapshot,
) -> GroupingSignalDerivationSnapshot:
    """Revalidate one immutable deterministic derivation snapshot."""
    if not isinstance(value, GroupingSignalDerivationSnapshot):
        raise GroupingSignalDerivationValidationError(
            "value must be a GroupingSignalDerivationSnapshot."
        )
    value.__post_init__()
    return value


def grouping_signal_derivation_snapshot_to_dict(
    value: GroupingSignalDerivationSnapshot,
) -> dict[str, object]:
    """Convert one exact derivation snapshot to JSON-native data."""
    snapshot = validate_grouping_signal_derivation_snapshot(value)
    return {
        "schema_version": snapshot.schema_version,
        "record_type": snapshot.record_type,
        "derivation_id": snapshot.derivation_id,
        "class_id": snapshot.class_id,
        "algorithm_version": snapshot.algorithm_version,
        "policy_reference": grouping_signal_derivation_policy_reference_to_dict(
            snapshot.policy_reference
        ),
        "roster_basis": grouping_signal_roster_basis_to_dict(
            snapshot.roster_basis
        ),
        "dimension_id": snapshot.dimension_id,
        "band_count": snapshot.band_count,
        "student_derivations": [
            grouping_signal_student_derivation_to_dict(item)
            for item in snapshot.student_derivations
        ],
        "calculation_fingerprint": snapshot.calculation_fingerprint,
    }


def grouping_signal_derivation_snapshot_from_dict(
    data: object,
) -> GroupingSignalDerivationSnapshot:
    """Parse one exact derivation snapshot mapping with a closed field set."""
    mapping = _exact_mapping(data, _DERIVATION_KEYS, "grouping-signal derivation")
    student_data = _require_list(
        mapping["student_derivations"],
        "student_derivations",
    )
    return GroupingSignalDerivationSnapshot(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        derivation_id=_require_str(mapping["derivation_id"], "derivation_id"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        algorithm_version=_require_str(
            mapping["algorithm_version"],
            "algorithm_version",
        ),
        policy_reference=grouping_signal_derivation_policy_reference_from_dict(
            mapping["policy_reference"]
        ),
        roster_basis=grouping_signal_roster_basis_from_dict(
            mapping["roster_basis"]
        ),
        dimension_id=_require_str(mapping["dimension_id"], "dimension_id"),
        band_count=_require_int(mapping["band_count"], "band_count"),
        student_derivations=tuple(
            grouping_signal_student_derivation_from_dict(item)
            for item in student_data
        ),
        calculation_fingerprint=_require_str(
            mapping["calculation_fingerprint"],
            "calculation_fingerprint",
        ),
    )


def grouping_signal_derivation_snapshot_to_json_bytes(
    value: GroupingSignalDerivationSnapshot,
) -> bytes:
    """Serialize one derivation snapshot as strict canonical JSON bytes."""
    payload = _canonical_json_bytes(grouping_signal_derivation_snapshot_to_dict(value))
    if len(payload) > MAXIMUM_GROUPING_SIGNAL_DERIVATION_BYTES:
        raise GroupingSignalDerivationSerializationError(
            "grouping-signal derivation exceeds the bounded canonical JSON size."
        )
    return payload


def grouping_signal_derivation_snapshot_from_json_bytes(
    data: bytes,
) -> GroupingSignalDerivationSnapshot:
    """Load only strict canonical JSON bytes for one derivation snapshot."""
    if not isinstance(data, bytes):
        raise GroupingSignalDerivationSerializationError(
            "grouping-signal derivation JSON must be bytes."
        )
    if len(data) > MAXIMUM_GROUPING_SIGNAL_DERIVATION_BYTES:
        raise GroupingSignalDerivationSerializationError(
            "grouping-signal derivation exceeds the bounded canonical JSON size."
        )
    parsed = _parse_json_bytes(data)
    value = grouping_signal_derivation_snapshot_from_dict(parsed)
    if grouping_signal_derivation_snapshot_to_json_bytes(value) != data:
        raise GroupingSignalDerivationSerializationError(
            "grouping-signal derivation is not canonical JSON."
        )
    return value


def grouping_signal_derivation_sha256(
    value: GroupingSignalDerivationSnapshot,
) -> str:
    """Return SHA-256 over exact canonical derivation snapshot bytes."""
    return hashlib.sha256(
        grouping_signal_derivation_snapshot_to_json_bytes(value)
    ).hexdigest()


def grouping_signal_derivation_reference(
    value: GroupingSignalDerivationSnapshot,
) -> GroupingSignalDerivationReference:
    """Return the exact immutable digest-bound derivation reference."""
    snapshot = validate_grouping_signal_derivation_snapshot(value)
    return GroupingSignalDerivationReference(
        class_id=snapshot.class_id,
        derivation_id=snapshot.derivation_id,
        derivation_sha256=grouping_signal_derivation_sha256(snapshot),
    )


def grouping_signal_derivation_reference_to_dict(
    value: GroupingSignalDerivationReference,
) -> dict[str, object]:
    """Convert one exact derivation reference to JSON-native data."""
    if not isinstance(value, GroupingSignalDerivationReference):
        raise GroupingSignalDerivationValidationError(
            "value must be a GroupingSignalDerivationReference."
        )
    value.__post_init__()
    return {
        "class_id": value.class_id,
        "derivation_id": value.derivation_id,
        "derivation_sha256": value.derivation_sha256,
    }


def grouping_signal_derivation_reference_from_dict(
    data: object,
) -> GroupingSignalDerivationReference:
    """Parse one exact derivation-reference mapping."""
    mapping = _exact_mapping(
        data,
        _DERIVATION_REFERENCE_KEYS,
        "grouping-signal derivation reference",
    )
    return GroupingSignalDerivationReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        derivation_id=_require_str(mapping["derivation_id"], "derivation_id"),
        derivation_sha256=_require_str(
            mapping["derivation_sha256"],
            "derivation_sha256",
        ),
    )


def grouping_signal_roster_basis_to_dict(
    value: GroupingSignalRosterBasis,
) -> dict[str, object]:
    """Convert one exact roster membership basis to JSON-native data."""
    if not isinstance(value, GroupingSignalRosterBasis):
        raise GroupingSignalDerivationValidationError(
            "value must be a GroupingSignalRosterBasis."
        )
    value.__post_init__()
    return {
        "class_id": value.class_id,
        "student_ids": list(value.student_ids),
        "membership_sha256": value.membership_sha256,
    }


def grouping_signal_roster_basis_from_dict(data: object) -> GroupingSignalRosterBasis:
    """Parse one exact roster-basis mapping."""
    mapping = _exact_mapping(data, _ROSTER_BASIS_KEYS, "grouping-signal roster basis")
    return GroupingSignalRosterBasis(
        class_id=_require_str(mapping["class_id"], "class_id"),
        student_ids=tuple(
            _require_str(item, "student_id")
            for item in _require_list(mapping["student_ids"], "student_ids")
        ),
        membership_sha256=_require_str(
            mapping["membership_sha256"],
            "membership_sha256",
        ),
    )


def grouping_signal_student_derivation_to_dict(
    value: GroupingSignalStudentDerivation,
) -> dict[str, object]:
    """Convert one exact per-student derivation to JSON-native data."""
    if not isinstance(value, GroupingSignalStudentDerivation):
        raise GroupingSignalDerivationValidationError(
            "value must be a GroupingSignalStudentDerivation."
        )
    value.__post_init__()
    return {
        "student_id": value.student_id,
        "source_state": value.source_state,
        "disposition": value.disposition,
        "source_result": (
            academic_period_proficiency_result_reference_to_dict(
                value.source_result
            )
            if value.source_result is not None
            else None
        ),
        "proficiency_level_id": value.proficiency_level_id,
        "scale_position": value.scale_position,
        "band": value.band,
    }


def grouping_signal_student_derivation_from_dict(
    data: object,
) -> GroupingSignalStudentDerivation:
    """Parse one exact per-student derivation mapping."""
    mapping = _exact_mapping(
        data,
        _STUDENT_DERIVATION_KEYS,
        "grouping-signal student derivation",
    )
    reference_data = mapping["source_result"]
    reference = (
        academic_period_proficiency_result_reference_from_dict(reference_data)
        if reference_data is not None
        else None
    )
    return GroupingSignalStudentDerivation(
        student_id=_require_str(mapping["student_id"], "student_id"),
        source_state=cast(
            GroupingSignalDerivationSourceState,
            _require_str(mapping["source_state"], "source_state"),
        ),
        disposition=cast(
            GroupingSignalDerivationDisposition,
            _require_str(mapping["disposition"], "disposition"),
        ),
        source_result=reference,
        proficiency_level_id=_optional_str(
            mapping["proficiency_level_id"],
            "proficiency_level_id",
        ),
        scale_position=_optional_int(mapping["scale_position"], "scale_position"),
        band=_optional_int(mapping["band"], "band"),
    )


def _validate_exact_source_result(
    result: AcademicPeriodProficiencyResultSnapshot,
    student_id: str,
    policy: GroupingSignalDerivationPolicy,
) -> AcademicPeriodProficiencyResultReference:
    try:
        reference = academic_period_proficiency_result_reference(result)
    except ValueError as error:
        raise GroupingSignalDerivationValidationError(str(error)) from error
    basis = policy.academic_basis
    expected_scope = (
        policy.class_id,
        basis.target_period,
        student_id,
        basis.standard_id,
        basis.source_policy,
        basis.target_scale,
    )
    actual_scope = (
        result.class_id,
        result.target_period,
        result.student_id,
        result.standard_id,
        result.policy_reference,
        result.target_scale,
    )
    if actual_scope != expected_scope:
        raise GroupingSignalDerivationValidationError(
            "selected #35 result must match the exact selected #37 academic basis."
        )
    return reference


def _band_for_position(
    policy: GroupingSignalDerivationPolicy,
    scale_position: int,
) -> int:
    for definition in policy.band_definitions:
        if (
            definition.minimum_scale_position
            <= scale_position
            <= definition.maximum_scale_position
        ):
            return definition.band
    raise GroupingSignalDerivationValidationError(
        "source scale position is outside the selected #37 band partition."
    )


def _resolved_students(
    value: tuple[GroupingSignalResolvedStudentResult, ...],
    roster_basis: GroupingSignalRosterBasis,
) -> tuple[GroupingSignalResolvedStudentResult, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalDerivationValidationError(
            "resolved_students must be a tuple."
        )
    if any(not isinstance(item, GroupingSignalResolvedStudentResult) for item in value):
        raise GroupingSignalDerivationValidationError(
            "resolved_students contains an invalid resolved student."
        )
    for item in value:
        item.__post_init__()
    ids = tuple(item.student_id for item in value)
    if len(set(ids)) != len(ids):
        raise GroupingSignalDerivationValidationError(
            "resolved_students must not duplicate student_id."
        )
    if set(ids) != set(roster_basis.student_ids):
        raise GroupingSignalDerivationValidationError(
            "resolved_students must cover the exact roster membership once each."
        )
    return tuple(sorted(value, key=lambda item: item.student_id))


def _student_derivations(
    value: tuple[GroupingSignalStudentDerivation, ...],
    roster_basis: GroupingSignalRosterBasis,
    class_id: str,
    band_count: int | None,
) -> tuple[GroupingSignalStudentDerivation, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalDerivationValidationError(
            "student_derivations must be a tuple."
        )
    if any(not isinstance(item, GroupingSignalStudentDerivation) for item in value):
        raise GroupingSignalDerivationValidationError(
            "student_derivations contains an invalid student derivation."
        )
    for item in value:
        item.__post_init__()
    ids = tuple(item.student_id for item in value)
    if len(set(ids)) != len(ids):
        raise GroupingSignalDerivationValidationError(
            "student_derivations must not duplicate student_id."
        )
    if set(ids) != set(roster_basis.student_ids):
        raise GroupingSignalDerivationValidationError(
            "student_derivations must cover the exact roster membership once each."
        )
    ordered = tuple(sorted(value, key=lambda item: item.student_id))
    for item in ordered:
        if item.source_result is not None and item.source_result.class_id != class_id:
            raise GroupingSignalDerivationValidationError(
                "student source_result class_id must match derivation class_id."
            )
        if band_count is not None and item.band is not None and item.band > band_count:
            raise GroupingSignalDerivationValidationError(
                "student band must not exceed derivation band_count."
            )
    return ordered


def _roster_membership_sha256(
    class_id: str,
    student_ids: tuple[str, ...],
) -> str:
    payload = {
        "class_id": class_id,
        "student_ids": list(student_ids),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _source_state(value: object) -> GroupingSignalDerivationSourceState:
    if value not in _SOURCE_STATES:
        raise GroupingSignalDerivationValidationError(
            "unsupported grouping-signal derivation source_state."
        )
    return value


def _disposition(value: object) -> GroupingSignalDerivationDisposition:
    if value not in _DISPOSITIONS:
        raise GroupingSignalDerivationValidationError(
            "unsupported grouping-signal derivation disposition."
        )
    return value


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalDerivationValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GroupingSignalDerivationValidationError(str(error)) from error


def _derivation_id(value: object) -> str:
    identifier = _identifier(value, "derivation_id")
    if _DERIVATION_ID.fullmatch(identifier) is None:
        raise GroupingSignalDerivationValidationError(
            "derivation_id must be gsd_ followed by a lowercase SHA-256 digest."
        )
    return identifier


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GroupingSignalDerivationValidationError(
            f"{field_name} must be a lowercase SHA-256 hexadecimal digest."
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise GroupingSignalDerivationValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _parse_json_bytes(data: bytes) -> object:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GroupingSignalDerivationSerializationError(
            "grouping-signal derivation JSON must be valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_invalid_json_constant,
        )
    except GroupingSignalDerivationSerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise GroupingSignalDerivationSerializationError(
            "grouping-signal derivation JSON is invalid."
        ) from error


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GroupingSignalDerivationSerializationError(
                f"duplicate JSON key is not allowed: {key}."
            )
        result[key] = value
    return result


def _reject_invalid_json_constant(value: str) -> NoReturn:
    raise GroupingSignalDerivationSerializationError(
        f"invalid JSON constant is not allowed: {value}."
    )


def _exact_mapping(
    data: object,
    expected_keys: frozenset[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(data, dict):
        raise GroupingSignalDerivationValidationError(
            f"{label} must be a JSON object."
        )
    keys = frozenset(data)
    if keys != expected_keys:
        missing = sorted(expected_keys - keys)
        unknown = sorted(keys - expected_keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise GroupingSignalDerivationValidationError(
            f"{label} fields must match the exact schema ({'; '.join(details)})."
        )
    return cast(dict[str, object], data)


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise GroupingSignalDerivationValidationError(
            f"{field_name} must be a JSON array."
        )
    return value


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalDerivationValidationError(
            f"{field_name} must be a string."
        )
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise GroupingSignalDerivationValidationError(
            f"{field_name} must be an integer."
        )
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)
