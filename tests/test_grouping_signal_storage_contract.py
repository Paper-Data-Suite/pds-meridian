from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.grouping_signal_storage import (
    GROUPING_SIGNAL_DIGEST_ALGORITHM,
    GroupingSignalConflictError,
    GroupingSignalIntegrityError,
    calculate_grouping_signal_digest,
    grouping_signal_digest_path,
    grouping_signal_path,
    list_grouping_signal_ids,
    load_grouping_signal,
    write_grouping_signal,
)
from pds_core.grouping_signals import (
    GROUPING_SIGNAL_RECORD_TYPE,
    GROUPING_SIGNAL_SCHEMA_VERSION,
    GroupingSignalDimension,
    GroupingSignalSet,
    GroupingSignalSource,
    GroupingSignalStudentBand,
    grouping_signal_set_to_json_bytes,
)

_SOURCE_DIGEST = "1" * 64


def _signal(
    *,
    signal_set_id: str = "meridian_signal_001",
    class_id: str = "synthetic_class_2026",
    band: int = 2,
) -> GroupingSignalSet:
    return GroupingSignalSet(
        schema_version=GROUPING_SIGNAL_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_RECORD_TYPE,
        signal_set_id=signal_set_id,
        class_id=class_id,
        created_at=datetime(2026, 9, 1, 18, 30, tzinfo=UTC),
        source=GroupingSignalSource(
            kind="module_generated",
            module_id="meridian",
            snapshot_id="meridian_derivation_001",
            snapshot_digest_algorithm="sha256",
            snapshot_digest=_SOURCE_DIGEST,
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
                band=band,
            ),
            GroupingSignalStudentBand(
                student_id="student_002",
                dimension_id="reading_analysis",
                band=4,
            ),
        ),
    )


def test_core_storage_creates_exact_canonical_pair_and_loads_it(
    tmp_path: Path,
) -> None:
    signal = _signal()
    expected_bytes = grouping_signal_set_to_json_bytes(signal)
    expected_digest = hashlib.sha256(expected_bytes).hexdigest()

    result = write_grouping_signal(tmp_path, signal)

    assert result.disposition == "created"
    assert result.stored.signal == signal
    assert result.stored.digest_algorithm == GROUPING_SIGNAL_DIGEST_ALGORITHM
    assert result.stored.digest == expected_digest
    assert calculate_grouping_signal_digest(signal) == expected_digest
    assert expected_digest != signal.source.snapshot_digest

    json_path = grouping_signal_path(
        tmp_path,
        signal.class_id,
        signal.signal_set_id,
    )
    digest_path = grouping_signal_digest_path(
        tmp_path,
        signal.class_id,
        signal.signal_set_id,
    )
    assert json_path.read_bytes() == expected_bytes
    assert digest_path.read_bytes() == f"{expected_digest}\n".encode("ascii")

    loaded = load_grouping_signal(
        tmp_path,
        signal.class_id,
        signal.signal_set_id,
    )
    assert loaded == result.stored


def test_core_storage_identical_replay_is_idempotent_without_rewrite(
    tmp_path: Path,
) -> None:
    signal = _signal()
    first = write_grouping_signal(tmp_path, signal)
    json_path = grouping_signal_path(
        tmp_path,
        signal.class_id,
        signal.signal_set_id,
    )
    digest_path = grouping_signal_digest_path(
        tmp_path,
        signal.class_id,
        signal.signal_set_id,
    )
    historical_json = json_path.read_bytes()
    historical_digest = digest_path.read_bytes()

    second = write_grouping_signal(tmp_path, signal)

    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert second.stored == first.stored
    assert json_path.read_bytes() == historical_json
    assert digest_path.read_bytes() == historical_digest


def test_core_storage_rejects_conflicting_immutable_identity(
    tmp_path: Path,
) -> None:
    original = _signal(band=2)
    conflicting = _signal(band=3)
    write_grouping_signal(tmp_path, original)

    json_path = grouping_signal_path(
        tmp_path,
        original.class_id,
        original.signal_set_id,
    )
    digest_path = grouping_signal_digest_path(
        tmp_path,
        original.class_id,
        original.signal_set_id,
    )
    historical_json = json_path.read_bytes()
    historical_digest = digest_path.read_bytes()

    with pytest.raises(GroupingSignalConflictError):
        write_grouping_signal(tmp_path, conflicting)

    assert json_path.read_bytes() == historical_json
    assert digest_path.read_bytes() == historical_digest
    assert load_grouping_signal(
        tmp_path,
        original.class_id,
        original.signal_set_id,
    ).signal == original


def test_core_storage_listing_is_deterministic_and_class_scoped(
    tmp_path: Path,
) -> None:
    for signal in (
        _signal(signal_set_id="signal_z"),
        _signal(signal_set_id="signal_a"),
        _signal(
            signal_set_id="other_class_signal",
            class_id="synthetic_class_other",
        ),
    ):
        write_grouping_signal(tmp_path, signal)

    assert list_grouping_signal_ids(
        tmp_path,
        "synthetic_class_2026",
    ) == ("signal_a", "signal_z")
    assert list_grouping_signal_ids(
        tmp_path,
        "synthetic_class_other",
    ) == ("other_class_signal",)
    assert list_grouping_signal_ids(
        tmp_path,
        "synthetic_class_empty",
    ) == ()


def test_core_storage_detects_canonical_byte_tampering_without_repair(
    tmp_path: Path,
) -> None:
    signal = _signal()
    write_grouping_signal(tmp_path, signal)
    json_path = grouping_signal_path(
        tmp_path,
        signal.class_id,
        signal.signal_set_id,
    )
    digest_path = grouping_signal_digest_path(
        tmp_path,
        signal.class_id,
        signal.signal_set_id,
    )
    original_digest = digest_path.read_bytes()
    tampered = json_path.read_bytes() + b" "
    json_path.write_bytes(tampered)

    with pytest.raises(GroupingSignalIntegrityError):
        load_grouping_signal(
            tmp_path,
            signal.class_id,
            signal.signal_set_id,
        )

    assert json_path.read_bytes() == tampered
    assert digest_path.read_bytes() == original_digest


def test_core_storage_rejects_incomplete_pair_without_repair(
    tmp_path: Path,
) -> None:
    signal = _signal()
    write_grouping_signal(tmp_path, signal)
    json_path = grouping_signal_path(
        tmp_path,
        signal.class_id,
        signal.signal_set_id,
    )
    digest_path = grouping_signal_digest_path(
        tmp_path,
        signal.class_id,
        signal.signal_set_id,
    )
    historical_json = json_path.read_bytes()
    digest_path.unlink()

    with pytest.raises(GroupingSignalIntegrityError):
        load_grouping_signal(
            tmp_path,
            signal.class_id,
            signal.signal_set_id,
        )
    with pytest.raises(GroupingSignalIntegrityError):
        write_grouping_signal(tmp_path, signal)
    with pytest.raises(GroupingSignalIntegrityError):
        list_grouping_signal_ids(tmp_path, signal.class_id)

    assert json_path.read_bytes() == historical_json
    assert not digest_path.exists()
