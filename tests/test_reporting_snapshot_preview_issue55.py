from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.grade_policy import GradePolicyReference
from meridian.grade_policy_activation import GradePolicyActivationReference
from meridian.grade_preview_explanation import (
    GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
    GradePreviewBasisEntry,
    GradePreviewObservation,
    GradePreviewTarget,
    grade_preview_observation_to_dict,
    grade_preview_observation_to_json_bytes,
)
from meridian.grade_report_preview import (
    GradeReportPreview,
    GradeReportPreviewRow,
    grade_report_preview_to_json_bytes,
)
from meridian.hybrid_grade_result import HybridGradeResultReference
from meridian.reporting_snapshot_preview import (
    DEFAULT_MAXIMUM_FROZEN_GRADE_REPORT_PREVIEW_BYTES,
    FrozenGradeReportPreview,
    ReportingSnapshotPreviewIntegrityError,
    frozen_grade_report_preview_from_json_bytes,
    frozen_grade_report_preview_sha256,
    frozen_grade_report_preview_to_json_bytes,
    grade_preview_observation_from_json_bytes,
)
from meridian.standards_grade_result import StandardsGradeResultReference
from meridian.teacher_grade_override import GradeOverrideSourceResultReference

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def _canonical_json_bytes(value: object) -> bytes:
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


def _common_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _compact_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pretty_digest(value: object) -> str:
    encoded = (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _target(
    family: str = "conventional",
    student_id: str = "student_001",
) -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=student_id,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family=family,  # type: ignore[arg-type]
    )


def _source_reference(target: GradePreviewTarget) -> GradeOverrideSourceResultReference:
    kwargs = {
        "class_id": target.class_id,
        "student_id": target.student_id,
        "school_year": target.target_period.school_year,
        "period_id": target.target_period.period_id,
        "calendar_revision": target.calendar_revision,
        "result_revision": 1,
        "result_sha256": SHA_A,
    }
    if target.calculation_family == "conventional":
        reference = ConventionalGradeResultReference(**kwargs)
    elif target.calculation_family == "standards_based":
        reference = StandardsGradeResultReference(**kwargs)
    else:
        reference = HybridGradeResultReference(**kwargs)
    return GradeOverrideSourceResultReference(
        target.calculation_family,
        reference,
    )


def _state_treatment() -> dict[str, str]:
    return {
        "missing": "blocking",
        "pending": "blocking",
        "incomplete": "blocking",
        "excused": "exclude",
        "excluded": "exclude",
        "not_applicable": "exclude",
        "insufficient_evidence": "blocking",
        "unavailable": "blocking",
        "withdrawn": "exclude",
        "invalid": "exclude",
        "unresolved": "blocking",
    }


def _policy_data(target: GradePreviewTarget) -> dict[str, object]:
    return {
        "activation_reference": {
            "class_id": target.class_id,
            "school_year": target.target_period.school_year,
            "period_id": target.target_period.period_id,
            "activation_revision": 1,
            "activation_sha256": SHA_D,
        },
        "policy_reference": {
            "class_id": target.class_id,
            "policy_id": "course_grade",
            "policy_revision": 1,
            "policy_sha256": SHA_E,
        },
        "title": "Course Grade",
        "calculation_family": target.calculation_family,
        "policy_actor": {"kind": "teacher", "actor_id": "teacher_local"},
        "policy_rationale": None,
        "policy_revised_at": "2026-09-19T22:00:00+00:00",
        "activation_actor": {"kind": "teacher", "actor_id": "teacher_local"},
        "activation_rationale": None,
        "activation_decided_at": "2026-09-19T22:05:00+00:00",
        "state_treatment": _state_treatment(),
        "reassessment_handling": {
            "selection_authority": "v02_attempt_and_reassessment_state",
            "unresolved_handling": "blocking",
        },
        "rounding": {
            "quantum": "0.01",
            "mode": "half_up",
            "application_stage": "final",
        },
    }


def _common_basis(target: GradePreviewTarget) -> list[GradePreviewBasisEntry]:
    policy = _policy_data(target)
    return [
        GradePreviewBasisEntry("activation", "selected_activation", SHA_D),
        GradePreviewBasisEntry("policy", "grade_policy", SHA_E),
        GradePreviewBasisEntry(
            "state_treatment",
            "grade_state_treatment",
            _common_digest(policy["state_treatment"]),
        ),
        GradePreviewBasisEntry(
            "reassessment",
            "grade_reassessment_handling",
            _common_digest(policy["reassessment_handling"]),
        ),
        GradePreviewBasisEntry(
            "rounding",
            "final_grade_rounding",
            _common_digest(policy["rounding"]),
        ),
        GradePreviewBasisEntry(
            "algorithm",
            target.calculation_family,
            _common_digest({"algorithm_version": "1"}),
        ),
    ]


def _common_explanation(
    target: GradePreviewTarget,
    *,
    base_status: str,
    base_grade: str | None,
    unrounded_grade: str | None,
    effective_grade: str | None,
    effective_source: str,
) -> dict[str, object]:
    source = grade_preview_observation_to_dict(
        _observation(
            target,
            family_basis=(),
            base_status=base_status,
            base_grade=base_grade,
            effective_grade=effective_grade,
            effective_source=effective_source,
            include_family_basis=False,
        )
    )["base_result_reference"]
    return {
        "target": {
            "class_id": target.class_id,
            "student_id": target.student_id,
            "target_period": {
                "school_year": target.target_period.school_year,
                "period_id": target.target_period.period_id,
            },
            "calendar_revision": target.calendar_revision,
            "calculation_family": target.calculation_family,
        },
        "base_result": {
            "source_result": source,
            "algorithm_version": "1",
            "calculation_fingerprint": SHA_B,
            "inputs_sha256": SHA_C,
            "calculated_at": "2026-09-19T22:10:00+00:00",
            "unrounded_grade": unrounded_grade,
            "rounded_grade": base_grade,
        },
        "base_result_status": base_status,
        "base_grade": base_grade,
        "base_freshness_status": "current",
        "base_freshness_reasons": [],
        "policy": _policy_data(target),
        "selected_override": None,
        "override_applicability": "no_override",
        "override_reasons": ["no_selected_override"],
        "effective_grade": effective_grade,
        "effective_source": effective_source,
    }


def _observation(
    target: GradePreviewTarget,
    *,
    family_basis: tuple[GradePreviewBasisEntry, ...],
    base_status: str = "calculated",
    base_grade: str | None = "90",
    effective_grade: str | None = "90",
    effective_source: str = "base",
    include_family_basis: bool = True,
) -> GradePreviewObservation:
    source = _source_reference(target)
    common = tuple(_common_basis(target))
    entries = common + family_basis if include_family_basis else common
    return GradePreviewObservation(
        schema_version=GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
        target=target,
        base_result_reference=source,
        base_result_status=base_status,
        base_grade=Decimal(base_grade) if base_grade is not None else None,
        base_freshness_status="current",
        base_freshness_reasons=(),
        algorithm_version="1",
        calculation_fingerprint=SHA_B,
        inputs_sha256=SHA_C,
        activation_reference=GradePolicyActivationReference(
            target.class_id,
            target.target_period.school_year,
            target.target_period.period_id,
            1,
            SHA_D,
        ),
        policy_reference=GradePolicyReference(
            target.class_id,
            "course_grade",
            1,
            SHA_E,
        ),
        selected_override_reference=None,
        override_applicability="no_override",
        override_replacement_grade=None,
        effective_grade=(
            Decimal(effective_grade) if effective_grade is not None else None
        ),
        effective_source=effective_source,  # type: ignore[arg-type]
        basis_entries=entries,
    )


def _conventional_detail(
) -> tuple[dict[str, object], tuple[GradePreviewBasisEntry, ...]]:
    reference = {
        "class_id": CLASS_ID,
        "grade_item_id": "unit_test",
        "grade_item_revision": 1,
        "grade_item_revision_sha256": "1" * 64,
    }
    item = {
        "grade_item": {
            "reference": reference,
            "title": "Unit Test",
            "purpose": "conventional",
            "status": "active",
        },
        "category_id": None,
        "weight": None,
        "policy_possible_points": "100",
        "source_state": "points",
        "action": "contribute",
        "earned": "90",
        "possible": "100",
        "percentage": "90",
        "contribution": "90",
        "reason_codes": [],
        "provenance": [],
    }
    formula = {
        "mode": "total_points",
        "total_earned": "90",
        "total_possible": "100",
        "final_fraction": "0.9",
        "unrounded_grade": "90",
        "rounded_grade": "90",
    }
    detail = {
        "mode": "total_points",
        "items": [item],
        "categories": [],
        "formula": formula,
        "reasons": [],
    }
    participation = [
        {
            "reference": reference,
            "category_id": None,
            "policy_possible_points": "100",
        }
    ]
    weighting = {
        "items": [{"grade_item_id": "unit_test", "weight": None}],
        "categories": [],
    }
    evidence = [
        {
            "grade_item_id": "unit_test",
            "source_state": "points",
            "action": "contribute",
            "earned": "90",
            "possible": "100",
            "reason_codes": [],
            "provenance": [],
        }
    ]
    basis = (
        GradePreviewBasisEntry(
            "formula",
            "conventional_formula",
            _compact_digest({"mode": "total_points"}),
        ),
        GradePreviewBasisEntry(
            "participation",
            "conventional_participation",
            _compact_digest(participation),
        ),
        GradePreviewBasisEntry(
            "evidence",
            "conventional_evidence_basis",
            _compact_digest(evidence),
        ),
        GradePreviewBasisEntry(
            "weighting",
            "conventional_weighting",
            _compact_digest(weighting),
        ),
    )
    return detail, basis


def _standards_detail() -> tuple[dict[str, object], tuple[GradePreviewBasisEntry, ...]]:
    scale = {
        "class_id": CLASS_ID,
        "scale_id": "course_scale",
        "scale_revision": 1,
        "scale_sha256": "2" * 64,
    }
    conversions = [{"proficiency_level_id": "proficient", "grade_value": "85"}]
    formula = {
        "aggregation_strategy": "weighted_mean",
        "minimum_calculated_results": 1,
        "actual_calculated_result_count": 0,
        "active_weight": None,
        "weighted_numerator": None,
        "unrounded_grade": None,
        "rounded_grade": None,
    }
    detail = {
        "status": "insufficient",
        "target_scale": scale,
        "conversions": conversions,
        "standards": [],
        "formula": formula,
        "reasons": [],
    }
    formula_basis = {
        "aggregation_strategy": "weighted_mean",
        "minimum_calculated_results": 1,
        "target_scale": scale,
        "conversions": conversions,
    }
    basis = (
        GradePreviewBasisEntry(
            "formula",
            "standards_formula",
            _compact_digest(formula_basis),
        ),
        GradePreviewBasisEntry(
            "participation",
            "standards_participation",
            _compact_digest([]),
        ),
        GradePreviewBasisEntry(
            "evidence",
            "standards_proficiency_basis",
            _compact_digest([]),
        ),
        GradePreviewBasisEntry(
            "weighting",
            "standards_weighting",
            _compact_digest([]),
        ),
    )
    return detail, basis


def _hybrid_detail() -> tuple[dict[str, object], tuple[GradePreviewBasisEntry, ...]]:
    conventional, conventional_basis_entries = _conventional_detail()
    standards, standards_basis_entries = _standards_detail()
    conventional_breakdown = {
        "status": "calculated",
        **conventional,
    }
    standards_breakdown = standards
    conventional_basis = {
        (entry.dimension, entry.key): entry.sha256
        for entry in conventional_basis_entries
    }
    standards_basis = {
        (entry.dimension, entry.key): entry.sha256 for entry in standards_basis_entries
    }
    conventional_component = {
        "component_kind": "conventional",
        "configured_weight": "0.5",
        "source_status": "calculated",
        "action": "contribute",
        "component_algorithm_version": "1",
        "component_calculation_fingerprint": "3" * 64,
        "unrounded_grade": "90",
        "weighted_contribution": "45",
        "reason_codes": [],
        "breakdown": conventional_breakdown,
    }
    standards_component = {
        "component_kind": "standards_based",
        "configured_weight": "0.5",
        "source_status": "insufficient",
        "action": "blocking",
        "component_algorithm_version": "1",
        "component_calculation_fingerprint": "4" * 64,
        "unrounded_grade": None,
        "weighted_contribution": None,
        "reason_codes": [],
        "breakdown": standards_breakdown,
    }
    detail = {
        "status": "blocked",
        "conventional_component": conventional_component,
        "standards_component": standards_component,
        "formula": {
            "active_weight": None,
            "weighted_numerator": None,
            "unrounded_grade": None,
            "rounded_grade": None,
        },
        "reasons": [],
    }
    component_identity = {
        "conventional": {
            "algorithm_version": "1",
            "calculation_fingerprint": "3" * 64,
            "source_status": "calculated",
            "action": "contribute",
        },
        "standards_based": {
            "algorithm_version": "1",
            "calculation_fingerprint": "4" * 64,
            "source_status": "insufficient",
            "action": "blocking",
        },
    }
    formula_basis = {
        "component_identity": component_identity,
        "conventional_formula_sha256": conventional_basis[
            ("formula", "conventional_formula")
        ],
        "standards_formula_sha256": standards_basis[
            ("formula", "standards_formula")
        ],
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
        "conventional": conventional_basis[
            ("evidence", "conventional_evidence_basis")
        ],
        "standards_based": standards_basis[
            ("evidence", "standards_proficiency_basis")
        ],
    }
    weighting = {
        "conventional_weight": "0.5",
        "standards_weight": "0.5",
        "conventional_component_weighting": conventional_basis[
            ("weighting", "conventional_weighting")
        ],
        "standards_component_weighting": standards_basis[
            ("weighting", "standards_weighting")
        ],
    }
    basis = (
        GradePreviewBasisEntry(
            "formula", "hybrid_formula", _pretty_digest(formula_basis)
        ),
        GradePreviewBasisEntry(
            "participation",
            "hybrid_participation",
            _pretty_digest(participation),
        ),
        GradePreviewBasisEntry(
            "evidence", "hybrid_component_basis", _pretty_digest(evidence)
        ),
        GradePreviewBasisEntry(
            "weighting", "hybrid_weighting", _pretty_digest(weighting)
        ),
    )
    return detail, basis


def _available_preview_bytes(family: str) -> tuple[bytes, GradePreviewObservation]:
    target = _target(family)
    if family == "conventional":
        detail, basis = _conventional_detail()
        base_status = "calculated"
        base_grade = "90"
        effective_grade = "90"
        effective_source = "base"
        explanation = {
            "common": _common_explanation(
                target,
                base_status=base_status,
                base_grade=base_grade,
                unrounded_grade="90",
                effective_grade=effective_grade,
                effective_source=effective_source,
            ),
            **detail,
        }
    elif family == "standards_based":
        detail, basis = _standards_detail()
        base_status = "insufficient"
        base_grade = None
        effective_grade = None
        effective_source = "none"
        explanation = {
            "common": _common_explanation(
                target,
                base_status=base_status,
                base_grade=base_grade,
                unrounded_grade=None,
                effective_grade=effective_grade,
                effective_source=effective_source,
            ),
            **detail,
        }
    else:
        detail, basis = _hybrid_detail()
        base_status = "blocked"
        base_grade = None
        effective_grade = None
        effective_source = "none"
        explanation = {
            "common": _common_explanation(
                target,
                base_status=base_status,
                base_grade=base_grade,
                unrounded_grade=None,
                effective_grade=effective_grade,
                effective_source=effective_source,
            ),
            **detail,
        }
    observation = _observation(
        target,
        family_basis=basis,
        base_status=base_status,
        base_grade=base_grade,
        effective_grade=effective_grade,
        effective_source=effective_source,
    )
    summary = {
        "requested_count": 1,
        "available_count": 1,
        "unavailable_count": 0,
        "base_calculated_count": int(base_status == "calculated"),
        "base_blocked_count": int(base_status == "blocked"),
        "base_insufficient_count": int(base_status == "insufficient"),
        "current_count": 1,
        "stale_count": 0,
        "effective_numeric_count": int(effective_grade is not None),
        "effective_nonnumeric_count": int(effective_grade is None),
        "effective_base_count": int(effective_source == "base"),
        "effective_override_count": 0,
        "effective_none_count": int(effective_source == "none"),
    }
    report = {
        "summary": summary,
        "rows": [
            {
                "target": explanation["common"]["target"],  # type: ignore[index]
                "status": "available",
                "unavailable_reason": None,
                "explanation": explanation,
                "observation": grade_preview_observation_to_dict(observation),
            }
        ],
    }
    return _canonical_json_bytes(report), observation


def test_observation_strict_round_trip_reconstructs_typed_contract() -> None:
    _, basis = _conventional_detail()
    original = _observation(_target(), family_basis=basis)
    encoded = grade_preview_observation_to_json_bytes(original)

    loaded = grade_preview_observation_from_json_bytes(encoded)

    assert loaded == original
    assert grade_preview_observation_to_json_bytes(loaded) == encoded


def test_observation_rejects_noncanonical_json_bytes() -> None:
    _, basis = _conventional_detail()
    original = _observation(_target(), family_basis=basis)
    data = grade_preview_observation_to_dict(original)
    noncanonical = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")

    with pytest.raises(
        ReportingSnapshotPreviewIntegrityError,
        match="canonical #54 encoding",
    ):
        grade_preview_observation_from_json_bytes(noncanonical)


def test_observation_rejects_duplicate_object_keys() -> None:
    _, basis = _conventional_detail()
    original = _observation(_target(), family_basis=basis)
    encoded = grade_preview_observation_to_json_bytes(original).decode("utf-8")
    duplicate = encoded.replace(
        '"schema_version":"1",',
        '"schema_version":"1","schema_version":"1",',
        1,
    ).encode("utf-8")

    with pytest.raises(
        ReportingSnapshotPreviewIntegrityError,
        match="duplicate JSON object key",
    ):
        grade_preview_observation_from_json_bytes(duplicate)


def test_unavailable_exact_issue54_preview_reloads_without_fake_observation() -> None:
    target = _target("standards_based")
    preview = GradeReportPreview(
        (
            GradeReportPreviewRow(
                target=target,
                status="unavailable",
                explanation=None,
                observation=None,
                unavailable_reason="no_selected_grade",
            ),
        )
    )
    encoded = grade_report_preview_to_json_bytes(preview)

    frozen = frozen_grade_report_preview_from_json_bytes(encoded)

    assert frozen_grade_report_preview_to_json_bytes(frozen) == encoded
    assert frozen.summary.unavailable_count == 1
    assert frozen.rows[0].observation is None
    assert frozen.rows[0].explanation_json is None
    assert frozen_grade_report_preview_sha256(frozen) == hashlib.sha256(
        encoded
    ).hexdigest()


@pytest.mark.parametrize(
    "family",
    ["conventional", "standards_based", "hybrid"],
)
def test_available_family_preview_reloads_and_preserves_observation_basis(
    family: str,
) -> None:
    encoded, observation = _available_preview_bytes(family)

    frozen = frozen_grade_report_preview_from_json_bytes(encoded)

    assert frozen.rows[0].observation == observation
    assert frozen.rows[0].observation_sha256 is not None
    assert frozen.rows[0].explanation_json is not None
    assert frozen.preview_sha256 == hashlib.sha256(encoded).hexdigest()


def test_report_rejects_summary_that_does_not_match_rows() -> None:
    encoded, _ = _available_preview_bytes("conventional")
    data = json.loads(encoded)
    data["summary"]["available_count"] = 0
    data["summary"]["unavailable_count"] = 1

    with pytest.raises(
        ReportingSnapshotPreviewIntegrityError,
        match="summary does not match",
    ):
        frozen_grade_report_preview_from_json_bytes(_canonical_json_bytes(data))


def test_report_rejects_common_state_that_disagrees_with_observation() -> None:
    encoded, _ = _available_preview_bytes("conventional")
    data = json.loads(encoded)
    data["rows"][0]["explanation"]["common"]["effective_grade"] = "89"

    with pytest.raises(
        ReportingSnapshotPreviewIntegrityError,
        match="effective Grade does not match",
    ):
        frozen_grade_report_preview_from_json_bytes(_canonical_json_bytes(data))


def test_report_rejects_family_detail_that_breaks_observation_basis() -> None:
    encoded, _ = _available_preview_bytes("conventional")
    data = json.loads(encoded)
    data["rows"][0]["explanation"]["items"][0]["earned"] = "89"

    with pytest.raises(
        ReportingSnapshotPreviewIntegrityError,
        match="does not reproduce the frozen observation basis",
    ):
        frozen_grade_report_preview_from_json_bytes(_canonical_json_bytes(data))


def test_report_rejects_unknown_explanation_field() -> None:
    encoded, _ = _available_preview_bytes("conventional")
    data = json.loads(encoded)
    data["rows"][0]["explanation"]["official_grade"] = True

    with pytest.raises(
        ReportingSnapshotPreviewIntegrityError,
        match="exact schema",
    ):
        frozen_grade_report_preview_from_json_bytes(_canonical_json_bytes(data))


def test_report_rejects_noncanonical_encoding() -> None:
    encoded, _ = _available_preview_bytes("conventional")
    data = json.loads(encoded)
    noncanonical = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")

    with pytest.raises(
        ReportingSnapshotPreviewIntegrityError,
        match="canonical #54 encoding",
    ):
        frozen_grade_report_preview_from_json_bytes(noncanonical)


def test_report_rejects_oversized_input_before_json_decode() -> None:
    encoded, _ = _available_preview_bytes("conventional")
    with pytest.raises(
        ReportingSnapshotPreviewIntegrityError,
        match="maximum byte size",
    ):
        frozen_grade_report_preview_from_json_bytes(
            encoded,
            maximum_bytes=len(encoded) - 1,
        )

    assert len(encoded) < DEFAULT_MAXIMUM_FROZEN_GRADE_REPORT_PREVIEW_BYTES


def test_frozen_preview_and_rows_are_immutable() -> None:
    encoded, _ = _available_preview_bytes("conventional")
    frozen = frozen_grade_report_preview_from_json_bytes(encoded)

    with pytest.raises(FrozenInstanceError):
        frozen.preview_sha256 = SHA_A  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        frozen.rows[0].status = "unavailable"  # type: ignore[misc]
    assert isinstance(frozen, FrozenGradeReportPreview)


def test_contradictory_preview_digest_is_rejected_by_model() -> None:
    encoded, _ = _available_preview_bytes("conventional")
    frozen = frozen_grade_report_preview_from_json_bytes(encoded)

    with pytest.raises(
        ReportingSnapshotPreviewIntegrityError,
        match="digest does not match",
    ):
        replace(frozen, preview_sha256=SHA_A)
