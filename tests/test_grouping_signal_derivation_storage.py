from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

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
    grouping_signal_derivation_snapshot_to_json_bytes,
    grouping_signal_roster_basis,
)
from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageConflictError,
    GroupingSignalDerivationStorageIntegrityError,
    GroupingSignalDerivationStorageLockError,
    GroupingSignalDerivationStorageNotFoundError,
    GroupingSignalDerivationStorageTooLargeError,
    GroupingSignalDerivationStorageValidationError,
    grouping_signal_derivation_path,
    grouping_signal_derivation_relative_path,
    grouping_signal_derivations_directory,
    list_grouping_signal_derivation_ids,
    load_grouping_signal_derivation,
    load_grouping_signal_derivation_reference,
    write_grouping_signal_derivation,
)
from meridian.grouping_signal_policy import (
    GroupingSignalDerivationPolicyReference,
)

CLASS_ID = "synthetic_class_2026"
STANDARD_ID = "urn:standard:reading"


def source_reference(
    student_id: str,
    digest: str,
) -> AcademicPeriodProficiencyResultReference:
    return AcademicPeriodProficiencyResultReference(
        class_id=CLASS_ID,
        school_year="2026-2027",
        period_id="mp1",
        student_id=student_id,
        standard_id=STANDARD_ID,
        result_revision=1,
        result_sha256=digest,
    )


def snapshot(*, suffix: str = "a") -> GroupingSignalDerivationSnapshot:
    policy_reference = GroupingSignalDerivationPolicyReference(
        class_id=CLASS_ID,
        policy_id="reading_grouping",
        policy_revision=1,
        policy_sha256="a" * 64,
    )
    roster = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_2", "student_1"),
    )
    derivations = (
        GroupingSignalStudentDerivation(
            student_id="student_1",
            source_state="calculated",
            disposition="contributing",
            source_result=source_reference("student_1", suffix * 64),
            proficiency_level_id="developing",
            scale_position=2,
            band=2,
        ),
        GroupingSignalStudentDerivation(
            student_id="student_2",
            source_state="missing",
            disposition="noncontributing",
            source_result=None,
            proficiency_level_id=None,
            scale_position=None,
            band=None,
        ),
    )
    fingerprint = grouping_signal_derivation_calculation_fingerprint(
        policy_reference,
        roster,
        derivations,
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
        student_derivations=derivations,
        calculation_fingerprint=fingerprint,
    )


def test_canonical_paths_are_class_local_and_content_addressed(tmp_path: Path) -> None:
    value = snapshot()
    path = grouping_signal_derivation_path(
        tmp_path,
        CLASS_ID,
        value.derivation_id,
    )
    assert path == (
        tmp_path
        / "classes"
        / CLASS_ID
        / "modules"
        / "meridian"
        / "grouping_signal_derivations"
        / f"{value.derivation_id}.json"
    )
    assert grouping_signal_derivation_relative_path(
        CLASS_ID,
        value.derivation_id,
    ) == (
        f"classes/{CLASS_ID}/modules/meridian/grouping_signal_derivations/"
        f"{value.derivation_id}.json"
    )


def test_first_write_and_exact_load_preserve_canonical_bytes(tmp_path: Path) -> None:
    value = snapshot()
    result = write_grouping_signal_derivation(tmp_path, value)
    assert result.disposition == "created"
    assert result.stored.snapshot == value
    assert result.stored.content == grouping_signal_derivation_snapshot_to_json_bytes(
        value
    )
    assert result.stored.reference == grouping_signal_derivation_reference(value)

    loaded = load_grouping_signal_derivation(
        tmp_path,
        CLASS_ID,
        value.derivation_id,
    )
    assert loaded == result.stored
    assert loaded.path.read_bytes() == loaded.content
    assert Path(str(loaded.path) + ".sha256").read_text(encoding="ascii") == (
        loaded.derivation_sha256 + "\n"
    )


def test_exact_replay_is_idempotent(tmp_path: Path) -> None:
    value = snapshot()
    first = write_grouping_signal_derivation(tmp_path, value)
    second = write_grouping_signal_derivation(tmp_path, value)
    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert second.stored == first.stored


def test_same_identity_with_different_valid_bytes_conflicts(tmp_path: Path) -> None:
    value = snapshot()
    write_grouping_signal_derivation(tmp_path, value)
    collision = replace(value, dimension_id="different_dimension")
    assert collision.derivation_id == value.derivation_id
    assert grouping_signal_derivation_snapshot_to_json_bytes(collision) != (
        grouping_signal_derivation_snapshot_to_json_bytes(value)
    )
    with pytest.raises(GroupingSignalDerivationStorageConflictError):
        write_grouping_signal_derivation(tmp_path, collision)


def test_listing_is_verified_and_deterministic(tmp_path: Path) -> None:
    first = snapshot(suffix="a")
    second = snapshot(suffix="b")
    write_grouping_signal_derivation(tmp_path, second)
    write_grouping_signal_derivation(tmp_path, first)
    assert list_grouping_signal_derivation_ids(tmp_path, CLASS_ID) == tuple(
        sorted((first.derivation_id, second.derivation_id))
    )


def test_storage_has_no_current_latest_active_or_revision_state(tmp_path: Path) -> None:
    value = snapshot()
    write_grouping_signal_derivation(tmp_path, value)
    collection = grouping_signal_derivations_directory(tmp_path, CLASS_ID)
    assert {entry.name for entry in collection.iterdir()} == {
        f"{value.derivation_id}.json",
        f"{value.derivation_id}.json.sha256",
    }
    assert not (collection / "current.json").exists()
    assert not (collection / "latest.json").exists()
    assert not (collection / "active.json").exists()
    assert not (collection / "revisions").exists()


def test_exact_reference_requires_matching_digest(tmp_path: Path) -> None:
    value = snapshot()
    stored = write_grouping_signal_derivation(tmp_path, value).stored
    assert load_grouping_signal_derivation_reference(
        tmp_path,
        stored.reference,
    ) == stored
    wrong = replace(stored.reference, derivation_sha256="0" * 64)
    with pytest.raises(
        GroupingSignalDerivationStorageIntegrityError,
        match="requested",
    ):
        load_grouping_signal_derivation_reference(tmp_path, wrong)


def test_missing_exact_identity_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(GroupingSignalDerivationStorageNotFoundError):
        load_grouping_signal_derivation(
            tmp_path,
            CLASS_ID,
            "gsd_" + "0" * 64,
        )


def test_lock_conflict_fails_without_mutation(tmp_path: Path) -> None:
    value = snapshot()
    collection = grouping_signal_derivations_directory(tmp_path, CLASS_ID)
    collection.mkdir(parents=True)
    lock = collection / ".write.lock"
    lock.write_text("other writer\n", encoding="utf-8")
    with pytest.raises(GroupingSignalDerivationStorageLockError):
        write_grouping_signal_derivation(tmp_path, value)
    assert not grouping_signal_derivation_path(
        tmp_path,
        CLASS_ID,
        value.derivation_id,
    ).exists()


def test_bounded_read_rejects_derivation_larger_than_requested_limit(
    tmp_path: Path,
) -> None:
    value = snapshot()
    stored = write_grouping_signal_derivation(tmp_path, value).stored
    with pytest.raises(GroupingSignalDerivationStorageTooLargeError):
        load_grouping_signal_derivation(
            tmp_path,
            CLASS_ID,
            value.derivation_id,
            maximum_derivation_bytes=len(stored.content) - 1,
        )


@pytest.mark.parametrize(
    "value",
    (
        "../escape",
        "a/b",
        r"C:\\escape",
        r"..\\escape",
    ),
)
def test_path_identifier_injection_is_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(GroupingSignalDerivationStorageValidationError):
        grouping_signal_derivation_path(tmp_path, CLASS_ID, value)
    with pytest.raises(GroupingSignalDerivationStorageValidationError):
        grouping_signal_derivations_directory(tmp_path, value)
