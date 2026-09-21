from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.reporting_snapshot import (
    MAXIMUM_REPORTING_ACTOR_ID_LENGTH,
    MAXIMUM_REPORTING_PURPOSE_LENGTH,
    MAXIMUM_REPORTING_RATIONALE_LENGTH,
    MAXIMUM_REPORTING_TITLE_LENGTH,
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionReference,
    ReportingDefinitionRevision,
    ReportingDefinitionValidationError,
    ReportingSnapshotPredecessor,
    ReportingSnapshotReference,
    ReportingSnapshotSerializationError,
    ReportingSnapshotValidationError,
    reporting_definition_reference,
    reporting_definition_reference_from_dict,
    reporting_definition_reference_to_dict,
    reporting_definition_revision_from_dict,
    reporting_definition_revision_from_json_bytes,
    reporting_definition_revision_to_dict,
    reporting_definition_revision_to_json_bytes,
    reporting_snapshot_predecessor_from_dict,
    reporting_snapshot_predecessor_to_dict,
    reporting_snapshot_reference_from_dict,
    reporting_snapshot_reference_to_dict,
    validate_reporting_definition_revision,
    validate_reporting_definition_transition,
)

CLASS_ID = "synthetic_class_2026"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 19, 23, 0, tzinfo=UTC)
SHA_A = "a" * 64


def definition(
    revision: int = 1,
    *,
    class_id: str = CLASS_ID,
    definition_id: str = "mp1_grade_report",
    purpose: str = "Marking-period Grade review",
    title: str = "MP1 Grade Report",
    period: AcademicPeriodRef = PERIOD,
    rationale: str | None = None,
    revised_at: datetime | None = None,
) -> ReportingDefinitionRevision:
    return ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=class_id,
        definition_id=definition_id,
        definition_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        report_kind="grade_report",
        purpose=purpose,
        title=title,
        target_period=period,
        intended_audience="teacher",
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=rationale,
        revised_at=revised_at or NOW + timedelta(minutes=revision - 1),
    )


def test_error_codes_preserve_definition_vs_general_scope_distinction() -> None:
    assert (
        ReportingDefinitionValidationError.code
        == "reporting_snapshot.definition_invalid"
    )
    assert ReportingSnapshotValidationError.code == "reporting_snapshot.scope_invalid"
    assert (
        ReportingSnapshotSerializationError.code
        == "reporting_snapshot.integrity_failed"
    )


def test_definition_is_frozen_and_slotted() -> None:
    value = definition()

    with pytest.raises(FrozenInstanceError):
        value.title = "Changed"  # type: ignore[misc]
    assert not hasattr(value, "__dict__")


def test_definition_round_trips_canonically_and_reference_binds_exact_bytes() -> None:
    value = definition(rationale="Frozen for the teacher's reporting review.")

    encoded = reporting_definition_revision_to_json_bytes(value)
    assert encoded.endswith(b"\n")
    assert reporting_definition_revision_from_json_bytes(encoded) == value

    reference = reporting_definition_reference(value)
    assert reference.definition_sha256 == hashlib.sha256(encoded).hexdigest()
    assert reporting_definition_reference_from_dict(
        reporting_definition_reference_to_dict(reference)
    ) == reference


def test_definition_serialization_uses_exact_schema() -> None:
    data = reporting_definition_revision_to_dict(definition())
    data["unexpected"] = True

    with pytest.raises(
        ReportingSnapshotValidationError,
        match="exact schema",
    ):
        reporting_definition_revision_from_dict(data)

    data = reporting_definition_revision_to_dict(definition())
    del data["title"]
    with pytest.raises(
        ReportingSnapshotValidationError,
        match="exact schema",
    ):
        reporting_definition_revision_from_dict(data)


def test_definition_json_rejects_noncanonical_encoding() -> None:
    data = reporting_definition_revision_to_dict(definition())
    alternate = json.dumps(data, sort_keys=True).encode("utf-8")

    with pytest.raises(
        ReportingSnapshotSerializationError,
        match="not the canonical encoding",
    ):
        reporting_definition_revision_from_json_bytes(alternate)


def test_definition_json_rejects_duplicate_object_keys() -> None:
    canonical = reporting_definition_revision_to_json_bytes(definition()).decode(
        "utf-8"
    )
    duplicate = canonical.replace(
        '  "class_id": "synthetic_class_2026",',
        '  "class_id": "synthetic_class_2026",\n'
        '  "class_id": "synthetic_class_2026",',
        1,
    ).encode("utf-8")

    with pytest.raises(
        ReportingSnapshotSerializationError,
        match="duplicate JSON object key",
    ):
        reporting_definition_revision_from_json_bytes(duplicate)


def test_definition_revision_transition_is_linear_and_identity_stable() -> None:
    first = definition()
    second = definition(
        revision=2,
        title="Updated MP1 Grade Report",
        rationale="Clarify teacher-facing report title.",
    )

    assert validate_reporting_definition_transition(first, second) == second

    with pytest.raises(
        ReportingSnapshotValidationError,
        match="definition_id must match",
    ):
        validate_reporting_definition_transition(
            first,
            replace(second, definition_id="another_definition"),
        )

    with pytest.raises(
        ReportingSnapshotValidationError,
        match="increment by one",
    ):
        validate_reporting_definition_transition(
            first,
            replace(second, definition_revision=3, supersedes_revision=2),
        )

    with pytest.raises(
        ReportingSnapshotValidationError,
        match="must not be earlier",
    ):
        validate_reporting_definition_transition(
            first,
            replace(second, revised_at=first.revised_at - timedelta(seconds=1)),
        )


def test_revision_fields_must_form_contiguous_history() -> None:
    with pytest.raises(
        ReportingSnapshotValidationError,
        match="revision 1",
    ):
        replace(definition(), supersedes_revision=1)

    with pytest.raises(
        ReportingSnapshotValidationError,
        match="definition_revision - 1",
    ):
        replace(definition(revision=2), supersedes_revision=None)


def test_definition_scope_uses_exact_core_academic_period_reference() -> None:
    value = definition()
    assert value.target_period == PERIOD
    assert reporting_definition_revision_to_dict(value)["target_period"] == {
        "school_year": "2026-2027",
        "period_id": "mp1",
    }


def test_v1_report_kind_and_audience_are_deliberately_bounded() -> None:
    value = reporting_definition_revision_to_dict(definition())
    value["report_kind"] = "intervention_report"
    with pytest.raises(
        ReportingSnapshotValidationError,
        match="report_kind must be grade_report",
    ):
        reporting_definition_revision_from_dict(value)

    value = reporting_definition_revision_to_dict(definition())
    value["intended_audience"] = "guardian"
    with pytest.raises(
        ReportingSnapshotValidationError,
        match="intended_audience must be teacher",
    ):
        reporting_definition_revision_from_dict(value)


def test_reporting_actor_is_explicit_teacher_only() -> None:
    actor = ReportingActor("teacher", "teacher_local")
    assert actor.actor_id == "teacher_local"

    with pytest.raises(
        ReportingSnapshotValidationError,
        match="actor kind must be teacher",
    ):
        ReportingActor("system", "automatic")  # type: ignore[arg-type]


def test_definition_requires_reporting_actor_not_grade_policy_actor_shape() -> None:
    with pytest.raises(
        ReportingSnapshotValidationError,
        match="ReportingActor",
    ):
        replace(definition(), actor={"kind": "teacher", "actor_id": "teacher"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", ""),
        ("purpose", " leading"),
        ("purpose", "trailing "),
        ("purpose", "line\nbreak"),
        ("title", ""),
        ("title", "line\nbreak"),
        ("rationale", ""),
        ("rationale", "line\nbreak"),
    ],
)
def test_human_text_is_bounded_clean_and_single_line(field: str, value: str) -> None:
    with pytest.raises(ReportingSnapshotValidationError):
        replace(definition(), **{field: value})


def test_text_limits_are_enforced() -> None:
    with pytest.raises(ReportingSnapshotValidationError, match="maximum length"):
        replace(definition(), title="x" * (MAXIMUM_REPORTING_TITLE_LENGTH + 1))
    with pytest.raises(ReportingSnapshotValidationError, match="maximum length"):
        replace(definition(), purpose="x" * (MAXIMUM_REPORTING_PURPOSE_LENGTH + 1))
    with pytest.raises(ReportingSnapshotValidationError, match="maximum length"):
        replace(
            definition(),
            rationale="x" * (MAXIMUM_REPORTING_RATIONALE_LENGTH + 1),
        )
    with pytest.raises(ReportingSnapshotValidationError, match="maximum length"):
        ReportingActor(
            "teacher",
            "x" * (MAXIMUM_REPORTING_ACTOR_ID_LENGTH + 1),
        )


def test_datetime_is_normalized_to_utc_and_must_be_aware() -> None:
    eastern = timezone(timedelta(hours=-4))
    value = definition(revised_at=datetime(2026, 9, 19, 19, 0, tzinfo=eastern))
    assert value.revised_at == NOW
    assert value.revised_at.tzinfo == UTC

    with pytest.raises(
        ReportingSnapshotValidationError,
        match="timezone-aware",
    ):
        definition(revised_at=datetime(2026, 9, 19, 23, 0))


def test_definition_validation_returns_fresh_equal_value() -> None:
    value = definition()
    validated = validate_reporting_definition_revision(value)

    assert validated == value
    assert validated is not value


def test_reference_requires_exact_lowercase_sha256_and_path_safe_identity() -> None:
    reference = ReportingDefinitionReference(
        CLASS_ID,
        "mp1_grade_report",
        1,
        SHA_A,
    )
    assert reference.definition_sha256 == SHA_A

    with pytest.raises(ReportingSnapshotValidationError):
        replace(reference, definition_sha256="A" * 64)
    with pytest.raises(ReportingSnapshotValidationError):
        replace(reference, definition_id="../escape")


def test_snapshot_reference_is_exact_frozen_identity_not_current_selection() -> None:
    reference = ReportingSnapshotReference(
        class_id=CLASS_ID,
        snapshot_id="snapshot_001",
        snapshot_sha256=SHA_A,
    )

    assert reporting_snapshot_reference_from_dict(
        reporting_snapshot_reference_to_dict(reference)
    ) == reference
    with pytest.raises(FrozenInstanceError):
        reference.snapshot_id = "snapshot_002"  # type: ignore[misc]
    assert not hasattr(reference, "__dict__")


def test_snapshot_reference_rejects_unsafe_identity_and_invalid_digest() -> None:
    with pytest.raises(ReportingSnapshotValidationError):
        ReportingSnapshotReference(CLASS_ID, "../snapshot", SHA_A)
    with pytest.raises(ReportingSnapshotValidationError):
        ReportingSnapshotReference(CLASS_ID, "snapshot_001", "bad")


def test_predecessor_relationship_is_explicit_and_round_trips() -> None:
    predecessor = ReportingSnapshotPredecessor(
        relationship="corrects",
        snapshot_reference=ReportingSnapshotReference(
            CLASS_ID,
            "snapshot_001",
            SHA_A,
        ),
    )

    assert reporting_snapshot_predecessor_from_dict(
        reporting_snapshot_predecessor_to_dict(predecessor)
    ) == predecessor


@pytest.mark.parametrize(
    "relationship",
    ["supersedes", "corrects", "replaces_for_current_use"],
)
def test_supported_predecessor_relationships_are_closed(relationship: str) -> None:
    value = ReportingSnapshotPredecessor(
        relationship=relationship,  # type: ignore[arg-type]
        snapshot_reference=ReportingSnapshotReference(
            CLASS_ID,
            "snapshot_001",
            SHA_A,
        ),
    )
    assert value.relationship == relationship


def test_predecessor_relationship_rejects_implicit_current_semantics() -> None:
    with pytest.raises(
        ReportingSnapshotValidationError,
        match="snapshot relationship",
    ):
        ReportingSnapshotPredecessor(
            relationship="current",  # type: ignore[arg-type]
            snapshot_reference=ReportingSnapshotReference(
                CLASS_ID,
                "snapshot_001",
                SHA_A,
            ),
        )


def test_reference_and_predecessor_dicts_reject_unknown_fields() -> None:
    definition_ref = reporting_definition_reference_to_dict(
        reporting_definition_reference(definition())
    )
    definition_ref["path"] = "private/path.json"
    with pytest.raises(ReportingSnapshotValidationError, match="exact schema"):
        reporting_definition_reference_from_dict(definition_ref)

    snapshot_ref = reporting_snapshot_reference_to_dict(
        ReportingSnapshotReference(CLASS_ID, "snapshot_001", SHA_A)
    )
    snapshot_ref["is_current"] = True
    with pytest.raises(ReportingSnapshotValidationError, match="exact schema"):
        reporting_snapshot_reference_from_dict(snapshot_ref)

    predecessor = reporting_snapshot_predecessor_to_dict(
        ReportingSnapshotPredecessor(
            "supersedes",
            ReportingSnapshotReference(CLASS_ID, "snapshot_001", SHA_A),
        )
    )
    predecessor["selected"] = True
    with pytest.raises(ReportingSnapshotValidationError, match="exact schema"):
        reporting_snapshot_predecessor_from_dict(predecessor)
