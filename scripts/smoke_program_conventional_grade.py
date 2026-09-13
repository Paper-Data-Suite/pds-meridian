"""Issue #50 installed ScoreForm conventional-Grade acceptance.

The program publishes real ScoreForm v0.11.0 producer state through Core,
projects it through installed Meridian, authors exact #28-#31 teacher state,
activates one conventional Grade policy, persists/selects/reloads the result,
and proves producer-owned bytes remain unchanged.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib import metadata
from pathlib import Path
from typing import cast

import pds_core
from pds_core.academic_catalog import PublicationCatalogQuery, rebuild_academic_catalog
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.publication_compatibility import PublicationProducerRegistry
from pds_core.rosters import create_roster, write_roster
from pds_core.routes import class_metadata_path, class_roster_path
from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    StandardsProfile,
    write_workspace_standards_library,
)
from scoreform.academic_result_manifest_generation import (
    generate_academic_result_manifest,
)
from scoreform.academic_result_publication import publish_scoreform_academic_results
from scoreform.academic_work_registration import register_scoreform_academic_work
from scoreform.assignment import validate_assignment_data
from scoreform.layouts import DEFAULT_LAYOUT_ID, require_layout
from scoreform.page_scoring import ScoredAnswer
from scoreform.pds_publication import get_publication_producer_profile
from scoreform.results import ScoreFormRoutedResult, export_scoreform_result_models
from scoreform.work_paths import initialize_scoreform_work_layout
from scoreform.workflows import write_assignment_json

import meridian
import meridian.attempt_selection_storage as attempt_storage
import meridian.evidence_eligibility_storage as eligibility_storage
import meridian.ingestion as ingestion
import meridian.reassessment_storage as reassessment_storage
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
from meridian.conventional_grade import (
    calculate_conventional_grade,
    create_conventional_grade_result_snapshot,
)
from meridian.conventional_grade_assembly import (
    ConventionalGradeWorkEvidenceSpec,
    assemble_conventional_grade_calculation,
)
from meridian.conventional_grade_storage import (
    StoredConventionalGradeResult,
    load_current_conventional_grade_result,
    select_conventional_grade_result_revision,
    write_conventional_grade_result_revision,
)
from meridian.evidence import EvidenceInventory, EvidenceItem
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
from meridian.grade_item_storage import (
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import (
    GRADE_ITEM_RECORD_TYPE,
    GRADE_ITEM_SCHEMA_VERSION,
    GradeItemRevision,
    GradeItemWorkReference,
)
from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
)
from meridian.grade_policy_activation import (
    GRADE_POLICY_ACTIVATION_RECORD_TYPE,
    GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
    GradePolicyActivationDecision,
)
from meridian.grade_policy_activation_storage import (
    select_grade_policy_activation_revision,
    write_grade_policy_activation_revision,
)
from meridian.grade_policy_storage import write_grade_policy_revision
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    ProjectionCacheWriteResult,
    cache_projected_inventory,
    load_authorized_projection_snapshot,
)
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

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "student_synthetic_001"
ASSIGNMENT_ID = "issue50_scoreform"
STANDARD_ID = "standard_issue50_1"
PROFILE_ID = "issue50_profile"
GRADE_ITEM_ID = "issue50_conventional_grade"
GRADE_POLICY_ID = "issue50_total_points"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "period_q1"
ACTOR_ID = "teacher_local"
ELIGIBILITY_POLICY_ID = "issue50_explicit_eligibility"
ATTEMPT_POLICY_ID = "issue50_explicit_attempts"
REASSESSMENT_POLICY_ID = "issue50_explicit_reassessment"
NOW = datetime(2026, 9, 10, 23, 0, tzinfo=UTC)
PERIOD = AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID)
BASELINE_NAME = "issue50-conventional-grade-baseline.json"


class AcceptanceFailure(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _installed_origin(module_name: str) -> None:
    module = importlib.import_module(module_name)
    raw = getattr(module, "__file__", None)
    _require(isinstance(raw, str) and bool(raw), f"{module_name} has no origin.")
    assert isinstance(raw, str)
    origin = Path(raw).resolve()
    prefix = Path(sys.prefix).resolve()
    _require(origin.is_relative_to(prefix), f"{module_name} is outside the venv.")
    _require(
        "site-packages" in {part.lower() for part in origin.parts},
        f"{module_name} is not installed from site-packages.",
    )


def _assert_absent_producers() -> None:
    for distribution_name, package_name in (
        ("quillan", "quillan"),
        ("pds-concord", "concord"),
    ):
        try:
            metadata.version(distribution_name)
        except metadata.PackageNotFoundError:
            pass
        else:
            raise AcceptanceFailure(f"{distribution_name} must be absent.")
        _require(
            importlib.util.find_spec(package_name) is None,
            f"{package_name} package must not be importable.",
        )
        _require(
            not any(name.split(".", 1)[0] == package_name for name in sys.modules),
            f"{package_name} must never be imported.",
        )


def _verify_installed_composition() -> None:
    _require(metadata.version("pds-core") == "0.6.3", "Core version mismatch.")
    _require(metadata.version("scoreform") == "0.11.0", "ScoreForm version mismatch.")
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
        "meridian",
        "meridian.scoreform_adapter",
        "meridian.conventional_grade",
        "meridian.conventional_grade_assembly",
        "meridian.conventional_grade_storage",
    ):
        _installed_origin(module_name)
    _assert_absent_producers()


def _seed_core_context(workspace: Path) -> None:
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
                    "first_name": "Student",
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
    write_workspace_standards_library(
        workspace,
        StandardsLibrary(
            standards=(
                StandardDefinition(
                    standard_id=STANDARD_ID,
                    code="ELA.ISSUE50.1",
                    source="issue50_synthetic",
                    short_name="Synthetic issue 50 standard",
                    description=(
                        "Synthetic Standard used only to make ScoreForm "
                        "publication realistic."
                    ),
                    subject="ELA",
                    grade_band="9-12",
                    active=True,
                    available_modules=("scoreform", "meridian"),
                ),
            ),
            profiles=(
                StandardsProfile(
                    profile_id=PROFILE_ID,
                    standards=(STANDARD_ID,),
                ),
            ),
        ),
    )


def _assignment() -> dict[str, object]:
    layout = require_layout(DEFAULT_LAYOUT_ID)
    candidate: dict[str, object] = {
        "assignment_id": ASSIGNMENT_ID,
        "title": "Issue 50 ScoreForm conventional Grade",
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


def _result(attempt_number: int) -> ScoreFormRoutedResult:
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
        assignment_id=ASSIGNMENT_ID,
        student_id=STUDENT_ID,
        last_name="Synthetic",
        first_name="Student",
        period="1",
        page_display="manual",
        score=sum(answer.correct for answer in answers),
        total_points=3,
        answers=answers,
        source_file="plain_paper_manual_entry",
    )


@dataclass(frozen=True, slots=True)
class ProducerBaseline:
    native_files: tuple[tuple[Path, bytes], ...]
    manifest_path: Path
    manifest_bytes: bytes
    publication_id: str


@dataclass(frozen=True, slots=True)
class CachedProjection:
    prepared: ingestion.PreparedPublicationInvocation
    inventory: EvidenceInventory
    cached: ProjectionCacheWriteResult


def _publish(workspace: Path) -> ProducerBaseline:
    paths = initialize_scoreform_work_layout(workspace, CLASS_ID, ASSIGNMENT_ID)
    _require(
        write_assignment_json(  # type: ignore[no-untyped-call]
            paths.assignment_path, _assignment()
        ),
        "ScoreForm assignment write failed.",
    )
    for attempt_number in (1, 2):
        exported = export_scoreform_result_models(
            (_result(attempt_number),),
            workspace_root=workspace,
        )
        _require(
            exported.succeeded and len(exported.appended_attempts) == 1,
            f"ScoreForm attempt {attempt_number} was not appended exactly once.",
        )
    native_files = (
        (paths.assignment_path, paths.assignment_path.read_bytes()),
        (paths.results_path, paths.results_path.read_bytes()),
    )
    registration = register_scoreform_academic_work(
        workspace,
        CLASS_ID,
        ASSIGNMENT_ID,
        academic_intent="summative",
        lifecycle="active",
    )
    _require(
        registration.registration.registration_revision == 1,
        "ScoreForm registration revision mismatch.",
    )
    generated = generate_academic_result_manifest(workspace, CLASS_ID, ASSIGNMENT_ID)
    published = publish_scoreform_academic_results(
        workspace,
        CLASS_ID,
        ASSIGNMENT_ID,
        manifest_revision=generated.revision,
    )
    return ProducerBaseline(
        native_files=native_files,
        manifest_path=generated.path,
        manifest_bytes=generated.content,
        publication_id=published.publication.publication_id,
    )


class AllowProjection:
    def authorize(
        self,
        request: ingestion.PublicationAuthorizationRequest,
    ) -> ingestion.PublicationAuthorizationDecision:
        return ingestion.PublicationAuthorizationDecision(
            True,
            "issue50_installed_acceptance",
            "1",
            (),
        )


def _project(workspace: Path, baseline: ProducerBaseline) -> CachedProjection:
    rebuild_academic_catalog(workspace)
    producer_registry = PublicationProducerRegistry(
        (get_publication_producer_profile(),)
    )
    adapter_registry = AdapterRegistry((ScoreFormAcademicResultAdapter(),))
    discovered = ingestion.discover_publication_candidates(
        workspace,
        ingestion.PublicationDiscoveryRequest(
            PublicationCatalogQuery(module_id="scoreform", state="current", limit=10)
        ),
    )
    _require(len(discovered.candidates) == 1, "ScoreForm discovery was not singular.")
    candidate = discovered.candidates[0]
    _require(
        candidate.publication_id == baseline.publication_id,
        "Publication identity changed.",
    )
    prepared = ingestion.prepare_publication_invocation(
        workspace,
        candidate,
        producer_registry=producer_registry,
        adapter_registry=adapter_registry,
        authorizer=AllowProjection(),
        authorization_purpose_id="grading_import",
        requested_student_ids=(STUDENT_ID,),
        distribution_version_resolver=installed_distribution_version,
    )
    inventory = adapter_registry.invoke(
        prepared.projection_request, installed_distribution_version
    )
    cached = cache_projected_inventory(
        workspace,
        prepared,
        inventory,
        authorizer=AllowProjection(),
    )
    return CachedProjection(prepared, inventory, cached)


def _authorized(
    workspace: Path,
    projected: CachedProjection,
) -> AuthorizedProjectionSnapshot:
    stored = projected.cached.stored
    return load_authorized_projection_snapshot(
        workspace,
        stored.snapshot.source.publication.publication_id,
        stored.cache_key,
        authorizer=AllowProjection(),
        authorization_purpose_id="grading_import",
        requested_student_ids=(STUDENT_ID,),
        producer_registry=PublicationProducerRegistry(
            (get_publication_producer_profile(),)
        ),
        adapter_registry=AdapterRegistry((ScoreFormAcademicResultAdapter(),)),
        distribution_version_resolver=installed_distribution_version,
    )


def _source(projected: CachedProjection, item: EvidenceItem) -> EvidenceSourceReference:
    stored = projected.cached.stored
    return EvidenceSourceReference(
        work=item.provenance.work,
        publication_id=item.provenance.publication_id,
        cache_key=stored.cache_key,
        snapshot_digest=stored.snapshot_digest,
        item_id=item.item_id,
    )


def _state_treatment() -> GradeStateTreatment:
    return GradeStateTreatment(
        missing="blocking",
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="blocking",
        unavailable="blocking",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="blocking",
    )


def _configure(
    workspace: Path,
    projected: CachedProjection,
    authorized: AuthorizedProjectionSnapshot,
) -> tuple[ConventionalGradeWorkEvidenceSpec, ...]:
    publication_work = projected.cached.stored.snapshot.source.publication.work
    item = GradeItemRevision(
        schema_version=GRADE_ITEM_SCHEMA_VERSION,
        record_type=GRADE_ITEM_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=1,
        supersedes_revision=None,
        title="Installed conventional Grade",
        purpose="conventional_grade",
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
        1,
        expected_current_revision=None,
    )
    membership = GradeItemMembershipDecision(
        schema_version=GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
        record_type=GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=1,
        grade_item_revision_sha256=stored_item.revision_sha256,
        work_reference=GradeItemWorkReference(publication_work, 1),
        membership_revision=1,
        supersedes_revision=None,
        decision="included",
        academic_period=GradeItemAcademicPeriodAssignment(PERIOD, 1),
        actor_id=ACTOR_ID,
        rationale="Explicit installed ScoreForm membership.",
        decided_at=NOW,
    )
    stored_membership = write_grade_item_membership_revision(
        workspace,
        membership,
    ).stored
    select_grade_item_membership_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        publication_work,
        1,
        expected_current_membership_revision=None,
    )

    for evidence_item in projected.inventory.items:
        if (
            evidence_item.subject is None
            or evidence_item.subject.student_id != STUDENT_ID
        ):
            continue
        source = _source(projected, evidence_item)
        decision = EvidenceEligibilityDecision(
            schema_version=EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
            record_type=EVIDENCE_ELIGIBILITY_RECORD_TYPE,
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            source=source,
            membership_revision=1,
            membership_revision_sha256=stored_membership.decision_sha256,
            eligibility_revision=1,
            supersedes_revision=None,
            disposition="included",
            actor=EvidenceDecisionActor("teacher", ACTOR_ID),
            policy=EvidenceEligibilityPolicyReference(ELIGIBILITY_POLICY_ID, "1"),
            reason_codes=(),
            rationale="Explicit installed inclusion.",
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
            1,
            authorized_snapshot=authorized,
            expected_current_eligibility_revision=None,
        )

    derivation = attempt_storage.derive_attempt_candidates(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        authorized,
    )
    _require(len(derivation.candidates) == 2, "Expected two ScoreForm attempts.")
    attempt_policy = AttemptSelectionPolicy(
        schema_version=ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=publication_work,
        policy_id=ATTEMPT_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        selection_basis="explicit",
        minimum_selected=2,
        maximum_selected=2,
        actor=AttemptSelectionActor("teacher", ACTOR_ID),
        rationale="Explicitly retain both attempts before reassessment.",
        revised_at=NOW,
    )
    stored_attempt_policy = attempt_storage.write_attempt_selection_policy_revision(
        workspace,
        attempt_policy,
    ).stored
    attempt_storage.select_attempt_selection_policy_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        publication_work,
        ATTEMPT_POLICY_ID,
        1,
        expected_current_policy_revision=None,
    )
    selection = AttemptSelectionDecision(
        schema_version=ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=publication_work,
        student_id=STUDENT_ID,
        membership_revision=1,
        membership_revision_sha256=stored_membership.decision_sha256,
        policy=AttemptSelectionPolicyReference(
            ATTEMPT_POLICY_ID,
            1,
            stored_attempt_policy.policy_sha256,
        ),
        source_snapshot=derivation.source_snapshot,
        candidates=derivation.candidates,
        selected_attempts=tuple(value.attempt for value in derivation.candidates),
        decision_revision=1,
        supersedes_revision=None,
        actor=AttemptSelectionActor("teacher", ACTOR_ID),
        rationale="Both attempts selected explicitly.",
        decided_at=NOW,
    )
    stored_selection = attempt_storage.write_attempt_selection_decision_revision(
        workspace,
        selection,
        authorized_snapshot=authorized,
    ).stored
    attempt_storage.select_attempt_selection_decision_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        publication_work,
        STUDENT_ID,
        1,
        authorized_snapshot=authorized,
        expected_current_decision_revision=None,
    )
    by_sequence = {
        candidate.attempt.native.sequence: candidate.attempt
        for candidate in derivation.candidates
    }
    first = by_sequence[1]
    second = by_sequence[2]
    reassessment_policy = ReassessmentPolicy(
        schema_version=REASSESSMENT_POLICY_SCHEMA_VERSION,
        record_type=REASSESSMENT_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=publication_work,
        policy_id=REASSESSMENT_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        relationship_basis="explicit",
        allowed_modes=("replace",),
        actor=ReassessmentActor("teacher", ACTOR_ID),
        rationale="Explicit installed replacement policy.",
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
        publication_work,
        REASSESSMENT_POLICY_ID,
        1,
        expected_current_policy_revision=None,
    )
    reassessment = ReassessmentDecision(
        schema_version=REASSESSMENT_DECISION_SCHEMA_VERSION,
        record_type=REASSESSMENT_DECISION_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=publication_work,
        student_id=STUDENT_ID,
        attempt_selection=AttemptSelectionDecisionReference(
            stored_selection.decision.decision_revision,
            stored_selection.decision_sha256,
        ),
        policy=ReassessmentPolicyReference(
            REASSESSMENT_POLICY_ID,
            1,
            stored_reassessment_policy.policy_sha256,
        ),
        mode="replace",
        contributing_attempts=(second,),
        replacement_relationships=(ReplacementRelationship(second, (first,)),),
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
        publication_work,
        STUDENT_ID,
        1,
        authorized_snapshot=authorized,
        expected_current_decision_revision=None,
    )

    policy = GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=GRADE_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Installed issue 50 total-points policy",
        calculation_family="conventional",
        configuration=ConventionalGradeConfiguration(
            mode="total_points",
            items=(
                GradePolicyItemParticipation(
                    grade_item=GradePolicyItemReference(
                        CLASS_ID,
                        GRADE_ITEM_ID,
                        1,
                        stored_item.revision_sha256,
                    ),
                    category_id=None,
                    weight=None,
                    possible_points=Decimal("3"),
                ),
            ),
            categories=(),
        ),
        state_treatment=_state_treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Installed issue #50 conventional Grade policy.",
        revised_at=NOW,
    )
    stored_policy = write_grade_policy_revision(workspace, policy).stored
    activation = GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=stored_policy.reference,
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Explicit installed activation.",
        decided_at=NOW,
    )
    write_grade_policy_activation_revision(workspace, activation)
    select_grade_policy_activation_revision(
        workspace,
        CLASS_ID,
        PERIOD,
        1,
        expected_current_revision=None,
    )
    return (
        ConventionalGradeWorkEvidenceSpec(
            grade_item_id=GRADE_ITEM_ID,
            work=publication_work,
            status="available",
            authorized_snapshots=(authorized,),
        ),
    )


def _assert_unchanged(baseline: ProducerBaseline) -> None:
    for path, expected in baseline.native_files:
        _require(path.read_bytes() == expected, "ScoreForm native bytes changed.")
    _require(
        baseline.manifest_path.read_bytes() == baseline.manifest_bytes,
        "ScoreForm manifest bytes changed.",
    )


def _write_baseline(
    root: Path,
    baseline: ProducerBaseline,
    stored: StoredConventionalGradeResult,
) -> None:
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
    document = {
        "schema_version": "1",
        "workspace": "workspace",
        "class_id": CLASS_ID,
        "student_id": STUDENT_ID,
        "school_year": SCHOOL_YEAR,
        "period_id": PERIOD_ID,
        "calendar_revision": 1,
        "result_revision": stored.snapshot.result_revision,
        "result_sha256": stored.result_sha256,
        "calculation_fingerprint": stored.snapshot.calculation_fingerprint,
        "rounded_grade": str(stored.snapshot.outcome.rounded_grade),
        "producer_files": files,
    }
    (root / BASELINE_NAME).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    _verify_installed_composition()
    root = Path(".").resolve()
    workspace = root / "workspace"
    _seed_core_context(workspace)
    baseline = _publish(workspace)
    projected = _project(workspace, baseline)
    authorized = _authorized(workspace, projected)
    work_evidence = _configure(workspace, projected, authorized)

    assembly = assemble_conventional_grade_calculation(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        work_evidence,
    )
    _require(assembly.outcome.status == "calculated", "Grade did not calculate.")
    _require(
        assembly.outcome.rounded_grade == Decimal("100.00"),
        "Expected 100.00 Grade.",
    )
    _require(
        assembly.inputs.items[0].earned == Decimal("3")
        and assembly.inputs.items[0].possible == Decimal("3"),
        "Explicit replacement did not leave the exact 3/3 ScoreForm attempt.",
    )
    snapshot = create_conventional_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    written = write_conventional_grade_result_revision(
        workspace,
        snapshot,
        work_evidence=work_evidence,
    )
    _require(written.disposition == "created", "Result revision was not created.")
    select_conventional_grade_result_revision(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    current = load_current_conventional_grade_result(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    )
    _require(current is not None, "Selected result did not reload.")
    assert current is not None
    _require(
        calculate_conventional_grade(current.snapshot.inputs)
        == current.snapshot.outcome,
        "Reloaded exact inputs did not reproduce the persisted outcome.",
    )
    _assert_unchanged(baseline)
    _write_baseline(root, baseline, current)
    _assert_absent_producers()
    print("Issue #50 installed ScoreForm conventional-Grade acceptance passed.")


if __name__ == "__main__":
    main()
