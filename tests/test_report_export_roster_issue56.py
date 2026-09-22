from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.classes import write_class_roster
from pds_core.rosters import create_roster

from meridian.export_profile import (
    EXPORT_PROFILE_RECORD_TYPE,
    EXPORT_PROFILE_SCHEMA_VERSION,
    EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
    ExportColumn,
    ExportProfileActor,
    ExportProfileRevision,
    ExportProfileValidationError,
    ExportRepresentation,
)
from meridian.report_export_roster import (
    EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
    EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
    ExportRosterObservation,
    ExportRosterObservationReference,
    ExportRosterObservedValue,
    ExportRosterStudentObservation,
    ReportExportRosterFieldMissingError,
    ReportExportRosterIntegrityError,
    ReportExportRosterSubjectMissingError,
    ReportExportRosterUnavailableError,
    ReportExportRosterValidationError,
    build_export_roster_observation,
    export_profile_roster_source_fields,
    export_roster_observation_from_dict,
    export_roster_observation_from_json_bytes,
    export_roster_observation_reference,
    export_roster_observation_reference_from_dict,
    export_roster_observation_reference_to_dict,
    export_roster_observation_sha256,
    export_roster_observation_to_dict,
    export_roster_observation_to_json_bytes,
)

CLASS_ID = "english_12"
NOW = datetime(2026, 9, 21, 22, 0, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


def _write_roster(
    root: Path,
    *,
    rows: list[dict[str, str]] | None = None,
    columns: tuple[str, ...] | None = None,
) -> None:
    if rows is None:
        rows = [
            {
                "student_id": "student_002",
                "last_name": "Rivera",
                "first_name": "Jordan",
                "period": "8",
                "preferred_name": "Jordy",
                "district_id": "D-002",
                "email": "jordan@example.test",
            },
            {
                "student_id": "student_001",
                "last_name": "Chen",
                "first_name": "Avery",
                "period": "8",
                "preferred_name": "",
                "district_id": "D-001",
                "email": "avery@example.test",
            },
            {
                "student_id": "student_999",
                "last_name": "Outside",
                "first_name": "Unselected",
                "period": "8",
                "preferred_name": "",
                "district_id": "D-999",
                "email": "outside@example.test",
            },
        ]
    roster = create_roster(CLASS_ID, rows, columns=columns)
    roster_path = root / "classes" / CLASS_ID / "roster.csv"
    write_class_roster(root, roster, overwrite=roster_path.exists())


def _profile(*source_fields: str) -> ExportProfileRevision:
    fields = source_fields or ("target.student_id",)
    return ExportProfileRevision(
        schema_version=EXPORT_PROFILE_SCHEMA_VERSION,
        record_type=EXPORT_PROFILE_RECORD_TYPE,
        source_registry_version=EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
        class_id=CLASS_ID,
        profile_id="district_grade_export",
        profile_revision=1,
        supersedes_revision=None,
        title="District Grade Export",
        purpose="district_gradebook_import",
        columns=tuple(
            ExportColumn(source_field=field, output_name=f"Column {index}")
            for index, field in enumerate(fields, start=1)
        ),
        representation=ExportRepresentation("csv", True, "crlf", False),
        actor=ExportProfileActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def _value_map(observation: ExportRosterObservation, student_id: str) -> dict[str, str]:
    student = next(
        item for item in observation.students if item.student_id == student_id
    )
    return {item.source_field: item.value for item in student.values}


def test_error_codes_preserve_roster_failure_distinctions() -> None:
    assert ReportExportRosterUnavailableError.code == "report_export.roster_unavailable"
    assert (
        ReportExportRosterSubjectMissingError.code
        == "report_export.roster_subject_missing"
    )
    assert (
        ReportExportRosterFieldMissingError.code
        == "report_export.roster_field_missing"
    )
    assert (
        ReportExportRosterIntegrityError.code
        == "report_export.roster_integrity_failed"
    )


def test_snapshot_only_profile_returns_none_without_loading_roster(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    result = build_export_roster_observation(
        root,
        _profile("target.student_id", "grade.effective_grade"),
        ("not_even_validated_for_snapshot_only",),
    )
    assert result is None
    assert not (root / "classes").exists()


def test_profile_roster_source_fields_are_distinct_and_canonically_sorted() -> None:
    profile = _profile(
        "roster.period",
        "target.student_id",
        "roster.first_name",
        "roster.period",
        "roster.extra:district_id",
    )
    assert export_profile_roster_source_fields(profile) == (
        "roster.extra:district_id",
        "roster.first_name",
        "roster.period",
    )


def test_observation_is_frozen_slotted_and_privacy_bounded(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    observation = build_export_roster_observation(
        root,
        _profile("roster.first_name", "roster.extra:district_id"),
        ("student_002", "student_001", "student_002"),
    )
    assert observation is not None
    assert observation.schema_version == EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION
    assert observation.record_type == EXPORT_ROSTER_OBSERVATION_RECORD_TYPE
    assert tuple(student.student_id for student in observation.students) == (
        "student_001",
        "student_002",
    )
    encoded = export_roster_observation_to_json_bytes(observation)
    assert b"student_999" not in encoded
    assert b"email" not in encoded
    assert b"roster.csv" not in encoded
    assert b"source_path" not in encoded
    with pytest.raises(FrozenInstanceError):
        observation.class_id = "changed"  # type: ignore[misc]
    assert not hasattr(observation, "__dict__")


def test_required_roster_fields_resolve_exact_values(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    observation = build_export_roster_observation(
        root,
        _profile(
            "roster.first_name",
            "roster.last_name",
            "roster.period",
        ),
        ("student_001",),
    )
    assert observation is not None
    assert _value_map(observation, "student_001") == {
        "roster.first_name": "Avery",
        "roster.last_name": "Chen",
        "roster.period": "8",
    }


def test_display_name_uses_public_core_preferred_name_semantics(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    observation = build_export_roster_observation(
        root,
        _profile("roster.display_name"),
        ("student_001", "student_002"),
    )
    assert observation is not None
    assert _value_map(observation, "student_001")["roster.display_name"] == "Avery Chen"
    assert (
        _value_map(observation, "student_002")["roster.display_name"]
        == "Jordy Rivera"
    )


def test_exact_optional_roster_field_can_be_blank(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    observation = build_export_roster_observation(
        root,
        _profile("roster.extra:preferred_name"),
        ("student_001",),
    )
    assert observation is not None
    assert _value_map(observation, "student_001") == {
        "roster.extra:preferred_name": ""
    }


def test_missing_optional_roster_column_fails_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write_roster(
        root,
        rows=[
            {
                "student_id": "student_001",
                "last_name": "Chen",
                "first_name": "Avery",
                "period": "8",
            }
        ],
    )
    with pytest.raises(ReportExportRosterFieldMissingError, match="district_id"):
        build_export_roster_observation(
            root,
            _profile("roster.extra:district_id"),
            ("student_001",),
        )


def test_missing_snapshot_student_fails_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    with pytest.raises(ReportExportRosterSubjectMissingError, match="student_missing"):
        build_export_roster_observation(
            root,
            _profile("roster.first_name"),
            ("student_missing",),
        )


def test_missing_roster_fails_as_unavailable(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    with pytest.raises(ReportExportRosterUnavailableError):
        build_export_roster_observation(
            root,
            _profile("roster.first_name"),
            ("student_001",),
        )


def test_invalid_roster_fails_as_unavailable(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    path = root / "classes" / CLASS_ID / "roster.csv"
    path.parent.mkdir(parents=True)
    path.write_text("not,a,valid,roster\n", encoding="utf-8")
    with pytest.raises(ReportExportRosterUnavailableError):
        build_export_roster_observation(
            root,
            _profile("roster.first_name"),
            ("student_001",),
        )


def test_roster_row_order_is_not_material_to_observation_digest(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    profile = _profile("roster.first_name", "roster.extra:district_id")
    first = build_export_roster_observation(
        root, profile, ("student_001", "student_002")
    )
    assert first is not None
    rows = [
        {
            "student_id": "student_001",
            "last_name": "Chen",
            "first_name": "Avery",
            "period": "8",
            "preferred_name": "",
            "district_id": "D-001",
            "email": "avery@example.test",
        },
        {
            "student_id": "student_999",
            "last_name": "Outside",
            "first_name": "Unselected",
            "period": "8",
            "preferred_name": "",
            "district_id": "D-999",
            "email": "outside@example.test",
        },
        {
            "student_id": "student_002",
            "last_name": "Rivera",
            "first_name": "Jordan",
            "period": "8",
            "preferred_name": "Jordy",
            "district_id": "D-002",
            "email": "jordan@example.test",
        },
    ]
    _write_roster(root, rows=rows)
    second = build_export_roster_observation(
        root, profile, ("student_002", "student_001")
    )
    assert second == first
    assert export_roster_observation_sha256(second) == (
        export_roster_observation_sha256(first)
    )


def test_profile_output_column_order_is_not_material_to_roster_observation(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    first = build_export_roster_observation(
        root,
        _profile("roster.last_name", "roster.first_name"),
        ("student_001",),
    )
    second = build_export_roster_observation(
        root,
        _profile("roster.first_name", "roster.last_name"),
        ("student_001",),
    )
    assert first == second


def test_unselected_roster_field_change_does_not_change_observation(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    profile = _profile("roster.first_name")
    first = build_export_roster_observation(root, profile, ("student_001",))
    assert first is not None
    rows = [
        {
            "student_id": "student_001",
            "last_name": "CHANGED BUT UNSELECTED",
            "first_name": "Avery",
            "period": "99",
            "preferred_name": "Other",
            "district_id": "CHANGED",
            "email": "changed@example.test",
        }
    ]
    _write_roster(root, rows=rows)
    second = build_export_roster_observation(root, profile, ("student_001",))
    assert second == first


def test_selected_roster_field_change_changes_observation_digest(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    profile = _profile("roster.first_name")
    first = build_export_roster_observation(root, profile, ("student_001",))
    assert first is not None
    rows = [
        {
            "student_id": "student_001",
            "last_name": "Chen",
            "first_name": "Avery Changed",
            "period": "8",
        }
    ]
    _write_roster(root, rows=rows)
    second = build_export_roster_observation(root, profile, ("student_001",))
    assert second is not None
    assert export_roster_observation_sha256(second) != (
        export_roster_observation_sha256(first)
    )


def test_unselected_student_change_does_not_change_observation(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    profile = _profile("roster.first_name", "roster.last_name")
    first = build_export_roster_observation(root, profile, ("student_001",))
    assert first is not None
    rows = [
        {
            "student_id": "student_001",
            "last_name": "Chen",
            "first_name": "Avery",
            "period": "8",
        },
        {
            "student_id": "student_999",
            "last_name": "Radically Changed",
            "first_name": "Someone Else",
            "period": "42",
        },
    ]
    _write_roster(root, rows=rows)
    second = build_export_roster_observation(root, profile, ("student_001",))
    assert second == first


def test_display_name_digest_changes_when_preferred_name_changes(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    profile = _profile("roster.display_name")
    first = build_export_roster_observation(root, profile, ("student_002",))
    assert first is not None
    rows = [
        {
            "student_id": "student_002",
            "last_name": "Rivera",
            "first_name": "Jordan",
            "period": "8",
            "preferred_name": "Jo",
        }
    ]
    _write_roster(root, rows=rows)
    second = build_export_roster_observation(root, profile, ("student_002",))
    assert second is not None
    assert _value_map(second, "student_002")["roster.display_name"] == "Jo Rivera"
    assert export_roster_observation_sha256(second) != (
        export_roster_observation_sha256(first)
    )


def test_empty_snapshot_student_set_produces_empty_bounded_observation(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    observation = build_export_roster_observation(
        root,
        _profile("roster.first_name"),
        (),
    )
    assert observation is not None
    assert observation.students == ()


def test_observation_round_trips_canonically_and_reference_binds_exact_bytes(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    observation = build_export_roster_observation(
        root,
        _profile("roster.display_name", "roster.extra:district_id"),
        ("student_002", "student_001"),
    )
    assert observation is not None
    encoded = export_roster_observation_to_json_bytes(observation)
    assert encoded.endswith(b"\n")
    assert export_roster_observation_from_json_bytes(encoded) == observation
    assert export_roster_observation_sha256(observation) == (
        hashlib.sha256(encoded).hexdigest()
    )
    reference = export_roster_observation_reference(observation)
    assert reference == ExportRosterObservationReference(
        CLASS_ID,
        hashlib.sha256(encoded).hexdigest(),
    )
    assert export_roster_observation_reference_from_dict(
        export_roster_observation_reference_to_dict(reference)
    ) == reference


def test_observation_mapping_rejects_unknown_fields(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    observation = build_export_roster_observation(
        root,
        _profile("roster.first_name"),
        ("student_001",),
    )
    assert observation is not None
    data = export_roster_observation_to_dict(observation)
    data["roster_path"] = "private/path.csv"
    with pytest.raises(ReportExportRosterValidationError, match="exact schema"):
        export_roster_observation_from_dict(data)


def test_observation_json_rejects_noncanonical_and_duplicate_keys(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    observation = build_export_roster_observation(
        root,
        _profile("roster.first_name"),
        ("student_001",),
    )
    assert observation is not None
    mapping = export_roster_observation_to_dict(observation)
    alternate = json.dumps(mapping, sort_keys=True).encode("utf-8")
    with pytest.raises(ReportExportRosterIntegrityError, match="canonical"):
        export_roster_observation_from_json_bytes(alternate)

    canonical = export_roster_observation_to_json_bytes(observation).decode("utf-8")
    duplicate = canonical.replace(
        '  "class_id": "english_12",',
        '  "class_id": "english_12",\n  "class_id": "english_12",',
        1,
    ).encode("utf-8")
    with pytest.raises(ReportExportRosterIntegrityError, match="duplicate"):
        export_roster_observation_from_json_bytes(duplicate)


def test_model_rejects_snapshot_fields_unsorted_fields_and_duplicate_students() -> None:
    with pytest.raises(ReportExportRosterValidationError, match="roster-backed"):
        ExportRosterObservedValue("target.student_id", "student_001")

    with pytest.raises(ReportExportRosterValidationError, match="canonically sorted"):
        ExportRosterObservation(
            EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
            EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
            CLASS_ID,
            ("roster.last_name", "roster.first_name"),
            (),
        )

    values = (ExportRosterObservedValue("roster.first_name", "Avery"),)
    student = ExportRosterStudentObservation("student_001", values)
    with pytest.raises(ReportExportRosterValidationError, match="duplicates"):
        ExportRosterObservation(
            EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
            EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
            CLASS_ID,
            ("roster.first_name",),
            (student, student),
        )


def test_student_observation_must_cover_exact_observation_fields() -> None:
    student = ExportRosterStudentObservation(
        "student_001",
        (ExportRosterObservedValue("roster.first_name", "Avery"),),
    )
    with pytest.raises(ReportExportRosterValidationError, match="cover exactly"):
        ExportRosterObservation(
            EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
            EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
            CLASS_ID,
            ("roster.first_name", "roster.last_name"),
            (student,),
        )


def test_student_ids_must_be_explicit_tuple_for_roster_backed_profile(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _write_roster(root)
    with pytest.raises(ReportExportRosterValidationError, match="student_ids"):
        build_export_roster_observation(
            root,
            _profile("roster.first_name"),
            ["student_001"],  # type: ignore[arg-type]
        )


def test_reference_rejects_noncanonical_digest() -> None:
    with pytest.raises(ReportExportRosterValidationError, match="SHA-256"):
        ExportRosterObservationReference(CLASS_ID, "A" * 64)


def test_required_core_field_must_not_be_requested_through_extra_registry() -> None:
    with pytest.raises(ExportProfileValidationError):
        _profile("roster.extra:first_name")
