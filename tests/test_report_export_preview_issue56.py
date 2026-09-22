from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.export_profile import (
    EXPORT_PROFILE_RECORD_TYPE,
    EXPORT_PROFILE_SCHEMA_VERSION,
    EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
    ExportColumn,
    ExportProfileActor,
    ExportProfileRevision,
    ExportRepresentation,
    export_profile_reference,
)
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.grade_report_preview import (
    GradeReportPreview,
    GradeReportPreviewRow,
    grade_report_preview_to_json_bytes,
)
from meridian.report_export_preview import (
    REPORT_EXPORTER_VERSION,
    BuiltExportPreview,
    ExportPreview,
    ReportExportPreviewIntegrityError,
    ReportExportPreviewValidationError,
    compose_export_preview,
    export_preview_from_json_bytes,
    export_preview_sha256,
    export_preview_to_json_bytes,
)
from meridian.report_export_roster import (
    EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
    EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
    ExportRosterObservation,
    ExportRosterObservedValue,
    ExportRosterStudentObservation,
    export_roster_observation_sha256,
)
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_preview import (
    frozen_grade_report_preview_from_json_bytes,
)
from tests.test_reporting_snapshot_preview_issue55 import _available_preview_bytes

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
SNAPSHOT_SHA = "9" * 64


def _profile(
    columns: tuple[ExportColumn, ...],
    *,
    format: str = "csv",
    include_header: bool = True,
    line_ending: str = "lf",
    utf8_bom: bool = False,
) -> ExportProfileRevision:
    return ExportProfileRevision(
        schema_version=EXPORT_PROFILE_SCHEMA_VERSION,
        record_type=EXPORT_PROFILE_RECORD_TYPE,
        source_registry_version=EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
        class_id=CLASS_ID,
        profile_id="grade_export",
        profile_revision=1,
        supersedes_revision=None,
        title="Grade export",
        purpose="Issue 56 deterministic export preview",
        columns=columns,
        representation=ExportRepresentation(
            format=format,  # type: ignore[arg-type]
            include_header=include_header,
            line_ending=line_ending,  # type: ignore[arg-type]
            utf8_bom=utf8_bom,
        ),
        actor=ExportProfileActor("teacher", "teacher_local"),
        rationale="Issue 56 qualification.",
        revised_at=NOW,
    )


def _snapshot_reference() -> ReportingSnapshotReference:
    return ReportingSnapshotReference(
        class_id=CLASS_ID,
        snapshot_id="snapshot_001",
        snapshot_sha256=SNAPSHOT_SHA,
    )


def _unavailable_preview(
    *,
    family: str = "standards_based",
    student_id: str = "student_001",
):
    target = GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=student_id,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family=family,  # type: ignore[arg-type]
    )
    preview = GradeReportPreview(
        (
            GradeReportPreviewRow(
                target=target,
                status="unavailable",
                explanation=None,
                observation=None,
                unavailable_reason="no_selected_grade",
            ),
        )
    )
    return frozen_grade_report_preview_from_json_bytes(
        grade_report_preview_to_json_bytes(preview)
    )


def _two_family_unavailable_preview():
    rows = tuple(
        GradeReportPreviewRow(
            target=GradePreviewTarget(
                class_id=CLASS_ID,
                student_id="student_001",
                target_period=PERIOD,
                calendar_revision=1,
                calculation_family=family,  # type: ignore[arg-type]
            ),
            status="unavailable",
            explanation=None,
            observation=None,
            unavailable_reason="no_selected_grade",
        )
        for family in ("conventional", "standards_based")
    )
    return frozen_grade_report_preview_from_json_bytes(
        grade_report_preview_to_json_bytes(GradeReportPreview(rows))
    )


def _roster_observation(
    source_fields: tuple[str, ...],
    values: tuple[str, ...],
) -> ExportRosterObservation:
    return ExportRosterObservation(
        schema_version=EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
        record_type=EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        source_fields=source_fields,
        students=(
            ExportRosterStudentObservation(
                student_id="student_001",
                values=tuple(
                    ExportRosterObservedValue(source_field, value)
                    for source_field, value in zip(
                        source_fields,
                        values,
                        strict=True,
                    )
                ),
            ),
        ),
    )


def _compose(
    profile: ExportProfileRevision,
    preview,
    roster: ExportRosterObservation | None = None,
) -> BuiltExportPreview:
    return compose_export_preview(
        snapshot_reference=_snapshot_reference(),
        report_preview=preview,
        profile_reference=export_profile_reference(profile),
        profile=profile,
        roster_observation=roster,
    )


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")


def test_snapshot_only_unavailable_row_renders_explicit_state_and_blank_grade() -> None:
    profile = _profile(
        (
            ExportColumn("target.student_id", "student_id"),
            ExportColumn("row.status", "status"),
            ExportColumn("row.unavailable_reason", "reason"),
            ExportColumn("grade.effective_grade", "effective_grade"),
        )
    )

    built = _compose(profile, _unavailable_preview())

    assert built.payload == (
        b"student_id,status,reason,effective_grade\n"
        b"student_001,unavailable,no_selected_grade,\n"
    )
    assert built.preview.row_count == 1
    assert built.preview.logical_rows[0].values[-1] is None
    assert built.preview.roster_observation_reference is None
    assert [(item.code, item.count) for item in built.preview.diagnostics] == [
        ("unavailable_rows", 1)
    ]


def test_available_grade_fields_are_projected_only_from_frozen_observation() -> None:
    encoded, observation = _available_preview_bytes("conventional")
    preview = frozen_grade_report_preview_from_json_bytes(encoded)
    profile = _profile(
        (
            ExportColumn("grade.base_result_status", "base_status"),
            ExportColumn("grade.base_grade", "base_grade"),
            ExportColumn("grade.base_freshness_status", "freshness"),
            ExportColumn("grade.effective_grade", "effective_grade"),
            ExportColumn("grade.effective_source", "effective_source"),
            ExportColumn("policy.policy_id", "policy_id"),
            ExportColumn("policy.policy_revision", "policy_revision"),
        )
    )

    built = _compose(profile, preview)

    assert observation.base_grade is not None
    assert observation.effective_grade is not None
    assert built.preview.logical_rows[0].values == (
        observation.base_result_status,
        format(observation.base_grade, "f"),
        observation.base_freshness_status,
        format(observation.effective_grade, "f"),
        observation.effective_source,
        observation.policy_reference.policy_id,
        str(observation.policy_reference.policy_revision),
    )
    assert b"rounding" not in built.payload
    assert b"formula" not in built.payload


def test_snapshot_identity_and_target_fields_use_exact_frozen_reference_scope() -> None:
    profile = _profile(
        (
            ExportColumn("snapshot.class_id", "class_id"),
            ExportColumn("snapshot.snapshot_id", "snapshot_id"),
            ExportColumn("snapshot.snapshot_sha256", "snapshot_sha256"),
            ExportColumn("target.school_year", "school_year"),
            ExportColumn("target.period_id", "period_id"),
            ExportColumn("target.calendar_revision", "calendar_revision"),
            ExportColumn("target.calculation_family", "family"),
        )
    )

    built = _compose(profile, _unavailable_preview())

    assert built.preview.logical_rows[0].values == (
        CLASS_ID,
        "snapshot_001",
        SNAPSHOT_SHA,
        "2026-2027",
        "q1",
        "1",
        "standards_based",
    )


def test_roster_backed_tsv_binds_exact_observation_and_respects_settings() -> None:
    source_fields = ("roster.display_name", "roster.extra:email")
    profile = _profile(
        (
            ExportColumn("roster.display_name", "name"),
            ExportColumn("roster.extra:email", "email"),
            ExportColumn("target.student_id", "student_id"),
        ),
        format="tsv",
        include_header=False,
        line_ending="crlf",
        utf8_bom=True,
    )
    roster = _roster_observation(
        source_fields,
        ("Jane Doe", "jane@example.test"),
    )

    built = _compose(profile, _unavailable_preview(), roster)

    assert built.payload == (
        b"\xef\xbb\xbfJane Doe\tjane@example.test\tstudent_001\r\n"
    )
    assert built.preview.roster_observation_reference is not None
    assert built.preview.roster_observation_reference.observation_sha256 == (
        export_roster_observation_sha256(roster)
    )


def test_csv_writer_quotes_selected_roster_text_without_transforming_it() -> None:
    source_fields = ("roster.extra:note",)
    profile = _profile((ExportColumn("roster.extra:note", "note"),))
    roster = _roster_observation(source_fields, ('He said "yes", then left',))

    built = _compose(profile, _unavailable_preview(), roster)

    assert built.payload == b'note\n"He said ""yes"", then left"\n'
    assert built.preview.logical_rows[0].values == ('He said "yes", then left',)


def test_one_bounded_roster_student_can_support_multiple_snapshot_family_rows() -> None:
    profile = _profile(
        (
            ExportColumn("target.student_id", "student_id"),
            ExportColumn("target.calculation_family", "family"),
            ExportColumn("roster.first_name", "first_name"),
        )
    )
    roster = _roster_observation(("roster.first_name",), ("Jane",))

    built = _compose(profile, _two_family_unavailable_preview(), roster)

    assert built.preview.row_count == 2
    assert [row.calculation_family for row in built.preview.logical_rows] == [
        "conventional",
        "standards_based",
    ]
    assert [row.values[-1] for row in built.preview.logical_rows] == [
        "Jane",
        "Jane",
    ]


def test_snapshot_native_profile_rejects_unnecessary_roster_observation() -> None:
    profile = _profile((ExportColumn("target.student_id", "student_id"),))
    roster = _roster_observation(("roster.first_name",), ("Jane",))

    with pytest.raises(
        ReportExportPreviewValidationError,
        match="must not bind a roster observation",
    ):
        _compose(profile, _unavailable_preview(), roster)


def test_roster_backed_profile_requires_exact_selected_fields_and_students() -> None:
    profile = _profile((ExportColumn("roster.first_name", "first_name"),))

    with pytest.raises(
        ReportExportPreviewValidationError,
        match="requires exact bounded roster observation",
    ):
        _compose(profile, _unavailable_preview(), None)

    wrong_field = _roster_observation(("roster.last_name",), ("Doe",))
    with pytest.raises(
        ReportExportPreviewValidationError,
        match="fields must match exactly",
    ):
        _compose(profile, _unavailable_preview(), wrong_field)


def test_profile_reference_must_bind_exact_profile_revision_bytes() -> None:
    profile = _profile((ExportColumn("target.student_id", "student_id"),))
    bad_reference = type(export_profile_reference(profile))(
        class_id=CLASS_ID,
        profile_id=profile.profile_id,
        profile_revision=profile.profile_revision,
        profile_sha256="f" * 64,
    )

    with pytest.raises(
        ReportExportPreviewIntegrityError,
        match="profile reference",
    ):
        compose_export_preview(
            snapshot_reference=_snapshot_reference(),
            report_preview=_unavailable_preview(),
            profile_reference=bad_reference,
            profile=profile,
            roster_observation=None,
        )


def test_preview_round_trips_canonically_and_binds_exact_payload() -> None:
    profile = _profile(
        (
            ExportColumn("target.student_id", "student_id"),
            ExportColumn("row.status", "status"),
        )
    )
    built = _compose(profile, _unavailable_preview())

    encoded = export_preview_to_json_bytes(built.preview)
    loaded = export_preview_from_json_bytes(encoded)

    assert loaded == built.preview
    assert export_preview_to_json_bytes(loaded) == encoded
    assert export_preview_sha256(loaded) == loaded.preview_sha256
    assert loaded.payload_sha256 == hashlib.sha256(built.payload).hexdigest()
    assert loaded.payload_byte_length == len(built.payload)
    assert loaded.exporter_version == REPORT_EXPORTER_VERSION


def test_preview_body_tamper_fails_preview_digest_validation() -> None:
    profile = _profile((ExportColumn("target.student_id", "student_id"),))
    built = _compose(profile, _unavailable_preview())
    data = json.loads(export_preview_to_json_bytes(built.preview))
    data["payload_byte_length"] += 1

    with pytest.raises(
        ReportExportPreviewIntegrityError,
        match="preview_sha256",
    ):
        export_preview_from_json_bytes(_canonical_json_bytes(data))


def test_noncanonical_preview_bytes_fail_closed() -> None:
    profile = _profile((ExportColumn("target.student_id", "student_id"),))
    built = _compose(profile, _unavailable_preview())
    data = json.loads(export_preview_to_json_bytes(built.preview))
    noncanonical = json.dumps(data, sort_keys=True).encode("utf-8")

    with pytest.raises(
        ReportExportPreviewIntegrityError,
        match="not canonical",
    ):
        export_preview_from_json_bytes(noncanonical)


def test_preview_exact_schema_rejects_unknown_fields() -> None:
    profile = _profile((ExportColumn("target.student_id", "student_id"),))
    built = _compose(profile, _unavailable_preview())
    data = json.loads(export_preview_to_json_bytes(built.preview))
    data["official_grade"] = True

    with pytest.raises(
        ReportExportPreviewValidationError,
        match="exact schema",
    ):
        export_preview_from_json_bytes(_canonical_json_bytes(data))


def test_built_preview_rejects_payload_that_does_not_match_bound_bytes() -> None:
    profile = _profile((ExportColumn("target.student_id", "student_id"),))
    built = _compose(profile, _unavailable_preview())

    with pytest.raises(
        ReportExportPreviewIntegrityError,
        match="payload digest",
    ):
        BuiltExportPreview(
            preview=built.preview,
            payload=b"x" * len(built.payload),
        )


def test_preview_model_is_frozen_and_requires_valid_digest() -> None:
    profile = _profile((ExportColumn("target.student_id", "student_id"),))
    built = _compose(profile, _unavailable_preview())
    data = json.loads(export_preview_to_json_bytes(built.preview))
    data["preview_sha256"] = "f" * 64

    with pytest.raises(ReportExportPreviewIntegrityError):
        export_preview_from_json_bytes(_canonical_json_bytes(data))

    assert isinstance(built.preview, ExportPreview)
