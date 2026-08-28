from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pds_core.routes import class_dir

from meridian.grade_item_storage import write_grade_item_revision
from meridian.grade_items import GradeItemRevision, GradeItemWeightingMetadata
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.proficiency_mapping_storage import write_proficiency_scale_revision
from meridian.standards_evidence import (
    STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
    STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
    GradeItemAggregationBasis,
    StandardAggregationInputs,
    standard_aggregation_inputs_sha256,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    StandardProficiencyActor,
    StandardProficiencyCalculationPolicy,
    StandardProficiencyResultSnapshot,
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
)
from meridian.standards_proficiency_storage import (
    StandardProficiencyResultDependencyError,
    StandardProficiencyStorageConflictError,
    StandardProficiencyStorageIntegrityError,
    StandardProficiencyStorageLockError,
    get_current_standard_proficiency_result_revision,
    list_standard_proficiency_result_revisions,
    load_current_standard_proficiency_result,
    load_standard_proficiency_result_revision,
    select_standard_proficiency_result_revision,
    standard_proficiency_policy_revision_path,
    standard_proficiency_result_current_path,
    standard_proficiency_result_family_directory,
    standard_proficiency_result_revision_relative_path,
    standard_proficiency_standard_key,
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
STANDARD_ID = "https://standards.example/NJSLS:ELA/RI.CR.11-12.1"
NOW = datetime(2026, 8, 27, 23, tzinfo=UTC)


def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    class_dir(root, CLASS_ID).mkdir(parents=True)
    return root


def grade_item() -> GradeItemRevision:
    return GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=1,
        supersedes_revision=None,
        title="Unit 1 assessment",
        purpose="standards_proficiency",
        status="active",
        weighting=GradeItemWeightingMetadata(
            category_id="assessment",
            relative_weight=Decimal("1.0"),
        ),
        created_at=NOW,
        revised_at=NOW,
    )


def scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="course_proficiency",
        scale_revision=1,
        supersedes_revision=None,
        title="Course proficiency",
        description="Synthetic criterion-referenced scale.",
        levels=(
            ProficiencyLevel("beginning", 1, "Beginning", "Initial evidence."),
            ProficiencyLevel("developing", 2, "Developing", "Partial evidence."),
            ProficiencyLevel("proficient", 3, "Proficient", "Meets criterion."),
            ProficiencyLevel("advanced", 4, "Advanced", "Extends criterion."),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def policy(target: ProficiencyScale) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="course_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Course policy",
        target_scale=proficiency_scale_reference(target),
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=("association_unresolved",),
        native_state_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def snapshot(
    root: Path,
    *,
    revision: int = 1,
    calculated_at: datetime = NOW,
) -> StandardProficiencyResultSnapshot:
    stored_grade_item = write_grade_item_revision(root, grade_item()).stored
    stored_scale = write_proficiency_scale_revision(root, scale()).stored.scale
    stored_policy = write_standard_proficiency_policy_revision(
        root,
        policy(stored_scale),
    ).stored.policy
    inputs = StandardAggregationInputs(
        schema_version=STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        record_type=STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item=GradeItemAggregationBasis(
            CLASS_ID,
            GRADE_ITEM_ID,
            1,
            stored_grade_item.revision_sha256,
        ),
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(stored_scale),
        entries=(),
    )
    outcome = calculate_standard_proficiency(
        inputs,
        stored_policy,
        stored_scale,
    )
    return create_standard_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=revision,
        calculated_at=calculated_at,
    )


def test_result_path_hashes_raw_standard_id(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    value = snapshot(root)
    key = standard_proficiency_standard_key(STANDARD_ID)
    assert len(key) == 64
    relative = standard_proficiency_result_revision_relative_path(
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
    )
    assert STANDARD_ID not in relative
    assert key in relative

    stored = write_standard_proficiency_result_revision(root, value).stored
    assert stored.relative_path == relative


def test_result_write_is_immutable_and_does_not_auto_select(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    value = snapshot(root)
    created = write_standard_proficiency_result_revision(root, value)
    retry = write_standard_proficiency_result_revision(root, value)

    assert created.disposition == "created"
    assert retry.disposition == "existing"
    assert retry.stored.reference == created.stored.reference
    assert (
        get_current_standard_proficiency_result_revision(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
        )
        is None
    )

    changed = replace(value, calculated_at=NOW + timedelta(seconds=1))
    with pytest.raises(StandardProficiencyStorageConflictError):
        write_standard_proficiency_result_revision(root, changed)


def test_result_history_is_contiguous_and_replayable(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    first = snapshot(root)
    second = snapshot(
        root,
        revision=2,
        calculated_at=NOW + timedelta(minutes=1),
    )
    write_standard_proficiency_result_revision(root, first)
    write_standard_proficiency_result_revision(root, second)

    assert list_standard_proficiency_result_revisions(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
    ) == (1, 2)
    assert (
        load_standard_proficiency_result_revision(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            1,
        ).snapshot
        == first
    )

    with pytest.raises(
        StandardProficiencyStorageConflictError,
        match="contiguous",
    ):
        write_standard_proficiency_result_revision(
            root,
            snapshot(
                root,
                revision=4,
                calculated_at=NOW + timedelta(minutes=4),
            ),
        )


def test_result_selection_is_explicit_cas_and_historical(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    first = snapshot(root)
    second = snapshot(
        root,
        revision=2,
        calculated_at=NOW + timedelta(minutes=1),
    )
    write_standard_proficiency_result_revision(root, first)
    write_standard_proficiency_result_revision(root, second)

    created = select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    assert created.disposition == "created"

    current = load_current_standard_proficiency_result(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
    )
    assert current is not None
    assert current.snapshot == first

    with pytest.raises(StandardProficiencyStorageConflictError, match="Expected"):
        select_standard_proficiency_result_revision(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            2,
            expected_current_result_revision=None,
        )

    updated = select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        2,
        expected_current_result_revision=1,
    )
    assert updated.disposition == "updated"

    historical = select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=2,
    )
    assert historical.disposition == "updated"
    assert (
        get_current_standard_proficiency_result_revision(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
        )
        == 1
    )


def test_new_result_write_verifies_exact_policy_dependency(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    value = snapshot(root)
    bad_reference = replace(
        value.policy_reference,
        policy_sha256="0" * 64,
    )
    bad_outcome = replace(
        value.outcome,
        policy_reference=bad_reference,
    )
    forged = replace(
        value,
        policy_reference=bad_reference,
        outcome=bad_outcome,
    )
    with pytest.raises(
        StandardProficiencyResultDependencyError,
        match="policy",
    ):
        write_standard_proficiency_result_revision(root, forged)


def test_new_result_write_verifies_exact_scale_dependency(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    value = snapshot(root)
    bad_scale = replace(
        value.target_scale,
        scale_sha256="0" * 64,
    )
    bad_inputs = replace(value.inputs, target_scale=bad_scale)
    bad_inputs_sha = standard_aggregation_inputs_sha256(bad_inputs)
    bad_outcome = replace(
        value.outcome,
        target_scale=bad_scale,
        aggregation_inputs_sha256=bad_inputs_sha,
    )
    forged = replace(
        value,
        inputs=bad_inputs,
        inputs_sha256=bad_inputs_sha,
        target_scale=bad_scale,
        outcome=bad_outcome,
    )
    with pytest.raises(
        StandardProficiencyResultDependencyError,
        match="scale",
    ):
        write_standard_proficiency_result_revision(root, forged)


def test_exact_result_replay_does_not_require_current_policy_state(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    value = snapshot(root)
    stored = write_standard_proficiency_result_revision(root, value).stored

    policy_path = standard_proficiency_policy_revision_path(
        root,
        CLASS_ID,
        value.policy_reference.policy_id,
        value.policy_reference.policy_revision,
    )
    policy_path.unlink()
    Path(str(policy_path) + ".sha256").unlink()

    replayed = load_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
    )
    assert replayed.content == stored.content
    assert (
        write_standard_proficiency_result_revision(root, value).disposition
        == "existing"
    )


def test_result_revision_digest_tamper_fails_closed(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    stored = write_standard_proficiency_result_revision(
        root,
        snapshot(root),
    ).stored
    stored.path.write_bytes(stored.content + b" ")

    with pytest.raises(StandardProficiencyStorageIntegrityError, match="digest"):
        load_standard_proficiency_result_revision(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            1,
        )


def test_result_pointer_tamper_fails_closed(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    value = snapshot(root)
    write_standard_proficiency_result_revision(root, value)
    select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )

    pointer = standard_proficiency_result_current_path(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
    )
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["result_sha256"] = "0" * 64
    pointer.write_bytes(
        (
            json.dumps(
                data,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )

    with pytest.raises(StandardProficiencyStorageIntegrityError, match="digest"):
        load_current_standard_proficiency_result(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
        )


def test_unexpected_result_family_entry_fails_closed(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    value = snapshot(root)
    write_standard_proficiency_result_revision(root, value)
    family = standard_proficiency_result_family_directory(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
    )
    (family / "latest.json").write_text("{}", encoding="utf-8")

    with pytest.raises(
        StandardProficiencyStorageIntegrityError,
        match="unexpected",
    ):
        load_standard_proficiency_result_revision(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            1,
        )


def test_result_family_lock_conflict_is_narrow(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    value = snapshot(root)
    family = standard_proficiency_result_family_directory(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
    )
    (family / "revisions").mkdir(parents=True)
    (family / ".write.lock").write_text("held\n", encoding="utf-8")

    with pytest.raises(StandardProficiencyStorageLockError):
        write_standard_proficiency_result_revision(root, value)
