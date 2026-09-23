"""Issue #51 installed standards-based Grade acceptance.

Build one self-contained persisted Core/Meridian proficiency basis with exact
ScoreForm/Quillan work provenance, then calculate, persist, select, reload, and
reproduce one standards-based Grade without importing sibling source packages.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib import metadata
from pathlib import Path

import pds_core
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    register_academic_work,
)
from pds_core.routes import class_metadata_path, module_work_dir
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef
from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    write_workspace_standards_library,
)

import meridian
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
from meridian.academic_period_proficiency_storage import (
    select_academic_period_proficiency_policy_revision,
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_policy_revision,
    write_academic_period_proficiency_result_revision,
)
from meridian.evidence_eligibility import EvidenceSourceReference
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
    GradePolicyActor,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    ProficiencyGradeConversion,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
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
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    NativeValueMappingProfileReference,
    ProficiencyLevel,
    ProficiencyScale,
)
from meridian.proficiency_mapping_storage import (
    StoredProficiencyScale,
    select_proficiency_scale_revision,
    write_proficiency_scale_revision,
)
from meridian.standards_evidence import (
    STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
    STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
    AggregationDecisionReference,
    GradeItemAggregationBasis,
    StandardAggregationInputEntry,
    StandardAggregationInputs,
    StandardEvidenceAssociationReference,
)
from meridian.standards_grade import calculate_standards_grade
from meridian.standards_grade_assembly import assemble_standards_grade_calculation
from meridian.standards_grade_result import (
    assess_standards_grade_result_freshness,
    create_standards_grade_result_snapshot,
    standards_grade_result_snapshot_from_json_bytes,
    standards_grade_result_snapshot_to_json_bytes,
)
from meridian.standards_grade_storage import (
    get_current_standards_grade_result_revision,
    load_current_standards_grade_result,
    select_standards_grade_result_revision,
    write_standards_grade_result_revision,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    StandardProficiencyActor,
    StandardProficiencyCalculationPolicy,
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
)
from meridian.standards_proficiency_storage import (
    StoredStandardProficiencyCalculationPolicy,
    select_standard_proficiency_policy_revision,
    select_standard_proficiency_result_revision,
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "issue51_installed_class"
STUDENT_ID = "issue51_student_001"
STANDARD_ID = "issue51_standard_ela"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "q1"
CALENDAR_REVISION = 1
ACTOR_ID = "teacher_local"
SCALE_ID = "issue51_installed_scale"
STANDARD_POLICY_ID = "issue51_grade_item_proficiency"
PERIOD_POLICY_ID = "issue51_period_proficiency"
GRADE_POLICY_ID = "issue51_standards_grade"
NOW = datetime(2026, 9, 13, 23, 0, tzinfo=UTC)
PERIOD = AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID)
TARGET = AcademicPeriodProficiencyTarget(PERIOD, CALENDAR_REVISION)
BASELINE_NAME = "issue51-standards-grade-baseline.json"
SCOREFORM_WORK = ModuleWorkRef("scoreform", CLASS_ID, "issue51_scoreform_work")
QUILLAN_WORK = ModuleWorkRef("quillan", CLASS_ID, "issue51_quillan_work")
CONVERSIONS = {
    "beginning": Decimal("60"),
    "developing": Decimal("75"),
    "proficient": Decimal("90"),
    "advanced": Decimal("100"),
}


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


def _verify_installed_composition() -> None:
    _require(metadata.version("pds-core") == "0.6.3", "Core version mismatch.")
    _require(metadata.version("scoreform") == "0.11.0", "ScoreForm version mismatch.")
    _require(metadata.version("quillan") == "0.10.1", "Quillan version mismatch.")
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
        "meridian.standards_grade",
        "meridian.standards_grade_assembly",
        "meridian.standards_grade_result",
        "meridian.standards_grade_storage",
    ):
        _installed_origin(module_name)
    try:
        metadata.version("pds-concord")
    except metadata.PackageNotFoundError:
        pass
    else:
        raise AcceptanceFailure("pds-concord must be absent from issue #51 smoke.")
    _require(
        importlib.util.find_spec("concord") is None,
        "concord package must not be importable in issue #51 smoke.",
    )


def _seed_core(workspace: Path) -> AcademicPeriodCalendar:
    workspace.mkdir(parents=True)
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
    calendar = AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=SCHOOL_YEAR,
        calendar_revision=CALENDAR_REVISION,
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
    )
    write_academic_period_calendar(
        workspace,
        calendar,
        expected_current_revision=None,
    )
    write_workspace_standards_library(
        workspace,
        StandardsLibrary(
            standards=(
                StandardDefinition(
                    standard_id=STANDARD_ID,
                    code="ELA.ISSUE51.1",
                    source="issue51_installed",
                    short_name="Issue 51 installed standard",
                    description="Synthetic durable Standard for installed acceptance.",
                    subject="ELA",
                    grade_band="9-12",
                    active=True,
                    available_modules=("scoreform", "quillan", "meridian"),
                ),
            ),
            profiles=(),
        ),
    )
    _register_work(
        workspace,
        SCOREFORM_WORK,
        contract_version="scoreform_academic_work_v1",
        source_contract=None,
    )
    _register_work(
        workspace,
        QUILLAN_WORK,
        contract_version="quillan_academic_work_v1",
        source_contract="2",
    )
    return calendar


def _register_work(
    workspace: Path,
    work: ModuleWorkRef,
    *,
    contract_version: str,
    source_contract: str | None,
) -> None:
    directory = module_work_dir(workspace, work)
    directory.mkdir(parents=True, exist_ok=True)
    result = register_academic_work(
        workspace,
        AcademicWorkRegistrationRequest(
            work=work,
            producer_contract_version=contract_version,
            title=f"Issue 51 {work.module_id} work",
            work_kind="assignment",
            academic_intent="formative",
            lifecycle="active",
            source_records=(
                ModuleRecordRef(
                    work.module_id,
                    "assignment",
                    work.work_id,
                    source_contract,
                ),
            ),
        ),
    )
    _require(
        result.registration.registration_revision == 1,
        f"{work.module_id} registration revision mismatch.",
    )
    (directory / "issue51-native-source.json").write_text(
        json.dumps(
            {
                "module_id": work.module_id,
                "work_id": work.work_id,
                "source": "producer-owned installed acceptance sentinel",
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _persist_scale(workspace: Path) -> StoredProficiencyScale:
    scale = ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id=SCALE_ID,
        scale_revision=1,
        supersedes_revision=None,
        title="Issue 51 installed proficiency",
        description="Synthetic criterion-referenced installed smoke scale.",
        levels=(
            ProficiencyLevel("beginning", 1, "Beginning", "Initial evidence."),
            ProficiencyLevel("developing", 2, "Developing", "Partial evidence."),
            ProficiencyLevel("proficient", 3, "Proficient", "Meets criterion."),
            ProficiencyLevel("advanced", 4, "Advanced", "Extends criterion."),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", ACTOR_ID),
        rationale="Issue #51 installed acceptance scale.",
        revised_at=NOW,
    )
    stored = write_proficiency_scale_revision(workspace, scale).stored
    selected = select_proficiency_scale_revision(
        workspace,
        CLASS_ID,
        SCALE_ID,
        1,
        expected_current_scale_revision=None,
    )
    _require(selected.stored.reference == stored.reference, "Scale selection failed.")
    return stored


def _persist_standard_policy(
    workspace: Path,
    scale: StoredProficiencyScale,
) -> StoredStandardProficiencyCalculationPolicy:
    policy = StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=STANDARD_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 51 Grade Item proficiency",
        target_scale=scale.reference,
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=(),
        native_state_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", ACTOR_ID),
        rationale="Issue #51 installed acceptance Grade Item proficiency.",
        revised_at=NOW,
    )
    stored = write_standard_proficiency_policy_revision(workspace, policy).stored
    selected = select_standard_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        STANDARD_POLICY_ID,
        1,
        expected_current_policy_revision=None,
    )
    _require(
        selected.stored.reference == stored.reference,
        "Standard proficiency policy selection failed.",
    )
    return stored


def _persist_grade_item_result(
    workspace: Path,
    work: ModuleWorkRef,
    level_id: str,
    scale: StoredProficiencyScale,
    policy: StoredStandardProficiencyCalculationPolicy,
) -> ResolvedAcademicPeriodProficiencyCandidate:
    grade_item_id = f"issue51_{work.module_id}_grade_item"
    item = GradeItemRevision(
        schema_version=GRADE_ITEM_SCHEMA_VERSION,
        record_type=GRADE_ITEM_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=grade_item_id,
        grade_item_revision=1,
        supersedes_revision=None,
        title=f"Issue 51 {work.module_id} proficiency",
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
        grade_item_id,
        1,
        expected_current_revision=None,
    )

    membership = GradeItemMembershipDecision(
        schema_version=GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
        record_type=GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=grade_item_id,
        grade_item_revision=1,
        grade_item_revision_sha256=stored_item.revision_sha256,
        work_reference=GradeItemWorkReference(
            work=work,
            registration_revision=1,
        ),
        membership_revision=1,
        supersedes_revision=None,
        decision="included",
        academic_period=GradeItemAcademicPeriodAssignment(
            period=PERIOD,
            calendar_revision=CALENDAR_REVISION,
        ),
        actor_id=ACTOR_ID,
        rationale="Issue #51 installed exact Academic Period membership.",
        decided_at=NOW,
    )
    stored_membership = write_grade_item_membership_revision(
        workspace,
        membership,
    ).stored
    select_grade_item_membership_revision(
        workspace,
        CLASS_ID,
        grade_item_id,
        work,
        1,
        expected_current_membership_revision=None,
    )

    basis = GradeItemAggregationBasis(
        CLASS_ID,
        grade_item_id,
        1,
        stored_item.revision_sha256,
    )
    source = EvidenceSourceReference(
        work,
        "pub_" + ("1" if work.module_id == "scoreform" else "2") * 32,
        "a" * 64,
        "b" * 64,
        f"{work.module_id}_issue51_item",
    )
    entry = StandardAggregationInputEntry(
        source=source,
        result_kind=(
            "question_correctness"
            if work.module_id == "scoreform"
            else "overall_standard_rating"
        ),
        target_kind=(
            "question" if work.module_id == "scoreform" else "standard"
        ),
        status="performance",
        exclusion_reason=None,
        membership_reference=AggregationDecisionReference(
            "membership",
            1,
            stored_membership.decision_sha256,
        ),
        eligibility_reference=AggregationDecisionReference(
            "eligibility",
            1,
            "c" * 64,
        ),
        attempt_selection_reference=None,
        reassessment_reference=None,
        association_reference=StandardEvidenceAssociationReference(
            CLASS_ID,
            grade_item_id,
            source,
            STANDARD_ID,
            1,
            "d" * 64,
        ),
        mapping_profile_reference=NativeValueMappingProfileReference(
            CLASS_ID,
            SCALE_ID,
            f"issue51_{work.module_id}_mapping",
            1,
            "e" * 64,
        ),
        mapping_status="mapped",
        proficiency_level_id=level_id,
        native_state=None,
    )
    inputs = StandardAggregationInputs(
        schema_version=STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        record_type=STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item=basis,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=scale.reference,
        entries=(entry,),
    )
    outcome = calculate_standard_proficiency(inputs, policy.policy, scale.scale)
    _require(
        outcome.status == "calculated",
        "Grade Item proficiency did not calculate.",
    )
    _require(
        outcome.proficiency_level_id == level_id,
        "Grade Item proficiency level changed unexpectedly.",
    )
    snapshot = create_standard_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    stored_result = write_standard_proficiency_result_revision(
        workspace,
        snapshot,
    ).stored
    select_standard_proficiency_result_revision(
        workspace,
        CLASS_ID,
        grade_item_id,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    membership_basis = academic_period_proficiency_membership_basis_from_decision(
        membership,
        stored_membership.decision_sha256,
    )
    return ResolvedAcademicPeriodProficiencyCandidate(
        grade_item=basis,
        memberships=(membership_basis,),
        result=stored_result.snapshot,
    )


def _persist_period_result(
    workspace: Path,
    calendar: AcademicPeriodCalendar,
    scale: StoredProficiencyScale,
    candidates: tuple[ResolvedAcademicPeriodProficiencyCandidate, ...],
) -> None:
    policy = AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=PERIOD_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 51 Academic Period proficiency",
        target_scale=scale.reference,
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="blocking",
        insufficient_result_handling="blocking",
        actor=StandardProficiencyActor("teacher", ACTOR_ID),
        rationale="Issue #51 installed Academic Period proficiency.",
        revised_at=NOW,
    )
    stored_policy = write_academic_period_proficiency_policy_revision(
        workspace,
        policy,
    ).stored
    select_academic_period_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        PERIOD_POLICY_ID,
        1,
        expected_current_policy_revision=None,
    )
    inputs = build_academic_period_proficiency_aggregation_inputs(
        target_period=TARGET,
        calendar=calendar,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=scale.reference,
        period_membership_scope="direct",
        candidates=candidates,
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        stored_policy.policy,
        scale.scale,
    )
    _require(outcome.status == "calculated", "Academic Period proficiency failed.")
    _require(
        outcome.proficiency_level_id == "advanced",
        "Expected highest Academic Period proficiency to be advanced.",
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
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
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


def _install_grade_policy(workspace: Path, scale: StoredProficiencyScale) -> None:
    policy = GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=GRADE_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 51 installed standards Grade",
        calculation_family="standards_based",
        configuration=StandardsBasedGradeConfiguration(
            target_scale=scale.reference,
            standards=(StandardGradeParticipation(STANDARD_ID, Decimal("1")),),
            conversions=tuple(
                ProficiencyGradeConversion(level_id, grade_value)
                for level_id, grade_value in CONVERSIONS.items()
            ),
            aggregation_strategy="weighted_mean",
            minimum_calculated_results=1,
        ),
        state_treatment=_state_treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Issue #51 installed standards Grade acceptance.",
        revised_at=NOW,
    )
    stored = write_grade_policy_revision(workspace, policy).stored
    activation = GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=CALENDAR_REVISION,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=stored.reference,
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Activate exact issue #51 installed standards Grade policy.",
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


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest_map(base: Path, workspace: Path) -> dict[str, str]:
    if not base.exists():
        return {}
    return {
        path.relative_to(workspace).as_posix(): _file_digest(path)
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _upstream_snapshot(workspace: Path) -> dict[str, dict[str, str]]:
    class_root = workspace / "classes" / CLASS_ID / "modules"
    meridian_root = class_root / "meridian"
    return {
        "scoreform": _tree_digest_map(class_root / "scoreform", workspace),
        "quillan": _tree_digest_map(class_root / "quillan", workspace),
        "proficiency_scales": _tree_digest_map(
            meridian_root / "proficiency_scales",
            workspace,
        ),
        "grade_items": _tree_digest_map(meridian_root / "grade_items", workspace),
        "standards_proficiency": _tree_digest_map(
            meridian_root / "standards_proficiency",
            workspace,
        ),
        "academic_period_proficiency": _tree_digest_map(
            meridian_root / "academic_period_proficiency",
            workspace,
        ),
    }


def _calculate_and_persist_grade(workspace: Path) -> dict[str, object]:
    assembly = assemble_standards_grade_calculation(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    _require(assembly.outcome.status == "calculated", "Standards Grade blocked.")
    _require(
        assembly.outcome.rounded_grade == Decimal("100.00"),
        "Installed standards Grade value mismatch.",
    )
    repeated = assemble_standards_grade_calculation(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    _require(repeated.inputs == assembly.inputs, "Assembly is not deterministic.")
    _require(repeated.outcome == assembly.outcome, "Outcome is not deterministic.")

    snapshot = create_standards_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    written = write_standards_grade_result_revision(workspace, snapshot)
    _require(written.disposition == "created", "Standards Grade write failed.")
    _require(
        get_current_standards_grade_result_revision(
            workspace,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            CALENDAR_REVISION,
        )
        is None,
        "Writing a standards Grade result must not select it.",
    )
    selected = select_standards_grade_result_revision(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
        1,
        expected_current_result_revision=None,
    )
    _require(
        selected.stored.reference == written.stored.reference,
        "Standards Grade selection reference mismatch.",
    )
    current = load_current_standards_grade_result(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    _require(current is not None, "Selected standards Grade result is missing.")
    assert current is not None
    _require(
        current.reference == written.stored.reference,
        "Reloaded standards Grade reference mismatch.",
    )
    _require(
        calculate_standards_grade(current.snapshot.inputs) == current.snapshot.outcome,
        "Stored standards Grade does not reproduce from embedded inputs.",
    )
    encoded = standards_grade_result_snapshot_to_json_bytes(current.snapshot)
    _require(
        standards_grade_result_snapshot_from_json_bytes(encoded) == current.snapshot,
        "Standards Grade canonical JSON round-trip failed.",
    )
    refreshed = assemble_standards_grade_calculation(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    freshness = assess_standards_grade_result_freshness(
        current.snapshot,
        refreshed.inputs,
    )
    _require(freshness.status == "current", "Standards Grade result is stale.")
    _require(freshness.reasons == (), "Current standards Grade has stale reasons.")
    return {
        "result_revision": current.snapshot.result_revision,
        "result_sha256": current.result_sha256,
        "calculation_fingerprint": current.snapshot.calculation_fingerprint,
        "rounded_grade": str(current.snapshot.outcome.rounded_grade),
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_program_standards_grade.py <workspace>")
    _verify_installed_composition()
    workspace = Path(sys.argv[1]).resolve()
    calendar = _seed_core(workspace)
    scale = _persist_scale(workspace)
    standard_policy = _persist_standard_policy(workspace, scale)
    scoreform = _persist_grade_item_result(
        workspace,
        SCOREFORM_WORK,
        "proficient",
        scale,
        standard_policy,
    )
    quillan = _persist_grade_item_result(
        workspace,
        QUILLAN_WORK,
        "advanced",
        scale,
        standard_policy,
    )
    _persist_period_result(
        workspace,
        calendar,
        scale,
        (scoreform, quillan),
    )
    upstream_before = _upstream_snapshot(workspace)
    _install_grade_policy(workspace, scale)
    result = _calculate_and_persist_grade(workspace)
    upstream_after = _upstream_snapshot(workspace)
    _require(
        upstream_after == upstream_before,
        "Standards Grade layer mutated producer or v0.2 proficiency source state.",
    )
    baseline = {
        **result,
        "upstream": upstream_before,
    }
    (workspace / BASELINE_NAME).write_text(
        json.dumps(baseline, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("Issue #51 installed standards Grade acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
