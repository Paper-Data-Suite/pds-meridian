from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pds_core.grouping_signal_storage import calculate_grouping_signal_digest
from pds_core.grouping_signals import (
    GROUPING_SIGNAL_RECORD_TYPE,
    GROUPING_SIGNAL_SCHEMA_VERSION,
    grouping_signal_set_to_dict,
)

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
)
from meridian.grouping_signal_derivation import (
    GROUPING_SIGNAL_DERIVATION_ALGORITHM_VERSION,
    GROUPING_SIGNAL_DERIVATION_RECORD_TYPE,
    GROUPING_SIGNAL_DERIVATION_SCHEMA_VERSION,
    GroupingSignalDerivationSnapshot,
    GroupingSignalStudentDerivation,
    grouping_signal_derivation_calculation_fingerprint,
    grouping_signal_derivation_id,
    grouping_signal_derivation_reference,
    grouping_signal_roster_basis,
)
from meridian.grouping_signal_export import (
    GroupingSignalExportProjectionError,
    GroupingSignalExportZeroContributorsError,
    build_grouping_signal_export_candidate,
)
from meridian.grouping_signal_policy import (
    GroupingSignalDerivationPolicyReference,
)

CLASS_ID = "synthetic_class_2026"
STANDARD_ID = "njsls-ela:RL.CR.9-10.1"
NOW = datetime(2026, 9, 1, 12, 30, tzinfo=UTC)


def _result_reference(
    student_id: str,
    digest_character: str,
) -> AcademicPeriodProficiencyResultReference:
    return AcademicPeriodProficiencyResultReference(
        class_id=CLASS_ID,
        school_year="2026-2027",
        period_id="mp1",
        student_id=student_id,
        standard_id=STANDARD_ID,
        result_revision=1,
        result_sha256=digest_character * 64,
    )


def _policy_reference() -> GroupingSignalDerivationPolicyReference:
    return GroupingSignalDerivationPolicyReference(
        class_id=CLASS_ID,
        policy_id="reading_planning_signal",
        policy_revision=1,
        policy_sha256="a" * 64,
    )


def _snapshot(
    student_derivations: tuple[GroupingSignalStudentDerivation, ...],
) -> GroupingSignalDerivationSnapshot:
    policy_reference = _policy_reference()
    roster = grouping_signal_roster_basis(
        CLASS_ID,
        tuple(item.student_id for item in student_derivations),
    )
    ordered = tuple(
        sorted(student_derivations, key=lambda item: item.student_id)
    )
    fingerprint = grouping_signal_derivation_calculation_fingerprint(
        policy_reference,
        roster,
        ordered,
    )
    return GroupingSignalDerivationSnapshot(
        schema_version=GROUPING_SIGNAL_DERIVATION_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_DERIVATION_RECORD_TYPE,
        derivation_id=grouping_signal_derivation_id(fingerprint),
        class_id=CLASS_ID,
        algorithm_version=GROUPING_SIGNAL_DERIVATION_ALGORITHM_VERSION,
        policy_reference=policy_reference,
        roster_basis=roster,
        dimension_id="reading_planning",
        band_count=3,
        student_derivations=ordered,
        calculation_fingerprint=fingerprint,
    )


def representative_derivation() -> GroupingSignalDerivationSnapshot:
    return _snapshot(
        (
            GroupingSignalStudentDerivation(
                student_id="student_4",
                source_state="insufficient_evidence",
                disposition="noncontributing",
                source_result=_result_reference("student_4", "4"),
                proficiency_level_id=None,
                scale_position=None,
                band=None,
            ),
            GroupingSignalStudentDerivation(
                student_id="student_2",
                source_state="calculated",
                disposition="contributing",
                source_result=_result_reference("student_2", "2"),
                proficiency_level_id="level_3",
                scale_position=3,
                band=2,
            ),
            GroupingSignalStudentDerivation(
                student_id="student_3",
                source_state="missing",
                disposition="noncontributing",
                source_result=None,
                proficiency_level_id=None,
                scale_position=None,
                band=None,
            ),
            GroupingSignalStudentDerivation(
                student_id="student_1",
                source_state="calculated",
                disposition="contributing",
                source_result=_result_reference("student_1", "1"),
                proficiency_level_id="level_1",
                scale_position=1,
                band=1,
            ),
        )
    )


def test_projection_builds_exact_minimal_core_signal() -> None:
    derivation = representative_derivation()
    reference = grouping_signal_derivation_reference(derivation)

    signal = build_grouping_signal_export_candidate(
        derivation,
        signal_set_id="reading_mp1_export_001",
        created_at=NOW,
    )

    assert signal.schema_version == GROUPING_SIGNAL_SCHEMA_VERSION
    assert signal.record_type == GROUPING_SIGNAL_RECORD_TYPE
    assert signal.signal_set_id == "reading_mp1_export_001"
    assert signal.class_id == CLASS_ID
    assert signal.created_at == NOW
    assert signal.source.kind == "module_generated"
    assert signal.source.module_id == "meridian"
    assert signal.source.snapshot_id == derivation.derivation_id
    assert signal.source.snapshot_digest_algorithm == "sha256"
    assert signal.source.snapshot_digest == reference.derivation_sha256
    assert signal.dimensions[0].dimension_id == derivation.dimension_id
    assert signal.dimensions[0].band_count == derivation.band_count
    assert tuple(
        (item.student_id, item.dimension_id, item.band)
        for item in signal.student_bands
    ) == (
        ("student_1", "reading_planning", 1),
        ("student_2", "reading_planning", 2),
    )


def test_projection_preserves_noncontributors_only_as_absent_entries() -> None:
    signal = build_grouping_signal_export_candidate(
        representative_derivation(),
        signal_set_id="reading_mp1_export_002",
        created_at=NOW,
    )

    exported_ids = {item.student_id for item in signal.student_bands}
    assert exported_ids == {"student_1", "student_2"}
    assert "student_3" not in exported_ids
    assert "student_4" not in exported_ids
    assert all(item.band >= 1 for item in signal.student_bands)


def test_projection_contains_no_private_academic_extension_fields() -> None:
    signal = build_grouping_signal_export_candidate(
        representative_derivation(),
        signal_set_id="reading_mp1_export_003",
        created_at=NOW,
    )
    payload = grouping_signal_set_to_dict(signal)

    assert set(payload) == {
        "schema_version",
        "record_type",
        "signal_set_id",
        "class_id",
        "created_at",
        "source",
        "dimensions",
        "student_bands",
    }
    assert isinstance(payload["source"], dict)
    assert set(payload["source"]) == {
        "kind",
        "module_id",
        "snapshot_id",
        "snapshot_digest_algorithm",
        "snapshot_digest",
    }
    student_bands = payload["student_bands"]
    assert isinstance(student_bands, list)
    assert all(
        isinstance(item, dict)
        and set(item) == {"student_id", "dimension_id", "band"}
        for item in student_bands
    )
    serialized = repr(payload)
    for forbidden in (
        "proficiency_level_id",
        "scale_position",
        "source_result",
        "standard_id",
        "policy_reference",
        "student_name",
        "display_name",
        "percentage",
        "raw_score",
    ):
        assert forbidden not in serialized


def test_projection_delegates_created_at_utc_normalization_to_core() -> None:
    eastern = timezone(timedelta(hours=-4))
    signal = build_grouping_signal_export_candidate(
        representative_derivation(),
        signal_set_id="reading_mp1_export_004",
        created_at=datetime(2026, 9, 1, 8, 30, tzinfo=eastern),
    )

    assert signal.created_at == NOW


@pytest.mark.parametrize(
    ("signal_set_id", "created_at", "message"),
    [
        ("bad id", NOW, "signal_set_id"),
        (
            "reading_mp1_export_005",
            datetime(2026, 9, 1, 12, 30),
            "timezone-aware",
        ),
    ],
)
def test_projection_rejects_invalid_explicit_core_identity_or_time(
    signal_set_id: str,
    created_at: datetime,
    message: str,
) -> None:
    with pytest.raises(GroupingSignalExportProjectionError, match=message):
        build_grouping_signal_export_candidate(
            representative_derivation(),
            signal_set_id=signal_set_id,
            created_at=created_at,
        )


def test_projection_rejects_zero_contributors_before_core_write() -> None:
    derivation = _snapshot(
        (
            GroupingSignalStudentDerivation(
                student_id="student_1",
                source_state="missing",
                disposition="noncontributing",
                source_result=None,
                proficiency_level_id=None,
                scale_position=None,
                band=None,
            ),
            GroupingSignalStudentDerivation(
                student_id="student_2",
                source_state="insufficient_evidence",
                disposition="noncontributing",
                source_result=_result_reference("student_2", "2"),
                proficiency_level_id=None,
                scale_position=None,
                band=None,
            ),
        )
    )

    with pytest.raises(
        GroupingSignalExportZeroContributorsError,
        match="zero contributors",
    ):
        build_grouping_signal_export_candidate(
            derivation,
            signal_set_id="reading_mp1_export_zero",
            created_at=NOW,
        )


def test_derivation_source_digest_and_core_signal_digest_are_distinct() -> None:
    derivation = representative_derivation()
    reference = grouping_signal_derivation_reference(derivation)
    signal = build_grouping_signal_export_candidate(
        derivation,
        signal_set_id="reading_mp1_export_006",
        created_at=NOW,
    )

    core_digest = calculate_grouping_signal_digest(signal)
    assert signal.source.snapshot_digest == reference.derivation_sha256
    assert core_digest != reference.derivation_sha256
