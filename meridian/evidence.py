"""Immutable producer-neutral evidence inventory models."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Final, Literal, TypeAlias, TypeVar, cast

from pds_core.academic_work_registrations import (
    AcademicWorkRegistration,
    validate_academic_work_registration,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.publication_records import (
    PublicationKind,
    PublicationRecord,
    PublicationWithdrawal,
    validate_publication_record,
    validate_publication_withdrawal,
    validate_publication_withdrawal_relationship,
)
from pds_core.routing_models import (
    ModuleRecordRef,
    ModuleWorkRef,
    validate_module_work_ref,
)

__all__ = [
    "EvidenceEligibility",
    "EvidenceInventory",
    "EvidenceItem",
    "EvidenceModelError",
    "EvidenceProvenance",
    "EvidenceTarget",
    "EvidenceTargetIdentity",
    "EvidenceValidationError",
    "EligibilityStatus",
    "EvidenceValue",
    "NativeArtifact",
    "NativePointValue",
    "NativeProvenance",
    "NativeReference",
    "NativeScalar",
    "NativeScalarValue",
    "NativeScale",
    "NativeScaleLevel",
    "NativeScaledValue",
    "NativeStateValue",
    "NativeTimestamp",
    "ProjectionIdentity",
    "StudentSubject",
    "UNEVALUATED_ELIGIBILITY",
]

NativeScalar: TypeAlias = str | int | float | bool
EligibilityStatus: TypeAlias = Literal["unevaluated", "eligible", "ineligible"]

_CONTRACT_CODE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$"
)
_DISTRIBUTION_NAME: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$"
)
_OPAQUE_IDENTIFIER: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
)
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


class EvidenceModelError(ValueError):
    """Base error for Meridian evidence-model failures."""


class EvidenceValidationError(EvidenceModelError):
    """Raised when a Meridian evidence value violates its contract."""


def _core_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise EvidenceValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise EvidenceValidationError(str(error)) from error


def _contract_code(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _CONTRACT_CODE.fullmatch(value) is None:
        raise EvidenceValidationError(
            f"{field_name} must be a lowercase contract identifier."
        )
    return value


def _opaque_identifier(value: object, field_name: str) -> str:
    text = _single_line(value, field_name)
    if _OPAQUE_IDENTIFIER.fullmatch(text) is None:
        raise EvidenceValidationError(
            f"{field_name} must be an opaque identifier without path separators."
        )
    return text


def _single_line(
    value: object, field_name: str, *, allow_empty: bool = False
) -> str:
    if not isinstance(value, str):
        raise EvidenceValidationError(f"{field_name} must be a string.")
    if value != value.strip():
        raise EvidenceValidationError(
            f"{field_name} must not contain surrounding whitespace."
        )
    if not value and not allow_empty:
        raise EvidenceValidationError(f"{field_name} must not be empty.")
    if any(
        ord(character) < 32
        or ord(character) == 127
        or character in {"\u2028", "\u2029"}
        for character in value
    ):
        raise EvidenceValidationError(
            f"{field_name} must be a control-free single-line string."
        )
    return value


def _producer_native_text(value: object, field_name: str) -> str:
    """Validate nonempty producer-owned text without normalization."""
    if not isinstance(value, str):
        raise EvidenceValidationError(f"{field_name} must be a string.")
    if not value or not value.strip():
        raise EvidenceValidationError(
            f"{field_name} must contain non-whitespace text."
        )
    if "\x00" in value:
        raise EvidenceValidationError(f"{field_name} must not contain NUL.")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EvidenceValidationError(f"{field_name} must be a positive integer.")
    return value


def _aware_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise EvidenceValidationError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceValidationError(f"{field_name} must be timezone-aware.")
    return value


def _finite_number(value: object, field_name: str) -> int | float:
    if type(value) not in {int, float}:
        raise EvidenceValidationError(f"{field_name} must be a finite number.")
    number = cast(int | float, value)
    if type(number) is float and not math.isfinite(number):
        raise EvidenceValidationError(f"{field_name} must be a finite number.")
    return number


def _native_scalar(value: object, field_name: str) -> NativeScalar:
    if type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        number = value
        if not math.isfinite(number):
            raise EvidenceValidationError(f"{field_name} must be finite.")
        return number
    if type(value) is str:
        return _single_line(value, field_name)
    raise EvidenceValidationError(
        f"{field_name} must be a string, integer, finite float, or boolean."
    )


def _scalar_key(value: NativeScalar) -> tuple[str, NativeScalar]:
    return type(value).__name__, value


_T = TypeVar("_T")


def _typed_tuple(
    value: object,
    expected_type: type[_T],
    field_name: str,
) -> tuple[_T, ...]:
    if isinstance(value, (str, bytes)):
        raise EvidenceValidationError(f"{field_name} must be an iterable.")
    try:
        items = tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise EvidenceValidationError(f"{field_name} must be an iterable.") from error
    if any(not isinstance(item, expected_type) for item in items):
        raise EvidenceValidationError(
            f"{field_name} must contain only {expected_type.__name__} values."
        )
    return cast(tuple[_T, ...], items)


def _artifact_path(value: object) -> str:
    path = _single_line(value, "path")
    if "\\" in path:
        raise EvidenceValidationError("path must use forward slashes only.")
    windows = PureWindowsPath(path)
    if path.startswith("/") or windows.is_absolute() or windows.drive:
        raise EvidenceValidationError("path must be workspace-relative.")
    components = path.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise EvidenceValidationError(
            "path must not contain empty, dot, or traversal components."
        )
    if PurePosixPath(path).is_absolute():
        raise EvidenceValidationError("path must be workspace-relative.")
    return path


@dataclass(frozen=True, slots=True)
class ProjectionIdentity:
    """Exact identity of the adapter projection and producer reader."""

    projection_id: str
    projection_contract_version: str
    producer_reader_distribution: str
    producer_reader_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "projection_id",
            _contract_code(self.projection_id, "projection_id"),
        )
        object.__setattr__(
            self,
            "projection_contract_version",
            _opaque_identifier(
                self.projection_contract_version,
                "projection_contract_version",
            ),
        )
        distribution = _single_line(
            self.producer_reader_distribution,
            "producer_reader_distribution",
        )
        if _DISTRIBUTION_NAME.fullmatch(distribution) is None:
            raise EvidenceValidationError(
                "producer_reader_distribution must be a valid distribution name."
            )
        object.__setattr__(self, "producer_reader_distribution", distribution)
        object.__setattr__(
            self,
            "producer_reader_version",
            _single_line(self.producer_reader_version, "producer_reader_version"),
        )


@dataclass(frozen=True, slots=True)
class NativeReference:
    """One ordered reference into a producer-owned native record hierarchy."""

    kind: str
    identifier: str | None = None
    sequence: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _contract_code(self.kind, "kind"))
        if self.identifier is not None:
            object.__setattr__(
                self,
                "identifier",
                _producer_native_text(self.identifier, "identifier"),
            )
        if self.sequence is not None:
            object.__setattr__(
                self,
                "sequence",
                _positive_int(self.sequence, "sequence"),
            )
        if self.identifier is None and self.sequence is None:
            raise EvidenceValidationError(
                "a native reference requires identifier or sequence."
            )


@dataclass(frozen=True, slots=True)
class NativeArtifact:
    """One privacy-safe producer artifact reference."""

    kind: str
    path: str | None = None
    digest_algorithm: str | None = None
    digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _contract_code(self.kind, "kind"))
        if self.path is not None:
            object.__setattr__(self, "path", _artifact_path(self.path))
        if (self.digest_algorithm is None) != (self.digest is None):
            raise EvidenceValidationError(
                "digest_algorithm and digest must be supplied together."
            )
        if self.digest_algorithm is not None:
            algorithm = _contract_code(
                self.digest_algorithm,
                "digest_algorithm",
            )
            digest = _single_line(self.digest, "digest")
            if algorithm == "sha256" and _SHA256.fullmatch(digest) is None:
                raise EvidenceValidationError(
                    "a sha256 digest must contain 64 lowercase hexadecimal characters."
                )
            object.__setattr__(self, "digest_algorithm", algorithm)
            object.__setattr__(self, "digest", digest)
        if self.path is None and self.digest is None:
            raise EvidenceValidationError(
                "a native artifact requires a path or digest."
            )


@dataclass(frozen=True, slots=True)
class NativeTimestamp:
    """One producer-native timestamp with an explicit semantic kind."""

    kind: str
    value: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _contract_code(self.kind, "kind"))
        object.__setattr__(
            self,
            "value",
            _aware_datetime(self.value, "value"),
        )


@dataclass(frozen=True, slots=True)
class NativeProvenance:
    """Ordered producer-native references, artifacts, and timestamps."""

    references: tuple[NativeReference, ...]
    artifacts: tuple[NativeArtifact, ...] = ()
    timestamps: tuple[NativeTimestamp, ...] = ()

    def __post_init__(self) -> None:
        references = _typed_tuple(
            self.references, NativeReference, "references"
        )
        if not references:
            raise EvidenceValidationError("references must not be empty.")
        object.__setattr__(self, "references", references)
        object.__setattr__(
            self,
            "artifacts",
            _typed_tuple(self.artifacts, NativeArtifact, "artifacts"),
        )
        object.__setattr__(
            self,
            "timestamps",
            _typed_tuple(self.timestamps, NativeTimestamp, "timestamps"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    """Exact Core and producer-native basis for one projected evidence item."""

    publication: PublicationRecord
    registration: AcademicWorkRegistration | None
    withdrawal: PublicationWithdrawal | None
    projection: ProjectionIdentity
    native: NativeProvenance

    def __post_init__(self) -> None:
        try:
            publication = validate_publication_record(self.publication)
        except ValueError as error:
            raise EvidenceValidationError(f"publication is invalid: {error}") from error
        registration: AcademicWorkRegistration | None = None
        if self.registration is not None:
            try:
                registration = validate_academic_work_registration(self.registration)
            except ValueError as error:
                raise EvidenceValidationError(
                    f"registration is invalid: {error}"
                ) from error
        withdrawal: PublicationWithdrawal | None = None
        if self.withdrawal is not None:
            try:
                withdrawal = validate_publication_withdrawal(self.withdrawal)
                validate_publication_withdrawal_relationship(publication, withdrawal)
            except ValueError as error:
                raise EvidenceValidationError(
                    f"withdrawal is invalid for publication: {error}"
                ) from error
        if publication.publication_kind == "academic_result_set":
            if registration is None:
                raise EvidenceValidationError(
                    "academic evidence requires its referenced registration."
                )
            if registration.work != publication.work:
                raise EvidenceValidationError(
                    "registration work must match publication work."
                )
            if (
                publication.academic_work_registration_revision
                != registration.registration_revision
            ):
                raise EvidenceValidationError(
                    "registration revision must match the publication reference."
                )
        elif registration is not None:
            raise EvidenceValidationError(
                "intervention evidence must not carry an Academic Work Registration."
            )
        if not isinstance(self.projection, ProjectionIdentity):
            raise EvidenceValidationError(
                "projection must be a ProjectionIdentity."
            )
        if not isinstance(self.native, NativeProvenance):
            raise EvidenceValidationError("native must be NativeProvenance.")
        object.__setattr__(self, "publication", publication)
        object.__setattr__(self, "registration", registration)
        object.__setattr__(self, "withdrawal", withdrawal)

    @property
    def producer_module_id(self) -> str:
        """Return the producer module from the exact Core work reference."""
        return self.publication.work.module_id

    @property
    def work(self) -> ModuleWorkRef:
        """Return the exact Core work reference."""
        return self.publication.work

    @property
    def publication_kind(self) -> PublicationKind:
        """Return the exact Core publication kind."""
        return self.publication.publication_kind

    @property
    def publication_id(self) -> str:
        """Return the exact Core Publication Record ID."""
        return self.publication.publication_id

    @property
    def core_publication_schema_version(self) -> str:
        """Return the exact Core Publication Record schema version."""
        return self.publication.schema_version

    @property
    def record_set_id(self) -> str:
        """Return the producer-owned record-set identity."""
        return self.publication.record_set_id

    @property
    def record_set_revision(self) -> int:
        """Return the exact producer record-set revision."""
        return self.publication.record_set_revision

    @property
    def manifest_contract_version(self) -> str:
        """Return the exact producer manifest contract version."""
        return self.publication.manifest_contract_version

    @property
    def manifest_digest_algorithm(self) -> str:
        """Return the exact manifest digest algorithm."""
        return self.publication.manifest_digest_algorithm

    @property
    def manifest_digest(self) -> str:
        """Return the exact Core-bound manifest digest."""
        return self.publication.manifest_digest

    @property
    def source_record(self) -> ModuleRecordRef | None:
        """Return the exact producer source-record reference, when present."""
        return self.publication.source_record

    @property
    def producer_contract_version(self) -> str | None:
        """Return the exact registered producer contract version, when present."""
        if self.registration is None:
            return None
        return self.registration.producer_contract_version


@dataclass(frozen=True, slots=True)
class StudentSubject:
    """Privacy-minimal student identity for one evidence item."""

    student_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "student_id",
            _core_identifier(self.student_id, "student_id"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceTargetIdentity:
    """One producer-native target identity."""

    target_kind: str
    target_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_kind",
            _contract_code(self.target_kind, "target_kind"),
        )
        if self.target_id is not None:
            object.__setattr__(
                self,
                "target_id",
                _producer_native_text(self.target_id, "target_id"),
            )


@dataclass(frozen=True, slots=True)
class EvidenceTarget:
    """Producer-native target plus alignment context."""

    target_kind: str
    target_id: str | None = None
    parent_target: EvidenceTargetIdentity | None = None
    standard_ids: tuple[str, ...] = ()
    sequence: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_kind",
            _contract_code(self.target_kind, "target_kind"),
        )
        if self.target_id is not None:
            object.__setattr__(
                self,
                "target_id",
                _producer_native_text(self.target_id, "target_id"),
            )
        if self.parent_target is not None and not isinstance(
            self.parent_target, EvidenceTargetIdentity
        ):
            raise EvidenceValidationError(
                "parent_target must be an EvidenceTargetIdentity."
            )
        try:
            standard_ids = tuple(self.standard_ids)
        except TypeError as error:
            raise EvidenceValidationError(
                "standard_ids must be an iterable of strings."
            ) from error
        validated_standards = tuple(
            _producer_native_text(value, "standard_id") for value in standard_ids
        )
        if len(set(validated_standards)) != len(validated_standards):
            raise EvidenceValidationError("standard_ids must not contain duplicates.")
        object.__setattr__(self, "standard_ids", validated_standards)
        if self.sequence is not None:
            object.__setattr__(
                self,
                "sequence",
                _positive_int(self.sequence, "sequence"),
            )


@dataclass(frozen=True, slots=True, eq=False)
class NativeScaleLevel:
    """One exact producer-native scale level."""

    value: NativeScalar
    label: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _native_scalar(self.value, "value"))
        if self.label is not None:
            object.__setattr__(
                self, "label", _producer_native_text(self.label, "label")
            )
        if self.description is not None:
            object.__setattr__(
                self,
                "description",
                _producer_native_text(self.description, "description"),
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NativeScaleLevel):
            return False
        return (
            _scalar_key(self.value) == _scalar_key(other.value)
            and self.label == other.label
            and self.description == other.description
        )

    def __hash__(self) -> int:
        return hash((_scalar_key(self.value), self.label, self.description))


@dataclass(frozen=True, slots=True)
class NativeScale:
    """Exact identity and ordered levels of a producer-owned scale."""

    scale_id: str
    levels: tuple[NativeScaleLevel, ...]
    contract_version: str | None = None
    order_is_meaningful: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scale_id",
            _producer_native_text(self.scale_id, "scale_id"),
        )
        if self.contract_version is not None:
            object.__setattr__(
                self,
                "contract_version",
                _opaque_identifier(self.contract_version, "contract_version"),
            )
        if not isinstance(self.order_is_meaningful, bool):
            raise EvidenceValidationError("order_is_meaningful must be boolean.")
        levels = _typed_tuple(self.levels, NativeScaleLevel, "levels")
        if not levels:
            raise EvidenceValidationError("levels must not be empty.")
        keys = tuple(_scalar_key(level.value) for level in levels)
        if len(set(keys)) != len(keys):
            raise EvidenceValidationError(
                "scale level values must be unique by exact scalar type and value."
            )
        object.__setattr__(self, "levels", levels)


@dataclass(frozen=True, slots=True, eq=False)
class NativeScalarValue:
    """One exact producer-native scalar value."""

    value: NativeScalar

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _native_scalar(self.value, "value"))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NativeScalarValue):
            return False
        return _scalar_key(self.value) == _scalar_key(other.value)

    def __hash__(self) -> int:
        return hash(_scalar_key(self.value))


@dataclass(frozen=True, slots=True, eq=False)
class NativePointValue:
    """Producer-native earned and possible points without normalization."""

    earned: int | float
    possible: int | float

    def __post_init__(self) -> None:
        earned = _finite_number(self.earned, "earned")
        possible = _finite_number(self.possible, "possible")
        if possible <= 0:
            raise EvidenceValidationError("possible must be greater than zero.")
        object.__setattr__(self, "earned", earned)
        object.__setattr__(self, "possible", possible)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NativePointValue):
            return False
        return (
            _scalar_key(self.earned) == _scalar_key(other.earned)
            and _scalar_key(self.possible) == _scalar_key(other.possible)
        )

    def __hash__(self) -> int:
        return hash((_scalar_key(self.earned), _scalar_key(self.possible)))


@dataclass(frozen=True, slots=True, eq=False)
class NativeScaledValue:
    """One exact value on one exact producer-owned native scale."""

    value: NativeScalar
    scale: NativeScale

    def __post_init__(self) -> None:
        value = _native_scalar(self.value, "value")
        if not isinstance(self.scale, NativeScale):
            raise EvidenceValidationError("scale must be a NativeScale.")
        if _scalar_key(value) not in {
            _scalar_key(level.value) for level in self.scale.levels
        }:
            raise EvidenceValidationError(
                "value must exactly match one level on the native scale."
            )
        object.__setattr__(self, "value", value)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NativeScaledValue):
            return False
        return (
            _scalar_key(self.value) == _scalar_key(other.value)
            and self.scale == other.scale
        )

    def __hash__(self) -> int:
        return hash((_scalar_key(self.value), self.scale))


@dataclass(frozen=True, slots=True)
class NativeStateValue:
    """One explicit producer-native non-score state or disposition."""

    code: str
    label: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _contract_code(self.code, "code"))
        if self.label is not None:
            object.__setattr__(self, "label", _single_line(self.label, "label"))
        if self.description is not None:
            object.__setattr__(
                self,
                "description",
                _single_line(self.description, "description"),
            )


EvidenceValue: TypeAlias = (
    NativeScalarValue | NativePointValue | NativeScaledValue | NativeStateValue
)


def _evidence_value(value: object) -> EvidenceValue:
    if not isinstance(
        value,
        (NativeScalarValue, NativePointValue, NativeScaledValue, NativeStateValue),
    ):
        raise EvidenceValidationError(
            "value must be a supported typed evidence-value variant."
        )
    return value


@dataclass(frozen=True, slots=True)
class EvidenceEligibility:
    """One explicit evidence-eligibility decision, separate from selection."""

    status: EligibilityStatus
    policy_id: str | None = None
    policy_version: str | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"unevaluated", "eligible", "ineligible"}:
            raise EvidenceValidationError("status is not a valid eligibility status.")
        policy_id = self.policy_id
        policy_version = self.policy_version
        if policy_id is not None:
            policy_id = _opaque_identifier(policy_id, "policy_id")
        if policy_version is not None:
            policy_version = _opaque_identifier(policy_version, "policy_version")
        try:
            reasons = tuple(self.reason_codes)
        except TypeError as error:
            raise EvidenceValidationError(
                "reason_codes must be an iterable of strings."
            ) from error
        validated_reasons = tuple(
            _contract_code(reason, "reason_code") for reason in reasons
        )
        if len(set(validated_reasons)) != len(validated_reasons):
            raise EvidenceValidationError(
                "reason_codes must not contain duplicates."
            )
        if self.status == "unevaluated":
            if policy_id is not None or policy_version is not None or validated_reasons:
                raise EvidenceValidationError(
                    "unevaluated eligibility must not claim policy or reasons."
                )
        elif self.status == "eligible":
            if policy_id is None or policy_version is None:
                raise EvidenceValidationError(
                    "eligible evidence requires policy identity and version."
                )
            if validated_reasons:
                raise EvidenceValidationError(
                    "eligible evidence must not carry ineligibility reasons."
                )
        else:
            if policy_id is None or policy_version is None:
                raise EvidenceValidationError(
                    "ineligible evidence requires policy identity and version."
                )
            if not validated_reasons:
                raise EvidenceValidationError(
                    "ineligible evidence requires at least one reason code."
                )
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "reason_codes", validated_reasons)

    @classmethod
    def unevaluated(cls) -> EvidenceEligibility:
        """Return an eligibility value for evidence not yet evaluated by policy."""
        return cls(status="unevaluated")

    @classmethod
    def eligible(
        cls, *, policy_id: str, policy_version: str
    ) -> EvidenceEligibility:
        """Return an eligible decision under one exact policy version."""
        return cls(
            status="eligible",
            policy_id=policy_id,
            policy_version=policy_version,
        )

    @classmethod
    def ineligible(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        reason_codes: Iterable[str],
    ) -> EvidenceEligibility:
        """Return an ineligible decision with explicit ordered reasons."""
        return cls(
            status="ineligible",
            policy_id=policy_id,
            policy_version=policy_version,
            reason_codes=tuple(reason_codes),
        )


UNEVALUATED_ELIGIBILITY: Final[EvidenceEligibility] = EvidenceEligibility.unevaluated()


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One immutable producer-native evidence item."""

    item_id: str
    subject: StudentSubject
    target: EvidenceTarget
    result_kind: str
    value: EvidenceValue
    provenance: EvidenceProvenance
    eligibility: EvidenceEligibility = UNEVALUATED_ELIGIBILITY

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _core_identifier(self.item_id, "item_id"))
        if not isinstance(self.subject, StudentSubject):
            raise EvidenceValidationError("subject must be a StudentSubject.")
        if not isinstance(self.target, EvidenceTarget):
            raise EvidenceValidationError("target must be an EvidenceTarget.")
        object.__setattr__(
            self,
            "result_kind",
            _contract_code(self.result_kind, "result_kind"),
        )
        object.__setattr__(self, "value", _evidence_value(self.value))
        if not isinstance(self.provenance, EvidenceProvenance):
            raise EvidenceValidationError(
                "provenance must be an EvidenceProvenance."
            )
        if not isinstance(self.eligibility, EvidenceEligibility):
            raise EvidenceValidationError(
                "eligibility must be an EvidenceEligibility."
            )


@dataclass(frozen=True, slots=True)
class EvidenceInventory:
    """Ordered immutable collection of distinct evidence items."""

    items: tuple[EvidenceItem, ...]

    def __post_init__(self) -> None:
        items = _typed_tuple(self.items, EvidenceItem, "items")
        item_ids = tuple(item.item_id for item in items)
        if len(set(item_ids)) != len(item_ids):
            raise EvidenceValidationError("item IDs must be unique.")
        object.__setattr__(self, "items", items)

    def for_student(self, student_id: str) -> tuple[EvidenceItem, ...]:
        """Return items for one exact student while preserving inventory order."""
        validated = _core_identifier(student_id, "student_id")
        return tuple(
            item for item in self.items if item.subject.student_id == validated
        )

    def for_work(self, work: ModuleWorkRef) -> tuple[EvidenceItem, ...]:
        """Return items for one exact Core work reference."""
        if not isinstance(work, ModuleWorkRef):
            raise EvidenceValidationError("work must be a ModuleWorkRef.")
        try:
            validated = validate_module_work_ref(work)
        except ValueError as error:
            raise EvidenceValidationError(f"work is invalid: {error}") from error
        return tuple(
            item for item in self.items if item.provenance.work == validated
        )

    def for_publication(self, publication_id: str) -> tuple[EvidenceItem, ...]:
        """Return items from one exact Core Publication Record."""
        validated = _core_identifier(publication_id, "publication_id")
        return tuple(
            item
            for item in self.items
            if item.provenance.publication_id == validated
        )

    def for_target_kind(self, target_kind: str) -> tuple[EvidenceItem, ...]:
        """Return items with one exact producer-native target kind."""
        validated = _contract_code(target_kind, "target_kind")
        return tuple(
            item for item in self.items if item.target.target_kind == validated
        )

    def for_standard(self, standard_id: str) -> tuple[EvidenceItem, ...]:
        """Return aligned items for one exact standard ID."""
        validated = _producer_native_text(standard_id, "standard_id")
        return tuple(
            item for item in self.items if validated in item.target.standard_ids
        )

    def for_eligibility(
        self, status: EligibilityStatus
    ) -> tuple[EvidenceItem, ...]:
        """Return items with one exact eligibility status."""
        if status not in {"unevaluated", "eligible", "ineligible"}:
            raise EvidenceValidationError("status is not a valid eligibility status.")
        return tuple(
            item for item in self.items if item.eligibility.status == status
        )
