"""Issue #52 installed bounded-hybrid Grade acceptance."""

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

import smoke_program_conventional_grade as conventional  # type: ignore
import smoke_program_standards_grade as standards  # type: ignore
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.routing_models import ModuleWorkRef

import meridian
from meridian.academic_period_proficiency import AcademicPeriodProficiencyTarget
from meridian.conventional_grade_storage import (
    get_current_conventional_grade_result_revision,
)
from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    HybridGradeConfiguration,
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
from meridian.grade_policy_storage import (
    load_grade_policy_revision,
    write_grade_policy_revision,
)
from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.hybrid_grade_assembly import assemble_hybrid_grade_calculation
from meridian.hybrid_grade_result import (
    assess_hybrid_grade_result_freshness,
    create_hybrid_grade_result_snapshot,
    hybrid_grade_result_snapshot_from_json_bytes,
    hybrid_grade_result_snapshot_to_json_bytes,
)
from meridian.hybrid_grade_storage import (
    get_current_hybrid_grade_result_revision,
    load_current_hybrid_grade_result,
    select_hybrid_grade_result_revision,
    write_hybrid_grade_result_revision,
)
from meridian.standards_grade_storage import (
    get_current_standards_grade_result_revision,
)

CLASS_ID = conventional.CLASS_ID
STUDENT_ID = conventional.STUDENT_ID
STANDARD_ID = conventional.STANDARD_ID
SCHOOL_YEAR = conventional.SCHOOL_YEAR
PERIOD_ID = conventional.PERIOD_ID
CALENDAR_REVISION = 1
ACTOR_ID = conventional.ACTOR_ID
PERIOD = AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID)
NOW = datetime(2026, 9, 15, 18, 0, tzinfo=UTC)
SCALE_ID = "issue52_installed_scale"
STANDARD_POLICY_ID = "issue52_grade_item_proficiency"
PERIOD_POLICY_ID = "issue52_period_proficiency"
HYBRID_POLICY_ID = "issue52_hybrid_grade"
QUILLAN_WORK = ModuleWorkRef("quillan", CLASS_ID, "issue52_quillan_work")
BASELINE_NAME = "issue52-hybrid-grade-baseline.json"
CONVENTIONAL_WEIGHT = Decimal("0.6")
STANDARDS_WEIGHT = Decimal("0.4")


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
    _require(metadata.version("quillan") == "0.10.2", "Quillan version mismatch.")
    _require(
        meridian.__version__ == metadata.version("pds-meridian"),
        "Meridian module/distribution versions disagree.",
    )
    for module_name in (
        "pds_core",
        "scoreform",
        "quillan",
        "meridian",
        "meridian.conventional_grade",
        "meridian.conventional_grade_assembly",
        "meridian.standards_grade",
        "meridian.standards_grade_assembly",
        "meridian.hybrid_grade",
        "meridian.hybrid_grade_assembly",
        "meridian.hybrid_grade_result",
        "meridian.hybrid_grade_storage",
    ):
        _installed_origin(module_name)
    try:
        metadata.version("pds-concord")
    except metadata.PackageNotFoundError:
        pass
    else:
        raise AcceptanceFailure("pds-concord must be absent from issue #52 smoke.")
    _require(
        importlib.util.find_spec("concord") is None,
        "concord package must not be importable in issue #52 smoke.",
    )


def _calendar() -> AcademicPeriodCalendar:
    return AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=SCHOOL_YEAR,
        calendar_revision=CALENDAR_REVISION,
        created_at=conventional.NOW,
        updated_at=conventional.NOW,
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


def _align_standards_harness(scoreform_work: ModuleWorkRef) -> None:
    standards.CLASS_ID = CLASS_ID
    standards.STUDENT_ID = STUDENT_ID
    standards.STANDARD_ID = STANDARD_ID
    standards.SCHOOL_YEAR = SCHOOL_YEAR
    standards.PERIOD_ID = PERIOD_ID
    standards.CALENDAR_REVISION = CALENDAR_REVISION
    standards.ACTOR_ID = ACTOR_ID
    standards.SCALE_ID = SCALE_ID
    standards.STANDARD_POLICY_ID = STANDARD_POLICY_ID
    standards.PERIOD_POLICY_ID = PERIOD_POLICY_ID
    standards.NOW = NOW
    standards.PERIOD = PERIOD
    standards.TARGET = AcademicPeriodProficiencyTarget(PERIOD, CALENDAR_REVISION)
    standards.SCOREFORM_WORK = scoreform_work
    standards.QUILLAN_WORK = QUILLAN_WORK


def _persist_proficiency_basis(
    workspace: Path,
    scoreform_work: ModuleWorkRef,
) -> standards.StoredProficiencyScale:
    _align_standards_harness(scoreform_work)
    standards._register_work(
        workspace,
        QUILLAN_WORK,
        contract_version="quillan_academic_work_v1",
        source_contract="2",
    )
    scale = standards._persist_scale(workspace)
    standard_policy = standards._persist_standard_policy(workspace, scale)
    scoreform = standards._persist_grade_item_result(
        workspace,
        scoreform_work,
        "proficient",
        scale,
        standard_policy,
    )
    quillan = standards._persist_grade_item_result(
        workspace,
        QUILLAN_WORK,
        "advanced",
        scale,
        standard_policy,
    )
    standards._persist_period_result(
        workspace,
        _calendar(),
        scale,
        (scoreform, quillan),
    )
    return scale


def _install_hybrid_policy(
    workspace: Path,
    scale: standards.StoredProficiencyScale,
) -> None:
    stored_conventional = load_grade_policy_revision(
        workspace,
        CLASS_ID,
        conventional.GRADE_POLICY_ID,
        1,
    )
    conventional_configuration = stored_conventional.policy.configuration
    _require(
        isinstance(conventional_configuration, ConventionalGradeConfiguration),
        "Historical conventional policy does not carry conventional configuration.",
    )
    assert isinstance(conventional_configuration, ConventionalGradeConfiguration)
    standards_configuration = StandardsBasedGradeConfiguration(
        target_scale=scale.reference,
        standards=(StandardGradeParticipation(STANDARD_ID, Decimal("1")),),
        conversions=tuple(
            ProficiencyGradeConversion(level_id, grade_value)
            for level_id, grade_value in standards.CONVERSIONS.items()
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=1,
    )
    policy = GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=HYBRID_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 52 installed bounded hybrid Grade",
        calculation_family="hybrid",
        configuration=HybridGradeConfiguration(
            conventional=conventional_configuration,
            standards_based=standards_configuration,
            conventional_weight=CONVENTIONAL_WEIGHT,
            standards_weight=STANDARDS_WEIGHT,
        ),
        state_treatment=conventional._state_treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Issue #52 installed bounded hybrid Grade acceptance.",
        revised_at=NOW,
    )
    stored = write_grade_policy_revision(workspace, policy).stored
    activation = GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=CALENDAR_REVISION,
        activation_revision=2,
        supersedes_revision=1,
        decision="activate",
        policy_reference=stored.reference,
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale=(
            "Replace historical conventional activation with exact hybrid policy."
        ),
        decided_at=NOW,
    )
    write_grade_policy_activation_revision(workspace, activation)
    select_grade_policy_activation_revision(
        workspace,
        CLASS_ID,
        PERIOD,
        2,
        expected_current_revision=1,
    )


def _tree_digest_map(base: Path, workspace: Path) -> dict[str, str]:
    if not base.exists():
        return {}
    return {
        path.relative_to(workspace).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _upstream_snapshot(workspace: Path) -> dict[str, dict[str, str]]:
    class_modules = workspace / "classes" / CLASS_ID / "modules"
    meridian_root = class_modules / "meridian"
    meridian_files = {
        path.relative_to(workspace).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(meridian_root.rglob("*"))
        if path.is_file()
        and path.relative_to(meridian_root).parts[0] != "hybrid_grades"
    }
    return {
        "scoreform": _tree_digest_map(class_modules / "scoreform", workspace),
        "quillan": _tree_digest_map(class_modules / "quillan", workspace),
        "meridian_upstream": meridian_files,
    }


def _assert_no_standalone_grade_results(workspace: Path) -> None:
    _require(
        get_current_conventional_grade_result_revision(
            workspace,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            CALENDAR_REVISION,
        )
        is None,
        "Standalone conventional Grade result must remain unselected and absent.",
    )
    _require(
        get_current_standards_grade_result_revision(
            workspace,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            CALENDAR_REVISION,
        )
        is None,
        "Standalone standards Grade result must remain unselected and absent.",
    )


def _calculate_and_persist(
    workspace: Path,
    work_evidence: tuple[conventional.ConventionalGradeWorkEvidenceSpec, ...],
) -> dict[str, object]:
    _assert_no_standalone_grade_results(workspace)
    assembly = assemble_hybrid_grade_calculation(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
        work_evidence,
    )
    _require(assembly.outcome.status == "calculated", "Hybrid Grade did not calculate.")
    _require(
        assembly.conventional.outcome.rounded_grade == Decimal("100.00"),
        "Installed conventional component value mismatch.",
    )
    _require(
        assembly.standards_based.outcome.rounded_grade == Decimal("100.00"),
        "Installed standards component value mismatch.",
    )
    _require(
        assembly.outcome.rounded_grade == Decimal("100.00"),
        "Installed hybrid Grade value mismatch.",
    )
    repeated = assemble_hybrid_grade_calculation(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
        work_evidence,
    )
    _require(
        repeated.inputs == assembly.inputs,
        "Hybrid assembly is not deterministic.",
    )
    _require(
        repeated.outcome == assembly.outcome,
        "Hybrid outcome is not deterministic.",
    )

    snapshot = create_hybrid_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    written = write_hybrid_grade_result_revision(
        workspace,
        snapshot,
        work_evidence=work_evidence,
    )
    _require(written.disposition == "created", "Hybrid Grade write failed.")
    _require(
        get_current_hybrid_grade_result_revision(
            workspace,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            CALENDAR_REVISION,
        )
        is None,
        "Writing a hybrid Grade result must not select it.",
    )
    selected = select_hybrid_grade_result_revision(
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
        "Hybrid Grade selection reference mismatch.",
    )
    current = load_current_hybrid_grade_result(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    _require(current is not None, "Selected hybrid Grade result is missing.")
    assert current is not None
    _require(
        calculate_hybrid_grade(current.snapshot.inputs) == current.snapshot.outcome,
        "Stored hybrid Grade does not reproduce from embedded inputs.",
    )
    encoded = hybrid_grade_result_snapshot_to_json_bytes(current.snapshot)
    _require(
        hybrid_grade_result_snapshot_from_json_bytes(encoded) == current.snapshot,
        "Hybrid Grade canonical JSON round-trip failed.",
    )
    refreshed = assemble_hybrid_grade_calculation(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
        work_evidence,
    )
    freshness = assess_hybrid_grade_result_freshness(
        current.snapshot,
        refreshed.inputs,
    )
    _require(freshness.status == "current", "Hybrid Grade result is stale.")
    _require(freshness.reasons == (), "Current hybrid Grade has stale reasons.")
    _assert_no_standalone_grade_results(workspace)
    return {
        "result_revision": current.snapshot.result_revision,
        "result_sha256": current.result_sha256,
        "calculation_fingerprint": current.snapshot.calculation_fingerprint,
        "rounded_grade": str(current.snapshot.outcome.rounded_grade),
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_program_hybrid_grade.py <workspace>")
    _verify_installed_composition()
    workspace = Path(sys.argv[1]).resolve()
    conventional._seed_core_context(workspace)
    producer = conventional._publish(workspace)
    projected = conventional._project(workspace, producer)
    authorized = conventional._authorized(workspace, projected)
    work_evidence = conventional._configure(workspace, projected, authorized)
    publication_work = projected.cached.stored.snapshot.source.publication.work
    scale = _persist_proficiency_basis(workspace, publication_work)
    _install_hybrid_policy(workspace, scale)
    upstream_before = _upstream_snapshot(workspace)
    result = _calculate_and_persist(workspace, work_evidence)
    upstream_after = _upstream_snapshot(workspace)
    _require(
        upstream_after == upstream_before,
        "Hybrid Grade layer mutated producer or v0.2/Grade-policy source state.",
    )
    _require(
        all(path.read_bytes() == expected for path, expected in producer.native_files),
        "Hybrid Grade layer mutated ScoreForm native source bytes.",
    )
    baseline = {
        "schema_version": "1",
        "workspace": workspace.name,
        "class_id": CLASS_ID,
        "student_id": STUDENT_ID,
        "school_year": SCHOOL_YEAR,
        "period_id": PERIOD_ID,
        "calendar_revision": CALENDAR_REVISION,
        **result,
        "upstream": upstream_before,
    }
    (workspace.parent / BASELINE_NAME).write_text(
        json.dumps(baseline, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("Issue #52 installed bounded hybrid Grade acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
