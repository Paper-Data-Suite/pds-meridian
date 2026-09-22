"""Strict #54 Grade-report handoff reload for immutable #55 snapshots.

This module is intentionally owned by reporting snapshots rather than the #54
preview/calculation layer.  It validates and freezes the stable #54 handoff:

* ``GradePreviewObservation`` is reconstructed as the exact typed comparison
  contract used by #54/#55;
* the richer ``GradeReportPreview`` representation is retained byte-for-byte as
  canonical JSON, with deterministic row metadata and explanation digests;
* common and family-specific semantic basis hashes are recomputed from the rich
  explanation and required to match each frozen observation.

It does not recalculate Grades, reopen workspace state, persist snapshots, select
current state, or turn #54 explanation models into mutable persistence objects.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_periods import (
    AcademicPeriodValidationError,
    academic_period_ref_from_dict,
    academic_period_ref_to_dict,
)

from meridian.academic_period_proficiency import (
    academic_period_proficiency_result_reference_from_dict,
)
from meridian.grade_policy import grade_policy_reference_from_dict
from meridian.grade_policy_activation import grade_policy_activation_reference_from_dict
from meridian.grade_preview_explanation import (
    GradePreviewBasisEntry,
    GradePreviewObservation,
    GradePreviewTarget,
    grade_preview_observation_sha256,
    grade_preview_observation_to_dict,
    grade_preview_observation_to_json_bytes,
)
from meridian.grade_report_preview import GradeReportPreviewSummary
from meridian.reporting_snapshot import ReportingSnapshotSerializationError
from meridian.teacher_grade_override import (
    grade_override_source_result_reference_from_dict,
    teacher_grade_override_reference_from_dict,
)

DEFAULT_MAXIMUM_FROZEN_GRADE_REPORT_PREVIEW_BYTES: Final[int] = 16 * 1024 * 1024

FrozenGradeReportPreviewRowStatus: TypeAlias = Literal["available", "unavailable"]
FrozenGradeReportPreviewUnavailableReason: TypeAlias = Literal["no_selected_grade"]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

_OBSERVATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "target",
        "base_result_reference",
        "base_result_status",
        "base_grade",
        "base_freshness_status",
        "base_freshness_reasons",
        "algorithm_version",
        "calculation_fingerprint",
        "inputs_sha256",
        "activation_reference",
        "policy_reference",
        "selected_override_reference",
        "override_applicability",
        "override_replacement_grade",
        "effective_grade",
        "effective_source",
        "basis_entries",
    }
)
_TARGET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "student_id",
        "target_period",
        "calendar_revision",
        "calculation_family",
    }
)
_BASIS_ENTRY_KEYS: Final[frozenset[str]] = frozenset(
    {"dimension", "key", "sha256"}
)
_PREVIEW_KEYS: Final[frozenset[str]] = frozenset({"summary", "rows"})
_ROW_KEYS: Final[frozenset[str]] = frozenset(
    {"target", "status", "unavailable_reason", "explanation", "observation"}
)
_SUMMARY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "requested_count",
        "available_count",
        "unavailable_count",
        "base_calculated_count",
        "base_blocked_count",
        "base_insufficient_count",
        "current_count",
        "stale_count",
        "effective_numeric_count",
        "effective_nonnumeric_count",
        "effective_base_count",
        "effective_override_count",
        "effective_none_count",
    }
)
_COMMON_KEYS: Final[frozenset[str]] = frozenset(
    {
        "target",
        "base_result",
        "base_result_status",
        "base_grade",
        "base_freshness_status",
        "base_freshness_reasons",
        "policy",
        "selected_override",
        "override_applicability",
        "override_reasons",
        "effective_grade",
        "effective_source",
    }
)
_BASE_RESULT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "source_result",
        "algorithm_version",
        "calculation_fingerprint",
        "inputs_sha256",
        "calculated_at",
        "unrounded_grade",
        "rounded_grade",
    }
)
_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "activation_reference",
        "policy_reference",
        "title",
        "calculation_family",
        "policy_actor",
        "policy_rationale",
        "policy_revised_at",
        "activation_actor",
        "activation_rationale",
        "activation_decided_at",
        "state_treatment",
        "reassessment_handling",
        "rounding",
    }
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_STATE_TREATMENT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "missing",
        "pending",
        "incomplete",
        "excused",
        "excluded",
        "not_applicable",
        "insufficient_evidence",
        "unavailable",
        "withdrawn",
        "invalid",
        "unresolved",
    }
)
_REASSESSMENT_KEYS: Final[frozenset[str]] = frozenset(
    {"selection_authority", "unresolved_handling"}
)
_ROUNDING_KEYS: Final[frozenset[str]] = frozenset(
    {"quantum", "mode", "application_stage"}
)
_OVERRIDE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "reference",
        "decision",
        "source_result",
        "replacement_grade",
        "withdrawn_override_reference",
        "actor_id",
        "rationale",
        "decided_at",
        "applicability",
        "reasons",
    }
)

_CONVENTIONAL_KEYS: Final[frozenset[str]] = frozenset(
    {"common", "mode", "items", "categories", "formula", "reasons"}
)
_CONVENTIONAL_BREAKDOWN_KEYS: Final[frozenset[str]] = frozenset(
    {"status", "mode", "items", "categories", "formula", "reasons"}
)
_CONVENTIONAL_ITEM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "grade_item",
        "category_id",
        "weight",
        "policy_possible_points",
        "source_state",
        "action",
        "earned",
        "possible",
        "percentage",
        "contribution",
        "reason_codes",
        "provenance",
    }
)
_GRADE_ITEM_KEYS: Final[frozenset[str]] = frozenset(
    {"reference", "title", "purpose", "status"}
)
_GRADE_ITEM_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "grade_item_id", "grade_item_revision", "grade_item_revision_sha256"}
)
_PROVENANCE_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "reference_key", "reference_sha256"}
)
_CONVENTIONAL_CATEGORY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "category_id",
        "title",
        "weight",
        "status",
        "included_grade_item_ids",
        "excluded_grade_item_ids",
        "earned",
        "possible",
        "fraction",
        "contribution",
        "reason_codes",
    }
)
_CONVENTIONAL_FORMULA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "mode",
        "total_earned",
        "total_possible",
        "final_fraction",
        "unrounded_grade",
        "rounded_grade",
    }
)
_CONVENTIONAL_REASON_KEYS: Final[frozenset[str]] = frozenset(
    {"code", "grade_item", "category_id"}
)

_STANDARDS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "common",
        "status",
        "target_scale",
        "conversions",
        "standards",
        "formula",
        "reasons",
    }
)
_STANDARDS_BREAKDOWN_KEYS: Final[frozenset[str]] = frozenset(
    {"status", "target_scale", "conversions", "standards", "formula", "reasons"}
)
_SCALE_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "scale_id", "scale_revision", "scale_sha256"}
)
_CONVERSION_KEYS: Final[frozenset[str]] = frozenset(
    {"proficiency_level_id", "grade_value"}
)
_STANDARD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "standard_id",
        "weight",
        "source_state",
        "action",
        "result_reference",
        "result_algorithm_version",
        "result_calculation_fingerprint",
        "target_scale",
        "proficiency_level_id",
        "converted_grade_value",
        "calculation_value",
        "weighted_contribution",
        "freshness_status",
        "freshness_reasons",
        "reason_codes",
        "nested_proficiency_explanation",
    }
)
_STANDARDS_FORMULA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "aggregation_strategy",
        "minimum_calculated_results",
        "actual_calculated_result_count",
        "active_weight",
        "weighted_numerator",
        "unrounded_grade",
        "rounded_grade",
    }
)
_STANDARDS_REASON_KEYS: Final[frozenset[str]] = frozenset(
    {"code", "standard_id", "required_results", "actual_results"}
)

_HYBRID_KEYS: Final[frozenset[str]] = frozenset(
    {
        "common",
        "status",
        "conventional_component",
        "standards_component",
        "formula",
        "reasons",
    }
)
_HYBRID_COMPONENT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "component_kind",
        "configured_weight",
        "source_status",
        "action",
        "component_algorithm_version",
        "component_calculation_fingerprint",
        "unrounded_grade",
        "weighted_contribution",
        "reason_codes",
        "breakdown",
    }
)
_HYBRID_FORMULA_KEYS: Final[frozenset[str]] = frozenset(
    {"active_weight", "weighted_numerator", "unrounded_grade", "rounded_grade"}
)
_HYBRID_REASON_KEYS: Final[frozenset[str]] = frozenset({"code", "component_kind"})

_COMMON_BASIS_KEYS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("activation", "selected_activation"),
        ("policy", "grade_policy"),
        ("state_treatment", "grade_state_treatment"),
        ("reassessment", "grade_reassessment_handling"),
        ("rounding", "final_grade_rounding"),
    }
)
_FAMILY_BASIS_KEYS: Final[dict[str, frozenset[tuple[str, str]]]] = {
    "conventional": frozenset(
        {
            ("formula", "conventional_formula"),
            ("participation", "conventional_participation"),
            ("evidence", "conventional_evidence_basis"),
            ("weighting", "conventional_weighting"),
        }
    ),
    "standards_based": frozenset(
        {
            ("formula", "standards_formula"),
            ("participation", "standards_participation"),
            ("evidence", "standards_proficiency_basis"),
            ("weighting", "standards_weighting"),
        }
    ),
    "hybrid": frozenset(
        {
            ("formula", "hybrid_formula"),
            ("participation", "hybrid_participation"),
            ("evidence", "hybrid_component_basis"),
            ("weighting", "hybrid_weighting"),
        }
    ),
}


class ReportingSnapshotPreviewIntegrityError(ReportingSnapshotSerializationError):
    """Raised when frozen #54 report-preview bytes cannot be trusted."""

    code = "reporting_snapshot.integrity_failed"


@dataclass(frozen=True, slots=True)
class FrozenGradeReportPreviewRow:
    """Stable #55 row metadata over one canonical #54 report row."""

    target: GradePreviewTarget
    status: FrozenGradeReportPreviewRowStatus
    unavailable_reason: FrozenGradeReportPreviewUnavailableReason | None
    observation: GradePreviewObservation | None
    observation_sha256: str | None
    explanation_json: bytes | None = field(repr=False)
    explanation_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, GradePreviewTarget):
            raise ReportingSnapshotPreviewIntegrityError(
                "frozen report row target is invalid."
            )
        if self.status == "available":
            if self.unavailable_reason is not None:
                raise ReportingSnapshotPreviewIntegrityError(
                    "available frozen row must not carry unavailable_reason."
                )
            if not isinstance(self.observation, GradePreviewObservation):
                raise ReportingSnapshotPreviewIntegrityError(
                    "available frozen row requires GradePreviewObservation."
                )
            if self.observation.target != self.target:
                raise ReportingSnapshotPreviewIntegrityError(
                    "frozen row observation target does not match row target."
                )
            if type(self.explanation_json) is not bytes or not self.explanation_json:
                raise ReportingSnapshotPreviewIntegrityError(
                    "available frozen row requires canonical explanation bytes."
                )
            expected_observation = grade_preview_observation_sha256(self.observation)
            if self.observation_sha256 != expected_observation:
                raise ReportingSnapshotPreviewIntegrityError(
                    "frozen row observation digest does not match exact observation."
                )
            expected_explanation = hashlib.sha256(self.explanation_json).hexdigest()
            if self.explanation_sha256 != expected_explanation:
                raise ReportingSnapshotPreviewIntegrityError(
                    "frozen row explanation digest does not match exact bytes."
                )
        elif self.status == "unavailable":
            if self.unavailable_reason != "no_selected_grade":
                raise ReportingSnapshotPreviewIntegrityError(
                    "unavailable frozen row requires no_selected_grade reason."
                )
            if any(
                value is not None
                for value in (
                    self.observation,
                    self.observation_sha256,
                    self.explanation_json,
                    self.explanation_sha256,
                )
            ):
                raise ReportingSnapshotPreviewIntegrityError(
                    "unavailable frozen row must not carry Grade explanation state."
                )
        else:
            raise ReportingSnapshotPreviewIntegrityError(
                "unsupported frozen report row status."
            )


@dataclass(frozen=True, slots=True)
class FrozenGradeReportPreview:
    """Canonical #54 report bytes plus typed #55 comparison/reload metadata."""

    canonical_json: bytes = field(repr=False)
    preview_sha256: str
    summary: GradeReportPreviewSummary
    rows: tuple[FrozenGradeReportPreviewRow, ...]

    def __post_init__(self) -> None:
        if type(self.canonical_json) is not bytes or not self.canonical_json:
            raise ReportingSnapshotPreviewIntegrityError(
                "frozen report preview requires canonical immutable bytes."
            )
        digest = _sha256(self.preview_sha256, "preview_sha256")
        if hashlib.sha256(self.canonical_json).hexdigest() != digest:
            raise ReportingSnapshotPreviewIntegrityError(
                "report-preview digest does not match canonical bytes."
            )
        if not isinstance(self.summary, GradeReportPreviewSummary):
            raise ReportingSnapshotPreviewIntegrityError(
                "frozen report preview summary is invalid."
            )
        rows = tuple(self.rows)
        if any(not isinstance(row, FrozenGradeReportPreviewRow) for row in rows):
            raise ReportingSnapshotPreviewIntegrityError(
                "frozen report rows are invalid."
            )
        keys = tuple(_target_key(row.target) for row in rows)
        if len(set(keys)) != len(keys):
            raise ReportingSnapshotPreviewIntegrityError(
                "frozen report preview contains duplicate exact Grade targets."
            )
        if rows != tuple(sorted(rows, key=lambda row: _target_key(row.target))):
            raise ReportingSnapshotPreviewIntegrityError(
                "frozen report rows are not in canonical target order."
            )
        if self.summary != _summary_from_rows(rows):
            raise ReportingSnapshotPreviewIntegrityError(
                "frozen report summary does not match frozen report rows."
            )
        object.__setattr__(self, "preview_sha256", digest)
        object.__setattr__(self, "rows", rows)


def grade_preview_observation_from_dict(data: object) -> GradePreviewObservation:
    """Strictly reconstruct one canonical #54 observation from JSON-native data."""

    mapping = _exact_mapping(data, _OBSERVATION_KEYS, "GradePreviewObservation")
    try:
        target = _target_from_dict(mapping["target"])
        base_result = grade_override_source_result_reference_from_dict(
            mapping["base_result_reference"]
        )
        activation = grade_policy_activation_reference_from_dict(
            mapping["activation_reference"]
        )
        policy = grade_policy_reference_from_dict(mapping["policy_reference"])
        selected_override = (
            teacher_grade_override_reference_from_dict(
                mapping["selected_override_reference"]
            )
            if mapping["selected_override_reference"] is not None
            else None
        )
        entries = tuple(
            GradePreviewBasisEntry(
                dimension=_require_str(
                    entry["dimension"], "basis.dimension"
                ),  # type: ignore[arg-type]
                key=_require_str(entry["key"], "basis.key"),
                sha256=_require_str(entry["sha256"], "basis.sha256"),
            )
            for entry in (
                _exact_mapping(item, _BASIS_ENTRY_KEYS, "basis entry")
                for item in _require_list(mapping["basis_entries"], "basis_entries")
            )
        )
        return GradePreviewObservation(
            schema_version=_require_str(mapping["schema_version"], "schema_version"),
            target=target,
            base_result_reference=base_result,
            base_result_status=_require_str(
                mapping["base_result_status"], "base_result_status"
            ),
            base_grade=_optional_decimal(mapping["base_grade"], "base_grade"),
            base_freshness_status=_require_str(
                mapping["base_freshness_status"], "base_freshness_status"
            ),
            base_freshness_reasons=_string_tuple(
                mapping["base_freshness_reasons"], "base_freshness_reasons"
            ),
            algorithm_version=_require_str(
                mapping["algorithm_version"], "algorithm_version"
            ),
            calculation_fingerprint=_require_str(
                mapping["calculation_fingerprint"], "calculation_fingerprint"
            ),
            inputs_sha256=_require_str(mapping["inputs_sha256"], "inputs_sha256"),
            activation_reference=activation,
            policy_reference=policy,
            selected_override_reference=selected_override,
            override_applicability=_require_str(
                mapping["override_applicability"], "override_applicability"
            ),  # type: ignore[arg-type]
            override_replacement_grade=_optional_decimal(
                mapping["override_replacement_grade"],
                "override_replacement_grade",
            ),
            effective_grade=_optional_decimal(
                mapping["effective_grade"], "effective_grade"
            ),
            effective_source=_require_str(
                mapping["effective_source"], "effective_source"
            ),  # type: ignore[arg-type]
            basis_entries=entries,
        )
    except ReportingSnapshotPreviewIntegrityError:
        raise
    except (TypeError, ValueError) as error:
        raise ReportingSnapshotPreviewIntegrityError(
            f"GradePreviewObservation is invalid: {error}"
        ) from error


def grade_preview_observation_from_json_bytes(data: bytes) -> GradePreviewObservation:
    """Strictly load one observation and require the exact #54 canonical encoding."""

    decoded = _decode_json(data, "GradePreviewObservation")
    value = grade_preview_observation_from_dict(decoded)
    if grade_preview_observation_to_json_bytes(value) != data:
        raise ReportingSnapshotPreviewIntegrityError(
            "GradePreviewObservation bytes are not the canonical #54 encoding."
        )
    return value


def frozen_grade_report_preview_from_dict(data: object) -> FrozenGradeReportPreview:
    """Validate one JSON-native #54 report representation for #55 freezing."""

    mapping = _exact_mapping(data, _PREVIEW_KEYS, "GradeReportPreview")
    summary = _summary_from_dict(mapping["summary"])
    rows = tuple(
        _row_from_dict(item)
        for item in _require_list(mapping["rows"], "rows")
    )
    canonical = _canonical_json_bytes(mapping)
    return FrozenGradeReportPreview(
        canonical_json=canonical,
        preview_sha256=hashlib.sha256(canonical).hexdigest(),
        summary=summary,
        rows=rows,
    )


def frozen_grade_report_preview_from_json_bytes(
    data: bytes,
    *,
    maximum_bytes: int = DEFAULT_MAXIMUM_FROZEN_GRADE_REPORT_PREVIEW_BYTES,
) -> FrozenGradeReportPreview:
    """Strictly load canonical #54 report bytes without reopening academic state."""

    if type(data) is not bytes:
        raise ReportingSnapshotPreviewIntegrityError(
            "GradeReportPreview data must be immutable bytes."
        )
    limit = _positive_int(maximum_bytes, "maximum_bytes")
    if len(data) > limit:
        raise ReportingSnapshotPreviewIntegrityError(
            "GradeReportPreview exceeds the configured maximum byte size."
        )
    decoded = _decode_json(data, "GradeReportPreview")
    frozen = frozen_grade_report_preview_from_dict(decoded)
    if frozen.canonical_json != data:
        raise ReportingSnapshotPreviewIntegrityError(
            "GradeReportPreview bytes are not the canonical #54 encoding."
        )
    return frozen


def frozen_grade_report_preview_to_json_bytes(value: FrozenGradeReportPreview) -> bytes:
    """Return the exact canonical #54 report bytes retained by #55."""

    if not isinstance(value, FrozenGradeReportPreview):
        raise ReportingSnapshotPreviewIntegrityError(
            "value must be FrozenGradeReportPreview."
        )
    return bytes(value.canonical_json)


def frozen_grade_report_preview_sha256(value: FrozenGradeReportPreview) -> str:
    """Return the exact SHA-256 identity of one canonical frozen report preview."""

    if not isinstance(value, FrozenGradeReportPreview):
        raise ReportingSnapshotPreviewIntegrityError(
            "value must be FrozenGradeReportPreview."
        )
    return value.preview_sha256


def _row_from_dict(data: object) -> FrozenGradeReportPreviewRow:
    mapping = _exact_mapping(data, _ROW_KEYS, "GradeReportPreview row")
    target = _target_from_dict(mapping["target"])
    status = _require_str(mapping["status"], "row.status")
    if status == "unavailable":
        if mapping["unavailable_reason"] != "no_selected_grade":
            raise ReportingSnapshotPreviewIntegrityError(
                "unavailable row requires no_selected_grade reason."
            )
        if mapping["explanation"] is not None or mapping["observation"] is not None:
            raise ReportingSnapshotPreviewIntegrityError(
                "unavailable row must not carry explanation or observation."
            )
        return FrozenGradeReportPreviewRow(
            target=target,
            status="unavailable",
            unavailable_reason="no_selected_grade",
            observation=None,
            observation_sha256=None,
            explanation_json=None,
            explanation_sha256=None,
        )
    if status != "available":
        raise ReportingSnapshotPreviewIntegrityError(
            "report row status must be available or unavailable."
        )
    if mapping["unavailable_reason"] is not None:
        raise ReportingSnapshotPreviewIntegrityError(
            "available row must not carry unavailable_reason."
        )
    explanation = _require_mapping(mapping["explanation"], "row.explanation")
    observation = grade_preview_observation_from_dict(mapping["observation"])
    if mapping["observation"] != grade_preview_observation_to_dict(observation):
        raise ReportingSnapshotPreviewIntegrityError(
            "embedded observation is not the canonical #54 JSON representation."
        )
    if mapping["target"] != _target_to_dict(target):
        raise ReportingSnapshotPreviewIntegrityError(
            "embedded report target is not the canonical #54 representation."
        )
    if observation.target != target:
        raise ReportingSnapshotPreviewIntegrityError(
            "row observation target does not match row target."
        )
    _validate_explanation_handoff(explanation, target, observation)
    explanation_json = _canonical_json_bytes(explanation)
    return FrozenGradeReportPreviewRow(
        target=target,
        status="available",
        unavailable_reason=None,
        observation=observation,
        observation_sha256=grade_preview_observation_sha256(observation),
        explanation_json=explanation_json,
        explanation_sha256=hashlib.sha256(explanation_json).hexdigest(),
    )


def _validate_explanation_handoff(
    explanation: Mapping[str, object],
    target: GradePreviewTarget,
    observation: GradePreviewObservation,
) -> None:
    family = target.calculation_family
    expected_keys = {
        "conventional": _CONVENTIONAL_KEYS,
        "standards_based": _STANDARDS_KEYS,
        "hybrid": _HYBRID_KEYS,
    }[family]
    mapping = _exact_mapping(explanation, expected_keys, f"{family} explanation")
    common = _validate_common_explanation(mapping["common"], target, observation)
    expected_basis = _common_basis(common, observation)
    if family == "conventional":
        expected_basis.update(_validate_conventional_detail(mapping))
    elif family == "standards_based":
        if _require_str(mapping["status"], "standards.status") != (
            observation.base_result_status
        ):
            raise ReportingSnapshotPreviewIntegrityError(
                "standards explanation status does not match frozen observation."
            )
        expected_basis.update(_validate_standards_detail(mapping))
    else:
        if _require_str(mapping["status"], "hybrid.status") != (
            observation.base_result_status
        ):
            raise ReportingSnapshotPreviewIntegrityError(
                "hybrid explanation status does not match frozen observation."
            )
        expected_basis.update(_validate_hybrid_detail(mapping))
    actual = {
        (entry.dimension, entry.key): entry.sha256
        for entry in observation.basis_entries
    }
    expected_keys_all = (
        _COMMON_BASIS_KEYS
        | {("algorithm", family)}
        | _FAMILY_BASIS_KEYS[family]
    )
    if set(actual) != expected_keys_all:
        raise ReportingSnapshotPreviewIntegrityError(
            "observation basis entries do not match the exact #54 family contract."
        )
    if actual != expected_basis:
        raise ReportingSnapshotPreviewIntegrityError(
            "rich Grade explanation does not reproduce the frozen observation basis."
        )


def _validate_common_explanation(
    data: object,
    target: GradePreviewTarget,
    observation: GradePreviewObservation,
) -> Mapping[str, object]:
    common = _exact_mapping(data, _COMMON_KEYS, "Grade preview common explanation")
    if _target_from_dict(common["target"]) != target:
        raise ReportingSnapshotPreviewIntegrityError(
            "common explanation target does not match report row target."
        )
    base = _exact_mapping(common["base_result"], _BASE_RESULT_KEYS, "base_result")
    try:
        source = grade_override_source_result_reference_from_dict(base["source_result"])
    except (TypeError, ValueError) as error:
        raise ReportingSnapshotPreviewIntegrityError(
            f"base_result source reference is invalid: {error}"
        ) from error
    if source != observation.base_result_reference:
        raise ReportingSnapshotPreviewIntegrityError(
            "common base-result reference does not match frozen observation."
        )
    if (
        _require_str(base["algorithm_version"], "algorithm_version")
        != observation.algorithm_version
    ):
        raise ReportingSnapshotPreviewIntegrityError(
            "common algorithm version does not match frozen observation."
        )
    if (
        _sha256(base["calculation_fingerprint"], "calculation_fingerprint")
        != observation.calculation_fingerprint
    ):
        raise ReportingSnapshotPreviewIntegrityError(
            "common calculation fingerprint does not match frozen observation."
        )
    if _sha256(base["inputs_sha256"], "inputs_sha256") != observation.inputs_sha256:
        raise ReportingSnapshotPreviewIntegrityError(
            "common inputs digest does not match frozen observation."
        )
    _utc_datetime_text(base["calculated_at"], "calculated_at")
    _optional_decimal(base["unrounded_grade"], "unrounded_grade")
    rounded = _optional_decimal(base["rounded_grade"], "rounded_grade")
    if rounded != observation.base_grade:
        raise ReportingSnapshotPreviewIntegrityError(
            "common rounded Grade does not match frozen observation base Grade."
        )
    if (
        _require_str(common["base_result_status"], "base_result_status")
        != observation.base_result_status
    ):
        raise ReportingSnapshotPreviewIntegrityError(
            "common base status does not match frozen observation."
        )
    if _optional_decimal(common["base_grade"], "base_grade") != observation.base_grade:
        raise ReportingSnapshotPreviewIntegrityError(
            "common base Grade does not match frozen observation."
        )
    if (
        _require_str(common["base_freshness_status"], "base_freshness_status")
        != observation.base_freshness_status
    ):
        raise ReportingSnapshotPreviewIntegrityError(
            "common freshness status does not match frozen observation."
        )
    if (
        _string_tuple(
            common["base_freshness_reasons"], "base_freshness_reasons"
        )
        != observation.base_freshness_reasons
    ):
        raise ReportingSnapshotPreviewIntegrityError(
            "common freshness reasons do not match frozen observation."
        )

    policy = _exact_mapping(common["policy"], _POLICY_KEYS, "policy explanation")
    try:
        activation = grade_policy_activation_reference_from_dict(
            policy["activation_reference"]
        )
        policy_reference = grade_policy_reference_from_dict(policy["policy_reference"])
    except (TypeError, ValueError) as error:
        raise ReportingSnapshotPreviewIntegrityError(
            f"policy explanation reference is invalid: {error}"
        ) from error
    if activation != observation.activation_reference:
        raise ReportingSnapshotPreviewIntegrityError(
            "policy activation does not match frozen observation."
        )
    if policy_reference != observation.policy_reference:
        raise ReportingSnapshotPreviewIntegrityError(
            "Grade policy does not match frozen observation."
        )
    _require_str(policy["title"], "policy.title")
    if (
        _require_str(
            policy["calculation_family"], "policy.calculation_family"
        )
        != target.calculation_family
    ):
        raise ReportingSnapshotPreviewIntegrityError(
            "policy family does not match report target."
        )
    for actor_field in ("policy_actor", "activation_actor"):
        actor = _exact_mapping(policy[actor_field], _ACTOR_KEYS, actor_field)
        if _require_str(actor["kind"], f"{actor_field}.kind") not in {
            "teacher",
            "policy",
        }:
            raise ReportingSnapshotPreviewIntegrityError(
                f"{actor_field}.kind is unsupported."
            )
        _require_str(actor["actor_id"], f"{actor_field}.actor_id")
    _optional_str(policy["policy_rationale"], "policy_rationale")
    _optional_str(policy["activation_rationale"], "activation_rationale")
    _utc_datetime_text(policy["policy_revised_at"], "policy_revised_at")
    _utc_datetime_text(policy["activation_decided_at"], "activation_decided_at")
    state_treatment = _exact_mapping(
        policy["state_treatment"], _STATE_TREATMENT_KEYS, "state_treatment"
    )
    for state, consequence in state_treatment.items():
        if _require_str(consequence, f"state_treatment.{state}") not in {
            "exclude",
            "blocking",
            "zero",
        }:
            raise ReportingSnapshotPreviewIntegrityError(
                f"state_treatment.{state} has unsupported consequence."
            )
    reassessment = _exact_mapping(
        policy["reassessment_handling"], _REASSESSMENT_KEYS, "reassessment_handling"
    )
    if (
        _require_str(
            reassessment["selection_authority"], "selection_authority"
        )
        != "v02_attempt_and_reassessment_state"
    ):
        raise ReportingSnapshotPreviewIntegrityError(
            "unsupported reassessment selection authority."
        )
    if _require_str(
        reassessment["unresolved_handling"], "unresolved_handling"
    ) not in {"exclude", "blocking"}:
        raise ReportingSnapshotPreviewIntegrityError(
            "unsupported reassessment unresolved handling."
        )
    rounding = _exact_mapping(policy["rounding"], _ROUNDING_KEYS, "rounding")
    quantum = _decimal(rounding["quantum"], "rounding.quantum")
    if quantum <= 0:
        raise ReportingSnapshotPreviewIntegrityError(
            "rounding.quantum must be positive."
        )
    _require_str(rounding["mode"], "rounding.mode")
    if (
        _require_str(
            rounding["application_stage"], "rounding.application_stage"
        )
        != "final"
    ):
        raise ReportingSnapshotPreviewIntegrityError(
            "rounding application_stage must be final."
        )

    selected_override = common["selected_override"]
    if selected_override is None:
        if observation.selected_override_reference is not None:
            raise ReportingSnapshotPreviewIntegrityError(
                "common explanation omitted selected frozen override."
            )
    else:
        override = _exact_mapping(
            selected_override, _OVERRIDE_KEYS, "selected_override"
        )
        try:
            override_reference = teacher_grade_override_reference_from_dict(
                override["reference"]
            )
            grade_override_source_result_reference_from_dict(override["source_result"])
            if override["withdrawn_override_reference"] is not None:
                teacher_grade_override_reference_from_dict(
                    override["withdrawn_override_reference"]
                )
        except (TypeError, ValueError) as error:
            raise ReportingSnapshotPreviewIntegrityError(
                f"selected override provenance is invalid: {error}"
            ) from error
        if override_reference != observation.selected_override_reference:
            raise ReportingSnapshotPreviewIntegrityError(
                "selected override reference does not match frozen observation."
            )
        _require_str(override["decision"], "override.decision")
        replacement = _optional_decimal(
            override["replacement_grade"], "override.replacement_grade"
        )
        applicability = _require_str(
            override["applicability"], "override.applicability"
        )
        if applicability != observation.override_applicability:
            raise ReportingSnapshotPreviewIntegrityError(
                "override applicability does not match frozen observation."
            )
        if replacement != observation.override_replacement_grade:
            raise ReportingSnapshotPreviewIntegrityError(
                "override replacement Grade does not match frozen observation."
            )
        _require_str(override["actor_id"], "override.actor_id")
        _require_str(override["rationale"], "override.rationale")
        _utc_datetime_text(override["decided_at"], "override.decided_at")
        if _string_tuple(
            override["reasons"], "override.reasons"
        ) != tuple(_expected_override_reasons(observation.override_applicability)):
            raise ReportingSnapshotPreviewIntegrityError(
                "selected override reasons do not match frozen observation."
            )

    if (
        _require_str(
            common["override_applicability"], "override_applicability"
        )
        != observation.override_applicability
    ):
        raise ReportingSnapshotPreviewIntegrityError(
            "common override applicability does not match frozen observation."
        )
    if _string_tuple(
        common["override_reasons"], "override_reasons"
    ) != tuple(_expected_override_reasons(observation.override_applicability)):
        raise ReportingSnapshotPreviewIntegrityError(
            "common override reasons do not match frozen observation."
        )
    if (
        _optional_decimal(common["effective_grade"], "effective_grade")
        != observation.effective_grade
    ):
        raise ReportingSnapshotPreviewIntegrityError(
            "common effective Grade does not match frozen observation."
        )
    if (
        _require_str(common["effective_source"], "effective_source")
        != observation.effective_source
    ):
        raise ReportingSnapshotPreviewIntegrityError(
            "common effective source does not match frozen observation."
        )
    return common


def _common_basis(
    common: Mapping[str, object],
    observation: GradePreviewObservation,
) -> dict[tuple[str, str], str]:
    policy = _require_mapping(common["policy"], "policy")
    state = _require_mapping(policy["state_treatment"], "state_treatment")
    reassessment = _require_mapping(
        policy["reassessment_handling"], "reassessment_handling"
    )
    rounding = _require_mapping(policy["rounding"], "rounding")
    return {
        ("activation", "selected_activation"): (
            observation.activation_reference.activation_sha256
        ),
        ("policy", "grade_policy"): observation.policy_reference.policy_sha256,
        ("state_treatment", "grade_state_treatment"): _common_semantic_digest(
            dict(state)
        ),
        ("reassessment", "grade_reassessment_handling"): (
            _common_semantic_digest(dict(reassessment))
        ),
        ("rounding", "final_grade_rounding"): _common_semantic_digest(
            {
                "quantum": _decimal_text(
                    _decimal(rounding["quantum"], "rounding.quantum")
                ),
                "mode": _require_str(rounding["mode"], "rounding.mode"),
                "application_stage": _require_str(
                    rounding["application_stage"], "rounding.application_stage"
                ),
            }
        ),
        ("algorithm", observation.target.calculation_family): _common_semantic_digest(
            {"algorithm_version": observation.algorithm_version}
        ),
    }


def _validate_conventional_detail(
    mapping: Mapping[str, object],
) -> dict[tuple[str, str], str]:
    mode = _require_str(mapping["mode"], "conventional.mode")
    if mode not in {"total_points", "weighted_items", "weighted_categories"}:
        raise ReportingSnapshotPreviewIntegrityError(
            "unsupported conventional Grade mode."
        )
    items = tuple(
        _validate_conventional_item(item)
        for item in _require_list(mapping["items"], "conventional.items")
    )
    categories = tuple(
        _validate_conventional_category(item)
        for item in _require_list(mapping["categories"], "conventional.categories")
    )
    formula = _exact_mapping(
        mapping["formula"], _CONVENTIONAL_FORMULA_KEYS, "conventional.formula"
    )
    if _require_str(formula["mode"], "formula.mode") != mode:
        raise ReportingSnapshotPreviewIntegrityError(
            "conventional formula mode does not match explanation mode."
        )
    for key in (
        "total_earned",
        "total_possible",
        "final_fraction",
        "unrounded_grade",
        "rounded_grade",
    ):
        _optional_decimal(formula[key], f"formula.{key}")
    for reason in _require_list(mapping["reasons"], "conventional.reasons"):
        value = _exact_mapping(reason, _CONVENTIONAL_REASON_KEYS, "conventional reason")
        _require_str(value["code"], "reason.code")
        if value["grade_item"] is not None:
            _validate_grade_item_reference(value["grade_item"])
        _optional_str(value["category_id"], "reason.category_id")

    participation = [
        {
            "reference": dict(
                cast(Mapping[str, object], item["grade_item_reference"])
            ),
            "category_id": item["category_id"],
            "policy_possible_points": item["policy_possible_points"],
        }
        for item in items
    ]
    weighting = {
        "items": [
            {
                "grade_item_id": cast(
                    Mapping[str, object], item["grade_item_reference"]
                )["grade_item_id"],
                "weight": item["weight"],
            }
            for item in items
        ],
        "categories": [
            {"category_id": item["category_id"], "weight": item["weight"]}
            for item in categories
        ],
    }
    evidence = [
        {
            "grade_item_id": cast(
                Mapping[str, object], item["grade_item_reference"]
            )["grade_item_id"],
            "source_state": item["source_state"],
            "action": item["action"],
            "earned": item["earned"],
            "possible": item["possible"],
            "reason_codes": list(cast(tuple[str, ...], item["reason_codes"])),
            "provenance": [
                dict(value)
                for value in cast(
                    tuple[Mapping[str, object], ...], item["provenance"]
                )
            ],
        }
        for item in items
    ]
    return {
        ("formula", "conventional_formula"): _compact_semantic_digest({"mode": mode}),
        ("participation", "conventional_participation"): (
            _compact_semantic_digest(participation)
        ),
        ("evidence", "conventional_evidence_basis"): _compact_semantic_digest(evidence),
        ("weighting", "conventional_weighting"): _compact_semantic_digest(weighting),
    }


def _validate_conventional_breakdown(data: object) -> dict[tuple[str, str], str]:
    mapping = _exact_mapping(
        data, _CONVENTIONAL_BREAKDOWN_KEYS, "conventional breakdown"
    )
    _require_str(mapping["status"], "conventional.status")
    return _validate_conventional_detail(
        {
            "mode": mapping["mode"],
            "items": mapping["items"],
            "categories": mapping["categories"],
            "formula": mapping["formula"],
            "reasons": mapping["reasons"],
        }
    )


def _validate_conventional_item(data: object) -> dict[str, object]:
    item = _exact_mapping(data, _CONVENTIONAL_ITEM_KEYS, "conventional item")
    grade_item = _exact_mapping(item["grade_item"], _GRADE_ITEM_KEYS, "grade_item")
    reference = _validate_grade_item_reference(grade_item["reference"])
    _require_str(grade_item["title"], "grade_item.title")
    _require_str(grade_item["purpose"], "grade_item.purpose")
    _require_str(grade_item["status"], "grade_item.status")
    category_id = _optional_str(item["category_id"], "category_id")
    weight = _canonical_optional_decimal_text(item["weight"], "weight")
    possible_points = _canonical_optional_decimal_text(
        item["policy_possible_points"], "policy_possible_points"
    )
    source_state = _require_str(item["source_state"], "source_state")
    action = _require_str(item["action"], "action")
    earned = _canonical_optional_decimal_text(item["earned"], "earned")
    possible = _canonical_optional_decimal_text(item["possible"], "possible")
    _canonical_optional_decimal_text(item["percentage"], "percentage")
    _canonical_optional_decimal_text(item["contribution"], "contribution")
    reasons = _string_tuple(item["reason_codes"], "reason_codes")
    provenance: list[Mapping[str, object]] = []
    for raw in _require_list(item["provenance"], "provenance"):
        value = _exact_mapping(raw, _PROVENANCE_KEYS, "conventional provenance")
        provenance.append(
            {
                "kind": _require_str(value["kind"], "provenance.kind"),
                "reference_key": _require_str(
                    value["reference_key"], "provenance.reference_key"
                ),
                "reference_sha256": _sha256(
                    value["reference_sha256"], "provenance.reference_sha256"
                ),
            }
        )
    return {
        "grade_item_reference": reference,
        "category_id": category_id,
        "weight": weight,
        "policy_possible_points": possible_points,
        "source_state": source_state,
        "action": action,
        "earned": earned,
        "possible": possible,
        "reason_codes": reasons,
        "provenance": tuple(provenance),
    }


def _validate_conventional_category(data: object) -> dict[str, object]:
    category = _exact_mapping(
        data, _CONVENTIONAL_CATEGORY_KEYS, "conventional category"
    )
    category_id = _require_str(category["category_id"], "category_id")
    _require_str(category["title"], "category.title")
    weight = _canonical_optional_decimal_text(category["weight"], "category.weight")
    _require_str(category["status"], "category.status")
    _string_tuple(category["included_grade_item_ids"], "included_grade_item_ids")
    _string_tuple(category["excluded_grade_item_ids"], "excluded_grade_item_ids")
    for key in ("earned", "possible", "fraction", "contribution"):
        _canonical_optional_decimal_text(category[key], f"category.{key}")
    _string_tuple(category["reason_codes"], "category.reason_codes")
    return {"category_id": category_id, "weight": weight}


def _validate_grade_item_reference(data: object) -> Mapping[str, object]:
    reference = _exact_mapping(data, _GRADE_ITEM_REFERENCE_KEYS, "Grade Item reference")
    return {
        "class_id": _require_str(reference["class_id"], "grade_item.class_id"),
        "grade_item_id": _require_str(reference["grade_item_id"], "grade_item_id"),
        "grade_item_revision": _positive_int(
            reference["grade_item_revision"], "grade_item_revision"
        ),
        "grade_item_revision_sha256": _sha256(
            reference["grade_item_revision_sha256"], "grade_item_revision_sha256"
        ),
    }


def _validate_standards_detail(
    mapping: Mapping[str, object],
) -> dict[tuple[str, str], str]:
    _require_str(mapping["status"], "standards.status")
    scale = _validate_scale_reference(mapping["target_scale"])
    conversions = tuple(
        _validate_conversion(item)
        for item in _require_list(mapping["conversions"], "standards.conversions")
    )
    standards = tuple(
        _validate_standard(item)
        for item in _require_list(mapping["standards"], "standards.standards")
    )
    formula = _exact_mapping(
        mapping["formula"], _STANDARDS_FORMULA_KEYS, "standards.formula"
    )
    aggregation = _require_str(formula["aggregation_strategy"], "aggregation_strategy")
    minimum = _positive_int(
        formula["minimum_calculated_results"], "minimum_calculated_results"
    )
    _nonnegative_int(
        formula["actual_calculated_result_count"],
        "actual_calculated_result_count",
    )
    for key in (
        "active_weight",
        "weighted_numerator",
        "unrounded_grade",
        "rounded_grade",
    ):
        _canonical_optional_decimal_text(formula[key], f"standards.formula.{key}")
    for reason in _require_list(mapping["reasons"], "standards.reasons"):
        value = _exact_mapping(reason, _STANDARDS_REASON_KEYS, "standards reason")
        _require_str(value["code"], "reason.code")
        _optional_str(value["standard_id"], "reason.standard_id")
        if value["required_results"] is not None:
            _nonnegative_int(value["required_results"], "reason.required_results")
        if value["actual_results"] is not None:
            _nonnegative_int(value["actual_results"], "reason.actual_results")

    formula_basis = {
        "aggregation_strategy": aggregation,
        "minimum_calculated_results": minimum,
        "target_scale": dict(scale),
        "conversions": [dict(item) for item in conversions],
    }
    participation = [{"standard_id": item["standard_id"]} for item in standards]
    weighting = [
        {"standard_id": item["standard_id"], "weight": item["weight"]}
        for item in standards
    ]
    evidence = [
        {
            "standard_id": item["standard_id"],
            "source_state": item["source_state"],
            "action": item["action"],
            "result_reference": item["result_reference"],
            "result_algorithm_version": item["result_algorithm_version"],
            "result_calculation_fingerprint": item["result_calculation_fingerprint"],
            "proficiency_level_id": item["proficiency_level_id"],
            "freshness_status": item["freshness_status"],
            "freshness_reasons": list(cast(tuple[str, ...], item["freshness_reasons"])),
            "reason_codes": list(cast(tuple[str, ...], item["reason_codes"])),
        }
        for item in standards
    ]
    return {
        ("formula", "standards_formula"): _compact_semantic_digest(formula_basis),
        ("participation", "standards_participation"): (
            _compact_semantic_digest(participation)
        ),
        ("evidence", "standards_proficiency_basis"): _compact_semantic_digest(evidence),
        ("weighting", "standards_weighting"): _compact_semantic_digest(weighting),
    }


def _validate_standards_breakdown(data: object) -> dict[tuple[str, str], str]:
    mapping = _exact_mapping(data, _STANDARDS_BREAKDOWN_KEYS, "standards breakdown")
    return _validate_standards_detail(mapping)


def _validate_scale_reference(data: object) -> Mapping[str, object]:
    scale = _exact_mapping(data, _SCALE_REFERENCE_KEYS, "proficiency scale reference")
    return {
        "class_id": _require_str(scale["class_id"], "scale.class_id"),
        "scale_id": _require_str(scale["scale_id"], "scale.scale_id"),
        "scale_revision": _positive_int(
            scale["scale_revision"], "scale.scale_revision"
        ),
        "scale_sha256": _sha256(scale["scale_sha256"], "scale.scale_sha256"),
    }


def _validate_conversion(data: object) -> Mapping[str, object]:
    conversion = _exact_mapping(data, _CONVERSION_KEYS, "standards conversion")
    return {
        "proficiency_level_id": _require_str(
            conversion["proficiency_level_id"], "proficiency_level_id"
        ),
        "grade_value": _canonical_decimal_text(
            conversion["grade_value"], "grade_value"
        ),
    }


def _validate_standard(data: object) -> dict[str, object]:
    standard = _exact_mapping(data, _STANDARD_KEYS, "standards entry")
    standard_id = _require_str(standard["standard_id"], "standard_id")
    weight = _canonical_decimal_text(standard["weight"], "standard.weight")
    source_state = _require_str(standard["source_state"], "standard.source_state")
    action = _require_str(standard["action"], "standard.action")
    result_reference: Mapping[str, object] | None = None
    if standard["result_reference"] is not None:
        try:
            ref = academic_period_proficiency_result_reference_from_dict(
                standard["result_reference"]
            )
        except (TypeError, ValueError) as error:
            raise ReportingSnapshotPreviewIntegrityError(
                f"standards result reference is invalid: {error}"
            ) from error
        result_reference = {
            "class_id": ref.class_id,
            "school_year": ref.school_year,
            "period_id": ref.period_id,
            "student_id": ref.student_id,
            "standard_id": ref.standard_id,
            "result_revision": ref.result_revision,
            "result_sha256": ref.result_sha256,
        }
    result_algorithm = _optional_str(
        standard["result_algorithm_version"], "result_algorithm_version"
    )
    fingerprint = None
    if standard["result_calculation_fingerprint"] is not None:
        fingerprint = _sha256(
            standard["result_calculation_fingerprint"],
            "result_calculation_fingerprint",
        )
    if standard["target_scale"] is not None:
        _validate_scale_reference(standard["target_scale"])
    proficiency_level = _optional_str(
        standard["proficiency_level_id"], "proficiency_level_id"
    )
    for key in ("converted_grade_value", "calculation_value", "weighted_contribution"):
        _canonical_optional_decimal_text(standard[key], f"standard.{key}")
    freshness = _optional_str(standard["freshness_status"], "freshness_status")
    freshness_reasons = _string_tuple(
        standard["freshness_reasons"], "freshness_reasons"
    )
    reason_codes = _string_tuple(standard["reason_codes"], "reason_codes")
    nested = standard["nested_proficiency_explanation"]
    if nested is not None:
        _require_mapping(nested, "nested_proficiency_explanation")
    return {
        "standard_id": standard_id,
        "weight": weight,
        "source_state": source_state,
        "action": action,
        "result_reference": (
            dict(result_reference) if result_reference is not None else None
        ),
        "result_algorithm_version": result_algorithm,
        "result_calculation_fingerprint": fingerprint,
        "proficiency_level_id": proficiency_level,
        "freshness_status": freshness,
        "freshness_reasons": freshness_reasons,
        "reason_codes": reason_codes,
    }


def _validate_hybrid_detail(
    mapping: Mapping[str, object],
) -> dict[tuple[str, str], str]:
    _require_str(mapping["status"], "hybrid.status")
    conventional = _validate_hybrid_component(
        mapping["conventional_component"], "conventional"
    )
    standards = _validate_hybrid_component(
        mapping["standards_component"], "standards_based"
    )
    formula = _exact_mapping(mapping["formula"], _HYBRID_FORMULA_KEYS, "hybrid.formula")
    for key in (
        "active_weight",
        "weighted_numerator",
        "unrounded_grade",
        "rounded_grade",
    ):
        _canonical_optional_decimal_text(formula[key], f"hybrid.formula.{key}")
    for reason in _require_list(mapping["reasons"], "hybrid.reasons"):
        value = _exact_mapping(reason, _HYBRID_REASON_KEYS, "hybrid reason")
        _require_str(value["code"], "hybrid.reason.code")
        component = _optional_str(
            value["component_kind"], "hybrid.reason.component_kind"
        )
        if component not in {None, "conventional", "standards_based"}:
            raise ReportingSnapshotPreviewIntegrityError(
                "hybrid reason component_kind is unsupported."
            )

    conventional_basis = cast(dict[tuple[str, str], str], conventional["basis"])
    standards_basis = cast(dict[tuple[str, str], str], standards["basis"])
    component_identity = {
        "conventional": {
            "algorithm_version": conventional["algorithm_version"],
            "calculation_fingerprint": conventional["calculation_fingerprint"],
            "source_status": conventional["source_status"],
            "action": conventional["action"],
        },
        "standards_based": {
            "algorithm_version": standards["algorithm_version"],
            "calculation_fingerprint": standards["calculation_fingerprint"],
            "source_status": standards["source_status"],
            "action": standards["action"],
        },
    }
    formula_basis = {
        "component_identity": component_identity,
        "conventional_formula_sha256": conventional_basis[
            ("formula", "conventional_formula")
        ],
        "standards_formula_sha256": standards_basis[("formula", "standards_formula")],
    }
    participation = {
        "conventional": conventional_basis[
            ("participation", "conventional_participation")
        ],
        "standards_based": standards_basis[
            ("participation", "standards_participation")
        ],
    }
    evidence = {
        "conventional": conventional_basis[("evidence", "conventional_evidence_basis")],
        "standards_based": standards_basis[("evidence", "standards_proficiency_basis")],
    }
    weighting = {
        "conventional_weight": conventional["configured_weight"],
        "standards_weight": standards["configured_weight"],
        "conventional_component_weighting": conventional_basis[
            ("weighting", "conventional_weighting")
        ],
        "standards_component_weighting": standards_basis[
            ("weighting", "standards_weighting")
        ],
    }
    return {
        ("formula", "hybrid_formula"): _pretty_semantic_digest(formula_basis),
        ("participation", "hybrid_participation"): (
            _pretty_semantic_digest(participation)
        ),
        ("evidence", "hybrid_component_basis"): _pretty_semantic_digest(evidence),
        ("weighting", "hybrid_weighting"): _pretty_semantic_digest(weighting),
    }


def _validate_hybrid_component(data: object, expected_kind: str) -> dict[str, object]:
    component = _exact_mapping(data, _HYBRID_COMPONENT_KEYS, "hybrid component")
    kind = _require_str(component["component_kind"], "component_kind")
    if kind != expected_kind:
        raise ReportingSnapshotPreviewIntegrityError(
            f"hybrid component kind must be {expected_kind}."
        )
    configured_weight = _canonical_decimal_text(
        component["configured_weight"], "configured_weight"
    )
    source_status = _require_str(component["source_status"], "source_status")
    action = _require_str(component["action"], "action")
    algorithm = _require_str(
        component["component_algorithm_version"], "component_algorithm_version"
    )
    fingerprint = _sha256(
        component["component_calculation_fingerprint"],
        "component_calculation_fingerprint",
    )
    _canonical_optional_decimal_text(component["unrounded_grade"], "unrounded_grade")
    _canonical_optional_decimal_text(
        component["weighted_contribution"], "weighted_contribution"
    )
    _string_tuple(component["reason_codes"], "reason_codes")
    if kind == "conventional":
        basis = _validate_conventional_breakdown(component["breakdown"])
    else:
        basis = _validate_standards_breakdown(component["breakdown"])
    return {
        "configured_weight": configured_weight,
        "source_status": source_status,
        "action": action,
        "algorithm_version": algorithm,
        "calculation_fingerprint": fingerprint,
        "basis": basis,
    }


def _expected_override_reasons(applicability: str) -> tuple[str, ...]:
    values: dict[str, tuple[str, ...]] = {
        "no_override": ("no_selected_override",),
        "applicable": (),
        "withdrawn": ("selected_override_withdrawn",),
        "source_result_changed": ("source_result_mismatch",),
        "source_result_stale": ("source_result_stale",),
    }
    try:
        return values[applicability]
    except KeyError as error:
        raise ReportingSnapshotPreviewIntegrityError(
            "unsupported override applicability."
        ) from error


def _summary_from_dict(data: object) -> GradeReportPreviewSummary:
    mapping = _exact_mapping(data, _SUMMARY_KEYS, "GradeReportPreview summary")
    try:
        return GradeReportPreviewSummary(
            requested_count=_nonnegative_int(
                mapping["requested_count"], "requested_count"
            ),
            available_count=_nonnegative_int(
                mapping["available_count"], "available_count"
            ),
            unavailable_count=_nonnegative_int(
                mapping["unavailable_count"], "unavailable_count"
            ),
            base_calculated_count=_nonnegative_int(
                mapping["base_calculated_count"], "base_calculated_count"
            ),
            base_blocked_count=_nonnegative_int(
                mapping["base_blocked_count"], "base_blocked_count"
            ),
            base_insufficient_count=_nonnegative_int(
                mapping["base_insufficient_count"], "base_insufficient_count"
            ),
            current_count=_nonnegative_int(
                mapping["current_count"], "current_count"
            ),
            stale_count=_nonnegative_int(mapping["stale_count"], "stale_count"),
            effective_numeric_count=_nonnegative_int(
                mapping["effective_numeric_count"], "effective_numeric_count"
            ),
            effective_nonnumeric_count=_nonnegative_int(
                mapping["effective_nonnumeric_count"],
                "effective_nonnumeric_count",
            ),
            effective_base_count=_nonnegative_int(
                mapping["effective_base_count"], "effective_base_count"
            ),
            effective_override_count=_nonnegative_int(
                mapping["effective_override_count"], "effective_override_count"
            ),
            effective_none_count=_nonnegative_int(
                mapping["effective_none_count"], "effective_none_count"
            ),
        )
    except (TypeError, ValueError) as error:
        raise ReportingSnapshotPreviewIntegrityError(
            "frozen report summary does not match GradeReportPreview invariants."
        ) from error


def _summary_from_rows(
    rows: tuple[FrozenGradeReportPreviewRow, ...],
) -> GradeReportPreviewSummary:
    available = tuple(row for row in rows if row.status == "available")
    observations = tuple(
        cast(GradePreviewObservation, row.observation) for row in available
    )
    return GradeReportPreviewSummary(
        requested_count=len(rows),
        available_count=len(available),
        unavailable_count=len(rows) - len(available),
        base_calculated_count=sum(
            item.base_result_status == "calculated" for item in observations
        ),
        base_blocked_count=sum(
            item.base_result_status == "blocked" for item in observations
        ),
        base_insufficient_count=sum(
            item.base_result_status == "insufficient" for item in observations
        ),
        current_count=sum(
            item.base_freshness_status == "current" for item in observations
        ),
        stale_count=sum(item.base_freshness_status == "stale" for item in observations),
        effective_numeric_count=sum(
            item.effective_grade is not None for item in observations
        ),
        effective_nonnumeric_count=sum(
            item.effective_grade is None for item in observations
        ),
        effective_base_count=sum(
            item.effective_source == "base" for item in observations
        ),
        effective_override_count=sum(
            item.effective_source == "override" for item in observations
        ),
        effective_none_count=sum(
            item.effective_source == "none" for item in observations
        ),
    )


def _target_from_dict(data: object) -> GradePreviewTarget:
    mapping = _exact_mapping(data, _TARGET_KEYS, "Grade preview target")
    try:
        period = academic_period_ref_from_dict(mapping["target_period"])
        return GradePreviewTarget(
            class_id=_require_str(mapping["class_id"], "class_id"),
            student_id=_require_str(mapping["student_id"], "student_id"),
            target_period=period,
            calendar_revision=_positive_int(
                mapping["calendar_revision"], "calendar_revision"
            ),
            calculation_family=_require_str(
                mapping["calculation_family"], "calculation_family"
            ),  # type: ignore[arg-type]
        )
    except (AcademicPeriodValidationError, TypeError, ValueError) as error:
        raise ReportingSnapshotPreviewIntegrityError(
            f"Grade preview target is invalid: {error}"
        ) from error


def _target_to_dict(value: GradePreviewTarget) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "student_id": value.student_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "calculation_family": value.calculation_family,
    }


def _target_key(value: GradePreviewTarget) -> tuple[str, str, str, str, int, str]:
    return (
        value.class_id,
        value.student_id,
        value.target_period.school_year,
        value.target_period.period_id,
        value.calendar_revision,
        value.calculation_family,
    )


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ReportingSnapshotPreviewIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} is not valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReportingSnapshotPreviewIntegrityError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ReportingSnapshotPreviewIntegrityError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    mapping = _require_mapping(data, label)
    actual = frozenset(mapping.keys())
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return mapping


def _require_mapping(data: object, label: str) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise ReportingSnapshotPreviewIntegrityError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} keys must be strings."
        )
    return cast(Mapping[str, object], data)


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ReportingSnapshotPreviewIntegrityError(f"{label} must be a JSON array.")
    return cast(list[object], value)


def _require_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} must be nonempty text."
        )
    return value


def _optional_str(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, label)


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} must be a positive integer."
        )
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} must be a nonnegative integer."
        )
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} must be a lowercase SHA-256 digest."
        )
    return value


def _decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, str):
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} must be canonical Decimal text."
        )
    try:
        decimal = Decimal(value)
    except InvalidOperation as error:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} must be valid Decimal text."
        ) from error
    if not decimal.is_finite():
        raise ReportingSnapshotPreviewIntegrityError(f"{label} must be finite.")
    if _decimal_text(decimal) != value:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} is not canonical Decimal text."
        )
    return decimal


def _optional_decimal(value: object, label: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, label)


def _canonical_decimal_text(value: object, label: str) -> str:
    return _decimal_text(_decimal(value, label))


def _canonical_optional_decimal_text(value: object, label: str) -> str | None:
    decimal = _optional_decimal(value, label)
    return _decimal_text(decimal) if decimal is not None else None


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    raw = _require_list(value, label)
    result = tuple(_require_str(item, label) for item in raw)
    if len(set(result)) != len(result):
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} must not contain duplicates."
        )
    return result


def _utc_datetime_text(value: object, label: str) -> datetime:
    text = _require_str(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} must be a valid ISO datetime."
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} must be timezone-aware."
        )
    utc = parsed.astimezone(UTC)
    if utc.isoformat() != text:
        raise ReportingSnapshotPreviewIntegrityError(
            f"{label} must use canonical UTC ISO representation."
        )
    return utc


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ReportingSnapshotPreviewIntegrityError(
            "value cannot be represented as canonical #54 JSON."
        ) from error


def _common_semantic_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _compact_semantic_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pretty_semantic_digest(value: object) -> str:
    encoded = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DEFAULT_MAXIMUM_FROZEN_GRADE_REPORT_PREVIEW_BYTES",
    "FrozenGradeReportPreview",
    "FrozenGradeReportPreviewRow",
    "FrozenGradeReportPreviewRowStatus",
    "FrozenGradeReportPreviewUnavailableReason",
    "ReportingSnapshotPreviewIntegrityError",
    "frozen_grade_report_preview_from_dict",
    "frozen_grade_report_preview_from_json_bytes",
    "frozen_grade_report_preview_sha256",
    "frozen_grade_report_preview_to_json_bytes",
    "grade_preview_observation_from_dict",
    "grade_preview_observation_from_json_bytes",
]
