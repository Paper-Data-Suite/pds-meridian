from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.assessment_impact as impact
from meridian.grade_item_storage import (
    StoredGradeItemRevision,
    grade_item_revision_relative_path,
)
from meridian.grade_items import (
    GRADE_ITEM_RECORD_TYPE,
    GRADE_ITEM_SCHEMA_VERSION,
    GradeItemRevision,
    grade_item_revision_to_json_bytes,
)
from meridian.grade_preview_comparison import (
    PriorReportingSnapshotGradeBasis,
    compare_grade_preview_basis,
)
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.grade_report_preview import GradeReportPreview, GradeReportPreviewRow
from meridian.report_export_roster import (
    EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
    EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
    ExportRosterObservation,
    ExportRosterObservedValue,
    ExportRosterStudentObservation,
)
from tests import test_grade_preview_comparison as comparison_support

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 10, 13, 4, 15, tzinfo=UTC)


def _stored_grade_item() -> StoredGradeItemRevision:
    revision = GradeItemRevision(
        schema_version=GRADE_ITEM_SCHEMA_VERSION,
        record_type=GRADE_ITEM_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id="essay_1",
        grade_item_revision=1,
        supersedes_revision=None,
        title="Comparative Essay",
        purpose="standards_and_conventional",
        status="active",
        weighting=None,
        created_at=NOW,
        revised_at=NOW,
    )
    content = grade_item_revision_to_json_bytes(revision)
    return StoredGradeItemRevision(
        revision=revision,
        revision_sha256=hashlib.sha256(content).hexdigest(),
        path=Path("1.json"),
        relative_path=grade_item_revision_relative_path(
            CLASS_ID,
            "essay_1",
            1,
        ),
        content=content,
    )


def _roster() -> ExportRosterObservation:
    return ExportRosterObservation(
        schema_version=EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
        record_type=EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        source_fields=("roster.display_name",),
        students=(
            ExportRosterStudentObservation(
                "student_001",
                (
                    ExportRosterObservedValue(
                        "roster.display_name",
                        "Avery Chen",
                    ),
                ),
            ),
        ),
    )


def _report() -> GradeReportPreview:
    target = GradePreviewTarget(
        class_id=CLASS_ID,
        student_id="student_001",
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="hybrid",
    )
    return GradeReportPreview(
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


def _histories() -> impact._HistoryCapture:
    event = impact.ProficiencyBasisEvent(
        student_id="student_001",
        standard_id="urn:njsls:ela:RL.CR.11-12.1",
        result_revision=2,
        result_sha256="d" * 64,
        selected_current=True,
        contributing=True,
        previous_proficiency="Approaching",
        current_proficiency="Meeting",
    )
    return impact._HistoryCapture(
        by_student=(("student_001", (event,)),),
        standards_by_student=(("student_001", ("urn:njsls:ela:RL.CR.11-12.1",)),),
        current_participation=(
            (
                "student_001",
                ("urn:njsls:ela:RL.CR.11-12.1:r2:calculated:meeting:contributing",),
            ),
        ),
        witness_sha256="e" * 64,
        source_references=(),
    )


def test_assessment_report_preserves_standards_history_and_noncausal_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        impact,
        "_grade_participation",
        lambda *args, **kwargs: (
            (
                "hybrid/conventional component_weight=0.4: "
                "action=contribute; contribution=8",
            ),
            ("urn:njsls:ela:RL.CR.11-12.1",),
            ("urn:njsls:ela:RL.CR.11-12.1:eligibility=included",),
        ),
    )

    preview = impact.compose_assessment_impact(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        grade_item=_stored_grade_item(),
        roster_observation=_roster(),
        live_grade_report=_report(),
        live_grade_report_sha256="a" * 64,
        histories=_histories(),
        generated_at=NOW,
    )

    row = preview.rows[0].values
    assert row[3] == "yes"
    assert "RL.CR.11-12.1" in str(row[4])
    assert "hybrid/conventional" in str(row[6])
    assert "eligibility=included" in str(row[7])
    assert "r2 entered basis" in str(row[8])
    assert "concurrent inputs may also have changed" in str(row[10])
    assert "does not claim" in " ".join(preview.summary).lower()


def test_checkpoint_association_never_claims_causation() -> None:
    prior = comparison_support._observation()
    current = comparison_support._change_entry(
        prior,
        "evidence",
        "f" * 64,
    )
    comparison = compare_grade_preview_basis(
        current,
        PriorReportingSnapshotGradeBasis(prior),
    )

    text = impact._checkpoint_association(comparison, represented=True)

    assert text is not None
    assert "concurrent inputs may also have changed" in text
    assert "caused" not in text.lower()


def test_unrepresented_student_remains_explicitly_nonparticipating() -> None:
    preview = impact.compose_assessment_impact(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        grade_item=_stored_grade_item(),
        roster_observation=_roster(),
        live_grade_report=_report(),
        live_grade_report_sha256="b" * 64,
        histories=impact._HistoryCapture(
            by_student=(("student_001", ()),),
            standards_by_student=(("student_001", ()),),
            current_participation=(("student_001", ()),),
            witness_sha256="c" * 64,
            source_references=(),
        ),
        generated_at=NOW,
    )

    assert preview.rows[0].values[3] == "no"
    assert preview.rows[0].values[10] is None
