"""#124 E2B: strict durable correlation storage with monotonic exact CAS."""

from __future__ import annotations

import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from meridian.assessment_setup_correlation import AssessmentSetupCorrelation
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStorageConflict,
    AssessmentSetupCorrelationStorageError,
    AssessmentSetupCorrelationStore,
)
from meridian.teacher_action_guided import _identity


def fixture(
    tmp_path: Path, *, kind: str = "create_and_link"
) -> tuple[AssessmentSetupCorrelationStore, AssessmentSetupCorrelation]:
    (tmp_path / "classes" / "english12").mkdir(parents=True)
    value = AssessmentSetupCorrelation(
        review_sha256="a" * 64,
        workspace_sha256=_identity("workspace", str(tmp_path.resolve())),
        class_id="english12",
        school_year="2026-2027",
        module_id="scoreform",
        work_id="scene",
        grade_item_id="gi_scene",
        period_id="mp1",
        registration_revision=2,
        publication_id=None,
        kind="create_and_link" if kind == "create_and_link" else "use_existing",
        actor_id="teacher",
        actor_profile_sha256="b" * 64,
        grade_action_id=None,
        grade_target_sha256=None,
        membership_action_id=None,
        membership_target_sha256=None,
    )
    return AssessmentSetupCorrelationStore(tmp_path, "english12"), value


def bound_grade(value: AssessmentSetupCorrelation) -> AssessmentSetupCorrelation:
    return replace(value, grade_action_id="c" * 32, grade_target_sha256="d" * 64)


def bound_member(value: AssessmentSetupCorrelation) -> AssessmentSetupCorrelation:
    return replace(
        value, membership_action_id="e" * 32, membership_target_sha256="f" * 64
    )


def test_first_claim_is_durable_before_any_academic_action(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    assert store.load(value.intent_sha256) is None
    assert store.list_records() == ()
    assert store.create_reviewed(value).disposition == "created"
    assert store.path_for(value.intent_sha256).read_bytes() == value.to_json_bytes()
    fresh = AssessmentSetupCorrelationStore(tmp_path, "english12")
    assert fresh.load(value.intent_sha256) == value
    assert fresh.list_records() == (value,)


def test_identical_repeated_claim_is_readonly_existing(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    before = store.path_for(value.intent_sha256).read_bytes()
    assert store.create_reviewed(value).disposition == "existing"
    assert store.path_for(value.intent_sha256).read_bytes() == before


def test_grade_then_membership_cas_survives_reopen(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    grade = bound_grade(value)
    assert store.advance_exact(expected=value, updated=grade).disposition == "advanced"
    member = bound_member(grade)
    assert store.advance_exact(expected=grade, updated=member).disposition == "advanced"
    assert store.load(value.intent_sha256) == member
    assert store.list_records() == (member,)


def test_existing_grade_item_has_one_membership_stage(tmp_path: Path) -> None:
    store, value = fixture(tmp_path, kind="use_existing")
    store.create_reviewed(value)
    member = bound_member(value)
    assert store.advance_exact(expected=value, updated=member).record == member


def test_stale_cas_cannot_replace_action_identity(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    grade = bound_grade(value)
    store.advance_exact(expected=value, updated=grade)
    with pytest.raises(AssessmentSetupCorrelationStorageConflict):
        store.advance_exact(
            expected=value, updated=replace(grade, grade_action_id="9" * 32)
        )
    assert store.load(value.intent_sha256) == grade


def test_create_cannot_reinitialize_advanced_record(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    store.advance_exact(expected=value, updated=bound_grade(value))
    with pytest.raises(AssessmentSetupCorrelationStorageConflict, match="advanced"):
        store.create_reviewed(value)


@pytest.mark.parametrize("problem", ["same_stage", "backward", "retarget"])
def test_invalid_transitions_cannot_persist(tmp_path: Path, problem: str) -> None:
    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    grade = bound_grade(value)
    if problem == "same_stage":
        candidate = value
        baseline = value
    elif problem == "backward":
        store.advance_exact(expected=value, updated=grade)
        candidate = value
        baseline = grade
    else:
        candidate = replace(grade, actor_id="stranger")
        baseline = value
    with pytest.raises(AssessmentSetupCorrelationStorageConflict):
        store.advance_exact(expected=baseline, updated=candidate)
    assert store.load(value.intent_sha256) == (
        grade if problem == "backward" else value
    )


def test_skip_grade_is_refused_by_core_contract(tmp_path: Path) -> None:
    from meridian.assessment_setup_correlation import AssessmentSetupCorrelationError

    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    with pytest.raises(AssessmentSetupCorrelationError, match="precede"):
        bound_member(value)
    assert store.load(value.intent_sha256) == value


def test_initial_claim_rejects_prebound_action(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    with pytest.raises(AssessmentSetupCorrelationStorageError, match="Initial"):
        store.create_reviewed(bound_grade(value))
    assert store.load(value.intent_sha256) is None


def test_wrong_workspace_or_class_rejected(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    with pytest.raises(AssessmentSetupCorrelationStorageError, match="workspace"):
        store.create_reviewed(replace(value, workspace_sha256="0" * 64))
    with pytest.raises(AssessmentSetupCorrelationStorageError, match="class"):
        store.create_reviewed(replace(value, class_id="other"))


def test_absent_class_cannot_be_fabricated(tmp_path: Path) -> None:
    store = AssessmentSetupCorrelationStore(tmp_path, "english12")
    with pytest.raises(Exception):
        with store._locked():
            pass
    assert not (tmp_path / "classes" / "english12").exists()


def test_corrupt_record_is_not_empty_history(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    store.path_for(value.intent_sha256).write_bytes(b"not-json")
    with pytest.raises(AssessmentSetupCorrelationStorageError):
        store.load(value.intent_sha256)
    with pytest.raises(AssessmentSetupCorrelationStorageError):
        store.create_reviewed(value)


def test_orphaned_temp_blocks_all_writers_and_inventory(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    (store.directory / ".correlation-orphan.tmp").write_bytes(b"partial")
    with pytest.raises(AssessmentSetupCorrelationStorageError, match="interrupted"):
        store.list_records()
    with pytest.raises(AssessmentSetupCorrelationStorageError, match="interrupted"):
        store.advance_exact(expected=value, updated=bound_grade(value))


def test_unknown_filename_blocks_collection(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    (store.directory / "unexpected.txt").write_bytes(b"no")
    with pytest.raises(AssessmentSetupCorrelationStorageError):
        store.list_records()


def test_read_only_absence_never_creates_folder_or_lock(tmp_path: Path) -> None:
    store = AssessmentSetupCorrelationStore(tmp_path, "english12")
    assert store.load("a" * 64) is None
    assert store.list_records() == ()
    assert list(tmp_path.iterdir()) == []


def test_symlink_file_rejected(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    target = store.path_for(value.intent_sha256)
    elsewhere = tmp_path / "original"
    os.replace(target, elsewhere)
    try:
        target.symlink_to(elsewhere)
    except (OSError, NotImplementedError):
        pytest.skip("Platform does not permit symlinks")
    with pytest.raises(Exception):
        store.load(value.intent_sha256)


def test_non_private_file_refused_on_posix(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("Windows relies on reparse and file-identity guards")
    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    target = store.path_for(value.intent_sha256)
    target.chmod(stat.S_IMODE(target.stat().st_mode) | 0o044)
    with pytest.raises(Exception):
        store.load(value.intent_sha256)


def test_second_writer_is_fenced_by_lock(tmp_path: Path) -> None:
    store, value = fixture(tmp_path)
    store.create_reviewed(value)
    other = AssessmentSetupCorrelationStore(tmp_path, "english12")
    with store._locked():
        with pytest.raises(AssessmentSetupCorrelationStorageConflict, match="busy"):
            other.advance_exact(expected=value, updated=bound_grade(value))
    assert store.load(value.intent_sha256) == value


def test_no_academic_side_ports_in_storage_module() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "meridian"
        / "assessment_setup_correlation_storage.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "commit_grade_item(",
        "commit_membership(",
        "select_grade_item(",
        "resume_restart_grade_item(",
        "input(",
        "prepare_membership_action(",
    ):
        assert forbidden not in source
