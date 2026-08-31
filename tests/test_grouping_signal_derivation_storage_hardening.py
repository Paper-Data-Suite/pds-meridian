from __future__ import annotations

import hashlib
import shutil
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
    grouping_signal_roster_basis,
)
from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageIntegrityError,
    grouping_signal_derivation_path,
    grouping_signal_derivations_directory,
    list_grouping_signal_derivation_ids,
    load_grouping_signal_derivation,
    write_grouping_signal_derivation,
)
from meridian.grouping_signal_policy import (
    GroupingSignalDerivationPolicyReference,
)

CLASS_ID = "synthetic_class_2026"
STANDARD_ID = "urn:standard:reading"


def snapshot() -> GroupingSignalDerivationSnapshot:
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
    source = AcademicPeriodProficiencyResultReference(
        class_id=CLASS_ID,
        school_year="2026-2027",
        period_id="mp1",
        student_id="student_1",
        standard_id=STANDARD_ID,
        result_revision=1,
        result_sha256="b" * 64,
    )
    derivations = (
        GroupingSignalStudentDerivation(
            student_id="student_1",
            source_state="calculated",
            disposition="contributing",
            source_result=source,
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


def test_tampered_json_fails_digest_integrity(tmp_path: Path) -> None:
    value = snapshot()
    stored = write_grouping_signal_derivation(tmp_path, value).stored
    stored.path.write_bytes(
        stored.content.replace(b"reading_planning", b"other_planning")
    )
    with pytest.raises(
        GroupingSignalDerivationStorageIntegrityError,
        match="does not match",
    ):
        load_grouping_signal_derivation(tmp_path, CLASS_ID, value.derivation_id)


def test_noncanonical_crlf_fails_even_with_matching_sidecar(tmp_path: Path) -> None:
    value = snapshot()
    stored = write_grouping_signal_derivation(tmp_path, value).stored
    crlf = stored.content.replace(b"\n", b"\r\n")
    stored.path.write_bytes(crlf)
    digest_path = Path(str(stored.path) + ".sha256")
    digest_path.write_bytes(
        (hashlib.sha256(crlf).hexdigest() + "\n").encode("ascii")
    )
    with pytest.raises(
        GroupingSignalDerivationStorageIntegrityError,
        match="noncanonical",
    ):
        load_grouping_signal_derivation(tmp_path, CLASS_ID, value.derivation_id)


def test_malformed_digest_sidecar_fails_closed(tmp_path: Path) -> None:
    value = snapshot()
    stored = write_grouping_signal_derivation(tmp_path, value).stored
    Path(str(stored.path) + ".sha256").write_bytes(b"not-a-digest\n")
    with pytest.raises(
        GroupingSignalDerivationStorageIntegrityError,
        match="invalid digest",
    ):
        load_grouping_signal_derivation(tmp_path, CLASS_ID, value.derivation_id)


def test_crlf_digest_sidecar_is_noncanonical(tmp_path: Path) -> None:
    value = snapshot()
    stored = write_grouping_signal_derivation(tmp_path, value).stored
    digest_path = Path(str(stored.path) + ".sha256")
    digest_path.write_bytes((stored.derivation_sha256 + "\r\n").encode("ascii"))
    with pytest.raises(GroupingSignalDerivationStorageIntegrityError):
        load_grouping_signal_derivation(tmp_path, CLASS_ID, value.derivation_id)


def test_incomplete_pair_fails_closed(tmp_path: Path) -> None:
    value = snapshot()
    stored = write_grouping_signal_derivation(tmp_path, value).stored
    Path(str(stored.path) + ".sha256").unlink()
    with pytest.raises(
        GroupingSignalDerivationStorageIntegrityError,
        match="both exist",
    ):
        load_grouping_signal_derivation(tmp_path, CLASS_ID, value.derivation_id)


def test_path_model_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    value = snapshot()
    stored = write_grouping_signal_derivation(tmp_path, value).stored
    fake_id = "gsd_" + "f" * 64
    if fake_id == value.derivation_id:
        fake_id = "gsd_" + "e" * 64
    fake_path = grouping_signal_derivation_path(tmp_path, CLASS_ID, fake_id)
    shutil.copyfile(stored.path, fake_path)
    shutil.copyfile(
        Path(str(stored.path) + ".sha256"),
        Path(str(fake_path) + ".sha256"),
    )
    with pytest.raises(
        GroupingSignalDerivationStorageIntegrityError,
        match="canonical path",
    ):
        load_grouping_signal_derivation(tmp_path, CLASS_ID, fake_id)


def test_unexpected_visible_entry_is_rejected(tmp_path: Path) -> None:
    value = snapshot()
    write_grouping_signal_derivation(tmp_path, value)
    collection = grouping_signal_derivations_directory(tmp_path, CLASS_ID)
    (collection / "current.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        GroupingSignalDerivationStorageIntegrityError,
        match="unexpected",
    ):
        list_grouping_signal_derivation_ids(tmp_path, CLASS_ID)


def test_unexpected_directory_is_rejected(tmp_path: Path) -> None:
    value = snapshot()
    write_grouping_signal_derivation(tmp_path, value)
    collection = grouping_signal_derivations_directory(tmp_path, CLASS_ID)
    (collection / "revisions").mkdir()
    with pytest.raises(GroupingSignalDerivationStorageIntegrityError, match="non-file"):
        list_grouping_signal_derivation_ids(tmp_path, CLASS_ID)


def test_symlinked_json_is_rejected_when_platform_permits_symlinks(
    tmp_path: Path,
) -> None:
    value = snapshot()
    stored = write_grouping_signal_derivation(tmp_path, value).stored
    outside = tmp_path / "outside.json"
    outside.write_bytes(stored.content)
    stored.path.unlink()
    try:
        stored.path.symlink_to(outside)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink creation not permitted: {error}")
    with pytest.raises(GroupingSignalDerivationStorageIntegrityError):
        load_grouping_signal_derivation(tmp_path, CLASS_ID, value.derivation_id)
