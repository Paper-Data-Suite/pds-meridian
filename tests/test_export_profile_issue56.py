from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from meridian.export_profile import (
    EXPORT_PROFILE_RECORD_TYPE,
    EXPORT_PROFILE_SCHEMA_VERSION,
    EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
    MAXIMUM_EXPORT_COLUMN_NAME_LENGTH,
    MAXIMUM_EXPORT_PROFILE_ACTOR_ID_LENGTH,
    MAXIMUM_EXPORT_PROFILE_COLUMNS,
    MAXIMUM_EXPORT_PROFILE_PURPOSE_LENGTH,
    MAXIMUM_EXPORT_PROFILE_RATIONALE_LENGTH,
    MAXIMUM_EXPORT_PROFILE_TITLE_LENGTH,
    ExportColumn,
    ExportProfileActor,
    ExportProfileReference,
    ExportProfileRevision,
    ExportProfileSerializationError,
    ExportProfileValidationError,
    ExportRepresentation,
    export_profile_reference,
    export_profile_reference_from_dict,
    export_profile_reference_to_dict,
    export_profile_requires_roster_observation,
    export_profile_revision_from_dict,
    export_profile_revision_from_json_bytes,
    export_profile_revision_to_dict,
    export_profile_revision_to_json_bytes,
    export_source_kind,
    roster_extra_field_name,
    validate_export_profile_revision,
    validate_export_profile_transition,
    validate_export_source_field,
)

CLASS_ID = "synthetic_class_2026"
NOW = datetime(2026, 9, 21, 20, 45, tzinfo=UTC)
SHA_A = "a" * 64


def snapshot_columns() -> tuple[ExportColumn, ...]:
    return (
        ExportColumn("target.student_id", "Student ID"),
        ExportColumn("grade.effective_grade", "Grade"),
        ExportColumn("grade.effective_source", "Grade Source"),
    )


def roster_columns() -> tuple[ExportColumn, ...]:
    return (
        ExportColumn("target.student_id", "Student ID"),
        ExportColumn("roster.last_name", "Last Name"),
        ExportColumn("roster.first_name", "First Name"),
        ExportColumn("roster.period", "Roster Period"),
        ExportColumn("roster.extra:district_student_id", "District Student ID"),
        ExportColumn("grade.effective_grade", "Grade"),
    )


def profile(
    revision: int = 1,
    *,
    columns: tuple[ExportColumn, ...] | None = None,
    representation: ExportRepresentation | None = None,
    title: str = "District Gradebook Import",
    purpose: str = "Teacher-controlled marking-period Grade transfer",
    rationale: str | None = None,
    revised_at: datetime | None = None,
) -> ExportProfileRevision:
    return ExportProfileRevision(
        schema_version=EXPORT_PROFILE_SCHEMA_VERSION,
        record_type=EXPORT_PROFILE_RECORD_TYPE,
        source_registry_version=EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
        class_id=CLASS_ID,
        profile_id="district_gradebook_csv",
        profile_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title=title,
        purpose=purpose,
        columns=snapshot_columns() if columns is None else columns,
        representation=representation
        or ExportRepresentation(
            format="csv",
            include_header=True,
            line_ending="crlf",
            utf8_bom=True,
        ),
        actor=ExportProfileActor("teacher", "teacher_local"),
        rationale=rationale,
        revised_at=revised_at or NOW + timedelta(minutes=revision - 1),
    )


def test_error_codes_distinguish_validation_from_integrity() -> None:
    assert ExportProfileValidationError.code == "export_profile.invalid"
    assert ExportProfileSerializationError.code == "export_profile.integrity_failed"


def test_profile_is_frozen_slotted_and_preserves_column_order() -> None:
    value = profile(columns=tuple(reversed(snapshot_columns())))

    assert value.columns == tuple(reversed(snapshot_columns()))
    with pytest.raises(FrozenInstanceError):
        value.title = "Changed"  # type: ignore[misc]
    assert not hasattr(value, "__dict__")


def test_snapshot_source_registry_is_closed_and_not_arbitrary_object_traversal(
) -> None:
    for source in (
        "snapshot.class_id",
        "snapshot.snapshot_id",
        "snapshot.snapshot_sha256",
        "target.student_id",
        "target.school_year",
        "target.period_id",
        "target.calendar_revision",
        "target.calculation_family",
        "row.status",
        "row.unavailable_reason",
        "grade.base_result_status",
        "grade.base_grade",
        "grade.base_freshness_status",
        "grade.effective_grade",
        "grade.effective_source",
        "policy.policy_id",
        "policy.policy_revision",
    ):
        assert validate_export_source_field(source) == source
        assert export_source_kind(source) == "snapshot"

    for source in (
        "grade.explanation.rounding.quantum",
        "snapshot.__dict__",
        "target.*",
        "jsonpath:$.rows[*]",
        "python:row.grade * 100",
    ):
        with pytest.raises(ExportProfileValidationError, match="not supported"):
            validate_export_source_field(source)


def test_roster_source_registry_is_explicit_and_optional_field_is_exact() -> None:
    for source in (
        "roster.first_name",
        "roster.last_name",
        "roster.display_name",
        "roster.period",
    ):
        assert validate_export_source_field(source) == source
        assert export_source_kind(source) == "roster"
        assert roster_extra_field_name(source) is None

    source = "roster.extra:district_student_id"
    assert validate_export_source_field(source) == source
    assert export_source_kind(source) == "roster"
    assert roster_extra_field_name(source) == "district_student_id"


@pytest.mark.parametrize(
    "source",
    [
        "roster.*",
        "roster.extra:*",
        "roster.extra:district_*",
        "roster.extra:",
        "roster.extra: district_id",
        "roster.extra:district_id ",
        "roster.extra:district\nid",
        "roster.extra:first_name",
        "roster.extra:last_name",
        "roster.extra:period",
        "roster.extra:student_id",
        "roster.extra:class_id",
    ],
)
def test_roster_wildcards_blank_dirty_and_required_aliases_are_rejected(
    source: str,
) -> None:
    with pytest.raises(ExportProfileValidationError):
        validate_export_source_field(source)


def test_profile_requires_roster_observation_only_for_roster_backed_columns() -> None:
    assert not export_profile_requires_roster_observation(profile())
    assert export_profile_requires_roster_observation(profile(columns=roster_columns()))


def test_column_names_are_explicit_unique_and_single_line() -> None:
    value = profile(
        columns=(
            ExportColumn("target.student_id", "Student ID"),
            ExportColumn("grade.effective_grade", "Grade, Final"),
        )
    )
    assert value.columns[1].output_name == "Grade, Final"

    with pytest.raises(ExportProfileValidationError, match="duplicates"):
        profile(
            columns=(
                ExportColumn("target.student_id", "Grade"),
                ExportColumn("grade.effective_grade", "Grade"),
            )
        )
    with pytest.raises(ExportProfileValidationError):
        ExportColumn("target.student_id", "Student\nID")
    with pytest.raises(ExportProfileValidationError, match="maximum length"):
        ExportColumn(
            "target.student_id",
            "x" * (MAXIMUM_EXPORT_COLUMN_NAME_LENGTH + 1),
        )


def test_profile_requires_one_bounded_column_tuple() -> None:
    with pytest.raises(ExportProfileValidationError, match="at least one"):
        profile(columns=())

    with pytest.raises(ExportProfileValidationError, match="maximum column count"):
        profile(
            columns=tuple(
                ExportColumn("target.student_id", f"Student ID {index}")
                for index in range(MAXIMUM_EXPORT_PROFILE_COLUMNS + 1)
            )
        )

    with pytest.raises(ExportProfileValidationError, match="tuple"):
        replace(profile(), columns=list(snapshot_columns()))  # type: ignore[arg-type]


def test_representation_is_bounded_to_csv_tsv_and_explicit_settings() -> None:
    assert ExportRepresentation("csv", True, "lf", False).format == "csv"
    assert ExportRepresentation("tsv", False, "crlf", True).format == "tsv"

    with pytest.raises(ExportProfileValidationError, match="csv or tsv"):
        ExportRepresentation("xlsx", True, "lf", False)  # type: ignore[arg-type]
    with pytest.raises(ExportProfileValidationError, match="lf or crlf"):
        ExportRepresentation("csv", True, "native", False)  # type: ignore[arg-type]
    with pytest.raises(ExportProfileValidationError, match="boolean"):
        ExportRepresentation("csv", 1, "lf", False)  # type: ignore[arg-type]
    with pytest.raises(ExportProfileValidationError, match="boolean"):
        ExportRepresentation("csv", True, "lf", 0)  # type: ignore[arg-type]


def test_profile_round_trips_canonically_and_reference_binds_exact_bytes() -> None:
    value = profile(columns=roster_columns(), rationale="District import layout.")

    encoded = export_profile_revision_to_json_bytes(value)
    assert encoded.endswith(b"\n")
    assert export_profile_revision_from_json_bytes(encoded) == value

    reference = export_profile_reference(value)
    assert reference.profile_sha256 == hashlib.sha256(encoded).hexdigest()
    assert export_profile_reference_from_dict(
        export_profile_reference_to_dict(reference)
    ) == reference


def test_profile_serialization_uses_exact_schema_at_each_level() -> None:
    data = export_profile_revision_to_dict(profile())
    data["expression_language"] = "python"
    with pytest.raises(ExportProfileValidationError, match="exact schema"):
        export_profile_revision_from_dict(data)

    data = export_profile_revision_to_dict(profile())
    del data["purpose"]
    with pytest.raises(ExportProfileValidationError, match="exact schema"):
        export_profile_revision_from_dict(data)

    data = export_profile_revision_to_dict(profile())
    columns = data["columns"]
    assert isinstance(columns, list)
    first = columns[0]
    assert isinstance(first, dict)
    first["formula"] = "grade * 100"
    with pytest.raises(ExportProfileValidationError, match="exact schema"):
        export_profile_revision_from_dict(data)

    data = export_profile_revision_to_dict(profile())
    representation = data["representation"]
    assert isinstance(representation, dict)
    representation["delimiter"] = ";"
    with pytest.raises(ExportProfileValidationError, match="exact schema"):
        export_profile_revision_from_dict(data)


def test_profile_json_rejects_noncanonical_duplicate_and_nonfinite_encodings() -> None:
    data = export_profile_revision_to_dict(profile())
    alternate = json.dumps(data, sort_keys=True).encode("utf-8")
    with pytest.raises(ExportProfileSerializationError, match="not the canonical"):
        export_profile_revision_from_json_bytes(alternate)

    canonical = export_profile_revision_to_json_bytes(profile()).decode("utf-8")
    duplicate = canonical.replace(
        '  "class_id": "synthetic_class_2026",',
        '  "class_id": "synthetic_class_2026",\n'
        '  "class_id": "synthetic_class_2026",',
        1,
    ).encode("utf-8")
    with pytest.raises(ExportProfileSerializationError, match="duplicate JSON"):
        export_profile_revision_from_json_bytes(duplicate)

    with pytest.raises(ExportProfileSerializationError, match="nonfinite"):
        export_profile_revision_from_json_bytes(b'{"value":NaN}')
    with pytest.raises(ExportProfileSerializationError, match="UTF-8"):
        export_profile_revision_from_json_bytes(b"\xff")


def test_revision_transition_is_linear_identity_stable_and_time_ordered() -> None:
    first = profile()
    second = profile(
        revision=2,
        title="District Gradebook Import v2",
        rationale="Add roster-backed identity columns.",
        columns=roster_columns(),
    )
    assert validate_export_profile_transition(first, second) == second

    with pytest.raises(ExportProfileValidationError, match="profile_id must match"):
        validate_export_profile_transition(
            first,
            replace(second, profile_id="another_profile"),
        )
    with pytest.raises(ExportProfileValidationError, match="increment by one"):
        validate_export_profile_transition(
            first,
            replace(second, profile_revision=3, supersedes_revision=2),
        )
    with pytest.raises(ExportProfileValidationError, match="must not be earlier"):
        validate_export_profile_transition(
            first,
            replace(second, revised_at=first.revised_at - timedelta(seconds=1)),
        )


def test_revision_fields_must_form_contiguous_history() -> None:
    with pytest.raises(ExportProfileValidationError, match="revision 1"):
        replace(profile(), supersedes_revision=1)

    with pytest.raises(ExportProfileValidationError, match="profile_revision - 1"):
        replace(profile(revision=2), supersedes_revision=None)


def test_text_fields_actor_and_timestamp_follow_meridian_conventions() -> None:
    with pytest.raises(ExportProfileValidationError, match="actor kind"):
        ExportProfileActor("system", "automatic")  # type: ignore[arg-type]
    with pytest.raises(ExportProfileValidationError, match="maximum length"):
        ExportProfileActor(
            "teacher",
            "x" * (MAXIMUM_EXPORT_PROFILE_ACTOR_ID_LENGTH + 1),
        )
    with pytest.raises(ExportProfileValidationError, match="maximum length"):
        replace(profile(), title="x" * (MAXIMUM_EXPORT_PROFILE_TITLE_LENGTH + 1))
    with pytest.raises(ExportProfileValidationError, match="maximum length"):
        replace(
            profile(),
            purpose="x" * (MAXIMUM_EXPORT_PROFILE_PURPOSE_LENGTH + 1),
        )
    with pytest.raises(ExportProfileValidationError, match="maximum length"):
        replace(
            profile(),
            rationale="x" * (MAXIMUM_EXPORT_PROFILE_RATIONALE_LENGTH + 1),
        )

    eastern = timezone(timedelta(hours=-4))
    value = profile(revised_at=datetime(2026, 9, 21, 16, 45, tzinfo=eastern))
    assert value.revised_at == NOW
    assert value.revised_at.tzinfo == UTC

    with pytest.raises(ExportProfileValidationError, match="timezone-aware"):
        profile(revised_at=datetime(2026, 9, 21, 20, 45))


def test_validation_returns_fresh_equal_value() -> None:
    value = profile(columns=roster_columns())
    validated = validate_export_profile_revision(value)

    assert validated == value
    assert validated is not value


def test_reference_requires_exact_digest_and_path_safe_identity() -> None:
    reference = ExportProfileReference(
        CLASS_ID,
        "district_gradebook_csv",
        1,
        SHA_A,
    )
    assert reference.profile_sha256 == SHA_A

    with pytest.raises(ExportProfileValidationError):
        replace(reference, profile_sha256="A" * 64)
    with pytest.raises(ExportProfileValidationError):
        replace(reference, profile_id="../escape")


def test_profile_contract_contains_representation_not_grade_calculation_semantics(
) -> None:
    encoded = export_profile_revision_to_json_bytes(profile()).decode("utf-8")

    assert "calculation_formula" not in encoded
    assert "rounding_policy" not in encoded
    assert "weights" not in encoded
    assert "override_selection" not in encoded
    assert "expression" not in encoded
