from __future__ import annotations

from datetime import UTC, datetime

from pds_core.academic_periods import AcademicPeriodRef

from meridian.external_gradebook_mapping import (
    ExternalGradebookMappingEntry,
    compose_external_gradebook_mapping_revision,
)
from meridian.proficiency_mapping import proficiency_scale_reference
from meridian.sis_gradebook_reconciliation import (
    CurrentProficiencyObservation,
    build_sis_gradebook_reconciliation,
)
from tests.test_external_gradebook_mapping_issue111 import scale

NOW = datetime(2026, 10, 12, 21, 0, tzinfo=UTC)
PERIOD = AcademicPeriodRef("2026-2027", "q1")


def mapping():
    target = scale()
    return compose_external_gradebook_mapping_revision(
        class_id=target.class_id,
        profile_id="gradebook_q1",
        profile_revision=1,
        title="External reporting scale",
        system_label="Any SIS",
        target_period=PERIOD,
        target_scale=proficiency_scale_reference(target),
        entries=(
            ExternalGradebookMappingEntry("developing", "6.5"),
            ExternalGradebookMappingEntry("approaching", "7.5"),
            ExternalGradebookMappingEntry("meeting", "8.7"),
            ExternalGradebookMappingEntry("exceeding", "9.7"),
        ),
        actor_id="teacher_local",
        revised_at=NOW,
    )


def observation(
    student_id: str,
    standard_id: str,
    level_id: str | None,
    *,
    revision: int = 1,
) -> CurrentProficiencyObservation:
    target = scale()
    return CurrentProficiencyObservation(
        class_id=target.class_id,
        target_period=PERIOD,
        calendar_revision=3,
        student_id=student_id,
        standard_id=standard_id,
        result_revision=revision,
        result_sha256=(f"{revision:x}" * 64)[:64],
        target_scale=proficiency_scale_reference(target),
        status="calculated" if level_id is not None else "insufficient_evidence",
        proficiency_level_id=level_id,
    )


def rows_by_identity(preview):
    indexes = {column.column_id: i for i, column in enumerate(preview.columns)}
    return {
        (
            row.values[indexes["student_id"]],
            row.values[indexes["standard_id"]],
        ): row.values
        for row in preview.rows
    }


def test_first_checkpoint_emits_new_and_review_required_without_inventing_absence() -> (
    None
):
    target = scale()
    built = build_sis_gradebook_reconciliation(
        class_id=target.class_id,
        target_period=PERIOD,
        calendar_revision=3,
        target_scale=target,
        mapping_profile=mapping(),
        current_observations=(
            observation("student_001", "RL.CR.11-12.1", "developing"),
            observation("student_002", "RL.CR.11-12.1", "meeting"),
            observation("student_003", "RL.CR.11-12.1", None),
            observation("student_005", "W.WP.11-12.4", "exceeding"),
        ),
        generated_at=NOW,
    )

    rows = rows_by_identity(built.display_preview)
    assert rows[("student_001", "RL.CR.11-12.1")][-1] == "NEW"
    assert rows[("student_001", "RL.CR.11-12.1")][4] == "6.5"
    assert rows[("student_002", "RL.CR.11-12.1")][-1] == "NEW"
    assert rows[("student_003", "RL.CR.11-12.1")][-1] == "REVIEW_REQUIRED"
    assert rows[("student_003", "RL.CR.11-12.1")][4] is None
    assert ("student_004", "RL.CR.11-12.1") not in rows
    assert built.display_preview == built.checkpoint_preview


def test_prior_checkpoint_drives_changed_unchanged_new_and_review_required() -> None:
    target = scale()
    first = build_sis_gradebook_reconciliation(
        class_id=target.class_id,
        target_period=PERIOD,
        calendar_revision=3,
        target_scale=target,
        mapping_profile=mapping(),
        current_observations=(
            observation("student_001", "RL.CR.11-12.1", "developing"),
            observation("student_002", "RL.CR.11-12.1", "meeting"),
            observation("student_003", "RL.CR.11-12.1", None),
            observation("student_005", "W.WP.11-12.4", "exceeding"),
        ),
        generated_at=NOW,
    )

    second = build_sis_gradebook_reconciliation(
        class_id=target.class_id,
        target_period=PERIOD,
        calendar_revision=3,
        target_scale=target,
        mapping_profile=mapping(),
        current_observations=(
            observation("student_001", "RL.CR.11-12.1", "approaching", revision=2),
            observation("student_002", "RL.CR.11-12.1", "meeting", revision=2),
            observation("student_003", "RL.CR.11-12.1", None, revision=2),
            observation("student_004", "W.WP.11-12.4", "exceeding"),
        ),
        generated_at=NOW,
        prior_checkpoint=first.checkpoint_preview,
        changed_only=True,
    )

    full = rows_by_identity(second.checkpoint_preview)
    changed = rows_by_identity(second.display_preview)

    assert full[("student_001", "RL.CR.11-12.1")][-1] == "CHANGED"
    assert full[("student_001", "RL.CR.11-12.1")][7] == "6.5"
    assert full[("student_001", "RL.CR.11-12.1")][4] == "7.5"
    assert full[("student_002", "RL.CR.11-12.1")][-1] == "UNCHANGED"
    assert full[("student_003", "RL.CR.11-12.1")][-1] == "REVIEW_REQUIRED"
    assert full[("student_004", "W.WP.11-12.4")][-1] == "NEW"
    assert full[("student_005", "W.WP.11-12.4")][-1] == "REVIEW_REQUIRED"

    assert ("student_002", "RL.CR.11-12.1") not in changed
    assert set(changed) == {
        ("student_001", "RL.CR.11-12.1"),
        ("student_003", "RL.CR.11-12.1"),
        ("student_004", "W.WP.11-12.4"),
        ("student_005", "W.WP.11-12.4"),
    }
