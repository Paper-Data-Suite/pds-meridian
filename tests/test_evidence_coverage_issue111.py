from __future__ import annotations

from datetime import UTC, datetime

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.routing_models import ModuleWorkRef

from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodGradeItemExplanation,
)
from meridian.evidence_coverage import (
    EvidenceCoverageMissingTarget,
    compose_evidence_coverage,
    evidence_source_attention_flags,
    grade_item_attention_flags,
)
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.grade_item_proficiency_explanation import (
    EvidenceSourceExplanation,
    GradeItemIdentityExplanation,
    ProvenanceStageExplanation,
    TraceField,
)
from meridian.report_export_roster import (
    EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
    EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
    ExportRosterObservation,
    ExportRosterObservedValue,
    ExportRosterStudentObservation,
)

CLASS_ID = "english_11"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
STANDARD = "urn:njsls:ela:RL.CR.11-12.1"
NOW = datetime(2026, 10, 13, 2, 30, tzinfo=UTC)


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


def test_no_current_judgment_is_attention_not_non_submission_claim() -> None:
    preview = compose_evidence_coverage(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        roster_observation=_roster(),
        explanations=(),
        missing_targets=(EvidenceCoverageMissingTarget("student_001", STANDARD),),
        generated_at=NOW,
    )

    assert preview.report_kind == "evidence_coverage"
    assert len(preview.rows) == 1
    values = preview.rows[0].values
    assert values[8] == "no_current_judgment"
    assert values[13] == "NO_CURRENT_JUDGMENT"
    knowledge = str(values[14]).lower()
    assert "does not establish submission or review status" in knowledge
    assert "never submitted" not in knowledge


def test_missing_grade_item_result_uses_bounded_attention_language() -> None:
    item = AcademicPeriodGradeItemExplanation(
        grade_item=GradeItemIdentityExplanation(
            class_id=CLASS_ID,
            grade_item_id="essay_1",
            grade_item_revision=1,
            grade_item_revision_sha256="a" * 64,
            title="Comparative Essay",
            purpose="standards_proficiency",
            status="active",
        ),
        memberships=(),
        period_scope_status="eligible",
        period_scope_mismatch_reason=None,
        status="missing_result",
        contributed=False,
        result_reference=None,
        result_algorithm_version=None,
        result_calculation_fingerprint=None,
        result_status=None,
        proficiency_level_id=None,
        result_insufficiency_reasons=(),
        nested_grade_item_explanation=None,
    )

    assert grade_item_attention_flags(item) == ("NO_REPRESENTED_GRADE_ITEM_RESULT",)


def test_existing_contract_states_surface_returned_and_pending_attention() -> None:
    source = EvidenceSourceExplanation(
        source_key="e" * 64,
        source=EvidenceSourceReference(
            work=ModuleWorkRef("quillan", CLASS_ID, "essay_1"),
            publication_id="pub_" + ("a" * 32),
            cache_key="b" * 64,
            snapshot_digest="c" * 64,
            item_id="review_state_1",
        ),
        result_kind="review_state",
        target_kind="student",
        aggregation_status="native_state",
        exclusion_reason=None,
        mapping_status="native_state",
        proficiency_level_id=None,
        native_state_code="returned_without_full_review",
        stages=(
            ProvenanceStageExplanation(
                name="eligibility",
                status="verified",
                revision=1,
                sha256="d" * 64,
                details=(TraceField("disposition", "pending"),),
            ),
        ),
    )

    assert evidence_source_attention_flags(source) == (
        "RETURNED_BEFORE_FULL_REVIEW",
        "PENDING_EVIDENCE",
    )
