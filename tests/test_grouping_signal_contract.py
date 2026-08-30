from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pds_core.grouping_signal_csv import (
    GROUPING_SIGNAL_CSV_CONTRACT_NAME,
    GroupingSignalCsvError,
    grouping_signal_csv_to_signal_set,
    grouping_signal_set_to_csv,
    grouping_signal_set_to_csv_bytes,
    parse_grouping_signal_csv,
)
from pds_core.grouping_signals import (
    GROUPING_SIGNAL_CONTRACT_NAME,
    GROUPING_SIGNAL_RECORD_TYPE,
    GROUPING_SIGNAL_SCHEMA_VERSION,
    GroupingSignalDimension,
    GroupingSignalSet,
    GroupingSignalSource,
    GroupingSignalStudentBand,
    GroupingSignalValidationError,
    grouping_signal_set_from_dict,
    grouping_signal_set_from_json,
    grouping_signal_set_to_dict,
    grouping_signal_set_to_json,
    grouping_signal_set_to_json_bytes,
)

_SOURCE_DIGEST = "1" * 64


def _module_generated_signal() -> GroupingSignalSet:
    return GroupingSignalSet(
        schema_version=GROUPING_SIGNAL_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_RECORD_TYPE,
        signal_set_id="meridian_planning_signal_001",
        class_id="synthetic_english10_p2",
        created_at=datetime(
            2026,
            9,
            1,
            14,
            30,
            tzinfo=timezone(-timedelta(hours=4)),
        ),
        source=GroupingSignalSource(
            kind="module_generated",
            module_id="meridian",
            snapshot_id="meridian_derivation_snapshot_001",
            snapshot_digest_algorithm="sha256",
            snapshot_digest=_SOURCE_DIGEST,
        ),
        dimensions=(
            GroupingSignalDimension(
                dimension_id="writing_claim_evidence",
                band_count=3,
            ),
            GroupingSignalDimension(
                dimension_id="reading_analysis",
                band_count=4,
            ),
        ),
        student_bands=(
            GroupingSignalStudentBand(
                student_id="student_002",
                dimension_id="reading_analysis",
                band=4,
            ),
            GroupingSignalStudentBand(
                student_id="student_001",
                dimension_id="writing_claim_evidence",
                band=2,
            ),
            GroupingSignalStudentBand(
                student_id="student_001",
                dimension_id="reading_analysis",
                band=1,
            ),
        ),
    )


def test_core_grouping_signal_contract_identity_is_exact() -> None:
    assert GROUPING_SIGNAL_CONTRACT_NAME == "grouping_signal_set_v1"
    assert GROUPING_SIGNAL_SCHEMA_VERSION == "1"
    assert GROUPING_SIGNAL_RECORD_TYPE == "grouping_signal_set"


def test_module_generated_meridian_signal_normalizes_runtime_order_and_time() -> None:
    signal = _module_generated_signal()

    assert signal.created_at == datetime(2026, 9, 1, 18, 30, tzinfo=UTC)
    assert signal.source.kind == "module_generated"
    assert signal.source.module_id == "meridian"
    assert signal.source.snapshot_id == "meridian_derivation_snapshot_001"
    assert signal.source.snapshot_digest_algorithm == "sha256"
    assert signal.source.snapshot_digest == _SOURCE_DIGEST
    assert tuple(item.dimension_id for item in signal.dimensions) == (
        "reading_analysis",
        "writing_claim_evidence",
    )
    assert tuple(
        (item.dimension_id, item.student_id) for item in signal.student_bands
    ) == (
        ("reading_analysis", "student_001"),
        ("reading_analysis", "student_002"),
        ("writing_claim_evidence", "student_001"),
    )


def test_teacher_authored_signal_does_not_require_module_provenance() -> None:
    signal = GroupingSignalSet(
        schema_version="1",
        record_type="grouping_signal_set",
        signal_set_id="teacher_signal_001",
        class_id="synthetic_english10_p2",
        created_at=datetime(2026, 9, 1, 18, 0, tzinfo=UTC),
        source=GroupingSignalSource(
            kind="teacher_authored",
            module_id=None,
            snapshot_id=None,
            snapshot_digest_algorithm=None,
            snapshot_digest=None,
        ),
        dimensions=(
            GroupingSignalDimension(
                dimension_id="discussion_support",
                band_count=3,
            ),
        ),
        student_bands=(
            GroupingSignalStudentBand(
                student_id="student_001",
                dimension_id="discussion_support",
                band=2,
            ),
        ),
    )

    assert signal.source.module_id is None
    assert signal.source.snapshot_id is None
    assert signal.source.snapshot_digest is None


def test_teacher_authored_snapshot_provenance_is_all_or_nothing() -> None:
    with pytest.raises(
        GroupingSignalValidationError,
        match="must be all null or all populated",
    ):
        GroupingSignalSource(
            kind="teacher_authored",
            module_id=None,
            snapshot_id="teacher_import_001",
            snapshot_digest_algorithm=None,
            snapshot_digest=None,
        )


def test_structurally_valid_partial_roster_coverage_remains_valid() -> None:
    signal = GroupingSignalSet(
        schema_version="1",
        record_type="grouping_signal_set",
        signal_set_id="partial_signal_001",
        class_id="synthetic_english10_p2",
        created_at=datetime(2026, 9, 1, 18, 0, tzinfo=UTC),
        source=GroupingSignalSource(
            kind="teacher_authored",
            module_id=None,
            snapshot_id=None,
            snapshot_digest_algorithm=None,
            snapshot_digest=None,
        ),
        dimensions=(
            GroupingSignalDimension(
                dimension_id="reading_analysis",
                band_count=4,
            ),
        ),
        student_bands=(
            GroupingSignalStudentBand(
                student_id="student_001",
                dimension_id="reading_analysis",
                band=3,
            ),
        ),
    )

    assert len(signal.student_bands) == 1
    assert signal.student_bands[0].student_id == "student_001"


@pytest.mark.parametrize(
    ("schema_version", "record_type"),
    (("2", "grouping_signal_set"), ("1", "meridian_grouping_signal")),
)
def test_unsupported_contract_identity_is_rejected(
    schema_version: str,
    record_type: str,
) -> None:
    with pytest.raises(GroupingSignalValidationError):
        GroupingSignalSet(
            schema_version=schema_version,
            record_type=record_type,
            signal_set_id="invalid_contract_001",
            class_id="synthetic_english10_p2",
            created_at=datetime(2026, 9, 1, 18, 0, tzinfo=UTC),
            source=GroupingSignalSource(
                kind="teacher_authored",
                module_id=None,
                snapshot_id=None,
                snapshot_digest_algorithm=None,
                snapshot_digest=None,
            ),
            dimensions=(
                GroupingSignalDimension(
                    dimension_id="reading_analysis",
                    band_count=4,
                ),
            ),
            student_bands=(
                GroupingSignalStudentBand(
                    student_id="student_001",
                    dimension_id="reading_analysis",
                    band=2,
                ),
            ),
        )


def test_invalid_band_and_undeclared_dimension_are_rejected() -> None:
    with pytest.raises(GroupingSignalValidationError, match="between 1 and 4"):
        GroupingSignalSet(
            schema_version="1",
            record_type="grouping_signal_set",
            signal_set_id="invalid_band_001",
            class_id="synthetic_english10_p2",
            created_at=datetime(2026, 9, 1, 18, 0, tzinfo=UTC),
            source=GroupingSignalSource(
                kind="teacher_authored",
                module_id=None,
                snapshot_id=None,
                snapshot_digest_algorithm=None,
                snapshot_digest=None,
            ),
            dimensions=(
                GroupingSignalDimension(
                    dimension_id="reading_analysis",
                    band_count=4,
                ),
            ),
            student_bands=(
                GroupingSignalStudentBand(
                    student_id="student_001",
                    dimension_id="reading_analysis",
                    band=5,
                ),
            ),
        )

    with pytest.raises(GroupingSignalValidationError, match="undeclared dimension"):
        GroupingSignalSet(
            schema_version="1",
            record_type="grouping_signal_set",
            signal_set_id="undeclared_dimension_001",
            class_id="synthetic_english10_p2",
            created_at=datetime(2026, 9, 1, 18, 0, tzinfo=UTC),
            source=GroupingSignalSource(
                kind="teacher_authored",
                module_id=None,
                snapshot_id=None,
                snapshot_digest_algorithm=None,
                snapshot_digest=None,
            ),
            dimensions=(
                GroupingSignalDimension(
                    dimension_id="reading_analysis",
                    band_count=4,
                ),
            ),
            student_bands=(
                GroupingSignalStudentBand(
                    student_id="student_001",
                    dimension_id="writing_claim_evidence",
                    band=2,
                ),
            ),
        )


def test_duplicate_student_dimension_pair_is_rejected() -> None:
    with pytest.raises(
        GroupingSignalValidationError,
        match=r"duplicate \(student_id, dimension_id\) pair",
    ):
        GroupingSignalSet(
            schema_version="1",
            record_type="grouping_signal_set",
            signal_set_id="duplicate_entry_001",
            class_id="synthetic_english10_p2",
            created_at=datetime(2026, 9, 1, 18, 0, tzinfo=UTC),
            source=GroupingSignalSource(
                kind="teacher_authored",
                module_id=None,
                snapshot_id=None,
                snapshot_digest_algorithm=None,
                snapshot_digest=None,
            ),
            dimensions=(
                GroupingSignalDimension(
                    dimension_id="reading_analysis",
                    band_count=4,
                ),
            ),
            student_bands=(
                GroupingSignalStudentBand(
                    student_id="student_001",
                    dimension_id="reading_analysis",
                    band=2,
                ),
                GroupingSignalStudentBand(
                    student_id="student_001",
                    dimension_id="reading_analysis",
                    band=3,
                ),
            ),
        )


def test_canonical_json_round_trip_is_deterministic() -> None:
    signal = _module_generated_signal()

    first_text = grouping_signal_set_to_json(signal)
    second_text = grouping_signal_set_to_json(signal)
    first_bytes = grouping_signal_set_to_json_bytes(signal)
    second_bytes = grouping_signal_set_to_json_bytes(signal)

    assert first_text == second_text
    assert first_bytes == second_bytes == first_text.encode("utf-8")
    assert first_text.endswith("\n")
    assert grouping_signal_set_from_json(first_text) == signal
    assert grouping_signal_set_from_json(first_bytes) == signal
    assert grouping_signal_set_from_dict(grouping_signal_set_to_dict(signal)) == signal


def test_strict_json_loader_rejects_semantically_valid_noncanonical_bytes() -> None:
    canonical = grouping_signal_set_to_json(_module_generated_signal())

    with pytest.raises(GroupingSignalValidationError, match="not in canonical"):
        grouping_signal_set_from_json(canonical.rstrip("\n"))


def test_mapping_loader_requires_canonical_list_order() -> None:
    canonical = grouping_signal_set_to_dict(_module_generated_signal())
    dimensions = canonical["dimensions"]
    assert isinstance(dimensions, list)
    canonical["dimensions"] = list(reversed(dimensions))

    with pytest.raises(GroupingSignalValidationError, match="canonical ascending"):
        grouping_signal_set_from_dict(canonical)


def test_upstream_source_digest_is_not_the_canonical_signal_digest() -> None:
    signal = _module_generated_signal()
    canonical_digest = hashlib.sha256(
        grouping_signal_set_to_json_bytes(signal)
    ).hexdigest()

    assert signal.source.snapshot_digest == _SOURCE_DIGEST
    assert canonical_digest != signal.source.snapshot_digest


def _single_dimension_signal() -> GroupingSignalSet:
    return GroupingSignalSet(
        schema_version="1",
        record_type="grouping_signal_set",
        signal_set_id="meridian_single_dimension_001",
        class_id="synthetic_english10_p2",
        created_at=datetime(2026, 9, 1, 18, 30, tzinfo=UTC),
        source=GroupingSignalSource(
            kind="module_generated",
            module_id="meridian",
            snapshot_id="meridian_derivation_snapshot_single_001",
            snapshot_digest_algorithm="sha256",
            snapshot_digest="2" * 64,
        ),
        dimensions=(
            GroupingSignalDimension(
                dimension_id="reading_analysis",
                band_count=4,
            ),
        ),
        student_bands=(
            GroupingSignalStudentBand(
                student_id="student_002",
                dimension_id="reading_analysis",
                band=4,
            ),
            GroupingSignalStudentBand(
                student_id="student_001",
                dimension_id="reading_analysis",
                band=2,
            ),
        ),
    )


def test_grouping_signal_csv_contract_identity_is_exact() -> None:
    assert GROUPING_SIGNAL_CSV_CONTRACT_NAME == "grouping_signal_csv_v1"


def test_single_dimension_csv_is_complete_identity_preserving_round_trip() -> None:
    signal = _single_dimension_signal()

    text = grouping_signal_set_to_csv(signal, "reading_analysis")
    document = parse_grouping_signal_csv(text)

    assert document.csv_contract == "grouping_signal_csv_v1"
    assert document.representation_scope == "complete_signal"
    assert document.requires_new_identity is False
    assert document.signal_set_id == signal.signal_set_id
    assert document.created_at == signal.created_at
    assert tuple(row.student_id for row in document.rows) == (
        "student_001",
        "student_002",
    )
    assert grouping_signal_csv_to_signal_set(document) == signal
    assert grouping_signal_set_to_csv_bytes(
        signal, "reading_analysis"
    ) == text.encode("utf-8")


def test_multi_dimension_csv_is_projection_and_requires_fresh_identity() -> None:
    signal = _module_generated_signal()

    text = grouping_signal_set_to_csv(signal, "reading_analysis")
    document = parse_grouping_signal_csv(text)

    assert document.representation_scope == "dimension_projection"
    assert document.requires_new_identity is True
    assert document.signal_set_id == signal.signal_set_id
    assert document.dimension.dimension_id == "reading_analysis"
    assert tuple((row.student_id, row.band) for row in document.rows) == (
        ("student_001", 1),
        ("student_002", 4),
    )

    with pytest.raises(
        GroupingSignalCsvError,
        match="requires a new signal_set_id and created_at",
    ):
        grouping_signal_csv_to_signal_set(document)

    replacement_time = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    projected = grouping_signal_csv_to_signal_set(
        document,
        new_signal_set_id="meridian_reading_projection_001",
        new_created_at=replacement_time,
    )

    assert projected.signal_set_id == "meridian_reading_projection_001"
    assert projected.created_at == replacement_time
    assert projected.class_id == signal.class_id
    assert projected.source == signal.source
    assert tuple(item.dimension_id for item in projected.dimensions) == (
        "reading_analysis",
    )
    assert tuple(
        (item.student_id, item.dimension_id, item.band)
        for item in projected.student_bands
    ) == (
        ("student_001", "reading_analysis", 1),
        ("student_002", "reading_analysis", 4),
    )


def test_csv_export_requires_explicit_declared_dimension() -> None:
    signal = _module_generated_signal()

    with pytest.raises(GroupingSignalCsvError, match="is not declared"):
        grouping_signal_set_to_csv(signal, "undeclared_dimension")
