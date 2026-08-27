from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.routes import class_dir

from meridian.evidence import NativeScale, NativeScaleLevel
from meridian.proficiency_mapping import (
    NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
    NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    NativeValueMappingProfile,
    NativeValueSourceSignature,
    ProficiencyLevel,
    ProficiencyScale,
    ScaledLevelMappingRule,
    proficiency_scale_reference,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingDependencyError,
    ProficiencyMappingStorageConflictError,
    ProficiencyMappingStorageIntegrityError,
    get_current_mapping_profile_revision,
    get_current_proficiency_scale_revision,
    load_current_mapping_profile,
    load_current_proficiency_scale,
    load_mapping_profile_revision,
    load_proficiency_scale_revision,
    mapping_profile_revision_relative_path,
    proficiency_scale_current_path,
    proficiency_scale_revision_relative_path,
    select_mapping_profile_revision,
    select_proficiency_scale_revision,
    write_mapping_profile_revision,
    write_proficiency_scale_revision,
)

CLASS_ID = "synthetic_class_2026"
NOW = datetime(2026, 8, 26, 17, tzinfo=UTC)


def root(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    class_dir(workspace, CLASS_ID).mkdir(parents=True)
    return workspace


def scale(*, revision: int = 1) -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="course_proficiency",
        scale_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Course proficiency",
        description="Criterion-referenced classroom proficiency.",
        levels=(
            ProficiencyLevel("beginning", 1, "Beginning", "Initial evidence."),
            ProficiencyLevel("developing", 2, "Developing", "Partial evidence."),
            ProficiencyLevel("proficient", 3, "Proficient", "Meets criterion."),
            ProficiencyLevel("advanced", 4, "Advanced", "Extends criterion."),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def profile(
    target: ProficiencyScale, *, revision: int = 1
) -> NativeValueMappingProfile:
    native = NativeScale(
        "rubric_024",
        (
            NativeScaleLevel(0, "Low", "Limited"),
            NativeScaleLevel(2, "Middle", "Developing"),
            NativeScaleLevel(4, "High", "Strong"),
        ),
    )
    return NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id=target.scale_id,
        profile_id="quillan_024",
        profile_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        target_scale=proficiency_scale_reference(target),
        source_signature=NativeValueSourceSignature(
            producer_module_id="quillan",
            publication_kind="academic_result_set",
            manifest_contract_version="quillan_academic_result_manifest_v1",
            producer_contract_version="quillan_academic_work_v1",
            projection_id="quillan.academic_result",
            projection_contract_version="1",
            producer_reader_distribution="quillan",
            producer_reader_version="0.10.0",
            result_kind="overall_standard_rating",
            target_kind="standard",
        ),
        mapping_kind="exact_native_scale",
        native_scale=native,
        points_possible=None,
        mapping_rules=(
            ScaledLevelMappingRule(0, "beginning"),
            ScaledLevelMappingRule(2, "proficient"),
            ScaledLevelMappingRule(4, "advanced"),
        ),
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def test_canonical_relative_paths() -> None:
    assert proficiency_scale_revision_relative_path(
        CLASS_ID, "course_proficiency", 1
    ) == (
        "classes/synthetic_class_2026/modules/meridian/proficiency_scales/"
        "course_proficiency/revisions/1.json"
    )
    assert mapping_profile_revision_relative_path(
        CLASS_ID, "course_proficiency", "quillan_024", 1
    ).endswith("mapping_profiles/quillan_024/revisions/1.json")


def test_scale_write_is_immutable_and_does_not_auto_select(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    written = write_proficiency_scale_revision(workspace, scale())
    assert written.disposition == "created"
    replay = write_proficiency_scale_revision(workspace, scale())
    assert replay.disposition == "existing"
    assert get_current_proficiency_scale_revision(
        workspace, CLASS_ID, "course_proficiency"
    ) is None
    with pytest.raises(ProficiencyMappingStorageConflictError):
        write_proficiency_scale_revision(
            workspace, replace(scale(), title="Changed in place")
        )


def test_scale_selection_is_explicit_cas_and_historical(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    write_proficiency_scale_revision(workspace, scale())
    write_proficiency_scale_revision(workspace, scale(revision=2))
    select_proficiency_scale_revision(
        workspace,
        CLASS_ID,
        "course_proficiency",
        1,
        expected_current_scale_revision=None,
    )
    current = load_current_proficiency_scale(
        workspace, CLASS_ID, "course_proficiency"
    )
    assert current is not None
    assert current.scale.scale_revision == 1
    with pytest.raises(ProficiencyMappingStorageConflictError, match="Expected"):
        select_proficiency_scale_revision(
            workspace,
            CLASS_ID,
            "course_proficiency",
            2,
            expected_current_scale_revision=None,
        )
    select_proficiency_scale_revision(
        workspace,
        CLASS_ID,
        "course_proficiency",
        2,
        expected_current_scale_revision=1,
    )
    select_proficiency_scale_revision(
        workspace,
        CLASS_ID,
        "course_proficiency",
        1,
        expected_current_scale_revision=2,
    )
    assert get_current_proficiency_scale_revision(
        workspace, CLASS_ID, "course_proficiency"
    ) == 1


def test_profile_requires_exact_persisted_target_scale(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    with pytest.raises(ProficiencyMappingDependencyError):
        write_mapping_profile_revision(workspace, profile(scale()))
    stored_scale = write_proficiency_scale_revision(workspace, scale()).stored
    value = profile(stored_scale.scale)
    written = write_mapping_profile_revision(workspace, value)
    assert written.disposition == "created"
    assert get_current_mapping_profile_revision(
        workspace, CLASS_ID, "course_proficiency", "quillan_024"
    ) is None


def test_profile_write_select_revision_and_replay(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    target = write_proficiency_scale_revision(workspace, scale()).stored.scale
    first = profile(target)
    write_mapping_profile_revision(workspace, first)
    assert write_mapping_profile_revision(workspace, first).disposition == "existing"
    select_mapping_profile_revision(
        workspace,
        CLASS_ID,
        target.scale_id,
        first.profile_id,
        1,
        expected_current_profile_revision=None,
    )
    current = load_current_mapping_profile(
        workspace, CLASS_ID, target.scale_id, first.profile_id
    )
    assert current is not None
    assert current.profile.profile_revision == 1
    second = profile(target, revision=2)
    write_mapping_profile_revision(workspace, second)
    assert get_current_mapping_profile_revision(
        workspace, CLASS_ID, target.scale_id, first.profile_id
    ) == 1
    select_mapping_profile_revision(
        workspace,
        CLASS_ID,
        target.scale_id,
        first.profile_id,
        2,
        expected_current_profile_revision=1,
    )
    assert load_mapping_profile_revision(
        workspace, CLASS_ID, target.scale_id, first.profile_id, 1
    ).profile == first


def test_scale_pointer_tamper_fails_closed(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    write_proficiency_scale_revision(workspace, scale())
    select_proficiency_scale_revision(
        workspace,
        CLASS_ID,
        "course_proficiency",
        1,
        expected_current_scale_revision=None,
    )
    pointer = proficiency_scale_current_path(
        workspace, CLASS_ID, "course_proficiency"
    )
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["scale_sha256"] = "0" * 64
    pointer.write_bytes(
        (json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    with pytest.raises(ProficiencyMappingStorageIntegrityError, match="digest"):
        load_current_proficiency_scale(workspace, CLASS_ID, "course_proficiency")


def test_revision_digest_tamper_fails_closed(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    stored = write_proficiency_scale_revision(workspace, scale()).stored
    stored.path.write_bytes(stored.content + b" ")
    with pytest.raises(ProficiencyMappingStorageIntegrityError, match="digest"):
        load_proficiency_scale_revision(
            workspace, CLASS_ID, "course_proficiency", 1
        )


def test_unexpected_scale_entry_fails_closed(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    stored = write_proficiency_scale_revision(workspace, scale()).stored
    (stored.path.parent.parent / "latest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ProficiencyMappingStorageIntegrityError, match="unexpected"):
        load_proficiency_scale_revision(
            workspace, CLASS_ID, "course_proficiency", 1
        )


def test_symlinked_scale_pointer_fails_closed(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    write_proficiency_scale_revision(workspace, scale())
    pointer = proficiency_scale_current_path(
        workspace, CLASS_ID, "course_proficiency"
    )
    target = tmp_path / "pointer.json"
    target.write_text("{}", encoding="utf-8")
    try:
        pointer.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation not permitted")
    with pytest.raises(ProficiencyMappingStorageIntegrityError):
        load_current_proficiency_scale(workspace, CLASS_ID, "course_proficiency")
