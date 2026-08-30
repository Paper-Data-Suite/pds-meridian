from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.grouping_signal_storage import list_grouping_signal_ids
from pds_core.routes import class_dir, class_metadata_path
from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    write_workspace_standards_library,
)

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyTarget,
    academic_period_proficiency_aggregation_policy_reference,
)
from meridian.academic_period_proficiency_storage import (
    write_academic_period_proficiency_policy_revision,
)
from meridian.grouping_signal_policy import (
    GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
    GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
    GroupingSignalAcademicBasis,
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicy,
    GroupingSignalPolicyActor,
)
from meridian.grouping_signal_policy_storage import (
    GroupingSignalPolicyDependencyError,
    GroupingSignalPolicyStorageConflictError,
    get_current_grouping_signal_policy_revision,
    load_current_grouping_signal_policy,
    select_grouping_signal_policy_revision,
    validate_grouping_signal_policy_dependencies,
    write_grouping_signal_policy_revision,
)
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.proficiency_mapping_storage import write_proficiency_scale_revision
from meridian.standards_proficiency import StandardProficiencyActor

CLASS_ID = "synthetic_class_2026"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "mp1"
STANDARD_ID = "urn:njsls:ela:RL.CR.9-10.1"
NOW = datetime(2026, 8, 30, 20, tzinfo=UTC)


def scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="teacher_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Teacher proficiency scale",
        description="Criterion-referenced scale.",
        levels=(
            ProficiencyLevel("level_1", 1, "Beginning", "Beginning evidence."),
            ProficiencyLevel("level_2", 2, "Developing", "Developing evidence."),
            ProficiencyLevel("level_3", 3, "Proficient", "Proficient evidence."),
            ProficiencyLevel("level_4", 4, "Extending", "Extending evidence."),
        ),
        proficiency_threshold_level_id="level_3",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def period_policy(
    target_scale: ProficiencyScale,
) -> AcademicPeriodProficiencyAggregationPolicy:
    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="period_proficiency_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Academic Period proficiency",
        target_scale=proficiency_scale_reference(target_scale),
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def grouping_policy(
    target_scale: ProficiencyScale,
    source_policy: AcademicPeriodProficiencyAggregationPolicy,
) -> GroupingSignalDerivationPolicy:
    return GroupingSignalDerivationPolicy(
        schema_version=GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="reading_planning_signal",
        policy_revision=1,
        supersedes_revision=None,
        title="Reading planning signal",
        academic_basis=GroupingSignalAcademicBasis(
            basis_kind="academic_period_proficiency",
            target_period=AcademicPeriodProficiencyTarget(
                AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
                1,
            ),
            standard_id=STANDARD_ID,
            source_policy=(
                academic_period_proficiency_aggregation_policy_reference(
                    source_policy
                )
            ),
            target_scale=proficiency_scale_reference(target_scale),
        ),
        dimension_id="reading_planning",
        band_count=3,
        band_definitions=(
            GroupingSignalBandDefinition(1, 1, 1),
            GroupingSignalBandDefinition(2, 2, 3),
            GroupingSignalBandDefinition(3, 4, 4),
        ),
        tie_handling="same_level_same_band",
        missing_result_handling="noncontributing",
        insufficient_result_handling="blocking",
        actor=GroupingSignalPolicyActor("teacher", "teacher_local"),
        rationale="Temporary contextual planning support.",
        revised_at=NOW,
    )


def seed_exact_dependencies(
    tmp_path: Path,
) -> tuple[
    Path,
    ProficiencyScale,
    AcademicPeriodProficiencyAggregationPolicy,
]:
    workspace = tmp_path / "workspace"
    class_dir(workspace, CLASS_ID).mkdir(parents=True)
    metadata = ClassMetadata(
        class_id=CLASS_ID,
        school_year=SCHOOL_YEAR,
        created_at=NOW,
        updated_at=NOW,
        module_details={},
    )
    write_class_metadata(class_metadata_path(workspace, CLASS_ID), metadata)

    calendar = AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=SCHOOL_YEAR,
        calendar_revision=1,
        created_at=NOW,
        updated_at=NOW,
        periods=(
            AcademicPeriod(
                period_id=PERIOD_ID,
                period_type="marking_period",
                label="Marking Period 1",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 11, 8),
                parent_period_id=None,
                sequence=1,
                lifecycle="active",
            ),
        ),
    )
    write_academic_period_calendar(
        workspace,
        calendar,
        expected_current_revision=None,
    )

    write_workspace_standards_library(
        workspace,
        StandardsLibrary(
            standards=(
                StandardDefinition(
                    standard_id=STANDARD_ID,
                    code="RL.CR.9-10.1",
                    source="NJSLS-ELA-2023",
                    short_name="Textual evidence",
                    description="Synthetic durable standard for policy testing.",
                    subject="ELA",
                    grade_band="9-10",
                    active=True,
                    available_modules=("meridian",),
                ),
            )
        ),
    )

    target_scale = scale()
    write_proficiency_scale_revision(workspace, target_scale)
    source = period_policy(target_scale)
    write_academic_period_proficiency_policy_revision(workspace, source)
    return workspace, target_scale, source


def test_exact_academic_dependencies_persist_select_and_replay(
    tmp_path: Path,
) -> None:
    workspace, target_scale, source = seed_exact_dependencies(tmp_path)
    value = grouping_policy(target_scale, source)

    dependencies = validate_grouping_signal_policy_dependencies(workspace, value)
    assert dependencies.class_metadata.class_id == CLASS_ID
    assert dependencies.target_period.period_id == PERIOD_ID
    assert dependencies.standard.standard_id == STANDARD_ID
    assert dependencies.source_policy.policy == source
    assert dependencies.target_scale.scale == target_scale

    created = write_grouping_signal_policy_revision(workspace, value)
    assert created.disposition == "created"
    assert get_current_grouping_signal_policy_revision(
        workspace,
        CLASS_ID,
        value.policy_id,
    ) is None

    replay = write_grouping_signal_policy_revision(workspace, value)
    assert replay.disposition == "existing"
    assert replay.stored.reference == created.stored.reference

    selected = select_grouping_signal_policy_revision(
        workspace,
        CLASS_ID,
        value.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    assert selected.disposition == "created"
    current = load_current_grouping_signal_policy(
        workspace,
        CLASS_ID,
        value.policy_id,
    )
    assert current is not None
    assert current.reference == created.stored.reference

    assert list_grouping_signal_ids(workspace, CLASS_ID) == ()


def test_exact_dependency_digest_mismatch_rejects_policy_write(
    tmp_path: Path,
) -> None:
    workspace, target_scale, source = seed_exact_dependencies(tmp_path)
    value = grouping_policy(target_scale, source)
    bad_basis = replace(
        value.academic_basis,
        source_policy=replace(
            value.academic_basis.source_policy,
            policy_sha256="0" * 64,
        ),
    )
    with pytest.raises(GroupingSignalPolicyDependencyError, match="digest"):
        write_grouping_signal_policy_revision(
            workspace,
            replace(value, academic_basis=bad_basis),
        )


def test_unresolved_period_standard_or_scale_rejects_policy_write(
    tmp_path: Path,
) -> None:
    workspace, target_scale, source = seed_exact_dependencies(tmp_path)
    value = grouping_policy(target_scale, source)

    missing_period = replace(
        value.academic_basis,
        target_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef(SCHOOL_YEAR, "mp2"),
            1,
        ),
    )
    with pytest.raises(GroupingSignalPolicyDependencyError, match="Period"):
        write_grouping_signal_policy_revision(
            workspace,
            replace(value, academic_basis=missing_period),
        )

    missing_standard = replace(
        value.academic_basis,
        standard_id="urn:njsls:ela:missing",
    )
    with pytest.raises(GroupingSignalPolicyDependencyError, match="standard_id"):
        write_grouping_signal_policy_revision(
            workspace,
            replace(value, academic_basis=missing_standard),
        )

    missing_scale = replace(
        value.academic_basis,
        target_scale=replace(
            value.academic_basis.target_scale,
            scale_revision=2,
        ),
    )
    with pytest.raises(GroupingSignalPolicyDependencyError, match="scale"):
        write_grouping_signal_policy_revision(
            workspace,
            replace(value, academic_basis=missing_scale),
        )


def test_same_revision_different_content_collision_remains_immutable(
    tmp_path: Path,
) -> None:
    workspace, target_scale, source = seed_exact_dependencies(tmp_path)
    value = grouping_policy(target_scale, source)
    first = write_grouping_signal_policy_revision(workspace, value).stored

    with pytest.raises(GroupingSignalPolicyStorageConflictError):
        write_grouping_signal_policy_revision(
            workspace,
            replace(value, rationale="Changed without a new revision."),
        )

    replay = write_grouping_signal_policy_revision(workspace, value).stored
    assert replay.content == first.content
    assert replay.policy_sha256 == first.policy_sha256
