from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import meridian.grade_policy_storage as storage_module
from meridian.grade_item_storage import (
    grade_item_revision_digest_path,
    write_grade_item_revision,
)
from meridian.grade_items import GradeItemRevision
from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    ProficiencyGradeConversion,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
)
from meridian.grade_policy_storage import (
    GradePolicyDependencyError,
    GradePolicyStorageConflictError,
    GradePolicyStorageIntegrityError,
    GradePolicyStorageLockError,
    GradePolicyStorageNotFoundError,
    GradePolicyStorageTooLargeError,
    get_current_grade_policy_revision,
    grade_policy_current_path,
    grade_policy_directory,
    grade_policy_revision_digest_path,
    grade_policy_revision_path,
    grade_policy_revision_relative_path,
    list_grade_policy_ids,
    list_grade_policy_revisions,
    load_current_grade_policy,
    load_grade_policy_revision,
    select_grade_policy_revision,
    validate_grade_policy_dependencies,
    write_grade_policy_revision,
)
from meridian.proficiency_mapping import (
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    ProficiencyScaleReference,
)
from meridian.proficiency_mapping_storage import write_proficiency_scale_revision

CLASS_ID = "synthetic_class_2026"
POLICY_ID = "course_grade_policy"
NOW = datetime(2026, 9, 9, 21, 0, tzinfo=UTC)
STANDARD_A = "https://standards.example/RL:9-10.1?edition=2026"
STANDARD_B = "https://standards.example/W:9-10.2?edition=2026"


def make_workspace(tmp_path: Path) -> Path:
    class_root = tmp_path / "classes" / CLASS_ID
    class_root.mkdir(parents=True)
    (class_root / "roster.csv").write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "synthetic_class_2026,s001,Synthetic,Student,1\n",
        encoding="utf-8",
    )
    return tmp_path


def state_treatment() -> GradeStateTreatment:
    return GradeStateTreatment(
        missing="blocking",
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="blocking",
        unavailable="blocking",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="blocking",
    )


def reassessment() -> GradeReassessmentHandling:
    return GradeReassessmentHandling(
        "v02_attempt_and_reassessment_state",
        "blocking",
    )


def rounding() -> GradeRoundingPolicy:
    return GradeRoundingPolicy(Decimal("0.01"), "half_up", "final")


def write_item(
    root: Path,
    item_id: str,
    *,
    purpose: str = "standards_and_conventional",
) -> GradePolicyItemReference:
    revision = GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=CLASS_ID,
        grade_item_id=item_id,
        grade_item_revision=1,
        supersedes_revision=None,
        title=item_id.replace("_", " ").title(),
        purpose=purpose,  # type: ignore[arg-type]
        status="active",
        weighting=None,
        created_at=NOW,
        revised_at=NOW,
    )
    stored = write_grade_item_revision(root, revision).stored
    return GradePolicyItemReference(
        CLASS_ID,
        item_id,
        1,
        stored.revision_sha256,
    )


def conventional_configuration(
    *references: GradePolicyItemReference,
) -> ConventionalGradeConfiguration:
    return ConventionalGradeConfiguration(
        "total_points",
        tuple(
            GradePolicyItemParticipation(reference, None, None)
            for reference in references
        ),
        (),
    )


def policy(
    configuration: ConventionalGradeConfiguration | StandardsBasedGradeConfiguration,
    *,
    family: str = "conventional",
    revision: int = 1,
    policy_id: str = POLICY_ID,
    title: str = "Course Grade Policy",
) -> GradePolicyRevision:
    return GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=policy_id,
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title=title,
        calculation_family=family,  # type: ignore[arg-type]
        configuration=configuration,
        state_treatment=state_treatment(),
        reassessment_handling=reassessment(),
        rounding=rounding(),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW + timedelta(hours=revision - 1),
    )


def write_conventional_dependencies(
    root: Path,
) -> tuple[GradePolicyItemReference, GradePolicyItemReference]:
    return write_item(root, "unit1_test"), write_item(root, "essay_1")


def write_scale(root: Path) -> ProficiencyScaleReference:
    scale = ProficiencyScale(
        schema_version="1",
        record_type="meridian_proficiency_scale",
        class_id=CLASS_ID,
        scale_id="course_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Course Scale",
        description="Synthetic four-level course scale.",
        levels=(
            ProficiencyLevel("beginning", 1, "Beginning", "Beginning"),
            ProficiencyLevel("developing", 2, "Developing", "Developing"),
            ProficiencyLevel("proficient", 3, "Proficient", "Proficient"),
            ProficiencyLevel("advanced", 4, "Advanced", "Advanced"),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )
    return write_proficiency_scale_revision(root, scale).stored.reference


def standards_configuration(
    scale: ProficiencyScaleReference,
    *,
    complete_conversions: bool = True,
) -> StandardsBasedGradeConfiguration:
    conversions = [
        ProficiencyGradeConversion("beginning", Decimal("55")),
        ProficiencyGradeConversion("developing", Decimal("70")),
        ProficiencyGradeConversion("proficient", Decimal("85")),
    ]
    if complete_conversions:
        conversions.append(
            ProficiencyGradeConversion("advanced", Decimal("100"))
        )
    return StandardsBasedGradeConfiguration(
        target_scale=scale,
        standards=(
            StandardGradeParticipation(STANDARD_A, Decimal("0.6")),
            StandardGradeParticipation(STANDARD_B, Decimal("0.4")),
        ),
        conversions=tuple(conversions),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=1,
    )


def patch_resolved_standards(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = object()
    monkeypatch.setattr(
        storage_module,
        "load_workspace_standards_library",
        lambda root: marker,
    )
    monkeypatch.setattr(
        storage_module,
        "find_standard_definition",
        lambda library, standard_id: marker,
    )


def test_write_uses_canonical_path_and_does_not_select(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    result = write_grade_policy_revision(
        root,
        policy(conventional_configuration(*references)),
    )
    assert result.disposition == "created"
    assert result.stored.relative_path == (
        "classes/synthetic_class_2026/modules/meridian/grade_policies/"
        "course_grade_policy/revisions/1.json"
    )
    assert result.stored.path == grade_policy_revision_path(
        root,
        CLASS_ID,
        POLICY_ID,
        1,
    )
    assert grade_policy_revision_digest_path(
        root,
        CLASS_ID,
        POLICY_ID,
        1,
    ).is_file()
    assert get_current_grade_policy_revision(root, CLASS_ID, POLICY_ID) is None


def test_write_requires_existing_core_class(tmp_path: Path) -> None:
    fake_ref = GradePolicyItemReference(CLASS_ID, "unit1", 1, "a" * 64)
    with pytest.raises(GradePolicyStorageNotFoundError):
        write_grade_policy_revision(
            tmp_path,
            policy(conventional_configuration(fake_ref)),
        )


def test_exact_retry_is_idempotent(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    value = policy(conventional_configuration(*references))
    created = write_grade_policy_revision(root, value)
    existing = write_grade_policy_revision(root, value)
    assert existing.disposition == "existing"
    assert existing.stored.policy_sha256 == created.stored.policy_sha256


def test_same_revision_identity_different_content_conflicts(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    configuration = conventional_configuration(*references)
    write_grade_policy_revision(root, policy(configuration))
    with pytest.raises(GradePolicyStorageConflictError):
        write_grade_policy_revision(
            root,
            policy(configuration, title="Changed Title"),
        )


def test_history_is_linear_and_immutable(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    configuration = conventional_configuration(*references)
    first = write_grade_policy_revision(
        root,
        policy(configuration),
    ).stored.content
    write_grade_policy_revision(
        root,
        policy(configuration, revision=2),
    )
    assert load_grade_policy_revision(
        root,
        CLASS_ID,
        POLICY_ID,
        1,
    ).content == first
    assert list_grade_policy_revisions(root, CLASS_ID, POLICY_ID) == (1, 2)

    skipped = replace(
        policy(configuration, revision=2),
        policy_revision=4,
        supersedes_revision=3,
        revised_at=NOW + timedelta(hours=4),
    )
    with pytest.raises(GradePolicyStorageConflictError):
        write_grade_policy_revision(root, skipped)


def test_policy_ids_are_listed_deterministically(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    configuration = conventional_configuration(*references)
    write_grade_policy_revision(
        root,
        policy(configuration, policy_id="z_policy"),
    )
    write_grade_policy_revision(
        root,
        policy(configuration, policy_id="a_policy"),
    )
    assert list_grade_policy_ids(root, CLASS_ID) == ("a_policy", "z_policy")


def test_selection_is_explicit_and_can_reselect_history(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    configuration = conventional_configuration(*references)
    write_grade_policy_revision(root, policy(configuration))
    write_grade_policy_revision(root, policy(configuration, revision=2))

    assert get_current_grade_policy_revision(root, CLASS_ID, POLICY_ID) is None
    selected2 = select_grade_policy_revision(
        root,
        CLASS_ID,
        POLICY_ID,
        2,
        expected_current_revision=None,
    )
    assert selected2.disposition == "created"
    assert get_current_grade_policy_revision(root, CLASS_ID, POLICY_ID) == 2

    selected1 = select_grade_policy_revision(
        root,
        CLASS_ID,
        POLICY_ID,
        1,
        expected_current_revision=2,
    )
    assert selected1.disposition == "updated"
    assert load_current_grade_policy(
        root,
        CLASS_ID,
        POLICY_ID,
    ).policy.policy_revision == 1


def test_selection_retry_and_stale_compare_and_swap(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    configuration = conventional_configuration(*references)
    write_grade_policy_revision(root, policy(configuration))

    first = select_grade_policy_revision(
        root,
        CLASS_ID,
        POLICY_ID,
        1,
        expected_current_revision=None,
    )
    retry = select_grade_policy_revision(
        root,
        CLASS_ID,
        POLICY_ID,
        1,
        expected_current_revision=1,
    )
    assert first.disposition == "created"
    assert retry.disposition == "existing"

    with pytest.raises(GradePolicyStorageConflictError):
        select_grade_policy_revision(
            root,
            CLASS_ID,
            POLICY_ID,
            1,
            expected_current_revision=None,
        )


def test_highest_revision_is_not_inferred_as_current(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    configuration = conventional_configuration(*references)
    write_grade_policy_revision(root, policy(configuration))
    write_grade_policy_revision(root, policy(configuration, revision=2))
    assert get_current_grade_policy_revision(root, CLASS_ID, POLICY_ID) is None
    assert load_current_grade_policy(root, CLASS_ID, POLICY_ID) is None


def test_stored_reference_binds_exact_digest(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    stored = write_grade_policy_revision(
        root,
        policy(conventional_configuration(*references)),
    ).stored
    assert stored.reference.policy_sha256 == stored.policy_sha256
    assert stored.reference.policy_revision == 1
    assert stored.policy_sha256 == hashlib.sha256(stored.content).hexdigest()


def test_revision_json_tampering_fails(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    stored = write_grade_policy_revision(
        root,
        policy(conventional_configuration(*references)),
    ).stored
    path = grade_policy_revision_path(root, CLASS_ID, POLICY_ID, 1)
    path.write_bytes(stored.content.replace(b"Course Grade", b"Course Xrade", 1))
    with pytest.raises(GradePolicyStorageIntegrityError):
        load_grade_policy_revision(root, CLASS_ID, POLICY_ID, 1)


def test_digest_sidecar_tampering_fails(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    write_grade_policy_revision(
        root,
        policy(conventional_configuration(*references)),
    )
    digest = grade_policy_revision_digest_path(root, CLASS_ID, POLICY_ID, 1)
    digest.write_text("0" * 64 + "\n", encoding="ascii")
    with pytest.raises(GradePolicyStorageIntegrityError):
        load_grade_policy_revision(root, CLASS_ID, POLICY_ID, 1)


def test_current_pointer_digest_is_verified(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    write_grade_policy_revision(
        root,
        policy(conventional_configuration(*references)),
    )
    select_grade_policy_revision(
        root,
        CLASS_ID,
        POLICY_ID,
        1,
        expected_current_revision=None,
    )
    current = grade_policy_current_path(root, CLASS_ID, POLICY_ID)
    data = json.loads(current.read_text(encoding="utf-8"))
    data["policy_sha256"] = "0" * 64
    current.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(GradePolicyStorageIntegrityError):
        load_current_grade_policy(root, CLASS_ID, POLICY_ID)


def test_noncanonical_pointer_fails(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    stored = write_grade_policy_revision(
        root,
        policy(conventional_configuration(*references)),
    ).stored
    current = grade_policy_current_path(root, CLASS_ID, POLICY_ID)
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "record_type": "meridian_grade_policy_current",
                "class_id": CLASS_ID,
                "policy_id": POLICY_ID,
                "policy_revision": 1,
                "policy_sha256": stored.policy_sha256,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(GradePolicyStorageIntegrityError):
        get_current_grade_policy_revision(root, CLASS_ID, POLICY_ID)


def test_unexpected_policy_entry_fails_closed(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    write_grade_policy_revision(
        root,
        policy(conventional_configuration(*references)),
    )
    (grade_policy_directory(root, CLASS_ID, POLICY_ID) / "notes.txt").write_text(
        "unexpected",
        encoding="utf-8",
    )
    with pytest.raises(GradePolicyStorageIntegrityError):
        list_grade_policy_revisions(root, CLASS_ID, POLICY_ID)


def test_lock_conflict_fails_closed(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    configuration = conventional_configuration(*references)
    write_grade_policy_revision(root, policy(configuration))
    lock = grade_policy_directory(root, CLASS_ID, POLICY_ID) / ".write.lock"
    lock.write_text("leftover", encoding="utf-8")
    with pytest.raises(GradePolicyStorageLockError):
        write_grade_policy_revision(
            root,
            policy(configuration, revision=2),
        )


def test_bounded_read_rejects_oversize(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    write_grade_policy_revision(
        root,
        policy(conventional_configuration(*references)),
    )
    with pytest.raises(GradePolicyStorageTooLargeError):
        load_grade_policy_revision(
            root,
            CLASS_ID,
            POLICY_ID,
            1,
            maximum_revision_bytes=8,
        )


def test_relative_path_is_platform_neutral() -> None:
    value = grade_policy_revision_relative_path(CLASS_ID, POLICY_ID, 3)
    assert value == (
        "classes/synthetic_class_2026/modules/meridian/grade_policies/"
        "course_grade_policy/revisions/3.json"
    )
    assert "\\" not in value


def test_invalid_policy_identifier_cannot_traverse(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    with pytest.raises(Exception):
        grade_policy_directory(root, CLASS_ID, "../outside")
    assert not (tmp_path / "outside").exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_symlinked_revision_is_rejected(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    write_grade_policy_revision(
        root,
        policy(conventional_configuration(*references)),
    )
    path = grade_policy_revision_path(root, CLASS_ID, POLICY_ID, 1)
    target = tmp_path / "outside.json"
    target.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not permitted on this platform")
    with pytest.raises(GradePolicyStorageIntegrityError):
        load_grade_policy_revision(root, CLASS_ID, POLICY_ID, 1)


def test_grade_item_digest_mismatch_is_dependency_error(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    reference = write_item(root, "unit1_test")
    bad = replace(reference, grade_item_revision_sha256="0" * 64)
    with pytest.raises(GradePolicyDependencyError, match="digest"):
        write_grade_policy_revision(
            root,
            policy(conventional_configuration(bad)),
        )


def test_reporting_only_grade_item_cannot_enter_conventional_policy(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    reference = write_item(root, "report_only", purpose="reporting_only")
    with pytest.raises(GradePolicyDependencyError, match="purpose"):
        write_grade_policy_revision(
            root,
            policy(conventional_configuration(reference)),
        )


def test_missing_grade_item_is_dependency_error(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    reference = GradePolicyItemReference(
        CLASS_ID,
        "missing_item",
        1,
        "a" * 64,
    )
    with pytest.raises(GradePolicyDependencyError):
        write_grade_policy_revision(
            root,
            policy(conventional_configuration(reference)),
        )


def test_valid_standards_dependencies_are_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_workspace(tmp_path)
    scale = write_scale(root)
    patch_resolved_standards(monkeypatch)
    value = policy(
        standards_configuration(scale),
        family="standards_based",
    )
    dependencies = validate_grade_policy_dependencies(root, value)
    assert dependencies.target_scale is not None
    assert dependencies.target_scale.reference == scale
    assert len(dependencies.standards) == 2
    assert write_grade_policy_revision(root, value).disposition == "created"


def test_scale_digest_mismatch_is_dependency_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_workspace(tmp_path)
    scale = write_scale(root)
    patch_resolved_standards(monkeypatch)
    bad = replace(scale, scale_sha256="0" * 64)
    with pytest.raises(GradePolicyDependencyError, match="scale digest"):
        write_grade_policy_revision(
            root,
            policy(
                standards_configuration(bad),
                family="standards_based",
            ),
        )


def test_conversion_must_cover_exact_scale_levels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_workspace(tmp_path)
    scale = write_scale(root)
    patch_resolved_standards(monkeypatch)
    with pytest.raises(GradePolicyDependencyError, match="cover exactly"):
        write_grade_policy_revision(
            root,
            policy(
                standards_configuration(
                    scale,
                    complete_conversions=False,
                ),
                family="standards_based",
            ),
        )


def test_unresolved_standard_is_dependency_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_workspace(tmp_path)
    scale = write_scale(root)
    marker = object()
    monkeypatch.setattr(
        storage_module,
        "load_workspace_standards_library",
        lambda root: marker,
    )
    monkeypatch.setattr(
        storage_module,
        "find_standard_definition",
        lambda library, standard_id: None,
    )
    with pytest.raises(GradePolicyDependencyError, match="does not resolve"):
        write_grade_policy_revision(
            root,
            policy(
                standards_configuration(scale),
                family="standards_based",
            ),
        )


def test_selection_revalidates_exact_dependencies(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    references = write_conventional_dependencies(root)
    write_grade_policy_revision(
        root,
        policy(conventional_configuration(*references)),
    )
    dependent = references[0]
    digest_path = grade_item_revision_digest_path(
        root,
        CLASS_ID,
        dependent.grade_item_id,
        dependent.grade_item_revision,
    )
    digest_path.write_text("0" * 64 + "\n", encoding="ascii")
    with pytest.raises(GradePolicyDependencyError):
        select_grade_policy_revision(
            root,
            CLASS_ID,
            POLICY_ID,
            1,
            expected_current_revision=None,
        )
