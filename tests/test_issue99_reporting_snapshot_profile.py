from __future__ import annotations

import json
from dataclasses import replace

import pytest

import meridian.standards_grade_explanation as standards_explanation
from meridian.grade_preview_comparison import (
    PriorReportingSnapshotGradeBasis,
    compare_grade_preview_basis,
)
from meridian.grade_preview_explanation import (
    GradePreviewBasisEntry,
    grade_preview_observation_to_dict,
)
from meridian.reporting_snapshot_preview import (
    ReportingSnapshotPreviewIntegrityError,
    frozen_grade_report_preview_from_json_bytes,
)
from tests.test_issue99_profile_grade_explanation import (
    _profile_basis,
    _stub_standard,
)
from tests.test_reporting_snapshot_preview_issue55 import (
    _available_preview_bytes,
    _canonical_json_bytes,
    _common_explanation,
    _conventional_detail,
    _observation,
    _pretty_digest,
    _target,
)


def _profile_standards_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], tuple[GradePreviewBasisEntry, ...]]:
    inputs, outcome = _profile_basis()
    monkeypatch.setattr(
        standards_explanation,
        "_standard_explanation",
        lambda _root, result: _stub_standard(result),
    )
    breakdown = standards_explanation.explain_standards_grade_breakdown(
        ".",
        inputs,
        outcome,
    )
    return (
        standards_explanation.standards_grade_breakdown_to_dict(breakdown),
        standards_explanation.standards_grade_breakdown_basis_entries(breakdown),
    )


def _profile_hybrid_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], tuple[GradePreviewBasisEntry, ...]]:
    conventional, conventional_entries = _conventional_detail()
    standards, standards_entries = _profile_standards_detail(monkeypatch)
    conventional_basis = {
        (entry.dimension, entry.key): entry.sha256 for entry in conventional_entries
    }
    standards_basis = {
        (entry.dimension, entry.key): entry.sha256 for entry in standards_entries
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
        "breakdown": {"status": "calculated", **conventional},
    }
    standards_component = {
        "component_kind": "standards_based",
        "configured_weight": "0.5",
        "source_status": "calculated",
        "action": "contribute",
        "component_algorithm_version": "2",
        "component_calculation_fingerprint": "4" * 64,
        "unrounded_grade": "90",
        "weighted_contribution": "45",
        "reason_codes": [],
        "breakdown": standards,
    }
    component_identity = {
        "conventional": {
            "algorithm_version": "1",
            "calculation_fingerprint": "3" * 64,
            "source_status": "calculated",
            "action": "contribute",
        },
        "standards_based": {
            "algorithm_version": "2",
            "calculation_fingerprint": "4" * 64,
            "source_status": "calculated",
            "action": "contribute",
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
    basis: list[GradePreviewBasisEntry] = [
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
    ]
    profile_keys = {
        "standards_profile_policy",
        "standards_base_mean",
        "standards_profile_predicates",
        "standards_profile_band",
        "standards_profile_adjustment",
    }
    basis.extend(
        GradePreviewBasisEntry(
            entry.dimension,
            f"hybrid_{entry.key}",
            entry.sha256,
        )
        for entry in standards_entries
        if entry.key in profile_keys
    )
    detail = {
        "status": "calculated",
        "conventional_component": conventional_component,
        "standards_component": standards_component,
        "formula": {
            "active_weight": "1",
            "weighted_numerator": "90",
            "unrounded_grade": "90",
            "rounded_grade": "90",
        },
        "reasons": [],
    }
    return detail, tuple(basis)


def _profile_preview_bytes(
    family: str,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[bytes, object]:
    target = _target(family)
    if family == "standards_based":
        detail, basis = _profile_standards_detail(monkeypatch)
    elif family == "hybrid":
        detail, basis = _profile_hybrid_detail(monkeypatch)
    else:
        raise AssertionError(family)

    explanation = {
        "common": _common_explanation(
            target,
            base_status="calculated",
            base_grade="90",
            unrounded_grade="90",
            effective_grade="90",
            effective_source="base",
        ),
        **detail,
    }
    observation = _observation(
        target,
        family_basis=basis,
        base_status="calculated",
        base_grade="90",
        effective_grade="90",
        effective_source="base",
    )
    report = {
        "summary": {
            "requested_count": 1,
            "available_count": 1,
            "unavailable_count": 0,
            "base_calculated_count": 1,
            "base_blocked_count": 0,
            "base_insufficient_count": 0,
            "current_count": 1,
            "stale_count": 0,
            "effective_numeric_count": 1,
            "effective_nonnumeric_count": 0,
            "effective_base_count": 1,
            "effective_override_count": 0,
            "effective_none_count": 0,
        },
        "rows": [
            {
                "target": explanation["common"]["target"],
                "status": "available",
                "unavailable_reason": None,
                "explanation": explanation,
                "observation": grade_preview_observation_to_dict(observation),
            }
        ],
    }
    return _canonical_json_bytes(report), observation


@pytest.mark.parametrize("family", ("standards_based", "hybrid"))
def test_profile_preview_reloads_with_exact_historical_profile_basis(
    family: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded, observation = _profile_preview_bytes(family, monkeypatch)

    frozen = frozen_grade_report_preview_from_json_bytes(encoded)

    row = frozen.rows[0]
    assert row.observation == observation
    assert row.explanation_json is not None
    rich = json.loads(row.explanation_json)
    standards = (
        rich
        if family == "standards_based"
        else rich["standards_component"]["breakdown"]
    )
    formula = standards["formula"]
    assert formula["aggregation_strategy"] == "profile_constrained_mean"
    assert formula["base_unrounded_grade"] == "87"
    assert formula["selected_profile_band_id"] == "high"
    assert formula["selected_profile_band_minimum_grade"] == "90"
    assert formula["selected_profile_band_maximum_grade"] == "100"
    assert formula["profile_adjustment"] == "floor"
    assert (
        formula["profile_evaluation"]["bands"][0]["predicates"][0]["status"]
        == "matched"
    )

    keys = {entry.key for entry in row.observation.basis_entries}
    prefix = "" if family == "standards_based" else "hybrid_"
    assert f"{prefix}standards_profile_policy" in keys
    assert f"{prefix}standards_base_mean" in keys
    assert f"{prefix}standards_profile_predicates" in keys
    assert f"{prefix}standards_profile_band" in keys
    assert f"{prefix}standards_profile_adjustment" in keys


def test_legacy_weighted_snapshot_shape_remains_reloadable() -> None:
    encoded, observation = _available_preview_bytes("standards_based")

    frozen = frozen_grade_report_preview_from_json_bytes(encoded)

    assert frozen.rows[0].observation == observation


def test_profile_predicate_tamper_is_rejected_against_frozen_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded, _ = _profile_preview_bytes("standards_based", monkeypatch)
    data = json.loads(encoded)
    predicate = data["rows"][0]["explanation"]["formula"][
        "profile_evaluation"
    ]["bands"][0]["predicates"][0]
    predicate["threshold_level_id"] = "exceeding"

    with pytest.raises(
        ReportingSnapshotPreviewIntegrityError,
        match="does not reproduce the frozen observation basis",
    ):
        frozen_grade_report_preview_from_json_bytes(_canonical_json_bytes(data))


@pytest.mark.parametrize(
    ("family", "key", "reason"),
    (
        (
            "standards_based",
            "standards_profile_band",
            "profile_band_changed",
        ),
        (
            "hybrid",
            "hybrid_standards_profile_policy",
            "profile_policy_changed",
        ),
    ),
)
def test_reloaded_profile_basis_drives_specific_historical_comparison(
    family: str,
    key: str,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded, _ = _profile_preview_bytes(family, monkeypatch)
    frozen = frozen_grade_report_preview_from_json_bytes(encoded)
    prior_observation = frozen.rows[0].observation
    assert prior_observation is not None

    changed_entries = tuple(
        replace(entry, sha256="f" * 64) if entry.key == key else entry
        for entry in prior_observation.basis_entries
    )
    current = replace(
        prior_observation,
        inputs_sha256="8" * 64,
        calculation_fingerprint="9" * 64,
        basis_entries=changed_entries,
    )

    comparison = compare_grade_preview_basis(
        current,
        PriorReportingSnapshotGradeBasis(prior_observation),
    )

    assert comparison.reasons == (reason,)
