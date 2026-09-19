from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.grade_policy import GradePolicyReference
from meridian.grade_policy_activation import GradePolicyActivationReference
from meridian.grade_preview_comparison import (
    PriorReportingSnapshotGradeBasis,
    compare_grade_preview_basis,
    grade_preview_comparison_to_json_bytes,
    prior_reporting_snapshot_grade_basis_from_observation,
    prior_reporting_snapshot_grade_basis_to_json_bytes,
)
from meridian.grade_preview_explanation import (
    GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
    GradePreviewBasisEntry,
    GradePreviewComparisonError,
    GradePreviewObservation,
    GradePreviewTarget,
)
from meridian.hybrid_grade_result import HybridGradeResultReference
from meridian.standards_grade_result import StandardsGradeResultReference
from meridian.teacher_grade_override import (
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideReference,
)

CLASS_ID = "english_12"
STUDENT_ID = "student_001"
PERIOD = AcademicPeriodRef("2026-2027", "q1")


def _target(family: str = "conventional") -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family=family,  # type: ignore[arg-type]
    )


def _source_reference(
    family: str,
    *,
    revision: int = 1,
    digest: str = "a" * 64,
) -> GradeOverrideSourceResultReference:
    common = dict(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        school_year=PERIOD.school_year,
        period_id=PERIOD.period_id,
        calendar_revision=1,
        result_revision=revision,
        result_sha256=digest,
    )
    if family == "conventional":
        reference = ConventionalGradeResultReference(**common)
    elif family == "standards_based":
        reference = StandardsGradeResultReference(**common)
    else:
        reference = HybridGradeResultReference(**common)
    return GradeOverrideSourceResultReference(
        family,  # type: ignore[arg-type]
        reference,
    )


def _entries(family: str) -> tuple[GradePreviewBasisEntry, ...]:
    dimensions = (
        "activation",
        "policy",
        "state_treatment",
        "reassessment",
        "rounding",
        "algorithm",
        "formula",
        "participation",
        "evidence",
        "weighting",
    )
    return tuple(
        GradePreviewBasisEntry(
            dimension,  # type: ignore[arg-type]
            f"{family}:{dimension}",
            f"{index:x}" * 64,
        )
        for index, dimension in enumerate(dimensions, start=1)
    )


def _observation(
    *,
    family: str = "conventional",
    base_grade: Decimal | None = Decimal("88.2"),
    base_status: str = "calculated",
    freshness_status: str = "current",
    freshness_reasons: tuple[str, ...] = (),
    algorithm_version: str = "1",
    calculation_fingerprint: str = "b" * 64,
    inputs_sha256: str = "c" * 64,
    activation_sha256: str = "d" * 64,
    policy_sha256: str = "e" * 64,
    entries: tuple[GradePreviewBasisEntry, ...] | None = None,
    override_reference: TeacherGradeOverrideReference | None = None,
    override_applicability: str = "no_override",
    override_replacement_grade: Decimal | None = None,
    effective_grade: Decimal | None = Decimal("88.2"),
    effective_source: str = "base",
) -> GradePreviewObservation:
    return GradePreviewObservation(
        schema_version=GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
        target=_target(family),
        base_result_reference=_source_reference(family),
        base_result_status=base_status,
        base_grade=base_grade,
        base_freshness_status=freshness_status,
        base_freshness_reasons=freshness_reasons,
        algorithm_version=algorithm_version,
        calculation_fingerprint=calculation_fingerprint,
        inputs_sha256=inputs_sha256,
        activation_reference=GradePolicyActivationReference(
            CLASS_ID,
            PERIOD.school_year,
            PERIOD.period_id,
            1,
            activation_sha256,
        ),
        policy_reference=GradePolicyReference(
            CLASS_ID,
            "course_grade",
            1,
            policy_sha256,
        ),
        selected_override_reference=override_reference,
        override_applicability=override_applicability,  # type: ignore[arg-type]
        override_replacement_grade=override_replacement_grade,
        effective_grade=effective_grade,
        effective_source=effective_source,  # type: ignore[arg-type]
        basis_entries=entries if entries is not None else _entries(family),
    )


def _change_entry(
    value: GradePreviewObservation,
    dimension: str,
    digest: str,
) -> GradePreviewObservation:
    entries = tuple(
        replace(entry, sha256=digest)
        if entry.dimension == dimension
        else entry
        for entry in value.basis_entries
    )
    return replace(value, basis_entries=entries)


def _override_reference(digest: str = "f" * 64) -> TeacherGradeOverrideReference:
    return TeacherGradeOverrideReference(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        school_year=PERIOD.school_year,
        period_id=PERIOD.period_id,
        calendar_revision=1,
        calculation_family="conventional",
        override_revision=1,
        override_sha256=digest,
    )


def test_prior_basis_is_snapshot_neutral_wrapper_over_frozen_observation() -> None:
    observation = _observation()
    basis = prior_reporting_snapshot_grade_basis_from_observation(observation)

    assert basis == PriorReportingSnapshotGradeBasis(observation)
    encoded = prior_reporting_snapshot_grade_basis_to_json_bytes(basis)
    assert encoded.endswith(b"\n")
    assert b'"observation"' in encoded
    assert b'"effective_grade":"88.2"' in encoded


def test_unchanged_comparison_is_comparable_with_exact_zero_delta() -> None:
    current = _observation()
    prior = PriorReportingSnapshotGradeBasis(current)

    comparison = compare_grade_preview_basis(current, prior)

    assert comparison.relationship == "comparable"
    assert comparison.changed is False
    assert comparison.reasons == ()
    assert comparison.effective_grade_delta == Decimal("0.0")


def test_new_and_removed_are_distinct_from_comparable_change_reasons() -> None:
    observation = _observation()
    prior = PriorReportingSnapshotGradeBasis(observation)

    new = compare_grade_preview_basis(observation, None)
    removed = compare_grade_preview_basis(None, prior)

    assert (new.relationship, new.changed, new.reasons) == ("new", True, ())
    assert (removed.relationship, removed.changed, removed.reasons) == (
        "removed",
        True,
        (),
    )
    assert new.effective_grade_delta is None
    assert removed.effective_grade_delta is None


def test_semantic_dimensions_map_to_closed_canonical_change_taxonomy() -> None:
    previous = _observation()
    current = _change_entry(previous, "formula", "1" * 64)
    current = _change_entry(current, "participation", "2" * 64)
    current = _change_entry(current, "evidence", "3" * 64)
    current = _change_entry(current, "weighting", "4" * 64)
    current = _change_entry(current, "state_treatment", "5" * 64)
    current = _change_entry(current, "rounding", "6" * 64)
    current = _change_entry(current, "algorithm", "7" * 64)
    current = replace(
        current,
        inputs_sha256="8" * 64,
        calculation_fingerprint="9" * 64,
        activation_reference=replace(
            current.activation_reference,
            activation_sha256="a" * 64,
        ),
        policy_reference=replace(
            current.policy_reference,
            policy_sha256="b" * 64,
        ),
        algorithm_version="2",
    )

    comparison = compare_grade_preview_basis(
        current,
        PriorReportingSnapshotGradeBasis(previous),
    )

    assert comparison.reasons == (
        "policy_changed",
        "formula_changed",
        "membership_or_participation_changed",
        "evidence_or_proficiency_basis_changed",
        "weighting_changed",
        "state_handling_changed",
        "rounding_changed",
        "algorithm_changed",
    )


def test_override_freshness_and_effective_changes_are_independent() -> None:
    previous = _observation()
    override = _override_reference()
    current = replace(
        previous,
        selected_override_reference=override,
        override_applicability="applicable",
        override_replacement_grade=Decimal("91.25"),
        effective_grade=Decimal("91.25"),
        effective_source="override",
    )

    comparison = compare_grade_preview_basis(
        current,
        PriorReportingSnapshotGradeBasis(previous),
    )

    assert comparison.reasons == (
        "override_changed",
        "override_applicability_changed",
        "effective_grade_changed",
        "effective_source_changed",
    )
    assert comparison.effective_grade_delta == Decimal("3.05")


def test_freshness_change_does_not_treat_missing_numeric_grade_as_zero() -> None:
    previous = _observation()
    current = replace(
        previous,
        base_freshness_status="stale",
        base_freshness_reasons=("inputs_changed",),
        effective_grade=None,
        effective_source="none",
    )

    comparison = compare_grade_preview_basis(
        current,
        PriorReportingSnapshotGradeBasis(previous),
    )

    assert comparison.reasons == (
        "freshness_changed",
        "effective_grade_changed",
        "effective_source_changed",
    )
    assert comparison.effective_grade_delta is None


def test_calculation_family_change_is_comparable_within_same_logical_scope() -> None:
    previous = _observation(family="conventional")
    current = _observation(family="standards_based")

    comparison = compare_grade_preview_basis(
        current,
        PriorReportingSnapshotGradeBasis(previous),
    )

    assert comparison.relationship == "comparable"
    assert comparison.reasons[0] == "calculation_family_changed"
    assert "base_result_changed" in comparison.reasons


def test_comparison_rejects_cross_student_or_cross_period_scope() -> None:
    previous = _observation()
    base_reference = previous.base_result_reference.reference
    assert isinstance(base_reference, ConventionalGradeResultReference)

    cross_student = replace(
        previous,
        target=replace(previous.target, student_id="student_002"),
        base_result_reference=GradeOverrideSourceResultReference(
            "conventional",
            replace(base_reference, student_id="student_002"),
        ),
    )

    cross_period = replace(
        previous,
        target=replace(
            previous.target,
            target_period=AcademicPeriodRef(PERIOD.school_year, "q2"),
        ),
        base_result_reference=GradeOverrideSourceResultReference(
            "conventional",
            replace(base_reference, period_id="q2"),
        ),
        activation_reference=replace(
            previous.activation_reference,
            period_id="q2",
        ),
    )

    for current in (cross_student, cross_period):
        with pytest.raises(GradePreviewComparisonError, match="same logical scope"):
            compare_grade_preview_basis(
                current,
                PriorReportingSnapshotGradeBasis(previous),
            )


def test_unmapped_input_change_fails_closed_instead_of_underexplaining() -> None:
    previous = _observation()
    current = replace(previous, inputs_sha256="f" * 64)

    with pytest.raises(GradePreviewComparisonError, match="without a mapped"):
        compare_grade_preview_basis(
            current,
            PriorReportingSnapshotGradeBasis(previous),
        )


def test_comparison_serialization_is_deterministic_and_decimal_exact() -> None:
    previous = _observation()
    current = replace(
        previous,
        base_grade=Decimal("88.25"),
        effective_grade=Decimal("88.25"),
    )
    comparison = compare_grade_preview_basis(
        current,
        PriorReportingSnapshotGradeBasis(previous),
    )

    first = grade_preview_comparison_to_json_bytes(comparison)
    second = grade_preview_comparison_to_json_bytes(comparison)

    assert first == second
    assert first.endswith(b"\n")
    assert b'"effective_grade_delta":"0.05"' in first
