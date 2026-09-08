"""Issue #45 installed ScoreForm/Quillan proficiency explanation acceptance.

Build released producer state and Core publications, project them through Meridian's
installed adapters without Concord, persist explicit teacher-owned Grade Item evidence
decisions, then persist and explain Grade Item and Academic Period proficiency for a
contributor and a deliberate noncontributor.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import pds_core
from pds_core.academic_catalog import PublicationCatalogQuery, rebuild_academic_catalog
from pds_core.academic_period_storage import (
    load_academic_period_calendar_revision,
    write_academic_period_calendar,
)
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.grouping_signal_csv import (
    grouping_signal_csv_to_signal_set,
    parse_grouping_signal_csv,
)
from pds_core.grouping_signal_storage import (
    list_grouping_signal_ids,
    load_grouping_signal,
)
from pds_core.grouping_signals import (
    grouping_signal_set_from_json,
    grouping_signal_set_to_json_bytes,
)
from pds_core.publication_compatibility import PublicationProducerRegistry
from pds_core.publication_records import PublicationRecord, publication_record_to_dict
from pds_core.rosters import create_roster, write_roster
from pds_core.routes import class_metadata_path, class_roster_path
from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    StandardsProfile,
    write_workspace_standards_library,
)
from quillan.academic_result_manifest_generation import (
    generate_academic_result_manifest as generate_quillan_manifest,
)
from quillan.academic_result_publication import publish_quillan_academic_results
from quillan.academic_work_registration import register_quillan_academic_work
from quillan.assignment_workflows import (
    build_assignment_config,
    write_assignment_config,
)
from quillan.pds_publication import (
    get_publication_producer_profile as quillan_profile,
)
from quillan.review_ratings import (
    mark_overall_ratings_complete,
    set_overall_standard_rating,
)
from quillan.review_record import build_empty_review_record
from quillan.review_record_paths import review_record_path, write_review_record
from quillan.submission_manifest import validate_submission_manifest
from quillan.submission_manifest_paths import (
    submission_manifest_path,
    write_submission_manifest,
)
from scoreform.academic_result_manifest_generation import (
    generate_academic_result_manifest as generate_scoreform_manifest,
)
from scoreform.academic_result_publication import (
    publish_scoreform_academic_results,
)
from scoreform.academic_work_registration import register_scoreform_academic_work
from scoreform.assignment import validate_assignment_data
from scoreform.layouts import DEFAULT_LAYOUT_ID, require_layout
from scoreform.page_scoring import ScoredAnswer
from scoreform.pds_publication import (
    get_publication_producer_profile as scoreform_profile,
)
from scoreform.results import ScoreFormRoutedResult, export_scoreform_result_models
from scoreform.work_paths import initialize_scoreform_work_layout
from scoreform.workflows import write_assignment_json

import meridian
import meridian.attempt_selection_storage as attempt_storage
import meridian.evidence_eligibility_storage as eligibility_storage
import meridian.ingestion as ingestion
import meridian.reassessment_storage as reassessment_storage
import meridian.standards_evidence_storage as standards_storage
from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyTarget,
    ResolvedAcademicPeriodProficiencyCandidate,
    academic_period_proficiency_membership_basis_from_decision,
    build_academic_period_proficiency_aggregation_inputs,
    calculate_academic_period_proficiency,
    create_academic_period_proficiency_result_snapshot,
)
from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodProficiencyTraceTarget,
    explain_academic_period_proficiency,
)
from meridian.academic_period_proficiency_storage import (
    load_current_academic_period_proficiency_result,
    select_academic_period_proficiency_policy_revision,
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_policy_revision,
    write_academic_period_proficiency_result_revision,
)
from meridian.adapters import AdapterRegistry, installed_distribution_version
from meridian.attempt_selection import (
    ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
    ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
    ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
    ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
    AttemptSelectionActor,
    AttemptSelectionDecision,
    AttemptSelectionPolicy,
    AttemptSelectionPolicyReference,
)
from meridian.evidence import (
    EvidenceInventory,
    EvidenceItem,
    NativeScalarValue,
    NativeScaledValue,
)
from meridian.evidence_eligibility import (
    EVIDENCE_ELIGIBILITY_RECORD_TYPE,
    EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
    EvidenceDecisionActor,
    EvidenceEligibilityDecision,
    EvidenceEligibilityPolicyReference,
    EvidenceSourceReference,
    EvidenceSourceStateObservation,
)
from meridian.grade_item_membership_storage import (
    select_grade_item_membership_revision,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
    GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_proficiency_explanation import (
    GradeItemProficiencyTraceTarget,
    explain_grade_item_proficiency,
)
from meridian.grade_item_storage import (
    load_current_grade_item_revision,
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import (
    GRADE_ITEM_RECORD_TYPE,
    GRADE_ITEM_SCHEMA_VERSION,
    GradeItemRevision,
    GradeItemWorkReference,
)
from meridian.grouping_signal_csv_export import export_grouping_signal_csv
from meridian.grouping_signal_derivation import GroupingSignalDerivationReference
from meridian.grouping_signal_export_receipt_workflow import export_grouping_signal
from meridian.grouping_signal_export_storage import (
    load_grouping_signal_export_receipt,
)
from meridian.grouping_signal_generation import generate_grouping_signal_derivation
from meridian.grouping_signal_policy import (
    GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
    GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
    GroupingSignalAcademicBasis,
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicy,
    GroupingSignalPolicyActor,
)
from meridian.grouping_signal_policy_storage import (
    select_grouping_signal_policy_revision,
    write_grouping_signal_policy_revision,
)
from meridian.grouping_signal_preview_generation import generate_grouping_signal_preview
from meridian.grouping_signal_preview_projection import (
    build_grouping_signal_teacher_projection,
)
from meridian.grouping_signal_review_storage import (
    select_grouping_signal_review_revision,
)
from meridian.grouping_signal_review_workflow import record_grouping_signal_review
from meridian.proficiency_mapping import (
    NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
    NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    NativeValueMappingProfile,
    ProficiencyLevel,
    ProficiencyScale,
    ScalarMappingRule,
    ScaledLevelMappingRule,
    native_value_source_signature_from_item,
)
from meridian.proficiency_mapping_storage import (
    StoredNativeValueMappingProfile,
    StoredProficiencyScale,
    write_mapping_profile_revision,
    write_proficiency_scale_revision,
)
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    ProjectionCacheWriteResult,
    cache_projected_inventory,
    load_authorized_projection_snapshot,
)
from meridian.quillan_adapter import QuillanAcademicResultAdapter
from meridian.reassessment import (
    REASSESSMENT_DECISION_RECORD_TYPE,
    REASSESSMENT_DECISION_SCHEMA_VERSION,
    REASSESSMENT_POLICY_RECORD_TYPE,
    REASSESSMENT_POLICY_SCHEMA_VERSION,
    AttemptSelectionDecisionReference,
    ReassessmentActor,
    ReassessmentDecision,
    ReassessmentPolicy,
    ReassessmentPolicyReference,
    ReplacementRelationship,
)
from meridian.scoreform_adapter import ScoreFormAcademicResultAdapter
from meridian.standards_evidence import (
    STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
    STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
    GradeItemAggregationBasis,
    StandardAggregationInputs,
    StandardEvidenceActor,
    StandardEvidenceAssociationDecision,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    StandardProficiencyActor,
    StandardProficiencyCalculationOutcome,
    StandardProficiencyCalculationPolicy,
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
)
from meridian.standards_proficiency_storage import (
    load_current_standard_proficiency_result,
    select_standard_proficiency_policy_revision,
    select_standard_proficiency_result_revision,
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "student_synthetic_001"
NONCONTRIBUTOR_ID = "student_synthetic_002"
STANDARD_ID = "standard_ela_1"
PROFILE_ID = "issue45_ela_profile"
SCOREFORM_ASSIGNMENT_ID = "issue45_scoreform"
QUILLAN_ASSIGNMENT_ID = "issue45_quillan"
GRADE_ITEM_ID = "issue45_installed_proficiency"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "period_q1"
ACTOR_ID = "teacher_local"
ELIGIBILITY_POLICY_ID = "issue45_explicit_eligibility"
ATTEMPT_POLICY_ID = "issue45_explicit_attempts"
REASSESSMENT_POLICY_ID = "issue45_explicit_reassessment"
PERIOD_POLICY_ID = "issue45_period_highest"
GROUPING_POLICY_ID = "issue45_ela_planning"
SIGNAL_SET_ID = "issue45_ela_planning_001"
NOW = datetime(2026, 9, 7, 14, tzinfo=UTC)
NOW_TEXT = NOW.isoformat()


class AcceptanceFailure(RuntimeError):
    """Bounded installed-acceptance failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _module_origin(module_name: str) -> Path:
    module = importlib.import_module(module_name)
    raw = getattr(module, "__file__", None)
    if not isinstance(raw, str) or not raw:
        raise AcceptanceFailure(f"{module_name} has no import origin.")
    return Path(raw).resolve()


def _installed_origin(module_name: str) -> None:
    origin = _module_origin(module_name)
    prefix = Path(sys.prefix).resolve()
    _require(origin.is_relative_to(prefix), f"{module_name} is outside the venv.")
    _require(
        "site-packages" in {part.lower() for part in origin.parts},
        f"{module_name} is not installed from site-packages.",
    )


def _assert_no_concord() -> None:
    try:
        metadata.version("pds-concord")
    except metadata.PackageNotFoundError:
        pass
    else:
        raise AcceptanceFailure("pds-concord distribution must be absent.")

    _require(
        importlib.util.find_spec("concord") is None,
        "concord package must not be importable.",
    )
    imported = tuple(
        sorted(name for name in sys.modules if name.split(".", 1)[0] == "concord")
    )
    _require(not imported, "Concord implementation modules were imported.")
    _require(
        "CONCORD_WHEEL" not in __import__("os").environ,
        "CONCORD_WHEEL leaked in.",
    )


def _verify_installed_composition() -> None:
    expected = {
        "pds-core": "0.6.3",
        "scoreform": "0.11.0",
        "quillan": "0.10.0",
    }
    for distribution_name, expected_version in expected.items():
        _require(
            metadata.version(distribution_name) == expected_version,
            f"{distribution_name} version mismatch.",
        )
    _require(
        meridian.__version__ == metadata.version("pds-meridian"),
        "Meridian module/distribution versions disagree.",
    )
    _require(
        pds_core.__version__ == metadata.version("pds-core"),
        "Core module/distribution versions disagree.",
    )
    for module_name in (
        "pds_core",
        "scoreform",
        "quillan",
        "meridian",
        "meridian.scoreform_adapter",
        "meridian.quillan_adapter",
    ):
        _installed_origin(module_name)
    _assert_no_concord()


def _seed_core_context(workspace: Path) -> StandardsLibrary:
    workspace.mkdir()
    write_class_metadata(
        class_metadata_path(workspace, CLASS_ID),
        ClassMetadata(
            class_id=CLASS_ID,
            school_year=SCHOOL_YEAR,
            created_at=NOW,
            updated_at=NOW,
            module_details={},
        ),
    )
    write_roster(
        class_roster_path(workspace, CLASS_ID),
        create_roster(
            CLASS_ID,
            (
                {
                    "student_id": STUDENT_ID,
                    "last_name": "Synthetic",
                    "first_name": "Contributor",
                    "period": "1",
                },
                {
                    "student_id": NONCONTRIBUTOR_ID,
                    "last_name": "Synthetic",
                    "first_name": "Noncontributor",
                    "period": "1",
                },
            ),
        ),
    )
    write_academic_period_calendar(
        workspace,
        AcademicPeriodCalendar(
            schema_version="1",
            record_type="academic_period_calendar",
            school_year=SCHOOL_YEAR,
            calendar_revision=1,
            created_at=NOW,
            updated_at=NOW,
            periods=(
                AcademicPeriod(
                    period_id=PERIOD_ID,
                    period_type="quarter",
                    label="Quarter 1",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 11, 6),
                    parent_period_id=None,
                    sequence=1,
                    lifecycle="active",
                ),
            ),
        ),
        expected_current_revision=None,
    )
    library = StandardsLibrary(
        standards=(
            StandardDefinition(
                standard_id=STANDARD_ID,
                code="ELA.1",
                source="issue45_synthetic",
                short_name="Synthetic ELA standard",
                description="Synthetic shared Standard for issue #45 acceptance.",
                subject="ELA",
                grade_band="9-12",
                active=True,
                available_modules=("scoreform", "quillan", "meridian"),
            ),
        ),
        profiles=(
            StandardsProfile(
                profile_id=PROFILE_ID,
                standards=(STANDARD_ID,),
            ),
        ),
    )
    write_workspace_standards_library(workspace, library)
    return library


def _scoreform_assignment() -> dict[str, object]:
    layout = require_layout(DEFAULT_LAYOUT_ID)
    candidate: dict[str, object] = {
        "assignment_id": SCOREFORM_ASSIGNMENT_ID,
        "title": "Issue 45 ScoreForm quiz",
        "question_count": 3,
        "choices": list(layout.choices),
        "layout_id": layout.layout_id,
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards_profile_id": PROFILE_ID,
        "standards": {"1": [STANDARD_ID], "2": [], "3": []},
    }
    normalized = validate_assignment_data(candidate)  # type: ignore[no-untyped-call]
    _require(normalized is not None, "ScoreForm assignment validation failed.")
    return cast(dict[str, object], normalized)


def _scoreform_result(attempt_number: int) -> ScoreFormRoutedResult:
    if attempt_number == 1:
        answers = (
            ScoredAnswer(1, "B", False),
            ScoredAnswer(2, "B", True),
            ScoredAnswer(3, "C", True),
        )
    elif attempt_number == 2:
        answers = (
            ScoredAnswer(1, "A", True),
            ScoredAnswer(2, "B", True),
            ScoredAnswer(3, "C", True),
        )
    else:
        raise ValueError("attempt_number must be 1 or 2")
    return ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id=CLASS_ID,
        assignment_id=SCOREFORM_ASSIGNMENT_ID,
        student_id=STUDENT_ID,
        last_name="Synthetic",
        first_name="Contributor",
        period="1",
        page_display="manual",
        score=sum(answer.correct for answer in answers),
        total_points=3,
        answers=answers,
        source_file="plain_paper_manual_entry",
    )


@dataclass(frozen=True, slots=True)
class ProducerBaseline:
    publication: PublicationRecord
    native_files: tuple[tuple[Path, bytes], ...]
    manifest_path: Path
    manifest_bytes: bytes


@dataclass(frozen=True, slots=True)
class CachedProjection:
    prepared: ingestion.PreparedPublicationInvocation
    inventory: EvidenceInventory
    cached: ProjectionCacheWriteResult


def _publish_scoreform(workspace: Path) -> ProducerBaseline:
    paths = initialize_scoreform_work_layout(
        workspace,
        CLASS_ID,
        SCOREFORM_ASSIGNMENT_ID,
    )
    _require(
        write_assignment_json(  # type: ignore[no-untyped-call]
            paths.assignment_path, _scoreform_assignment()
        ),
        "ScoreForm assignment write failed.",
    )
    for attempt_number in (1, 2):
        exported = export_scoreform_result_models(
            (_scoreform_result(attempt_number),),
            workspace_root=workspace,
        )
        _require(
            exported.succeeded and len(exported.appended_attempts) == 1,
            f"ScoreForm attempt {attempt_number} was not appended exactly once.",
        )

    native_before = (
        (paths.assignment_path, paths.assignment_path.read_bytes()),
        (paths.results_path, paths.results_path.read_bytes()),
    )
    registration = register_scoreform_academic_work(
        workspace,
        CLASS_ID,
        SCOREFORM_ASSIGNMENT_ID,
        academic_intent="summative",
        lifecycle="active",
    )
    _require(
        registration.registration.registration_revision == 1,
        "ScoreForm registration revision mismatch.",
    )
    generated = generate_scoreform_manifest(
        workspace,
        CLASS_ID,
        SCOREFORM_ASSIGNMENT_ID,
    )
    _require(generated.revision == 1, "ScoreForm manifest revision mismatch.")
    published = publish_scoreform_academic_results(
        workspace,
        CLASS_ID,
        SCOREFORM_ASSIGNMENT_ID,
        manifest_revision=generated.revision,
    )
    return ProducerBaseline(
        publication=published.publication,
        native_files=native_before,
        manifest_path=generated.path,
        manifest_bytes=generated.content,
    )


def _quillan_submission() -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "1",
        "module": "quillan",
        "record_type": "submission_manifest",
        "class_id": CLASS_ID,
        "assignment_id": QUILLAN_ASSIGNMENT_ID,
        "student_id": STUDENT_ID,
        "expected_pages": None,
        "submission_state": "unreviewed",
        "pages": [],
        "created_at": NOW_TEXT,
        "updated_at": NOW_TEXT,
        "module_details": {
            "submission_entry_method": "plain_paper_manual",
            "physical_evidence_status": "teacher_has_external_plain_paper",
            "created_by_workflow": "plain_paper_submission",
        },
    }
    validate_submission_manifest(value)
    return value


def _publish_quillan(workspace: Path) -> ProducerBaseline:
    assignment = build_assignment_config(
        assignment_id=QUILLAN_ASSIGNMENT_ID,
        title="Issue 45 Quillan writing",
        writing_type="argument",
        student_prompt="Write a synthetic standards-aligned response.",
        standards_profile_id=PROFILE_ID,
        focus_standard_ids=(STANDARD_ID,),
        review_unit={
            "type": "paragraph",
            "singular_label": "paragraph",
            "plural_label": "paragraphs",
        },
        rating_scale={
            "scale_id": "issue45_four_level",
            "levels": [
                {"value": 1, "label": "Beginning", "description": "Beginning."},
                {"value": 2, "label": "Developing", "description": "Developing."},
                {"value": 3, "label": "Proficient", "description": "Proficient."},
                {"value": 4, "label": "Advanced", "description": "Advanced."},
            ],
        },
        basic_requirements={},
        minimum_requirement_policy={"allow_return_without_full_review": True},
        class_id=CLASS_ID,
        created_at=NOW,
    )
    assignment_path = write_assignment_config(workspace, CLASS_ID, assignment)

    submission_path = submission_manifest_path(
        workspace,
        CLASS_ID,
        QUILLAN_ASSIGNMENT_ID,
        STUDENT_ID,
    )
    write_submission_manifest(submission_path, _quillan_submission())

    review = build_empty_review_record(
        class_id=CLASS_ID,
        assignment_id=QUILLAN_ASSIGNMENT_ID,
        student_id=STUDENT_ID,
        created_at=NOW_TEXT,
    )
    review_path = review_record_path(
        workspace,
        CLASS_ID,
        QUILLAN_ASSIGNMENT_ID,
        STUDENT_ID,
    )
    write_review_record(review_path, review)
    set_overall_standard_rating(
        workspace,
        CLASS_ID,
        QUILLAN_ASSIGNMENT_ID,
        STUDENT_ID,
        standard_id=STANDARD_ID,
        rating=3,
        rationale="Synthetic teacher-authored rating.",
        include_in_feedback=False,
        updated_at=NOW_TEXT,
    )
    mark_overall_ratings_complete(
        workspace,
        CLASS_ID,
        QUILLAN_ASSIGNMENT_ID,
        STUDENT_ID,
        updated_at=NOW_TEXT,
    )

    native_before = (
        (assignment_path, assignment_path.read_bytes()),
        (submission_path, submission_path.read_bytes()),
        (review_path, review_path.read_bytes()),
    )
    registration = register_quillan_academic_work(
        workspace,
        CLASS_ID,
        QUILLAN_ASSIGNMENT_ID,
        academic_intent="summative",
        lifecycle="active",
    )
    _require(
        registration.registration.registration_revision == 1,
        "Quillan registration revision mismatch.",
    )
    generated = generate_quillan_manifest(
        workspace,
        CLASS_ID,
        QUILLAN_ASSIGNMENT_ID,
    )
    _require(generated.revision == 1, "Quillan manifest revision mismatch.")
    published = publish_quillan_academic_results(
        workspace,
        CLASS_ID,
        QUILLAN_ASSIGNMENT_ID,
        manifest_revision=generated.revision,
    )
    return ProducerBaseline(
        publication=published.publication,
        native_files=native_before,
        manifest_path=generated.path,
        manifest_bytes=generated.content,
    )


class AllowInstalledProjection:
    """Synthetic deployment authorization for this isolated acceptance only."""

    def authorize(
        self,
        request: ingestion.PublicationAuthorizationRequest,
    ) -> ingestion.PublicationAuthorizationDecision:
        return ingestion.PublicationAuthorizationDecision(
            True,
            "issue45_installed_acceptance",
            "1",
            (),
        )


def _project_and_cache(
    workspace: Path,
    baselines: dict[str, ProducerBaseline],
) -> dict[str, CachedProjection]:
    rebuild_academic_catalog(workspace)
    producer_registry = PublicationProducerRegistry(
        (
            scoreform_profile(),
            quillan_profile(),
        )
    )
    adapter_registry = AdapterRegistry(
        (
            ScoreFormAcademicResultAdapter(),
            QuillanAcademicResultAdapter(),
        )
    )
    authorizer = AllowInstalledProjection()
    result: dict[str, CachedProjection] = {}

    for module_id in ("scoreform", "quillan"):
        discovered = ingestion.discover_publication_candidates(
            workspace,
            ingestion.PublicationDiscoveryRequest(
                PublicationCatalogQuery(
                    module_id=module_id,
                    state="current",
                    limit=10,
                )
            ),
        )
        _require(
            len(discovered.candidates) == 1,
            f"{module_id} publication discovery was not singular.",
        )
        candidate = discovered.candidates[0]
        _require(
            candidate.publication_id == baselines[module_id].publication.publication_id,
            f"{module_id} discovery changed publication identity.",
        )
        prepared = ingestion.prepare_publication_invocation(
            workspace,
            candidate,
            producer_registry=producer_registry,
            adapter_registry=adapter_registry,
            authorizer=authorizer,
            authorization_purpose_id="grading_import",
            requested_student_ids=(STUDENT_ID, NONCONTRIBUTOR_ID),
            distribution_version_resolver=installed_distribution_version,
        )
        inventory = adapter_registry.invoke(
            prepared.projection_request,
            installed_distribution_version,
        )
        cached = cache_projected_inventory(
            workspace,
            prepared,
            inventory,
            authorizer=authorizer,
        )
        _require(
            cached.stored.snapshot.source.publication.publication_id
            == candidate.publication_id,
            f"{module_id} cache changed publication identity.",
        )
        result[module_id] = CachedProjection(prepared, inventory, cached)

    return result


def _assert_projection_semantics(projected: dict[str, CachedProjection]) -> None:
    scoreform_inventory = projected["scoreform"].inventory
    scoreform_points = [
        item
        for item in scoreform_inventory.items
        if item.subject is not None
        and item.subject.student_id == STUDENT_ID
        and item.result_kind == "attempt_points"
    ]
    _require(
        len(scoreform_points) == 2,
        "ScoreForm projection must preserve both native attempts.",
    )
    attempt_sequences = sorted(
        reference.sequence
        for item in scoreform_points
        for reference in item.provenance.native.references
        if reference.kind == "attempt" and reference.sequence is not None
    )
    _require(
        attempt_sequences == [1, 2],
        "ScoreForm attempt provenance was not preserved exactly.",
    )

    quillan_inventory = projected["quillan"].inventory
    ratings = [
        item
        for item in quillan_inventory.items
        if item.subject is not None
        and item.subject.student_id == STUDENT_ID
        and item.result_kind == "overall_standard_rating"
        and STANDARD_ID in item.target.standard_ids
    ]
    _require(
        len(ratings) == 1,
        "Quillan projection must expose one Standard-backed overall rating.",
    )

    all_subject_ids = {
        item.subject.student_id
        for inventory in (scoreform_inventory, quillan_inventory)
        for item in inventory.items
        if item.subject is not None
    }
    _require(
        NONCONTRIBUTOR_ID not in all_subject_ids,
        "The deliberate noncontributor unexpectedly acquired producer evidence.",
    )



def _producer_registry() -> PublicationProducerRegistry:
    return PublicationProducerRegistry((scoreform_profile(), quillan_profile()))


def _adapter_registry() -> AdapterRegistry:
    return AdapterRegistry(
        (
            ScoreFormAcademicResultAdapter(),
            QuillanAcademicResultAdapter(),
        )
    )


def _authorized_projection(
    workspace: Path,
    projected: CachedProjection,
) -> AuthorizedProjectionSnapshot:
    stored = projected.cached.stored
    return load_authorized_projection_snapshot(
        workspace,
        stored.snapshot.source.publication.publication_id,
        stored.cache_key,
        authorizer=AllowInstalledProjection(),
        authorization_purpose_id="grading_import",
        requested_student_ids=(STUDENT_ID, NONCONTRIBUTOR_ID),
        producer_registry=_producer_registry(),
        adapter_registry=_adapter_registry(),
        distribution_version_resolver=installed_distribution_version,
    )


def _source_reference(
    projection: CachedProjection,
    item: EvidenceItem,
) -> EvidenceSourceReference:
    stored = projection.cached.stored
    publication_id = stored.snapshot.source.publication.publication_id
    _require(
        item.provenance.publication_id == publication_id,
        "Evidence item and cached publication identity disagree.",
    )
    return EvidenceSourceReference(
        work=item.provenance.work,
        publication_id=item.provenance.publication_id,
        cache_key=stored.cache_key,
        snapshot_digest=stored.snapshot_digest,
        item_id=item.item_id,
    )


def _persist_grade_item(
    workspace: Path,
    baselines: dict[str, ProducerBaseline],
) -> tuple[GradeItemAggregationBasis, dict[str, GradeItemMembershipDecision]]:
    item = GradeItemRevision(
        schema_version=GRADE_ITEM_SCHEMA_VERSION,
        record_type=GRADE_ITEM_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=1,
        supersedes_revision=None,
        title="Installed ScoreForm and Quillan proficiency",
        purpose="standards_proficiency",
        status="active",
        weighting=None,
        created_at=NOW,
        revised_at=NOW,
    )
    stored_item = write_grade_item_revision(workspace, item).stored
    select_grade_item_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        item.grade_item_revision,
        expected_current_revision=None,
    )
    current = load_current_grade_item_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
    )
    _require(current is not None, "Grade Item selection did not resolve.")
    assert current is not None

    memberships: dict[str, GradeItemMembershipDecision] = {}
    for module_id in ("scoreform", "quillan"):
        publication = baselines[module_id].publication
        registration_revision = publication.academic_work_registration_revision
        _require(
            isinstance(registration_revision, int),
            f"{module_id} publication lacks a registration revision.",
        )
        assert isinstance(registration_revision, int)
        decision = GradeItemMembershipDecision(
            schema_version=GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
            record_type=GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            grade_item_revision=item.grade_item_revision,
            grade_item_revision_sha256=stored_item.revision_sha256,
            work_reference=GradeItemWorkReference(
                work=publication.work,
                registration_revision=registration_revision,
            ),
            membership_revision=1,
            supersedes_revision=None,
            decision="included",
            academic_period=GradeItemAcademicPeriodAssignment(
                period=AcademicPeriodRef(
                    school_year=SCHOOL_YEAR,
                    period_id=PERIOD_ID,
                ),
                calendar_revision=1,
            ),
            actor_id=ACTOR_ID,
            rationale=f"Explicitly include released {module_id} work.",
            decided_at=NOW,
        )
        write_grade_item_membership_revision(workspace, decision)
        select_grade_item_membership_revision(
            workspace,
            CLASS_ID,
            GRADE_ITEM_ID,
            publication.work,
            decision.membership_revision,
            expected_current_membership_revision=None,
        )
        memberships[module_id] = decision

    return (
        GradeItemAggregationBasis(
            current.revision.class_id,
            current.revision.grade_item_id,
            current.revision.grade_item_revision,
            current.revision_sha256,
        ),
        memberships,
    )


def _persist_included_eligibility(
    workspace: Path,
    projection: CachedProjection,
    authorized: AuthorizedProjectionSnapshot,
    membership: GradeItemMembershipDecision,
    item: EvidenceItem,
) -> None:
    source = _source_reference(projection, item)
    membership_stored = write_grade_item_membership_revision(
        workspace,
        membership,
    ).stored
    decision = EvidenceEligibilityDecision(
        schema_version=EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
        record_type=EVIDENCE_ELIGIBILITY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        source=source,
        membership_revision=membership.membership_revision,
        membership_revision_sha256=membership_stored.decision_sha256,
        eligibility_revision=1,
        supersedes_revision=None,
        disposition="included",
        actor=EvidenceDecisionActor("teacher", ACTOR_ID),
        policy=EvidenceEligibilityPolicyReference(
            ELIGIBILITY_POLICY_ID,
            "1",
        ),
        reason_codes=(),
        rationale="Explicit issue #45 installed-acceptance inclusion.",
        source_state=EvidenceSourceStateObservation(
            state="current",
            head_publication_id=source.publication_id,
            successor_publication_id=None,
            withdrawn_at=None,
        ),
        decided_at=NOW,
    )
    eligibility_storage.write_evidence_eligibility_revision(
        workspace,
        decision,
        authorized_snapshot=authorized,
    )
    eligibility_storage.select_evidence_eligibility_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        source,
        decision.eligibility_revision,
        authorized_snapshot=authorized,
        expected_current_eligibility_revision=None,
    )


def _prepare_eligibility(
    workspace: Path,
    projected: dict[str, CachedProjection],
    authorized: dict[str, AuthorizedProjectionSnapshot],
    memberships: dict[str, GradeItemMembershipDecision],
) -> EvidenceItem:
    for item in projected["scoreform"].inventory.items:
        if item.subject is None or item.subject.student_id != STUDENT_ID:
            continue
        _persist_included_eligibility(
            workspace,
            projected["scoreform"],
            authorized["scoreform"],
            memberships["scoreform"],
            item,
        )

    quillan_rating = next(
        item
        for item in projected["quillan"].inventory.items
        if item.subject is not None
        and item.subject.student_id == STUDENT_ID
        and item.result_kind == "overall_standard_rating"
        and STANDARD_ID in item.target.standard_ids
        and isinstance(item.value, NativeScaledValue)
        and item.value.value == 3
    )
    _persist_included_eligibility(
        workspace,
        projected["quillan"],
        authorized["quillan"],
        memberships["quillan"],
        quillan_rating,
    )
    return quillan_rating


def _select_and_replace_scoreform_attempts(
    workspace: Path,
    baselines: dict[str, ProducerBaseline],
    authorized: AuthorizedProjectionSnapshot,
    membership: GradeItemMembershipDecision,
) -> None:
    work = baselines["scoreform"].publication.work
    derivation = attempt_storage.derive_attempt_candidates(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        authorized,
    )
    _require(
        len(derivation.candidates) == 2,
        "ScoreForm attempt derivation must expose exactly two attempts.",
    )

    policy = AttemptSelectionPolicy(
        schema_version=ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        policy_id=ATTEMPT_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        selection_basis="explicit",
        minimum_selected=2,
        maximum_selected=2,
        actor=AttemptSelectionActor("teacher", ACTOR_ID),
        rationale="Explicitly select both released ScoreForm native attempts.",
        revised_at=NOW,
    )
    stored_policy = attempt_storage.write_attempt_selection_policy_revision(
        workspace,
        policy,
    ).stored
    attempt_storage.select_attempt_selection_policy_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        work,
        policy.policy_id,
        policy.policy_revision,
        expected_current_policy_revision=None,
    )
    membership_stored = write_grade_item_membership_revision(
        workspace,
        membership,
    ).stored
    decision = AttemptSelectionDecision(
        schema_version=ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        student_id=STUDENT_ID,
        membership_revision=membership.membership_revision,
        membership_revision_sha256=membership_stored.decision_sha256,
        policy=AttemptSelectionPolicyReference(
            policy_id=policy.policy_id,
            policy_revision=policy.policy_revision,
            policy_revision_sha256=stored_policy.policy_sha256,
        ),
        source_snapshot=derivation.source_snapshot,
        candidates=derivation.candidates,
        selected_attempts=tuple(
            candidate.attempt for candidate in derivation.candidates
        ),
        decision_revision=1,
        supersedes_revision=None,
        actor=AttemptSelectionActor("teacher", ACTOR_ID),
        rationale="Both native attempts remain selected before reassessment.",
        decided_at=NOW,
    )
    attempt_storage.write_attempt_selection_decision_revision(
        workspace,
        decision,
        authorized_snapshot=authorized,
    )
    attempt_storage.select_attempt_selection_decision_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        work,
        STUDENT_ID,
        decision.decision_revision,
        authorized_snapshot=authorized,
        expected_current_decision_revision=None,
    )
    selection = attempt_storage.resolve_current_attempt_selection(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        work,
        STUDENT_ID,
        authorized_snapshot=authorized,
    )
    _require(
        selection.status == "selected" and selection.selected is not None,
        "ScoreForm attempt selection must resolve.",
    )
    assert selection.selected is not None
    selected_attempts = selection.selected.decision.selected_attempts
    by_sequence = {
        attempt.native.sequence: attempt
        for attempt in selected_attempts
    }
    _require(
        set(by_sequence) == {1, 2},
        "ScoreForm selected attempt sequences must remain exactly 1 and 2.",
    )
    first = by_sequence[1]
    second = by_sequence[2]

    reassessment_policy = ReassessmentPolicy(
        schema_version=REASSESSMENT_POLICY_SCHEMA_VERSION,
        record_type=REASSESSMENT_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        policy_id=REASSESSMENT_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        relationship_basis="explicit",
        allowed_modes=("replace",),
        actor=ReassessmentActor("teacher", ACTOR_ID),
        rationale="Explicit issue #45 replacement policy.",
        revised_at=NOW,
    )
    stored_reassessment_policy = (
        reassessment_storage.write_reassessment_policy_revision(
            workspace,
            reassessment_policy,
        ).stored
    )
    reassessment_storage.select_reassessment_policy_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        work,
        reassessment_policy.policy_id,
        reassessment_policy.policy_revision,
        expected_current_policy_revision=None,
    )
    reassessment = ReassessmentDecision(
        schema_version=REASSESSMENT_DECISION_SCHEMA_VERSION,
        record_type=REASSESSMENT_DECISION_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        student_id=STUDENT_ID,
        attempt_selection=AttemptSelectionDecisionReference(
            selection.selected.decision.decision_revision,
            selection.selected.decision_sha256,
        ),
        policy=ReassessmentPolicyReference(
            reassessment_policy.policy_id,
            reassessment_policy.policy_revision,
            stored_reassessment_policy.policy_sha256,
        ),
        mode="replace",
        contributing_attempts=(second,),
        replacement_relationships=(
            ReplacementRelationship(second, (first,)),
        ),
        combinations=(),
        recency_order=(),
        decision_revision=1,
        supersedes_revision=None,
        actor=ReassessmentActor("teacher", ACTOR_ID),
        rationale="Attempt 2 explicitly replaces attempt 1.",
        decided_at=NOW,
    )
    reassessment_storage.write_reassessment_decision_revision(
        workspace,
        reassessment,
        authorized_snapshot=authorized,
    )
    reassessment_storage.select_reassessment_decision_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        work,
        STUDENT_ID,
        reassessment.decision_revision,
        authorized_snapshot=authorized,
        expected_current_decision_revision=None,
    )
    resolved = reassessment_storage.resolve_current_reassessment(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        work,
        STUDENT_ID,
        authorized_snapshot=authorized,
    )
    _require(
        resolved.status == "resolved",
        "ScoreForm reassessment replacement must resolve.",
    )


def _native_attempt_sequence(item: EvidenceItem) -> int:
    sequences = tuple(
        reference.sequence
        for reference in item.provenance.native.references
        if reference.kind == "attempt"
    )
    _require(
        len(sequences) == 1 and isinstance(sequences[0], int),
        "Evidence must carry exactly one native attempt sequence.",
    )
    value = sequences[0]
    assert isinstance(value, int)
    return value


def _scoreform_standard_items(
    projected: CachedProjection,
) -> tuple[EvidenceItem, EvidenceItem]:
    items = tuple(
        item
        for item in projected.inventory.items
        if item.subject is not None
        and item.subject.student_id == STUDENT_ID
        and item.result_kind == "question_correctness"
        and item.target.target_id == "question_1"
        and STANDARD_ID in item.target.standard_ids
        and isinstance(item.value, NativeScalarValue)
    )
    _require(
        len(items) == 2,
        "ScoreForm must expose two Standard-backed Q1 correctness observations.",
    )
    by_sequence = {_native_attempt_sequence(item): item for item in items}
    _require(
        set(by_sequence) == {1, 2},
        "ScoreForm Q1 correctness must preserve native attempts 1 and 2.",
    )
    first = by_sequence[1]
    second = by_sequence[2]
    _require(
        isinstance(first.value, NativeScalarValue) and first.value.value is False,
        "ScoreForm attempt 1 Q1 must be the deliberate incorrect response.",
    )
    _require(
        isinstance(second.value, NativeScalarValue) and second.value.value is True,
        "ScoreForm attempt 2 Q1 must be the deliberate corrected response.",
    )
    return first, second


def _persist_standard_association(
    workspace: Path,
    projection: CachedProjection,
    authorized: AuthorizedProjectionSnapshot,
    item: EvidenceItem,
    library: StandardsLibrary,
) -> None:
    source = _source_reference(projection, item)
    decision = StandardEvidenceAssociationDecision(
        schema_version=STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
        record_type=STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        source=source,
        standard_id=STANDARD_ID,
        association_revision=1,
        supersedes_revision=None,
        disposition="associated",
        basis="producer_declared",
        actor=StandardEvidenceActor("teacher", ACTOR_ID),
        rationale="Accept the producer-declared shared Standard explicitly.",
        decided_at=NOW,
    )
    standards_storage.write_standard_evidence_association_revision(
        workspace,
        decision,
        authorized_snapshot=authorized,
        standards_library=library,
    )
    standards_storage.select_standard_evidence_association_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        source,
        STANDARD_ID,
        decision.association_revision,
        expected_current_association_revision=None,
    )


def _proficiency_scale(workspace: Path) -> StoredProficiencyScale:
    scale = ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="issue45_proficiency",
        scale_revision=1,
        supersedes_revision=None,
        title="Issue 45 proficiency",
        description="Synthetic installed cross-producer target scale.",
        levels=(
            ProficiencyLevel("beginning", 1, "Beginning", "Initial evidence."),
            ProficiencyLevel("developing", 2, "Developing", "Partial evidence."),
            ProficiencyLevel("proficient", 3, "Proficient", "Meets criterion."),
            ProficiencyLevel("advanced", 4, "Advanced", "Extends criterion."),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", ACTOR_ID),
        rationale="Explicit issue #45 target scale.",
        revised_at=NOW,
    )
    return write_proficiency_scale_revision(workspace, scale).stored


def _scoreform_mapping_profile(
    workspace: Path,
    first: EvidenceItem,
    second: EvidenceItem,
    scale: StoredProficiencyScale,
) -> StoredNativeValueMappingProfile:
    first_signature = native_value_source_signature_from_item(first)
    second_signature = native_value_source_signature_from_item(second)
    _require(
        first_signature == second_signature,
        "ScoreForm Q1 correctness attempts must share one source signature.",
    )
    profile = NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id=scale.scale.scale_id,
        profile_id="issue45_scoreform_q1_correctness",
        profile_revision=1,
        supersedes_revision=None,
        target_scale=scale.reference,
        source_signature=first_signature,
        mapping_kind="exact_scalar",
        native_scale=None,
        points_possible=None,
        mapping_rules=(
            ScalarMappingRule(False, "beginning"),
            ScalarMappingRule(True, "proficient"),
        ),
        actor=MappingActor("teacher", ACTOR_ID),
        rationale="Explicit Boolean correctness mapping for ScoreForm Q1.",
        revised_at=NOW,
    )
    return write_mapping_profile_revision(workspace, profile).stored


def _quillan_mapping_profile(
    workspace: Path,
    item: EvidenceItem,
    scale: StoredProficiencyScale,
) -> StoredNativeValueMappingProfile:
    value = item.value
    _require(
        isinstance(value, NativeScaledValue) and value.value == 3,
        "Quillan Standard rating must remain native value 3.",
    )
    assert isinstance(value, NativeScaledValue)
    profile = NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id=scale.scale.scale_id,
        profile_id="issue45_quillan_standard_rating",
        profile_revision=1,
        supersedes_revision=None,
        target_scale=scale.reference,
        source_signature=native_value_source_signature_from_item(item),
        mapping_kind="exact_native_scale",
        native_scale=value.scale,
        points_possible=None,
        mapping_rules=(ScaledLevelMappingRule(3, "proficient"),),
        actor=MappingActor("teacher", ACTOR_ID),
        rationale="Explicit Quillan native rating mapping.",
        revised_at=NOW,
    )
    return write_mapping_profile_revision(workspace, profile).stored


def _proficiency_policy(
    scale: StoredProficiencyScale,
) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="issue45_installed_highest",
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 45 installed cross-producer proficiency",
        target_scale=scale.reference,
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=(
            "association_unresolved",
            "eligibility_unresolved",
            "attempt_selection_unresolved",
            "reassessment_unresolved",
            "mapping_not_supplied",
            "mapping_unmapped",
            "mapping_unsupported",
            "scale_mismatch",
            "source_unverifiable",
            "standard_unresolved",
        ),
        native_state_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", ACTOR_ID),
        rationale="Use only resolved contributing performance evidence.",
        revised_at=NOW,
    )


def _persist_grade_item_result(
    workspace: Path,
    inputs: StandardAggregationInputs,
    outcome: StandardProficiencyCalculationOutcome,
    student_id: str,
) -> None:
    snapshot = create_standard_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    written = write_standard_proficiency_result_revision(workspace, snapshot).stored
    _require(
        written.snapshot.student_id == student_id,
        "Persisted Grade Item result student identity changed.",
    )
    select_standard_proficiency_result_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        student_id,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )


def _calculate_grade_item_proficiency(
    workspace: Path,
    baselines: dict[str, ProducerBaseline],
    projected: dict[str, CachedProjection],
    library: StandardsLibrary,
) -> tuple[
    GradeItemAggregationBasis,
    dict[str, GradeItemMembershipDecision],
    StoredProficiencyScale,
]:
    grade_item, memberships = _persist_grade_item(workspace, baselines)
    authorized = {
        module_id: _authorized_projection(workspace, projected[module_id])
        for module_id in ("scoreform", "quillan")
    }
    quillan_rating = _prepare_eligibility(
        workspace,
        projected,
        authorized,
        memberships,
    )
    _select_and_replace_scoreform_attempts(
        workspace,
        baselines,
        authorized["scoreform"],
        memberships["scoreform"],
    )
    scoreform_first, scoreform_second = _scoreform_standard_items(
        projected["scoreform"]
    )
    for item in (scoreform_first, scoreform_second):
        _persist_standard_association(
            workspace,
            projected["scoreform"],
            authorized["scoreform"],
            item,
            library,
        )
    _persist_standard_association(
        workspace,
        projected["quillan"],
        authorized["quillan"],
        quillan_rating,
        library,
    )

    scale = _proficiency_scale(workspace)
    scoreform_profile = _scoreform_mapping_profile(
        workspace,
        scoreform_first,
        scoreform_second,
        scale,
    )
    quillan_profile = _quillan_mapping_profile(
        workspace,
        quillan_rating,
        scale,
    )
    bindings = (
        standards_storage.StandardAggregationCandidateBinding(
            _source_reference(projected["scoreform"], scoreform_first),
            authorized["scoreform"],
            scoreform_profile.reference,
        ),
        standards_storage.StandardAggregationCandidateBinding(
            _source_reference(projected["scoreform"], scoreform_second),
            authorized["scoreform"],
            scoreform_profile.reference,
        ),
        standards_storage.StandardAggregationCandidateBinding(
            _source_reference(projected["quillan"], quillan_rating),
            authorized["quillan"],
            quillan_profile.reference,
        ),
    )
    contributor_inputs = standards_storage.resolve_standard_aggregation_inputs(
        workspace,
        grade_item,
        STUDENT_ID,
        STANDARD_ID,
        scale.reference,
        bindings,
        standards_library=library,
    )
    contributor_entries = {
        entry.source.item_id: entry for entry in contributor_inputs.entries
    }
    first_entry = contributor_entries[scoreform_first.item_id]
    second_entry = contributor_entries[scoreform_second.item_id]
    quillan_entry = contributor_entries[quillan_rating.item_id]
    _require(
        first_entry.status == "excluded"
        and first_entry.exclusion_reason == "reassessment_noncontributing",
        "Replaced ScoreForm attempt 1 must be explicitly noncontributing.",
    )
    _require(
        second_entry.status == "performance"
        and second_entry.proficiency_level_id == "proficient",
        "Current ScoreForm attempt must contribute proficient performance.",
    )
    _require(
        quillan_entry.status == "performance"
        and quillan_entry.proficiency_level_id == "proficient",
        "Quillan Standard rating must contribute proficient performance.",
    )

    policy = _proficiency_policy(scale)
    stored_policy = write_standard_proficiency_policy_revision(
        workspace,
        policy,
    ).stored
    select_standard_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        stored_policy.policy.policy_id,
        stored_policy.policy.policy_revision,
        expected_current_policy_revision=None,
    )
    exact_policy = stored_policy.policy

    contributor = calculate_standard_proficiency(
        contributor_inputs,
        exact_policy,
        scale.scale,
    )
    _require(
        contributor.status == "calculated"
        and contributor.proficiency_level_id == "proficient",
        "Contributor Grade Item proficiency must calculate as proficient.",
    )
    _require(
        contributor.performance_observation_count == 2,
        "Contributor must have exactly two contributing performance observations.",
    )
    _persist_grade_item_result(
        workspace,
        contributor_inputs,
        contributor,
        STUDENT_ID,
    )

    noncontributor_inputs = standards_storage.resolve_standard_aggregation_inputs(
        workspace,
        grade_item,
        NONCONTRIBUTOR_ID,
        STANDARD_ID,
        scale.reference,
        (),
        standards_library=library,
    )
    _require(
        not noncontributor_inputs.entries,
        "Noncontributor must not acquire synthetic aggregation entries.",
    )
    noncontributor = calculate_standard_proficiency(
        noncontributor_inputs,
        exact_policy,
        scale.scale,
    )
    _require(
        noncontributor.status == "insufficient_evidence"
        and noncontributor.proficiency_level_id is None,
        "Missing evidence must remain insufficient, never a low proficiency level.",
    )
    _require(
        tuple(reason.kind for reason in noncontributor.insufficiency_reasons)
        == ("no_performance_evidence",),
        "Noncontributor insufficiency must be explicit no-performance evidence.",
    )
    _persist_grade_item_result(
        workspace,
        noncontributor_inputs,
        noncontributor,
        NONCONTRIBUTOR_ID,
    )

    contributor_trace = explain_grade_item_proficiency(
        workspace,
        GradeItemProficiencyTraceTarget(
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            "current",
        ),
    )
    _require(
        contributor_trace.selection_state == "selected_current"
        and contributor_trace.calculation.status == "calculated"
        and contributor_trace.calculation.proficiency_level_id == "proficient",
        "Persisted contributor Grade Item explanation must resolve "
        "current proficiency.",
    )
    _require(
        len(contributor_trace.evidence) == 3
        and sum(row.contributes_performance for row in contributor_trace.evidence) == 2,
        "Grade Item explanation must preserve two contributors and one exclusion.",
    )
    _require(
        any(
            row.exclusion_reason == "reassessment_noncontributing"
            for row in contributor_trace.evidence
        ),
        "Grade Item explanation must preserve the reassessment exclusion reason.",
    )

    noncontributor_trace = explain_grade_item_proficiency(
        workspace,
        GradeItemProficiencyTraceTarget(
            CLASS_ID,
            GRADE_ITEM_ID,
            NONCONTRIBUTOR_ID,
            STANDARD_ID,
            "current",
        ),
    )
    _require(
        noncontributor_trace.selection_state == "selected_current"
        and noncontributor_trace.calculation.status == "insufficient_evidence"
        and noncontributor_trace.calculation.proficiency_level_id is None
        and not noncontributor_trace.evidence,
        "Persisted noncontributor explanation must remain insufficient "
        "with no evidence.",
    )
    return grade_item, memberships, scale


def _academic_period_policy(
    scale: StoredProficiencyScale,
) -> AcademicPeriodProficiencyAggregationPolicy:
    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=PERIOD_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 45 installed Academic Period proficiency",
        target_scale=scale.reference,
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", ACTOR_ID),
        rationale="Aggregate only exact calculated Grade Item proficiency results.",
        revised_at=NOW,
    )


def _calculate_academic_period_proficiency(
    workspace: Path,
    grade_item: GradeItemAggregationBasis,
    memberships: dict[str, GradeItemMembershipDecision],
    scale: StoredProficiencyScale,
) -> None:
    policy_write = write_academic_period_proficiency_policy_revision(
        workspace,
        _academic_period_policy(scale),
    )
    policy = policy_write.stored.policy
    select_academic_period_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        policy.policy_id,
        policy.policy_revision,
        expected_current_policy_revision=None,
    )
    calendar = load_academic_period_calendar_revision(workspace, SCHOOL_YEAR, 1)
    target = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
        1,
    )
    membership_bases = tuple(
        sorted(
            (
                academic_period_proficiency_membership_basis_from_decision(
                    memberships[module_id],
                    write_grade_item_membership_revision(
                        workspace,
                        memberships[module_id],
                    ).stored.decision_sha256,
                )
                for module_id in ("scoreform", "quillan")
            ),
            key=lambda item: (
                item.work_reference.work.module_id,
                item.work_reference.work.work_id,
            ),
        )
    )

    for student_id, expected_status, expected_level in (
        (STUDENT_ID, "calculated", "proficient"),
        (NONCONTRIBUTOR_ID, "insufficient_evidence", None),
    ):
        grade_result = load_current_standard_proficiency_result(
            workspace,
            CLASS_ID,
            GRADE_ITEM_ID,
            student_id,
            STANDARD_ID,
        )
        _require(grade_result is not None, "Selected Grade Item result must reload.")
        assert grade_result is not None
        inputs = build_academic_period_proficiency_aggregation_inputs(
            target_period=target,
            calendar=calendar,
            student_id=student_id,
            standard_id=STANDARD_ID,
            target_scale=scale.reference,
            period_membership_scope="direct",
            candidates=(
                ResolvedAcademicPeriodProficiencyCandidate(
                    grade_item,
                    membership_bases,
                    grade_result.snapshot,
                ),
            ),
        )
        _require(
            len(inputs.entries) == 1,
            "Academic Period inputs must contain the explicit Grade Item exactly once.",
        )
        outcome = calculate_academic_period_proficiency(
            inputs,
            policy,
            scale.scale,
        )
        _require(
            outcome.status == expected_status
            and outcome.proficiency_level_id == expected_level,
            "Academic Period proficiency did not preserve contributor semantics.",
        )
        if student_id == NONCONTRIBUTOR_ID:
            _require(
                inputs.entries[0].status == "insufficient_evidence"
                and outcome.calculated_result_count == 0
                and outcome.insufficient_result_count == 1,
                "Noncontributor #34 insufficiency must remain noncontributing in #35.",
            )
        snapshot = create_academic_period_proficiency_result_snapshot(
            inputs,
            outcome,
            result_revision=1,
            calculated_at=NOW,
        )
        write_academic_period_proficiency_result_revision(workspace, snapshot)
        select_academic_period_proficiency_result_revision(
            workspace,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            student_id,
            STANDARD_ID,
            1,
            expected_current_result_revision=None,
        )
        reloaded = load_current_academic_period_proficiency_result(
            workspace,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            student_id,
            STANDARD_ID,
        )
        _require(
            reloaded is not None
            and reloaded.snapshot.outcome.status == expected_status
            and reloaded.snapshot.outcome.proficiency_level_id == expected_level,
            "Selected Academic Period result must reload with exact outcome semantics.",
        )

        trace = explain_academic_period_proficiency(
            workspace,
            AcademicPeriodProficiencyTraceTarget(
                CLASS_ID,
                SCHOOL_YEAR,
                PERIOD_ID,
                student_id,
                STANDARD_ID,
                "current",
            ),
        )
        _require(
            trace.selection_state == "selected_current"
            and trace.calculation.status == expected_status
            and trace.calculation.proficiency_level_id == expected_level,
            "Academic Period explanation must match the exact persisted #35 result.",
        )
        _require(
            len(trace.grade_items) == 1
            and trace.grade_items[0].nested_grade_item_explanation is not None,
            "Academic Period explanation must drill down to the exact #34 result.",
        )
        nested = trace.grade_items[0].nested_grade_item_explanation
        assert nested is not None
        _require(
            nested.student_id == student_id
            and nested.result_sha256 == grade_result.result_sha256,
            "Nested #35 explanation must bind the exact stored #34 result digest.",
        )


def _grouping_signal_policy(
    workspace: Path,
    scale: StoredProficiencyScale,
) -> GroupingSignalDerivationPolicy:
    period_result = load_current_academic_period_proficiency_result(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
    )
    _require(
        period_result is not None,
        "Contributor Academic Period result must exist before grouping policy.",
    )
    assert period_result is not None
    return GroupingSignalDerivationPolicy(
        schema_version=GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=GROUPING_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 45 contextual ELA planning signal",
        academic_basis=GroupingSignalAcademicBasis(
            basis_kind="academic_period_proficiency",
            target_period=AcademicPeriodProficiencyTarget(
                AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
                1,
            ),
            standard_id=STANDARD_ID,
            source_policy=period_result.snapshot.policy_reference,
            target_scale=scale.reference,
        ),
        dimension_id="ela_planning",
        band_count=2,
        band_definitions=(
            GroupingSignalBandDefinition(1, 1, 2),
            GroupingSignalBandDefinition(2, 3, 4),
        ),
        tie_handling="same_level_same_band",
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=GroupingSignalPolicyActor("teacher", ACTOR_ID),
        rationale="Contextual planning signal for the exact installed acceptance.",
        revised_at=NOW,
    )


def _derive_preview_review_and_export(
    workspace: Path,
    scale: StoredProficiencyScale,
) -> GroupingSignalDerivationReference:
    policy_write = write_grouping_signal_policy_revision(
        workspace,
        _grouping_signal_policy(workspace, scale),
    )
    policy = policy_write.stored.policy
    select_grouping_signal_policy_revision(
        workspace,
        CLASS_ID,
        policy.policy_id,
        policy.policy_revision,
        expected_current_policy_revision=None,
    )

    _require(
        list_grouping_signal_ids(workspace, CLASS_ID) == (),
        "Derivation must not implicitly export a Core grouping signal.",
    )
    generated = generate_grouping_signal_derivation(
        workspace,
        CLASS_ID,
        policy.policy_id,
    )
    _require(
        generated.status == "generated"
        and generated.write_disposition == "created"
        and generated.stored is not None,
        "Grouping-signal derivation must be created from selected #35 state.",
    )
    assert generated.stored is not None
    derivation = generated.stored.snapshot
    _require(
        derivation.roster_basis.student_ids
        == tuple(sorted((STUDENT_ID, NONCONTRIBUTOR_ID))),
        "Derivation must bind the complete exact Core roster membership.",
    )
    rows = {item.student_id: item for item in derivation.student_derivations}
    _require(
        tuple(sorted(rows)) == tuple(sorted((STUDENT_ID, NONCONTRIBUTOR_ID))),
        "Derivation must retain both roster students.",
    )
    contributor = rows[STUDENT_ID]
    _require(
        contributor.source_state == "calculated"
        and contributor.disposition == "contributing"
        and contributor.proficiency_level_id == "proficient"
        and contributor.scale_position == 3
        and contributor.band == 2,
        "Contributor must deterministically map to contextual Band 2.",
    )
    noncontributor = rows[NONCONTRIBUTOR_ID]
    _require(
        noncontributor.source_state == "insufficient_evidence"
        and noncontributor.disposition == "noncontributing"
        and noncontributor.source_result is not None
        and noncontributor.proficiency_level_id is None
        and noncontributor.scale_position is None
        and noncontributor.band is None,
        "Insufficient student must remain a provenance-bearing noncontributor.",
    )
    _require(
        list_grouping_signal_ids(workspace, CLASS_ID) == (),
        "Derivation creation must still leave Core signal storage empty.",
    )

    replay = generate_grouping_signal_derivation(
        workspace,
        CLASS_ID,
        policy.policy_id,
    )
    _require(
        replay.status == "generated"
        and replay.write_disposition == "existing"
        and replay.stored is not None
        and replay.stored.reference == generated.stored.reference
        and replay.stored.content == generated.stored.content,
        "Unchanged derivation generation must reconcile to exact existing bytes.",
    )

    preview_result = generate_grouping_signal_preview(
        workspace,
        generated.stored.reference,
    )
    _require(
        preview_result.write_disposition == "created",
        "Grouping-signal preview must be explicitly generated before review.",
    )
    preview = preview_result.stored.snapshot
    _require(
        preview.currentness.state == "current"
        and preview.coverage.roster_student_count == 2
        and preview.coverage.contributing_student_count == 1,
        "Preview must expose one contributor across the two-student roster.",
    )
    preview_rows = {item.student_id: item for item in preview.student_rows}
    _require(
        preview_rows[STUDENT_ID].band == 2
        and preview_rows[NONCONTRIBUTOR_ID].band is None,
        "Preview must show the noncontributor without a sentinel band.",
    )
    warning_ids = tuple(
        sorted(
            item.diagnostic_id
            for item in preview.diagnostics
            if item.severity == "warning"
        )
    )
    review_result = record_grouping_signal_review(
        workspace,
        preview_result.stored.reference,
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=warning_ids,
        actor_id=ACTOR_ID,
        reviewed_at=NOW,
    )
    _require(
        review_result.disposition == "created",
        "Accepted-for-export review must be explicitly authored.",
    )
    selected_review = select_grouping_signal_review_revision(
        workspace,
        CLASS_ID,
        generated.stored.reference.derivation_id,
        1,
        expected_current_review_revision=None,
    )
    _require(
        selected_review.disposition == "created",
        "Accepted review revision must be explicitly selected.",
    )
    teacher_projection = build_grouping_signal_teacher_projection(
        workspace,
        preview_result.stored.reference,
    )
    _require(
        teacher_projection.live_currentness.state == "current"
        and teacher_projection.review_status.decision == "accepted_for_export"
        and teacher_projection.review_status.applicability is not None
        and teacher_projection.review_status.applicability.status == "current",
        "Teacher projection must show a current accepted export path.",
    )

    exported = export_grouping_signal(
        workspace,
        CLASS_ID,
        generated.stored.reference.derivation_id,
        signal_set_id=SIGNAL_SET_ID,
        created_at=NOW,
    )
    _require(
        exported.core.write_result.disposition == "created"
        and exported.receipt.disposition == "created",
        "#40 must create both Core signal and Meridian export receipt.",
    )
    stored_signal = load_grouping_signal(workspace, CLASS_ID, SIGNAL_SET_ID)
    signal = stored_signal.signal
    _require(
        signal.source.kind == "module_generated"
        and signal.source.module_id == "meridian"
        and signal.source.snapshot_id == generated.stored.reference.derivation_id
        and signal.source.snapshot_digest_algorithm == "sha256"
        and signal.source.snapshot_digest
        == generated.stored.reference.derivation_sha256,
        "Core signal must bind the exact immutable Meridian derivation.",
    )
    _require(
        len(signal.dimensions) == 1
        and signal.dimensions[0].dimension_id == "ela_planning"
        and signal.dimensions[0].band_count == 2,
        "Core signal must contain exactly the selected contextual dimension.",
    )
    _require(
        len(signal.student_bands) == 1
        and signal.student_bands[0].student_id == STUDENT_ID
        and signal.student_bands[0].dimension_id == "ela_planning"
        and signal.student_bands[0].band == 2,
        "Core signal must export only the contributing student and exact band.",
    )
    _require(
        all(item.student_id != NONCONTRIBUTOR_ID for item in signal.student_bands),
        "Noncontributor must be absent from Core student_bands, "
        "not assigned a sentinel.",
    )
    receipt = load_grouping_signal_export_receipt(
        workspace,
        CLASS_ID,
        SIGNAL_SET_ID,
    )
    _require(
        receipt.receipt.core_signal_digest == stored_signal.digest,
        "Meridian export receipt must bind the exact Core storage digest.",
    )

    canonical = grouping_signal_set_to_json_bytes(signal)
    parsed = grouping_signal_set_from_json(canonical)
    _require(
        parsed == signal
        and grouping_signal_set_to_json_bytes(parsed) == canonical
        and stored_signal.digest == hashlib.sha256(canonical).hexdigest(),
        "Core grouping signal must canonical-JSON round-trip with exact digest.",
    )
    forbidden = (
        STANDARD_ID,
        GRADE_ITEM_ID,
        SCOREFORM_ASSIGNMENT_ID,
        QUILLAN_ASSIGNMENT_ID,
        ATTEMPT_POLICY_ID,
        REASSESSMENT_POLICY_ID,
        ACTOR_ID,
        "proficient",
        "question_correctness",
        "overall_standard_rating",
        "Contributor",
        "Noncontributor",
        NONCONTRIBUTOR_ID,
    )
    canonical_text = canonical.decode("utf-8")
    _require(
        all(value not in canonical_text for value in forbidden),
        "Core signal leaked Meridian-private academic/proficiency provenance.",
    )

    csv_path = workspace.parent / "issue45-ela-planning.csv"
    csv_result = export_grouping_signal_csv(
        workspace,
        CLASS_ID,
        SIGNAL_SET_ID,
        csv_path,
    )
    _require(
        csv_result.disposition == "created",
        "Core-native grouping-signal CSV must be explicitly created.",
    )
    csv_bytes = csv_path.read_bytes()
    document = parse_grouping_signal_csv(csv_bytes)
    reconstructed = grouping_signal_csv_to_signal_set(document)
    _require(
        document.representation_scope == "complete_signal"
        and reconstructed == signal
        and grouping_signal_set_to_json_bytes(reconstructed) == canonical,
        "Core-native CSV must reconstruct the exact one-dimension Core signal.",
    )
    csv_text = csv_bytes.decode("utf-8")
    _require(
        all(value not in csv_text for value in forbidden),
        "Core-native CSV leaked Meridian-private academic/proficiency provenance.",
    )
    _require(
        export_grouping_signal_csv(
            workspace,
            CLASS_ID,
            SIGNAL_SET_ID,
            csv_path,
        ).disposition
        == "existing",
        "Exact CSV replay must reconcile without overwriting different bytes.",
    )
    export_replay = export_grouping_signal(
        workspace,
        CLASS_ID,
        generated.stored.reference.derivation_id,
        signal_set_id=SIGNAL_SET_ID,
        created_at=NOW,
    )
    _require(
        export_replay.core.write_result.disposition == "existing"
        and export_replay.receipt.disposition == "existing",
        "Exact Core export replay must be idempotent.",
    )
    return generated.stored.reference

def _write_reload_baseline(
    root: Path,
    baselines: dict[str, ProducerBaseline],
    projected: dict[str, CachedProjection],
) -> None:
    publications: dict[str, object] = {}
    for module_id, baseline in baselines.items():
        files = [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(expected).hexdigest(),
            }
            for path, expected in baseline.native_files
        ]
        files.append(
            {
                "path": baseline.manifest_path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(baseline.manifest_bytes).hexdigest(),
            }
        )
        cached = projected[module_id].cached.stored
        publications[module_id] = {
            "publication": publication_record_to_dict(baseline.publication),
            "cache_key": cached.cache_key,
            "snapshot_digest": cached.snapshot_digest,
            "files": files,
        }

    csv_path = root / "issue45-ela-planning.csv"
    document = {
        "schema_version": "1",
        "workspace": "workspace",
        "signal_set_id": SIGNAL_SET_ID,
        "csv_path": csv_path.relative_to(root).as_posix(),
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "publications": publications,
    }
    target = root / "issue45-reload-baseline.json"
    target.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _assert_producer_immutability(baselines: dict[str, ProducerBaseline]) -> None:
    for module_id, baseline in baselines.items():
        for path, expected in baseline.native_files:
            _require(
                path.read_bytes() == expected,
                f"{module_id} native source bytes changed during Meridian projection.",
            )
        _require(
            baseline.manifest_path.read_bytes() == baseline.manifest_bytes,
            f"{module_id} immutable manifest bytes changed during Meridian projection.",
        )


def main() -> None:
    _verify_installed_composition()
    root = Path(".").resolve()
    workspace = root / "workspace"
    library = _seed_core_context(workspace)

    baselines = {
        "scoreform": _publish_scoreform(workspace),
        "quillan": _publish_quillan(workspace),
    }
    _assert_no_concord()

    projected = _project_and_cache(workspace, baselines)
    _assert_projection_semantics(projected)
    grade_item, memberships, scale = _calculate_grade_item_proficiency(
        workspace,
        baselines,
        projected,
        library,
    )
    _calculate_academic_period_proficiency(
        workspace,
        grade_item,
        memberships,
        scale,
    )
    _derive_preview_review_and_export(workspace, scale)
    _assert_producer_immutability(baselines)
    _write_reload_baseline(root, baselines, projected)
    _assert_no_concord()

    _require(
        not any(name.split(".", 1)[0] == "concord" for name in sys.modules),
        "Concord appeared in sys.modules after installed projection.",
    )
    print(
        "Issue #45 installed ScoreForm/Quillan proficiency and Core signal "
        "export acceptance passed without Concord."
    )


if __name__ == "__main__":
    main()
