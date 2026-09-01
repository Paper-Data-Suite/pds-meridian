"""Pure deterministic grouping-signal preview and diagnostic contracts.

This module owns immutable #39 preview-domain state only. It performs no
workspace reads, persistence, teacher review, Core export, or Concord work.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final, Literal, NoReturn, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
    academic_period_proficiency_result_reference_from_dict,
    academic_period_proficiency_result_reference_to_dict,
)
from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationDisposition,
    GroupingSignalDerivationReference,
    GroupingSignalDerivationSnapshot,
    GroupingSignalDerivationSourceState,
    GroupingSignalRosterBasis,
    GroupingSignalStudentDerivation,
    grouping_signal_derivation_reference,
    grouping_signal_derivation_reference_from_dict,
    grouping_signal_derivation_reference_to_dict,
    grouping_signal_roster_basis_from_dict,
    grouping_signal_roster_basis_to_dict,
    validate_grouping_signal_derivation_snapshot,
)
from meridian.grouping_signal_policy import (
    GroupingSignalAcademicBasis,
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicy,
    GroupingSignalDerivationPolicyReference,
    GroupingSignalResultHandling,
    GroupingSignalTieHandling,
    grouping_signal_academic_basis_from_dict,
    grouping_signal_academic_basis_to_dict,
    grouping_signal_band_definition_from_dict,
    grouping_signal_band_definition_to_dict,
    grouping_signal_derivation_policy_reference,
    grouping_signal_derivation_policy_reference_from_dict,
    grouping_signal_derivation_policy_reference_to_dict,
    validate_grouping_signal_derivation_policy_against_scale,
)
from meridian.proficiency_mapping import ProficiencyScale

GROUPING_SIGNAL_PREVIEW_SCHEMA_VERSION: Final = "1"
GROUPING_SIGNAL_PREVIEW_RECORD_TYPE: Final = "meridian_grouping_signal_preview"
GROUPING_SIGNAL_PREVIEW_ALGORITHM_VERSION: Final = "grouping_signal_preview_v1"
GROUPING_SIGNAL_PREVIEW_ID_PREFIX: Final = "gsp_"
GROUPING_SIGNAL_DIAGNOSTIC_ID_PREFIX: Final = "gpd_"
MAXIMUM_GROUPING_SIGNAL_PREVIEW_BYTES: Final = 8 * 1024 * 1024

PreviewCurrentnessState: TypeAlias = Literal["current", "stale", "blocked"]
PreviewSeverity: TypeAlias = Literal["informational", "warning", "blocking"]
PreviewDiagnosticCode: TypeAlias = Literal[
    "derivation_not_current",
    "current_generation_blocked",
    "zero_contributors",
    "missing_noncontributors",
    "insufficient_noncontributors",
    "partial_coverage",
    "empty_bands",
    "single_occupied_band",
]

_SHA = re.compile(r"^[0-9a-f]{64}$")
_PID = re.compile(r"^gsp_[0-9a-f]{64}$")
_DID = re.compile(r"^gpd_[0-9a-f]{64}$")
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SEVERITY: Final[dict[PreviewDiagnosticCode, PreviewSeverity]] = {
    "derivation_not_current": "blocking",
    "current_generation_blocked": "blocking",
    "zero_contributors": "blocking",
    "missing_noncontributors": "warning",
    "insufficient_noncontributors": "warning",
    "partial_coverage": "warning",
    "empty_bands": "warning",
    "single_occupied_band": "warning",
}
_SEVERITY_ORDER: Final[dict[PreviewSeverity, int]] = {
    "blocking": 0,
    "warning": 1,
    "informational": 2,
}


class GroupingSignalPreviewError(ValueError):
    """Base #39 preview-domain error."""


class GroupingSignalPreviewValidationError(GroupingSignalPreviewError):
    """Preview model validation failed."""


class GroupingSignalPreviewSerializationError(GroupingSignalPreviewError):
    """Preview canonical JSON validation failed."""


@dataclass(frozen=True, slots=True)
class GroupingSignalPreviewCurrentness:
    state: PreviewCurrentnessState
    reason_codes: tuple[str, ...]
    current_derivation_reference: GroupingSignalDerivationReference | None

    def __post_init__(self) -> None:
        if self.state not in ("current", "stale", "blocked"):
            raise GroupingSignalPreviewValidationError("invalid currentness state.")
        reasons = _codes(self.reason_codes, "reason_codes")
        ref = self.current_derivation_reference
        if ref is not None:
            if not isinstance(ref, GroupingSignalDerivationReference):
                raise GroupingSignalPreviewValidationError(
                    "current_derivation_reference must be an exact #38 reference."
                )
            ref.__post_init__()
        if self.state == "current" and (reasons or ref is None):
            raise GroupingSignalPreviewValidationError(
                "current state requires one reference and no reasons."
            )
        if self.state == "stale" and (not reasons or ref is None):
            raise GroupingSignalPreviewValidationError(
                "stale state requires reasons and a current candidate reference."
            )
        if self.state == "blocked" and (not reasons or ref is not None):
            raise GroupingSignalPreviewValidationError(
                "blocked state requires reasons and no candidate reference."
            )
        object.__setattr__(self, "reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class GroupingSignalPreviewStudentRow:
    student_id: str
    source_state: str
    disposition: str
    source_result: AcademicPeriodProficiencyResultReference | None
    proficiency_level_id: str | None
    scale_position: int | None
    band: int | None

    def __post_init__(self) -> None:
        try:
            source = GroupingSignalStudentDerivation(
                self.student_id,
                cast(GroupingSignalDerivationSourceState, self.source_state),
                cast(GroupingSignalDerivationDisposition, self.disposition),
                self.source_result,
                self.proficiency_level_id,
                self.scale_position,
                self.band,
            )
        except ValueError as error:
            raise GroupingSignalPreviewValidationError(str(error)) from error
        for name in (
            "student_id",
            "source_state",
            "disposition",
            "source_result",
            "proficiency_level_id",
            "scale_position",
            "band",
        ):
            object.__setattr__(self, name, getattr(source, name))


@dataclass(frozen=True, slots=True)
class GroupingSignalPreviewBandSummary:
    band: int
    minimum_scale_position: int
    maximum_scale_position: int
    proficiency_level_ids: tuple[str, ...]
    student_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        band = _positive(self.band, "band")
        low = _positive(self.minimum_scale_position, "minimum_scale_position")
        high = _positive(self.maximum_scale_position, "maximum_scale_position")
        if low > high:
            raise GroupingSignalPreviewValidationError("invalid band range.")
        levels = _ids(self.proficiency_level_ids, "proficiency_level_ids", False)
        students = _ids(self.student_ids, "student_ids", True)
        object.__setattr__(self, "band", band)
        object.__setattr__(self, "minimum_scale_position", low)
        object.__setattr__(self, "maximum_scale_position", high)
        object.__setattr__(self, "proficiency_level_ids", levels)
        object.__setattr__(self, "student_ids", students)

    @property
    def student_count(self) -> int:
        return len(self.student_ids)


@dataclass(frozen=True, slots=True)
class GroupingSignalPreviewTieGroup:
    proficiency_level_id: str
    scale_position: int
    band: int
    student_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "proficiency_level_id", _id(self.proficiency_level_id, "level_id")
        )
        object.__setattr__(
            self,
            "scale_position",
            _positive(self.scale_position, "scale_position"),
        )
        object.__setattr__(self, "band", _positive(self.band, "band"))
        students = _ids(self.student_ids, "student_ids", True)
        if len(students) < 2:
            raise GroupingSignalPreviewValidationError(
                "tie group requires at least two students."
            )
        object.__setattr__(self, "student_ids", students)


@dataclass(frozen=True, slots=True)
class GroupingSignalPreviewCoverage:
    roster_student_count: int
    contributing_student_count: int
    noncontributing_student_count: int
    missing_noncontributor_count: int
    insufficient_noncontributor_count: int
    occupied_band_count: int
    empty_band_count: int

    def __post_init__(self) -> None:
        names = (
            "roster_student_count",
            "contributing_student_count",
            "noncontributing_student_count",
            "missing_noncontributor_count",
            "insufficient_noncontributor_count",
            "occupied_band_count",
            "empty_band_count",
        )
        values = {name: _nonnegative(getattr(self, name), name) for name in names}
        if (
            values["contributing_student_count"]
            + values["noncontributing_student_count"]
            != values["roster_student_count"]
        ):
            raise GroupingSignalPreviewValidationError("coverage totals disagree.")
        if (
            values["missing_noncontributor_count"]
            + values["insufficient_noncontributor_count"]
            != values["noncontributing_student_count"]
        ):
            raise GroupingSignalPreviewValidationError(
                "noncontributor reason totals disagree."
            )
        for name, value in values.items():
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class GroupingSignalPreviewDiagnostic:
    diagnostic_id: str
    code: PreviewDiagnosticCode
    severity: PreviewSeverity
    student_ids: tuple[str, ...] = ()
    bands: tuple[int, ...] = ()
    details: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        code = _diagnostic_code(self.code)
        severity = _SEVERITY[code]
        if self.severity != severity:
            raise GroupingSignalPreviewValidationError("diagnostic severity mismatch.")
        students = _ids(self.student_ids, "student_ids", True)
        bands = _positive_tuple(self.bands, "bands")
        details = _codes(self.details, "details")
        expected = grouping_signal_preview_diagnostic_id(
            code, severity, students, bands, details
        )
        if not isinstance(self.diagnostic_id, str) or not _DID.fullmatch(
            self.diagnostic_id
        ):
            raise GroupingSignalPreviewValidationError("invalid diagnostic_id.")
        if self.diagnostic_id != expected:
            raise GroupingSignalPreviewValidationError(
                "diagnostic_id does not bind diagnostic semantics."
            )
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "student_ids", students)
        object.__setattr__(self, "bands", bands)
        object.__setattr__(self, "details", details)


@dataclass(frozen=True, slots=True)
class GroupingSignalPreviewSnapshot:
    schema_version: str
    record_type: str
    preview_id: str
    preview_algorithm_version: str
    derivation_reference: GroupingSignalDerivationReference
    derivation_algorithm_version: str
    derivation_calculation_fingerprint: str
    policy_reference: GroupingSignalDerivationPolicyReference
    policy_title: str
    academic_basis: GroupingSignalAcademicBasis
    roster_basis: GroupingSignalRosterBasis
    dimension_id: str
    band_count: int
    band_definitions: tuple[GroupingSignalBandDefinition, ...]
    tie_handling: GroupingSignalTieHandling
    missing_result_handling: GroupingSignalResultHandling
    insufficient_result_handling: GroupingSignalResultHandling
    coverage: GroupingSignalPreviewCoverage
    band_summaries: tuple[GroupingSignalPreviewBandSummary, ...]
    student_rows: tuple[GroupingSignalPreviewStudentRow, ...]
    tie_groups: tuple[GroupingSignalPreviewTieGroup, ...]
    currentness: GroupingSignalPreviewCurrentness
    diagnostics: tuple[GroupingSignalPreviewDiagnostic, ...]
    preview_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema_version != GROUPING_SIGNAL_PREVIEW_SCHEMA_VERSION:
            raise GroupingSignalPreviewValidationError("unsupported preview schema.")
        if self.record_type != GROUPING_SIGNAL_PREVIEW_RECORD_TYPE:
            raise GroupingSignalPreviewValidationError("invalid preview record_type.")
        if self.preview_algorithm_version != GROUPING_SIGNAL_PREVIEW_ALGORITHM_VERSION:
            raise GroupingSignalPreviewValidationError("unsupported preview algorithm.")
        if not isinstance(self.derivation_reference, GroupingSignalDerivationReference):
            raise GroupingSignalPreviewValidationError("invalid derivation reference.")
        self.derivation_reference.__post_init__()
        if not isinstance(
            self.policy_reference,
            GroupingSignalDerivationPolicyReference,
        ):
            raise GroupingSignalPreviewValidationError("invalid policy reference.")
        self.policy_reference.__post_init__()
        class_id = self.derivation_reference.class_id
        if self.policy_reference.class_id != class_id:
            raise GroupingSignalPreviewValidationError("preview class scope disagrees.")
        if not isinstance(self.academic_basis, GroupingSignalAcademicBasis):
            raise GroupingSignalPreviewValidationError("invalid academic basis.")
        grouping_signal_academic_basis_to_dict(self.academic_basis)
        if self.academic_basis.class_id != class_id:
            raise GroupingSignalPreviewValidationError(
                "academic basis class disagrees."
            )
        if not isinstance(self.roster_basis, GroupingSignalRosterBasis):
            raise GroupingSignalPreviewValidationError("invalid roster basis.")
        self.roster_basis.__post_init__()
        if self.roster_basis.class_id != class_id:
            raise GroupingSignalPreviewValidationError("roster class disagrees.")
        title = _text(self.policy_title, "policy_title", 256)
        dimension = _id(self.dimension_id, "dimension_id")
        band_count = _positive(self.band_count, "band_count")
        if band_count < 2:
            raise GroupingSignalPreviewValidationError("band_count must be >= 2.")
        definitions = _definitions(self.band_definitions, band_count)
        rows = _rows(self.student_rows, self.roster_basis, band_count)
        summaries = _summaries(self.band_summaries, definitions, rows)
        coverage = _check_coverage(self.coverage, rows, summaries, band_count)
        ties = _check_ties(self.tie_groups, rows)
        if not isinstance(self.currentness, GroupingSignalPreviewCurrentness):
            raise GroupingSignalPreviewValidationError("invalid currentness.")
        self.currentness.__post_init__()
        _check_currentness(self.currentness, self.derivation_reference)
        diagnostics = _ordered_diagnostics(self.diagnostics)
        expected_diagnostics = _derive_diagnostics(
            self.currentness, coverage, rows, summaries
        )
        if diagnostics != expected_diagnostics:
            raise GroupingSignalPreviewValidationError(
                "diagnostics do not match deterministic preview state."
            )
        derivation_algorithm = _text(
            self.derivation_algorithm_version, "derivation_algorithm_version", 128
        )
        derivation_fingerprint = _sha(
            self.derivation_calculation_fingerprint,
            "derivation_calculation_fingerprint",
        )
        preview_fingerprint = _sha(self.preview_fingerprint, "preview_fingerprint")
        object.__setattr__(self, "policy_title", title)
        object.__setattr__(self, "dimension_id", dimension)
        object.__setattr__(self, "band_count", band_count)
        object.__setattr__(self, "band_definitions", definitions)
        object.__setattr__(self, "student_rows", rows)
        object.__setattr__(self, "band_summaries", summaries)
        object.__setattr__(self, "coverage", coverage)
        object.__setattr__(self, "tie_groups", ties)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "derivation_algorithm_version", derivation_algorithm)
        object.__setattr__(
            self, "derivation_calculation_fingerprint", derivation_fingerprint
        )
        expected_fp = grouping_signal_preview_fingerprint(self)
        if preview_fingerprint != expected_fp:
            raise GroupingSignalPreviewValidationError(
                "preview_fingerprint does not bind preview semantics."
            )
        if not isinstance(self.preview_id, str) or not _PID.fullmatch(self.preview_id):
            raise GroupingSignalPreviewValidationError("invalid preview_id.")
        if self.preview_id != grouping_signal_preview_id(preview_fingerprint):
            raise GroupingSignalPreviewValidationError(
                "preview_id is not content-addressed from preview_fingerprint."
            )
        object.__setattr__(self, "preview_fingerprint", preview_fingerprint)


@dataclass(frozen=True, slots=True)
class GroupingSignalPreviewReference:
    class_id: str
    preview_id: str
    preview_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _id(self.class_id, "class_id"))
        if not isinstance(self.preview_id, str) or not _PID.fullmatch(self.preview_id):
            raise GroupingSignalPreviewValidationError("invalid preview_id.")
        object.__setattr__(
            self, "preview_sha256", _sha(self.preview_sha256, "preview_sha256")
        )


def build_grouping_signal_preview_snapshot(
    derivation: GroupingSignalDerivationSnapshot,
    policy: GroupingSignalDerivationPolicy,
    target_scale: ProficiencyScale,
    currentness: GroupingSignalPreviewCurrentness,
) -> GroupingSignalPreviewSnapshot:
    """Build one deterministic preview from already-resolved immutable inputs."""
    try:
        derivation = validate_grouping_signal_derivation_snapshot(derivation)
        policy = validate_grouping_signal_derivation_policy_against_scale(
            policy, target_scale
        )
        policy_ref = grouping_signal_derivation_policy_reference(policy)
    except ValueError as error:
        raise GroupingSignalPreviewValidationError(str(error)) from error
    if derivation.policy_reference != policy_ref:
        raise GroupingSignalPreviewValidationError(
            "preview policy must be the exact policy bound by the derivation."
        )
    if (
        policy.class_id != derivation.class_id
        or policy.dimension_id != derivation.dimension_id
        or policy.band_count != derivation.band_count
    ):
        raise GroupingSignalPreviewValidationError(
            "policy shape must match the exact derivation."
        )
    ref = grouping_signal_derivation_reference(derivation)
    if not isinstance(currentness, GroupingSignalPreviewCurrentness):
        raise GroupingSignalPreviewValidationError("invalid currentness.")
    currentness.__post_init__()
    _check_currentness(currentness, ref)

    rows = tuple(
        GroupingSignalPreviewStudentRow(
            item.student_id,
            item.source_state,
            item.disposition,
            item.source_result,
            item.proficiency_level_id,
            item.scale_position,
            item.band,
        )
        for item in derivation.student_derivations
    )
    by_position = {level.position: level.level_id for level in target_scale.levels}
    summaries = tuple(
        GroupingSignalPreviewBandSummary(
            definition.band,
            definition.minimum_scale_position,
            definition.maximum_scale_position,
            tuple(
                by_position[position]
                for position in range(
                    definition.minimum_scale_position,
                    definition.maximum_scale_position + 1,
                )
            ),
            tuple(
                row.student_id
                for row in rows
                if row.disposition == "contributing" and row.band == definition.band
            ),
        )
        for definition in policy.band_definitions
    )
    contributing = sum(row.disposition == "contributing" for row in rows)
    missing = sum(row.source_state == "missing" for row in rows)
    insufficient = sum(
        row.source_state == "insufficient_evidence" for row in rows
    )
    occupied = sum(bool(summary.student_ids) for summary in summaries)
    coverage = GroupingSignalPreviewCoverage(
        len(rows),
        contributing,
        len(rows) - contributing,
        missing,
        insufficient,
        occupied,
        policy.band_count - occupied,
    )
    ties = _derive_ties(rows)
    diagnostics = _derive_diagnostics(currentness, coverage, rows, summaries)
    semantic = _semantic_parts(
        ref,
        derivation.algorithm_version,
        derivation.calculation_fingerprint,
        policy_ref,
        policy.title,
        policy.academic_basis,
        derivation.roster_basis,
        policy.dimension_id,
        policy.band_count,
        policy.band_definitions,
        policy.tie_handling,
        policy.missing_result_handling,
        policy.insufficient_result_handling,
        coverage,
        summaries,
        rows,
        ties,
        currentness,
        diagnostics,
    )
    fingerprint = hashlib.sha256(_canonical(semantic)).hexdigest()
    return GroupingSignalPreviewSnapshot(
        GROUPING_SIGNAL_PREVIEW_SCHEMA_VERSION,
        GROUPING_SIGNAL_PREVIEW_RECORD_TYPE,
        grouping_signal_preview_id(fingerprint),
        GROUPING_SIGNAL_PREVIEW_ALGORITHM_VERSION,
        ref,
        derivation.algorithm_version,
        derivation.calculation_fingerprint,
        policy_ref,
        policy.title,
        policy.academic_basis,
        derivation.roster_basis,
        policy.dimension_id,
        policy.band_count,
        policy.band_definitions,
        policy.tie_handling,
        policy.missing_result_handling,
        policy.insufficient_result_handling,
        coverage,
        summaries,
        rows,
        ties,
        currentness,
        diagnostics,
        fingerprint,
    )


def grouping_signal_preview_diagnostic_id(
    code: PreviewDiagnosticCode,
    severity: PreviewSeverity,
    student_ids: tuple[str, ...] = (),
    bands: tuple[int, ...] = (),
    details: tuple[str, ...] = (),
) -> str:
    code = _diagnostic_code(code)
    if severity != _SEVERITY[code]:
        raise GroupingSignalPreviewValidationError("diagnostic severity mismatch.")
    payload = {
        "code": code,
        "severity": severity,
        "student_ids": list(_ids(student_ids, "student_ids", True)),
        "bands": list(_positive_tuple(bands, "bands")),
        "details": list(_codes(details, "details")),
    }
    return GROUPING_SIGNAL_DIAGNOSTIC_ID_PREFIX + hashlib.sha256(
        _canonical(payload)
    ).hexdigest()


def grouping_signal_preview_id(fingerprint: str) -> str:
    fingerprint = _sha(fingerprint, "preview_fingerprint")
    value = GROUPING_SIGNAL_PREVIEW_ID_PREFIX + fingerprint
    try:
        validate_identifier(value, "preview_id")
    except IdentifierValidationError as error:
        raise GroupingSignalPreviewValidationError(str(error)) from error
    return value


def grouping_signal_preview_fingerprint(
    value: GroupingSignalPreviewSnapshot,
) -> str:
    if not isinstance(value, GroupingSignalPreviewSnapshot):
        raise GroupingSignalPreviewValidationError("invalid preview snapshot.")
    return hashlib.sha256(_canonical(_semantic_from_snapshot(value))).hexdigest()


def grouping_signal_preview_sha256(value: GroupingSignalPreviewSnapshot) -> str:
    return hashlib.sha256(
        grouping_signal_preview_snapshot_to_json_bytes(value)
    ).hexdigest()


def grouping_signal_preview_reference(
    value: GroupingSignalPreviewSnapshot,
) -> GroupingSignalPreviewReference:
    value = validate_grouping_signal_preview_snapshot(value)
    return GroupingSignalPreviewReference(
        value.derivation_reference.class_id,
        value.preview_id,
        grouping_signal_preview_sha256(value),
    )



def grouping_signal_preview_reference_to_dict(
    value: GroupingSignalPreviewReference,
) -> dict[str, object]:
    if not isinstance(value, GroupingSignalPreviewReference):
        raise GroupingSignalPreviewValidationError("invalid preview reference.")
    value.__post_init__()
    return {
        "class_id": value.class_id,
        "preview_id": value.preview_id,
        "preview_sha256": value.preview_sha256,
    }


def grouping_signal_preview_reference_from_dict(
    data: object,
) -> GroupingSignalPreviewReference:
    m = _mapping(
        data,
        frozenset({"class_id", "preview_id", "preview_sha256"}),
        "preview_reference",
    )
    return GroupingSignalPreviewReference(
        _str(m["class_id"], "class_id"),
        _str(m["preview_id"], "preview_id"),
        _str(m["preview_sha256"], "preview_sha256"),
    )

def validate_grouping_signal_preview_snapshot(
    value: GroupingSignalPreviewSnapshot,
) -> GroupingSignalPreviewSnapshot:
    if not isinstance(value, GroupingSignalPreviewSnapshot):
        raise GroupingSignalPreviewValidationError("invalid preview snapshot.")
    value.__post_init__()
    return value


def grouping_signal_preview_snapshot_to_dict(
    value: GroupingSignalPreviewSnapshot,
) -> dict[str, object]:
    value = validate_grouping_signal_preview_snapshot(value)
    return {
        **_semantic_from_snapshot(value),
        "preview_id": value.preview_id,
        "preview_fingerprint": value.preview_fingerprint,
    }


def grouping_signal_preview_snapshot_from_dict(
    data: object,
) -> GroupingSignalPreviewSnapshot:
    m = _mapping(data, _PREVIEW_KEYS, "preview")
    return GroupingSignalPreviewSnapshot(
        _str(m["schema_version"], "schema_version"),
        _str(m["record_type"], "record_type"),
        _str(m["preview_id"], "preview_id"),
        _str(m["preview_algorithm_version"], "preview_algorithm_version"),
        grouping_signal_derivation_reference_from_dict(m["derivation_reference"]),
        _str(m["derivation_algorithm_version"], "derivation_algorithm_version"),
        _str(
            m["derivation_calculation_fingerprint"],
            "derivation_calculation_fingerprint",
        ),
        grouping_signal_derivation_policy_reference_from_dict(m["policy_reference"]),
        _str(m["policy_title"], "policy_title"),
        grouping_signal_academic_basis_from_dict(m["academic_basis"]),
        grouping_signal_roster_basis_from_dict(m["roster_basis"]),
        _str(m["dimension_id"], "dimension_id"),
        _int(m["band_count"], "band_count"),
        tuple(
            grouping_signal_band_definition_from_dict(item)
            for item in _list(m["band_definitions"], "band_definitions")
        ),
        cast(GroupingSignalTieHandling, _str(m["tie_handling"], "tie_handling")),
        cast(
            GroupingSignalResultHandling,
            _str(m["missing_result_handling"], "missing_result_handling"),
        ),
        cast(
            GroupingSignalResultHandling,
            _str(
                m["insufficient_result_handling"],
                "insufficient_result_handling",
            ),
        ),
        _coverage_from(m["coverage"]),
        tuple(
            _summary_from(item)
            for item in _list(m["band_summaries"], "band_summaries")
        ),
        tuple(_row_from(item) for item in _list(m["student_rows"], "student_rows")),
        tuple(_tie_from(item) for item in _list(m["tie_groups"], "tie_groups")),
        _currentness_from(m["currentness"]),
        tuple(
            _diagnostic_from(item)
            for item in _list(m["diagnostics"], "diagnostics")
        ),
        _str(m["preview_fingerprint"], "preview_fingerprint"),
    )


def grouping_signal_preview_snapshot_to_json_bytes(
    value: GroupingSignalPreviewSnapshot,
) -> bytes:
    payload = _canonical(grouping_signal_preview_snapshot_to_dict(value))
    if len(payload) > MAXIMUM_GROUPING_SIGNAL_PREVIEW_BYTES:
        raise GroupingSignalPreviewSerializationError("preview JSON is too large.")
    return payload


def grouping_signal_preview_snapshot_from_json_bytes(
    data: bytes,
) -> GroupingSignalPreviewSnapshot:
    if not isinstance(data, bytes):
        raise GroupingSignalPreviewSerializationError("preview JSON must be bytes.")
    if len(data) > MAXIMUM_GROUPING_SIGNAL_PREVIEW_BYTES:
        raise GroupingSignalPreviewSerializationError("preview JSON is too large.")
    value = grouping_signal_preview_snapshot_from_dict(_parse(data))
    if grouping_signal_preview_snapshot_to_json_bytes(value) != data:
        raise GroupingSignalPreviewSerializationError("preview JSON is not canonical.")
    return value


def _semantic_from_snapshot(value: GroupingSignalPreviewSnapshot) -> dict[str, object]:
    return _semantic_parts(
        value.derivation_reference,
        value.derivation_algorithm_version,
        value.derivation_calculation_fingerprint,
        value.policy_reference,
        value.policy_title,
        value.academic_basis,
        value.roster_basis,
        value.dimension_id,
        value.band_count,
        value.band_definitions,
        value.tie_handling,
        value.missing_result_handling,
        value.insufficient_result_handling,
        value.coverage,
        value.band_summaries,
        value.student_rows,
        value.tie_groups,
        value.currentness,
        value.diagnostics,
    )


def _semantic_parts(
    derivation_reference: GroupingSignalDerivationReference,
    derivation_algorithm_version: str,
    derivation_calculation_fingerprint: str,
    policy_reference: GroupingSignalDerivationPolicyReference,
    policy_title: str,
    academic_basis: GroupingSignalAcademicBasis,
    roster_basis: GroupingSignalRosterBasis,
    dimension_id: str,
    band_count: int,
    band_definitions: tuple[GroupingSignalBandDefinition, ...],
    tie_handling: GroupingSignalTieHandling,
    missing_result_handling: GroupingSignalResultHandling,
    insufficient_result_handling: GroupingSignalResultHandling,
    coverage: GroupingSignalPreviewCoverage,
    band_summaries: tuple[GroupingSignalPreviewBandSummary, ...],
    student_rows: tuple[GroupingSignalPreviewStudentRow, ...],
    tie_groups: tuple[GroupingSignalPreviewTieGroup, ...],
    currentness: GroupingSignalPreviewCurrentness,
    diagnostics: tuple[GroupingSignalPreviewDiagnostic, ...],
) -> dict[str, object]:
    return {
        "schema_version": GROUPING_SIGNAL_PREVIEW_SCHEMA_VERSION,
        "record_type": GROUPING_SIGNAL_PREVIEW_RECORD_TYPE,
        "preview_algorithm_version": GROUPING_SIGNAL_PREVIEW_ALGORITHM_VERSION,
        "derivation_reference": grouping_signal_derivation_reference_to_dict(
            derivation_reference
        ),
        "derivation_algorithm_version": derivation_algorithm_version,
        "derivation_calculation_fingerprint": derivation_calculation_fingerprint,
        "policy_reference": grouping_signal_derivation_policy_reference_to_dict(
            policy_reference
        ),
        "policy_title": policy_title,
        "academic_basis": grouping_signal_academic_basis_to_dict(academic_basis),
        "roster_basis": grouping_signal_roster_basis_to_dict(roster_basis),
        "dimension_id": dimension_id,
        "band_count": band_count,
        "band_definitions": [
            grouping_signal_band_definition_to_dict(item) for item in band_definitions
        ],
        "tie_handling": tie_handling,
        "missing_result_handling": missing_result_handling,
        "insufficient_result_handling": insufficient_result_handling,
        "coverage": _coverage_to(coverage),
        "band_summaries": [_summary_to(item) for item in band_summaries],
        "student_rows": [_row_to(item) for item in student_rows],
        "tie_groups": [_tie_to(item) for item in tie_groups],
        "currentness": _currentness_to(currentness),
        "diagnostics": [_diagnostic_to(item) for item in diagnostics],
    }


def _derive_diagnostics(
    currentness: GroupingSignalPreviewCurrentness,
    coverage: GroupingSignalPreviewCoverage,
    rows: tuple[GroupingSignalPreviewStudentRow, ...],
    summaries: tuple[GroupingSignalPreviewBandSummary, ...],
) -> tuple[GroupingSignalPreviewDiagnostic, ...]:
    result: list[GroupingSignalPreviewDiagnostic] = []

    def add(
        code: PreviewDiagnosticCode,
        students: tuple[str, ...] = (),
        bands: tuple[int, ...] = (),
        details: tuple[str, ...] = (),
    ) -> None:
        severity = _SEVERITY[code]
        result.append(
            GroupingSignalPreviewDiagnostic(
                grouping_signal_preview_diagnostic_id(
                    code, severity, students, bands, details
                ),
                code,
                severity,
                students,
                bands,
                details,
            )
        )

    if currentness.state == "stale":
        add("derivation_not_current", details=currentness.reason_codes)
    elif currentness.state == "blocked":
        add("current_generation_blocked", details=currentness.reason_codes)
    missing = tuple(row.student_id for row in rows if row.source_state == "missing")
    insufficient = tuple(
        row.student_id for row in rows if row.source_state == "insufficient_evidence"
    )
    noncontributing = tuple(
        row.student_id for row in rows if row.disposition == "noncontributing"
    )
    empty = tuple(summary.band for summary in summaries if not summary.student_ids)
    if coverage.contributing_student_count == 0:
        add("zero_contributors", noncontributing)
    if missing:
        add("missing_noncontributors", missing)
    if insufficient:
        add("insufficient_noncontributors", insufficient)
    if noncontributing:
        add("partial_coverage", noncontributing)
    if empty:
        add("empty_bands", bands=empty)
    if coverage.contributing_student_count and coverage.occupied_band_count == 1:
        occupied = tuple(summary.band for summary in summaries if summary.student_ids)
        add("single_occupied_band", bands=occupied)
    return _ordered_diagnostics(tuple(result))


def _derive_ties(
    rows: tuple[GroupingSignalPreviewStudentRow, ...],
) -> tuple[GroupingSignalPreviewTieGroup, ...]:
    grouped: dict[tuple[str, int, int], list[str]] = {}
    for row in rows:
        if row.disposition != "contributing":
            continue
        assert row.proficiency_level_id is not None
        assert row.scale_position is not None
        assert row.band is not None
        grouped.setdefault(
            (row.proficiency_level_id, row.scale_position, row.band), []
        ).append(row.student_id)
    return tuple(
        sorted(
            (
                GroupingSignalPreviewTieGroup(level, position, band, tuple(students))
                for (level, position, band), students in grouped.items()
                if len(students) >= 2
            ),
            key=lambda item: (
                item.scale_position,
                item.proficiency_level_id,
                item.band,
                item.student_ids,
            ),
        )
    )


def _definitions(
    value: object, band_count: int
) -> tuple[GroupingSignalBandDefinition, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalPreviewValidationError("band_definitions must be tuple.")
    items: list[GroupingSignalBandDefinition] = []
    for item in value:
        if not isinstance(item, GroupingSignalBandDefinition):
            raise GroupingSignalPreviewValidationError("invalid band definition.")
        item.__post_init__()
        items.append(item)
    ordered = tuple(sorted(items, key=lambda item: item.band))
    if tuple(item.band for item in ordered) != tuple(range(1, band_count + 1)):
        raise GroupingSignalPreviewValidationError("band definitions are incomplete.")
    return ordered


def _rows(
    value: object, roster: GroupingSignalRosterBasis, band_count: int
) -> tuple[GroupingSignalPreviewStudentRow, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalPreviewValidationError("student_rows must be tuple.")
    items: list[GroupingSignalPreviewStudentRow] = []
    for item in value:
        if not isinstance(item, GroupingSignalPreviewStudentRow):
            raise GroupingSignalPreviewValidationError("invalid student row.")
        item.__post_init__()
        if item.band is not None and item.band > band_count:
            raise GroupingSignalPreviewValidationError(
                "student band exceeds band_count."
            )
        items.append(item)
    ordered = tuple(sorted(items, key=lambda item: item.student_id))
    if tuple(item.student_id for item in ordered) != roster.student_ids:
        raise GroupingSignalPreviewValidationError(
            "student rows must exactly cover the #38 roster."
        )
    return ordered


def _summaries(
    value: object,
    definitions: tuple[GroupingSignalBandDefinition, ...],
    rows: tuple[GroupingSignalPreviewStudentRow, ...],
) -> tuple[GroupingSignalPreviewBandSummary, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalPreviewValidationError("band_summaries must be tuple.")
    items: list[GroupingSignalPreviewBandSummary] = []
    for item in value:
        if not isinstance(item, GroupingSignalPreviewBandSummary):
            raise GroupingSignalPreviewValidationError("invalid band summary.")
        item.__post_init__()
        items.append(item)
    ordered = tuple(sorted(items, key=lambda item: item.band))
    if tuple(item.band for item in ordered) != tuple(d.band for d in definitions):
        raise GroupingSignalPreviewValidationError("band summaries are incomplete.")
    for summary, definition in zip(ordered, definitions, strict=True):
        if (
            summary.minimum_scale_position != definition.minimum_scale_position
            or summary.maximum_scale_position != definition.maximum_scale_position
        ):
            raise GroupingSignalPreviewValidationError("band summary range disagrees.")
        students = tuple(
            row.student_id
            for row in rows
            if row.disposition == "contributing" and row.band == summary.band
        )
        if summary.student_ids != students:
            raise GroupingSignalPreviewValidationError(
                "band summary students disagree with rows."
            )
    return ordered


def _check_coverage(
    value: object,
    rows: tuple[GroupingSignalPreviewStudentRow, ...],
    summaries: tuple[GroupingSignalPreviewBandSummary, ...],
    band_count: int,
) -> GroupingSignalPreviewCoverage:
    if not isinstance(value, GroupingSignalPreviewCoverage):
        raise GroupingSignalPreviewValidationError("invalid coverage.")
    value.__post_init__()
    contributing = sum(row.disposition == "contributing" for row in rows)
    expected = GroupingSignalPreviewCoverage(
        len(rows),
        contributing,
        len(rows) - contributing,
        sum(row.source_state == "missing" for row in rows),
        sum(row.source_state == "insufficient_evidence" for row in rows),
        sum(bool(summary.student_ids) for summary in summaries),
        band_count - sum(bool(summary.student_ids) for summary in summaries),
    )
    if value != expected:
        raise GroupingSignalPreviewValidationError("coverage disagrees with rows.")
    return value


def _check_ties(
    value: object, rows: tuple[GroupingSignalPreviewStudentRow, ...]
) -> tuple[GroupingSignalPreviewTieGroup, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalPreviewValidationError("tie_groups must be tuple.")
    items: list[GroupingSignalPreviewTieGroup] = []
    for item in value:
        if not isinstance(item, GroupingSignalPreviewTieGroup):
            raise GroupingSignalPreviewValidationError("invalid tie group.")
        item.__post_init__()
        items.append(item)
    ordered = tuple(
        sorted(
            items,
            key=lambda item: (
                item.scale_position,
                item.proficiency_level_id,
                item.band,
                item.student_ids,
            ),
        )
    )
    if ordered != _derive_ties(rows):
        raise GroupingSignalPreviewValidationError("tie groups disagree with rows.")
    return ordered


def _check_currentness(
    value: GroupingSignalPreviewCurrentness,
    source: GroupingSignalDerivationReference,
) -> None:
    current = value.current_derivation_reference
    if value.state == "current" and current != source:
        raise GroupingSignalPreviewValidationError(
            "current preview must reference the exact previewed derivation."
        )
    if value.state == "stale" and current == source:
        raise GroupingSignalPreviewValidationError(
            "stale preview must reference a different current candidate."
        )
    if current is not None and current.class_id != source.class_id:
        raise GroupingSignalPreviewValidationError("currentness class disagrees.")


def _ordered_diagnostics(
    value: object,
) -> tuple[GroupingSignalPreviewDiagnostic, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalPreviewValidationError("diagnostics must be tuple.")
    items: list[GroupingSignalPreviewDiagnostic] = []
    for item in value:
        if not isinstance(item, GroupingSignalPreviewDiagnostic):
            raise GroupingSignalPreviewValidationError("invalid diagnostic.")
        item.__post_init__()
        items.append(item)
    ordered = tuple(
        sorted(
            items,
            key=lambda item: (
                _SEVERITY_ORDER[item.severity],
                item.code,
                item.student_ids,
                item.bands,
                item.details,
            ),
        )
    )
    if len({item.diagnostic_id for item in ordered}) != len(ordered):
        raise GroupingSignalPreviewValidationError("duplicate diagnostic identity.")
    return ordered


def _currentness_to(value: GroupingSignalPreviewCurrentness) -> dict[str, object]:
    value.__post_init__()
    return {
        "state": value.state,
        "reason_codes": list(value.reason_codes),
        "current_derivation_reference": (
            grouping_signal_derivation_reference_to_dict(
                value.current_derivation_reference
            )
            if value.current_derivation_reference is not None
            else None
        ),
    }


def _currentness_from(data: object) -> GroupingSignalPreviewCurrentness:
    m = _mapping(
        data,
        frozenset({"state", "reason_codes", "current_derivation_reference"}),
        "currentness",
    )
    raw = m["current_derivation_reference"]
    return GroupingSignalPreviewCurrentness(
        cast(PreviewCurrentnessState, _str(m["state"], "state")),
        tuple(
            _str(item, "reason_code")
            for item in _list(m["reason_codes"], "reason_codes")
        ),
        (
            grouping_signal_derivation_reference_from_dict(raw)
            if raw is not None
            else None
        ),
    )


def _row_to(value: GroupingSignalPreviewStudentRow) -> dict[str, object]:
    value.__post_init__()
    return {
        "student_id": value.student_id,
        "source_state": value.source_state,
        "disposition": value.disposition,
        "source_result": (
            academic_period_proficiency_result_reference_to_dict(value.source_result)
            if value.source_result is not None
            else None
        ),
        "proficiency_level_id": value.proficiency_level_id,
        "scale_position": value.scale_position,
        "band": value.band,
    }


def _row_from(data: object) -> GroupingSignalPreviewStudentRow:
    m = _mapping(
        data,
        frozenset(
            {
                "student_id",
                "source_state",
                "disposition",
                "source_result",
                "proficiency_level_id",
                "scale_position",
                "band",
            }
        ),
        "student_row",
    )
    raw = m["source_result"]
    return GroupingSignalPreviewStudentRow(
        _str(m["student_id"], "student_id"),
        _str(m["source_state"], "source_state"),
        _str(m["disposition"], "disposition"),
        (
            academic_period_proficiency_result_reference_from_dict(raw)
            if raw is not None
            else None
        ),
        _optional_str(m["proficiency_level_id"], "proficiency_level_id"),
        _optional_int(m["scale_position"], "scale_position"),
        _optional_int(m["band"], "band"),
    )


def _summary_to(value: GroupingSignalPreviewBandSummary) -> dict[str, object]:
    value.__post_init__()
    return {
        "band": value.band,
        "minimum_scale_position": value.minimum_scale_position,
        "maximum_scale_position": value.maximum_scale_position,
        "proficiency_level_ids": list(value.proficiency_level_ids),
        "student_count": value.student_count,
        "student_ids": list(value.student_ids),
    }


def _summary_from(data: object) -> GroupingSignalPreviewBandSummary:
    m = _mapping(
        data,
        frozenset(
            {
                "band",
                "minimum_scale_position",
                "maximum_scale_position",
                "proficiency_level_ids",
                "student_count",
                "student_ids",
            }
        ),
        "band_summary",
    )
    summary = GroupingSignalPreviewBandSummary(
        _int(m["band"], "band"),
        _int(m["minimum_scale_position"], "minimum_scale_position"),
        _int(m["maximum_scale_position"], "maximum_scale_position"),
        tuple(
            _str(item, "proficiency_level_id")
            for item in _list(m["proficiency_level_ids"], "proficiency_level_ids")
        ),
        tuple(
            _str(item, "student_id")
            for item in _list(m["student_ids"], "student_ids")
        ),
    )
    if _int(m["student_count"], "student_count") != summary.student_count:
        raise GroupingSignalPreviewSerializationError("student_count disagrees.")
    return summary


def _tie_to(value: GroupingSignalPreviewTieGroup) -> dict[str, object]:
    value.__post_init__()
    return {
        "proficiency_level_id": value.proficiency_level_id,
        "scale_position": value.scale_position,
        "band": value.band,
        "student_ids": list(value.student_ids),
    }


def _tie_from(data: object) -> GroupingSignalPreviewTieGroup:
    m = _mapping(
        data,
        frozenset({"proficiency_level_id", "scale_position", "band", "student_ids"}),
        "tie_group",
    )
    return GroupingSignalPreviewTieGroup(
        _str(m["proficiency_level_id"], "proficiency_level_id"),
        _int(m["scale_position"], "scale_position"),
        _int(m["band"], "band"),
        tuple(
            _str(item, "student_id")
            for item in _list(m["student_ids"], "student_ids")
        ),
    )


def _coverage_to(value: GroupingSignalPreviewCoverage) -> dict[str, object]:
    value.__post_init__()
    return {
        "roster_student_count": value.roster_student_count,
        "contributing_student_count": value.contributing_student_count,
        "noncontributing_student_count": value.noncontributing_student_count,
        "missing_noncontributor_count": value.missing_noncontributor_count,
        "insufficient_noncontributor_count": value.insufficient_noncontributor_count,
        "occupied_band_count": value.occupied_band_count,
        "empty_band_count": value.empty_band_count,
    }


def _coverage_from(data: object) -> GroupingSignalPreviewCoverage:
    keys = frozenset(
        {
            "roster_student_count",
            "contributing_student_count",
            "noncontributing_student_count",
            "missing_noncontributor_count",
            "insufficient_noncontributor_count",
            "occupied_band_count",
            "empty_band_count",
        }
    )
    m = _mapping(data, keys, "coverage")
    return GroupingSignalPreviewCoverage(
        _int(m["roster_student_count"], "roster_student_count"),
        _int(m["contributing_student_count"], "contributing_student_count"),
        _int(
            m["noncontributing_student_count"],
            "noncontributing_student_count",
        ),
        _int(
            m["missing_noncontributor_count"],
            "missing_noncontributor_count",
        ),
        _int(
            m["insufficient_noncontributor_count"],
            "insufficient_noncontributor_count",
        ),
        _int(m["occupied_band_count"], "occupied_band_count"),
        _int(m["empty_band_count"], "empty_band_count"),
    )


def _diagnostic_to(value: GroupingSignalPreviewDiagnostic) -> dict[str, object]:
    value.__post_init__()
    return {
        "diagnostic_id": value.diagnostic_id,
        "code": value.code,
        "severity": value.severity,
        "student_ids": list(value.student_ids),
        "bands": list(value.bands),
        "details": list(value.details),
    }


def _diagnostic_from(data: object) -> GroupingSignalPreviewDiagnostic:
    m = _mapping(
        data,
        frozenset(
            {"diagnostic_id", "code", "severity", "student_ids", "bands", "details"}
        ),
        "diagnostic",
    )
    return GroupingSignalPreviewDiagnostic(
        _str(m["diagnostic_id"], "diagnostic_id"),
        cast(PreviewDiagnosticCode, _str(m["code"], "code")),
        cast(PreviewSeverity, _str(m["severity"], "severity")),
        tuple(
            _str(item, "student_id")
            for item in _list(m["student_ids"], "student_ids")
        ),
        tuple(_int(item, "band") for item in _list(m["bands"], "bands")),
        tuple(_str(item, "detail") for item in _list(m["details"], "details")),
    )


_PREVIEW_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "preview_id",
        "preview_algorithm_version",
        "derivation_reference",
        "derivation_algorithm_version",
        "derivation_calculation_fingerprint",
        "policy_reference",
        "policy_title",
        "academic_basis",
        "roster_basis",
        "dimension_id",
        "band_count",
        "band_definitions",
        "tie_handling",
        "missing_result_handling",
        "insufficient_result_handling",
        "coverage",
        "band_summaries",
        "student_rows",
        "tie_groups",
        "currentness",
        "diagnostics",
        "preview_fingerprint",
    }
)


def _diagnostic_code(value: object) -> PreviewDiagnosticCode:
    if not isinstance(value, str) or value not in _SEVERITY:
        raise GroupingSignalPreviewValidationError("unsupported diagnostic code.")
    return value


def _id(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalPreviewValidationError(
            f"{field} must be an identifier string."
        )
    try:
        return validate_identifier(value, field)
    except (IdentifierValidationError, TypeError, ValueError) as error:
        raise GroupingSignalPreviewValidationError(str(error)) from error


def _ids(value: object, field: str, sort: bool) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalPreviewValidationError(f"{field} must be tuple.")
    items = tuple(_id(item, field) for item in value)
    if len(set(items)) != len(items):
        raise GroupingSignalPreviewValidationError(f"{field} has duplicates.")
    return tuple(sorted(items)) if sort else items


def _codes(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalPreviewValidationError(f"{field} must be tuple.")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or _CODE.fullmatch(item) is None:
            raise GroupingSignalPreviewValidationError(f"{field} has invalid code.")
        items.append(item)
    if len(set(items)) != len(items):
        raise GroupingSignalPreviewValidationError(f"{field} has duplicates.")
    return tuple(sorted(items))


def _positive_tuple(value: object, field: str) -> tuple[int, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalPreviewValidationError(f"{field} must be tuple.")
    items = tuple(_positive(item, field) for item in value)
    if len(set(items)) != len(items):
        raise GroupingSignalPreviewValidationError(f"{field} has duplicates.")
    return tuple(sorted(items))


def _positive(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise GroupingSignalPreviewValidationError(f"{field} must be positive integer.")
    return value


def _nonnegative(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise GroupingSignalPreviewValidationError(
            f"{field} must be nonnegative integer."
        )
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise GroupingSignalPreviewValidationError(f"{field} must be SHA-256.")
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\n" in value
        or "\r" in value
    ):
        raise GroupingSignalPreviewValidationError(
            f"{field} must be bounded one-line text."
        )
    return value


def _mapping(data: object, keys: frozenset[str], label: str) -> dict[str, object]:
    if not isinstance(data, dict) or set(data) != keys:
        raise GroupingSignalPreviewSerializationError(f"{label} keys are not exact.")
    return cast(dict[str, object], data)


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise GroupingSignalPreviewSerializationError(f"{field} must be JSON array.")
    return cast(list[object], value)


def _str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalPreviewSerializationError(f"{field} must be string.")
    return value


def _optional_str(value: object, field: str) -> str | None:
    return None if value is None else _str(value, field)


def _int(value: object, field: str) -> int:
    if type(value) is not int:
        raise GroupingSignalPreviewSerializationError(f"{field} must be integer.")
    return value


def _optional_int(value: object, field: str) -> int | None:
    return None if value is None else _int(value, field)


def _canonical(value: object) -> bytes:
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
        raise GroupingSignalPreviewSerializationError(
            "preview is not JSON serializable."
        ) from error


def _parse(data: bytes) -> object:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GroupingSignalPreviewSerializationError(
            "preview JSON must be UTF-8."
        ) from error

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise GroupingSignalPreviewSerializationError("duplicate JSON key.")
            result[key] = value
        return result

    def constant(value: str) -> NoReturn:
        raise GroupingSignalPreviewSerializationError(
            f"nonfinite JSON value {value!r} is forbidden."
        )

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except GroupingSignalPreviewSerializationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise GroupingSignalPreviewSerializationError(
            "invalid preview JSON."
        ) from error
