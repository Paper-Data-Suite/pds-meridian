from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from meridian.grouping_signal_derivation import (
    grouping_signal_derivation_reference,
)
from meridian.grouping_signal_preview import (
    GroupingSignalPreviewCurrentness,
    grouping_signal_preview_reference,
)
from meridian.grouping_signal_review import (
    GROUPING_SIGNAL_REVIEW_RECORD_TYPE,
    GROUPING_SIGNAL_REVIEW_SCHEMA_VERSION,
    GroupingSignalReviewSerializationError,
    GroupingSignalReviewValidationError,
    assess_grouping_signal_review_applicability,
    create_grouping_signal_review_decision,
    grouping_signal_review_from_json_bytes,
    grouping_signal_review_reference,
    grouping_signal_review_to_dict,
    grouping_signal_review_to_json_bytes,
)
from tests.test_grouping_signal_derivation import derived_snapshot
from tests.test_grouping_signal_preview import _preview

NOW = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)


def _warning_ids(preview) -> tuple[str, ...]:
    return tuple(
        sorted(
            item.diagnostic_id
            for item in preview.diagnostics
            if item.severity == "warning"
        )
    )


def test_warning_free_current_preview_can_be_deliberately_accepted() -> None:
    preview = _preview()
    review = create_grouping_signal_review_decision(
        preview,
        grouping_signal_preview_reference(preview),
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=(),
        actor_id="teacher_local",
        reviewed_at=NOW,
    )

    assert review.schema_version == GROUPING_SIGNAL_REVIEW_SCHEMA_VERSION
    assert review.record_type == GROUPING_SIGNAL_REVIEW_RECORD_TYPE
    assert review.decision == "accepted_for_export"
    assert review.acknowledged_warning_ids == ()
    assert review.derivation_reference == preview.derivation_reference
    assert review.preview_reference == grouping_signal_preview_reference(preview)
    assert not hasattr(review, "__dict__")
    with pytest.raises(FrozenInstanceError):
        review.decision = "rejected"  # type: ignore[misc]


def test_acceptance_requires_exactly_every_warning_id() -> None:
    preview = _preview(
        levels={
            "student_2": None,
            "student_3": "level_4",
        }
    )
    required = _warning_ids(preview)
    assert required

    with pytest.raises(
        GroupingSignalReviewValidationError,
        match="exactly every warning",
    ):
        create_grouping_signal_review_decision(
            preview,
            grouping_signal_preview_reference(preview),
            review_revision=1,
            supersedes_revision=None,
            decision="accepted_for_export",
            acknowledged_warning_ids=(),
            actor_id="teacher_local",
            reviewed_at=NOW,
        )

    review = create_grouping_signal_review_decision(
        preview,
        grouping_signal_preview_reference(preview),
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=tuple(reversed(required)),
        actor_id="teacher_local",
        reviewed_at=NOW,
    )
    assert review.acknowledged_warning_ids == required


def test_acceptance_cannot_acknowledge_away_blocking_diagnostic() -> None:
    preview = _preview(
        levels={
            "student_1": None,
            "student_2": None,
        }
    )
    blocking = tuple(
        item.diagnostic_id
        for item in preview.diagnostics
        if item.severity == "blocking"
    )
    assert blocking

    with pytest.raises(
        GroupingSignalReviewValidationError,
        match="blocking diagnostics",
    ):
        create_grouping_signal_review_decision(
            preview,
            grouping_signal_preview_reference(preview),
            review_revision=1,
            supersedes_revision=None,
            decision="accepted_for_export",
            acknowledged_warning_ids=_warning_ids(preview),
            actor_id="teacher_local",
            reviewed_at=NOW,
        )

    rejected = create_grouping_signal_review_decision(
        preview,
        grouping_signal_preview_reference(preview),
        review_revision=1,
        supersedes_revision=None,
        decision="rejected",
        acknowledged_warning_ids=(),
        actor_id="teacher_local",
        reviewed_at=NOW,
    )
    assert rejected.decision == "rejected"


def test_rejected_review_cannot_record_acknowledgments() -> None:
    preview = _preview(
        levels={
            "student_2": None,
            "student_3": "level_4",
        }
    )
    with pytest.raises(
        GroupingSignalReviewValidationError,
        match="rejected review",
    ):
        create_grouping_signal_review_decision(
            preview,
            grouping_signal_preview_reference(preview),
            review_revision=1,
            supersedes_revision=None,
            decision="rejected",
            acknowledged_warning_ids=_warning_ids(preview),
            actor_id="teacher_local",
            reviewed_at=NOW,
        )


def test_review_applicability_is_separate_from_immutable_decision() -> None:
    preview = _preview()
    review = create_grouping_signal_review_decision(
        preview,
        grouping_signal_preview_reference(preview),
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=(),
        actor_id="teacher_local",
        reviewed_at=NOW,
    )

    current = assess_grouping_signal_review_applicability(
        review,
        preview.currentness,
    )
    assert current.status == "current"

    changed = derived_snapshot(
        levels={
            "student_1": "level_2",
            "student_2": "level_3",
            "student_3": "level_4",
        }
    )
    stale = assess_grouping_signal_review_applicability(
        review,
        GroupingSignalPreviewCurrentness(
            "stale",
            ("source_proficiency_changed",),
            grouping_signal_derivation_reference(changed),
        ),
    )
    assert stale.status == "stale"
    assert stale.reason_codes == ("source_proficiency_changed",)

    rejected = replace(
        review,
        review_revision=2,
        supersedes_revision=1,
        decision="rejected",
        acknowledged_warning_ids=(),
        reviewed_at=NOW + timedelta(seconds=1),
    )
    not_accepted = assess_grouping_signal_review_applicability(
        rejected,
        preview.currentness,
    )
    assert not_accepted.status == "not_accepted"


def test_review_canonical_round_trip_and_reference() -> None:
    preview = _preview()
    review = create_grouping_signal_review_decision(
        preview,
        grouping_signal_preview_reference(preview),
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=(),
        actor_id="teacher_local",
        reviewed_at=NOW,
    )
    payload = grouping_signal_review_to_json_bytes(review)
    assert grouping_signal_review_from_json_bytes(payload) == review
    reference = grouping_signal_review_reference(review)
    assert reference.derivation_id == review.derivation_reference.derivation_id
    assert reference.review_revision == 1
    assert len(reference.review_sha256) == 64

    mapping = grouping_signal_review_to_dict(review)
    mapping["unexpected"] = True
    noncanonical = (json.dumps(mapping, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(GroupingSignalReviewSerializationError, match="keys"):
        grouping_signal_review_from_json_bytes(noncanonical)

    with pytest.raises(GroupingSignalReviewSerializationError, match="canonical"):
        grouping_signal_review_from_json_bytes(
            payload.replace(b"\n", b"\r\n")
        )


def test_review_revision_lineage_is_explicit_and_contiguous() -> None:
    preview = _preview()
    with pytest.raises(GroupingSignalReviewValidationError, match="supersede"):
        create_grouping_signal_review_decision(
            preview,
            grouping_signal_preview_reference(preview),
            review_revision=2,
            supersedes_revision=None,
            decision="accepted_for_export",
            acknowledged_warning_ids=(),
            actor_id="teacher_local",
            reviewed_at=NOW,
        )
