from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.external_gradebook_mapping import (
    ExternalGradebookMappingEntry,
    ExternalGradebookMappingValidationError,
    compose_external_gradebook_mapping_revision,
    external_gradebook_mapping_from_json_bytes,
    external_gradebook_mapping_reference,
    external_gradebook_mapping_to_json_bytes,
    validate_external_gradebook_mapping_against_scale,
)
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)

NOW = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)
PERIOD = AcademicPeriodRef("2026-2027", "q1")


def scale(*, revision: int = 1) -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id="english_12",
        scale_id="focus_standards",
        scale_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Focus Standards",
        description="Synthetic test scale.",
        levels=(
            ProficiencyLevel("developing", 1, "Developing", "Developing."),
            ProficiencyLevel("approaching", 2, "Approaching", "Approaching."),
            ProficiencyLevel("meeting", 3, "Meeting", "Meeting."),
            ProficiencyLevel("exceeding", 4, "Exceeding", "Exceeding."),
        ),
        proficiency_threshold_level_id="meeting",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def profile(*, target: ProficiencyScale | None = None):
    selected = scale() if target is None else target
    return compose_external_gradebook_mapping_revision(
        class_id=selected.class_id,
        profile_id="external_gradebook_q1",
        profile_revision=1,
        title="District gradebook scale",
        system_label="Vendor Neutral Gradebook",
        target_period=PERIOD,
        target_scale=proficiency_scale_reference(selected),
        entries=(
            ExternalGradebookMappingEntry("developing", "6.5"),
            ExternalGradebookMappingEntry("approaching", "7.5"),
            ExternalGradebookMappingEntry("meeting", "8.7"),
            ExternalGradebookMappingEntry("exceeding", "9.7"),
        ),
        actor_id="teacher_local",
        revised_at=NOW,
    )


def test_mapping_is_exact_scale_bound_versioned_and_canonical() -> None:
    target = scale()
    value = profile(target=target)

    assert validate_external_gradebook_mapping_against_scale(value, target) == value
    encoded = external_gradebook_mapping_to_json_bytes(value)
    loaded = external_gradebook_mapping_from_json_bytes(encoded)

    assert loaded == value
    assert external_gradebook_mapping_to_json_bytes(loaded) == encoded
    reference = external_gradebook_mapping_reference(value)
    assert reference.profile_revision == 1
    assert len(reference.profile_sha256) == 64
    assert value.system_label == "Vendor Neutral Gradebook"


def test_mapping_must_cover_every_level_and_fail_on_scale_change() -> None:
    target = scale()
    incomplete = compose_external_gradebook_mapping_revision(
        class_id=target.class_id,
        profile_id="incomplete",
        profile_revision=1,
        title="Incomplete",
        system_label="Any SIS",
        target_period=PERIOD,
        target_scale=proficiency_scale_reference(target),
        entries=(ExternalGradebookMappingEntry("meeting", "87"),),
        actor_id="teacher_local",
        revised_at=NOW,
    )

    with pytest.raises(
        ExternalGradebookMappingValidationError,
        match="every proficiency level",
    ):
        validate_external_gradebook_mapping_against_scale(incomplete, target)

    with pytest.raises(
        ExternalGradebookMappingValidationError,
        match="exact proficiency scale",
    ):
        validate_external_gradebook_mapping_against_scale(
            profile(target=target),
            scale(revision=2),
        )
