"""Installed deep-path acceptance for Meridian issue #102."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.academic_work_registration_storage import (
    write_academic_work_registration,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.routes import class_metadata_path, module_work_dir
from pds_core.routing_models import ModuleWorkRef

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyTarget,
    calculate_academic_period_proficiency,
    create_academic_period_proficiency_result_snapshot,
)
from meridian.academic_period_proficiency_storage import (
    load_current_academic_period_proficiency_result,
    select_academic_period_proficiency_policy_revision,
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_policy_revision,
    write_academic_period_proficiency_result_revision,
)
from meridian.evidence import NativeScale, NativeScaleLevel
from meridian.export_profile import (
    EXPORT_PROFILE_RECORD_TYPE,
    EXPORT_PROFILE_SCHEMA_VERSION,
    EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
    ExportColumn,
    ExportProfileActor,
    ExportProfileRevision,
    ExportRepresentation,
)
from meridian.export_profile_storage import (
    load_current_export_profile,
    select_export_profile,
    write_export_profile_revision,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
    select_grade_item_membership_revision,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_storage import (
    load_current_grade_item_revision,
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import GradeItemRevision, GradeItemWorkReference
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
from meridian.grade_policy_storage import (
    load_current_grade_policy,
    select_grade_policy_revision,
    write_grade_policy_revision,
)
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.proficiency_mapping import (
    NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
    NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    NativeValueMappingProfile,
    NativeValueSourceSignature,
    ProficiencyLevel,
    ProficiencyScale,
    ScaledLevelMappingRule,
    proficiency_scale_reference,
)
from meridian.proficiency_mapping_storage import (
    load_current_mapping_profile,
    load_current_proficiency_scale,
    select_mapping_profile_revision,
    select_proficiency_scale_revision,
    write_mapping_profile_revision,
    write_proficiency_scale_revision,
)
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionRevision,
)
from meridian.reporting_snapshot_preview import (
    frozen_grade_report_preview_from_json_bytes,
)
from meridian.reporting_snapshot_record import (
    REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
    ReportingSnapshotBuildRequest,
    ReportingSnapshotGradeRequest,
    compose_reporting_snapshot,
    reporting_snapshot_provenance_binding,
)
from meridian.reporting_snapshot_selection import (
    load_current_reporting_snapshot,
    select_reporting_snapshot,
)
from meridian.reporting_snapshot_storage import (
    load_reporting_definition_revision,
    write_reporting_definition_revision,
    write_reporting_snapshot,
)
from meridian.standards_proficiency import StandardProficiencyActor
from meridian.storage_path_keys import (
    STORAGE_PATH_KEY_JSON_SHA256_FILENAME_MAX_LENGTH,
    STORAGE_PATH_KEY_MAX_LENGTH,
    storage_path_key,
)

CLASS_ID = "synthetic_class_2026"
SCHOOL_YEAR = "2026-2027"
PERIOD = AcademicPeriodRef(SCHOOL_YEAR, "mp1")
STANDARD_ID = "urn:njsls:ela:RL.CR.11-12.1"
NOW = datetime(2026, 10, 3, 18, 0, tzinfo=UTC)
LONG_ID_SIZE = 1024
LONG_WORK_SIZE = 80


def _long_id(prefix: str, character: str, size: int = LONG_ID_SIZE) -> str:
    return prefix + (character * size)


def _long_paths_enabled() -> object | None:
    """Read Windows path-policy state without mutating it."""

    if os.name != "nt":
        return None
    winreg: Any = importlib.import_module("winreg")
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        ) as key:
            value = winreg.QueryValueEx(key, "LongPathsEnabled")[0]
            return cast(object, value)
    except OSError:
        return "unavailable"


def _deep_workspace() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Create a controlled deep workspace that stays below legacy MAX_PATH."""

    temporary = tempfile.TemporaryDirectory(prefix="m102-", dir=tempfile.gettempdir())
    base = Path(temporary.name)
    counter = 0
    while len(str(base / "workspace")) < 100:
        base = base / f"managed_{counter:02d}"
        counter += 1
    workspace = base / "workspace"
    workspace.mkdir(parents=True)
    if len(str(workspace)) < 100:
        raise AssertionError(
            "Deep-workspace qualification did not create path pressure."
        )
    return temporary, workspace


def _preview(target: GradePreviewTarget) -> Any:
    data = {
        "summary": {
            "requested_count": 1,
            "available_count": 0,
            "unavailable_count": 1,
            "base_calculated_count": 0,
            "base_blocked_count": 0,
            "base_insufficient_count": 0,
            "current_count": 0,
            "stale_count": 0,
            "effective_numeric_count": 0,
            "effective_nonnumeric_count": 0,
            "effective_base_count": 0,
            "effective_override_count": 0,
            "effective_none_count": 0,
        },
        "rows": [
            {
                "target": {
                    "class_id": target.class_id,
                    "student_id": target.student_id,
                    "target_period": {
                        "school_year": target.target_period.school_year,
                        "period_id": target.target_period.period_id,
                    },
                    "calendar_revision": target.calendar_revision,
                    "calculation_family": target.calculation_family,
                },
                "status": "unavailable",
                "unavailable_reason": "no_selected_grade",
                "explanation": None,
                "observation": None,
            }
        ],
    }
    encoded = (
        json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return frozen_grade_report_preview_from_json_bytes(encoded)


def _assert_installed_origins() -> None:
    import pds_core

    import meridian

    environment = Path(sys.prefix).resolve()
    for module in (meridian, pds_core):
        if module.__file__ is None:
            raise AssertionError("Installed package has no import origin.")
        origin = Path(module.__file__).resolve()
        if not origin.is_relative_to(environment):
            raise AssertionError(
                "Package shadowed outside prepared environment: "
                f"{origin}"
            )

    if importlib.metadata.version("pds-core") != "0.6.4":
        raise AssertionError("Issue #102 requires exact installed pds-core 0.6.4.")

    for module_name in ("scoreform", "quillan", "concord", "pds_concord"):
        if importlib.util.find_spec(module_name) is not None:
            raise AssertionError(
                f"Issue #102 Core-only acceptance unexpectedly found {module_name}."
            )


def _assert_fresh_process_determinism(long_grade_item_id: str) -> None:
    expected = storage_path_key("grade_item", long_grade_item_id)
    code = (
        "from meridian.storage_path_keys import storage_path_key; "
        "print(storage_path_key('grade_item', 'grade_' + ('g' * 1024)))"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip() != expected:
        raise AssertionError("Fresh-process storage path key changed.")
    if completed.stderr:
        raise AssertionError("Fresh-process key derivation wrote stderr.")


def _assert_meridian_path_budget(
    workspace: Path,
    forbidden_identities: tuple[str, ...],
) -> None:
    meridian_root = (
        workspace
        / "classes"
        / CLASS_ID
        / "modules"
        / "meridian"
    )
    if not meridian_root.is_dir():
        raise AssertionError("Meridian canonical storage root was not created.")

    observed = 0
    for entry in meridian_root.rglob("*"):
        observed += 1
        relative = entry.relative_to(meridian_root)
        for part in relative.parts:
            if len(part) > STORAGE_PATH_KEY_JSON_SHA256_FILENAME_MAX_LENGTH:
                raise AssertionError(
                    f"Meridian-owned component exceeds documented bound: {part!r}"
                )
        rendered = relative.as_posix()
        for identity in forbidden_identities:
            if identity in rendered:
                raise AssertionError(
                    "Semantic identity leaked into Meridian canonical path: "
                    f"{identity[:32]!r}"
                )

    if observed == 0:
        raise AssertionError("No Meridian canonical storage was observed.")


def main() -> None:
    """Persist and reload long identities from the installed candidate wheel."""

    _assert_installed_origins()
    before_long_paths = _long_paths_enabled()
    temporary, workspace = _deep_workspace()

    long_grade_item_id = _long_id("grade_", "g")
    long_work_id = _long_id("work_", "w", LONG_WORK_SIZE)
    long_grade_policy_id = _long_id("grade_policy_", "p")
    long_scale_id = _long_id("scale_", "s")
    long_mapping_profile_id = _long_id("mapping_", "m")
    long_student_id = _long_id("student_", "u")
    long_reporting_definition_id = _long_id("definition_", "d")
    long_snapshot_id = _long_id("snapshot_", "n")
    long_export_profile_id = _long_id("export_", "e")
    long_ap_policy_id = _long_id("ap_policy_", "a")

    try:
        metadata = ClassMetadata(
            class_id=CLASS_ID,
            school_year=SCHOOL_YEAR,
            created_at=NOW,
            updated_at=NOW,
            module_details={},
        )
        write_class_metadata(class_metadata_path(workspace, CLASS_ID), metadata)

        calendar = AcademicPeriodCalendar(
            schema_version="1",
            record_type="academic_period_calendar",
            school_year=SCHOOL_YEAR,
            calendar_revision=1,
            created_at=NOW,
            updated_at=NOW,
            periods=(
                AcademicPeriod(
                    period_id=PERIOD.period_id,
                    period_type="marking_period",
                    label="Marking Period 1",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 11, 8),
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

        work = ModuleWorkRef(
            module_id="scoreform",
            class_id=CLASS_ID,
            work_id=long_work_id,
        )
        module_work_dir(workspace, work).mkdir(parents=True, exist_ok=True)
        write_academic_work_registration(
            workspace,
            AcademicWorkRegistration(
                schema_version="1",
                record_type="academic_work_registration",
                work=work,
                registration_revision=1,
                producer_contract_version="v1",
                title="Long work identity",
                work_kind="assessment",
                academic_intent="summative",
                lifecycle="active",
                created_at=NOW,
                updated_at=NOW,
                source_records=(),
            ),
            expected_current_revision=None,
        )

        grade_item = GradeItemRevision(
            schema_version="1",
            record_type="meridian_grade_item",
            class_id=CLASS_ID,
            grade_item_id=long_grade_item_id,
            grade_item_revision=1,
            supersedes_revision=None,
            title="Long Grade Item",
            purpose="standards_and_conventional",
            status="active",
            weighting=None,
            created_at=NOW,
            revised_at=NOW,
        )
        stored_item = write_grade_item_revision(workspace, grade_item).stored
        select_grade_item_revision(
            workspace,
            CLASS_ID,
            long_grade_item_id,
            1,
            expected_current_revision=None,
        )
        current_item = load_current_grade_item_revision(
            workspace,
            CLASS_ID,
            long_grade_item_id,
        )
        assert current_item is not None
        assert current_item.revision.grade_item_id == long_grade_item_id
        assert len(stored_item.path.parent.name) == STORAGE_PATH_KEY_MAX_LENGTH

        membership = GradeItemMembershipDecision(
            schema_version="1",
            record_type="meridian_grade_item_membership",
            class_id=CLASS_ID,
            grade_item_id=long_grade_item_id,
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
                calendar_revision=1,
            ),
            actor_id="teacher_local",
            rationale=None,
            decided_at=NOW,
        )
        stored_membership = write_grade_item_membership_revision(
            workspace,
            membership,
        ).stored
        select_grade_item_membership_revision(
            workspace,
            CLASS_ID,
            long_grade_item_id,
            work,
            1,
            expected_current_membership_revision=None,
        )
        current_membership = load_current_grade_item_membership_decision(
            workspace,
            CLASS_ID,
            long_grade_item_id,
            work,
        )
        assert current_membership is not None
        assert current_membership.decision.work_reference.work.work_id == long_work_id
        assert len(stored_membership.path.parent.name) == STORAGE_PATH_KEY_MAX_LENGTH

        item_reference = GradePolicyItemReference(
            CLASS_ID,
            long_grade_item_id,
            1,
            stored_item.revision_sha256,
        )
        grade_policy = GradePolicyRevision(
            schema_version=GRADE_POLICY_SCHEMA_VERSION,
            record_type=GRADE_POLICY_RECORD_TYPE,
            class_id=CLASS_ID,
            policy_id=long_grade_policy_id,
            policy_revision=1,
            supersedes_revision=None,
            title="Long Grade policy",
            calculation_family="conventional",
            configuration=ConventionalGradeConfiguration(
                "total_points",
                (
                    GradePolicyItemParticipation(
                        item_reference,
                        None,
                        None,
                        Decimal("100"),
                    ),
                ),
                (),
            ),
            state_treatment=GradeStateTreatment(
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
            ),
            reassessment_handling=GradeReassessmentHandling(
                "v02_attempt_and_reassessment_state",
                "blocking",
            ),
            rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
            actor=GradePolicyActor("teacher", "teacher_local"),
            rationale=None,
            revised_at=NOW,
        )
        stored_grade_policy = write_grade_policy_revision(
            workspace,
            grade_policy,
        ).stored
        select_grade_policy_revision(
            workspace,
            CLASS_ID,
            long_grade_policy_id,
            1,
            expected_current_revision=None,
        )
        current_grade_policy = load_current_grade_policy(
            workspace,
            CLASS_ID,
            long_grade_policy_id,
        )
        assert current_grade_policy is not None
        assert current_grade_policy.policy.policy_id == long_grade_policy_id
        assert len(stored_grade_policy.path.parent.name) == STORAGE_PATH_KEY_MAX_LENGTH

        scale = ProficiencyScale(
            schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
            record_type=PROFICIENCY_SCALE_RECORD_TYPE,
            class_id=CLASS_ID,
            scale_id=long_scale_id,
            scale_revision=1,
            supersedes_revision=None,
            title="Long scale",
            description="Installed path qualification scale.",
            levels=(
                ProficiencyLevel("beginning", 1, "Beginning", "Initial"),
                ProficiencyLevel("proficient", 2, "Proficient", "Meets"),
            ),
            proficiency_threshold_level_id="proficient",
            actor=MappingActor("teacher", "teacher_local"),
            rationale=None,
            revised_at=NOW,
        )
        stored_scale = write_proficiency_scale_revision(workspace, scale).stored
        select_proficiency_scale_revision(
            workspace,
            CLASS_ID,
            long_scale_id,
            1,
            expected_current_scale_revision=None,
        )
        current_scale = load_current_proficiency_scale(
            workspace,
            CLASS_ID,
            long_scale_id,
        )
        assert current_scale is not None
        assert current_scale.scale.scale_id == long_scale_id
        assert len(stored_scale.path.parent.name) == STORAGE_PATH_KEY_MAX_LENGTH

        mapping_profile = NativeValueMappingProfile(
            schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
            record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
            class_id=CLASS_ID,
            scale_id=long_scale_id,
            profile_id=long_mapping_profile_id,
            profile_revision=1,
            supersedes_revision=None,
            target_scale=proficiency_scale_reference(stored_scale.scale),
            source_signature=NativeValueSourceSignature(
                producer_module_id="quillan",
                publication_kind="academic_result_set",
                manifest_contract_version="quillan_academic_result_manifest_v1",
                producer_contract_version="quillan_academic_work_v1",
                projection_id="quillan.academic_result",
                projection_contract_version="1",
                producer_reader_distribution="quillan",
                producer_reader_version="0.10.3",
                result_kind="overall_standard_rating",
                target_kind="standard",
            ),
            mapping_kind="exact_native_scale",
            native_scale=NativeScale(
                "rubric_02",
                (
                    NativeScaleLevel(0, "Low", "Initial"),
                    NativeScaleLevel(2, "High", "Meets"),
                ),
            ),
            points_possible=None,
            mapping_rules=(
                ScaledLevelMappingRule(0, "beginning"),
                ScaledLevelMappingRule(2, "proficient"),
            ),
            actor=MappingActor("teacher", "teacher_local"),
            rationale=None,
            revised_at=NOW,
        )
        stored_mapping = write_mapping_profile_revision(
            workspace,
            mapping_profile,
        ).stored
        select_mapping_profile_revision(
            workspace,
            CLASS_ID,
            long_scale_id,
            long_mapping_profile_id,
            1,
            expected_current_profile_revision=None,
        )
        current_mapping = load_current_mapping_profile(
            workspace,
            CLASS_ID,
            long_scale_id,
            long_mapping_profile_id,
        )
        assert current_mapping is not None
        assert current_mapping.profile.profile_id == long_mapping_profile_id
        assert len(stored_mapping.path.parent.name) == STORAGE_PATH_KEY_MAX_LENGTH

        ap_policy = AcademicPeriodProficiencyAggregationPolicy(
            schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
            record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
            class_id=CLASS_ID,
            policy_id=long_ap_policy_id,
            policy_revision=1,
            supersedes_revision=None,
            title="Long Academic Period proficiency policy",
            target_scale=proficiency_scale_reference(stored_scale.scale),
            strategy="highest",
            period_membership_scope="direct",
            minimum_calculated_results=1,
            mode_tie_rule=None,
            median_even_rule=None,
            missing_result_handling="noncontributing",
            insufficient_result_handling="blocking",
            actor=StandardProficiencyActor("teacher", "teacher_local"),
            rationale=None,
            revised_at=NOW,
        )
        write_academic_period_proficiency_policy_revision(
            workspace,
            ap_policy,
        )
        select_academic_period_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            long_ap_policy_id,
            1,
            expected_current_policy_revision=None,
        )
        target = AcademicPeriodProficiencyTarget(PERIOD, 1)
        inputs = AcademicPeriodProficiencyAggregationInputs(
            schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
            record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
            class_id=CLASS_ID,
            target_period=target,
            student_id=long_student_id,
            standard_id=STANDARD_ID,
            target_scale=proficiency_scale_reference(stored_scale.scale),
            period_membership_scope="direct",
            entries=(),
        )
        outcome = calculate_academic_period_proficiency(
            inputs,
            ap_policy,
            stored_scale.scale,
        )
        ap_snapshot = create_academic_period_proficiency_result_snapshot(
            inputs,
            outcome,
            result_revision=1,
            calculated_at=NOW,
        )
        stored_ap = write_academic_period_proficiency_result_revision(
            workspace,
            ap_snapshot,
        ).stored
        select_academic_period_proficiency_result_revision(
            workspace,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD.period_id,
            long_student_id,
            STANDARD_ID,
            1,
            expected_current_result_revision=None,
        )
        current_ap = load_current_academic_period_proficiency_result(
            workspace,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD.period_id,
            long_student_id,
            STANDARD_ID,
        )
        assert current_ap is not None
        assert current_ap.snapshot.student_id == long_student_id
        assert len(stored_ap.path.parent.name) == STORAGE_PATH_KEY_MAX_LENGTH

        definition = ReportingDefinitionRevision(
            schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
            record_type=REPORTING_DEFINITION_RECORD_TYPE,
            class_id=CLASS_ID,
            definition_id=long_reporting_definition_id,
            definition_revision=1,
            supersedes_revision=None,
            report_kind="grade_report",
            purpose="quarter_grade_review",
            title="Long reporting definition",
            target_period=PERIOD,
            intended_audience="teacher",
            actor=ReportingActor("teacher", "teacher_local"),
            rationale=None,
            revised_at=NOW,
        )
        stored_definition = write_reporting_definition_revision(
            workspace,
            definition,
        ).stored
        assert load_reporting_definition_revision(
            workspace,
            CLASS_ID,
            long_reporting_definition_id,
            1,
        ).definition.definition_id == long_reporting_definition_id

        preview_target = GradePreviewTarget(
            class_id=CLASS_ID,
            student_id=long_student_id,
            target_period=PERIOD,
            calendar_revision=1,
            calculation_family="standards_based",
        )
        build_request = ReportingSnapshotBuildRequest(
            schema_version=REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
            definition_reference=stored_definition.reference,
            grade_requests=(
                ReportingSnapshotGradeRequest(
                    target=preview_target,
                    work_evidence=None,
                ),
            ),
            actor=ReportingActor("teacher", "teacher_local"),
            rationale="Freeze long-identity acceptance report.",
            requested_at=NOW,
            predecessor=None,
        )
        snapshot = compose_reporting_snapshot(
            snapshot_id=long_snapshot_id,
            build_request=build_request,
            report_preview=_preview(preview_target),
            provenance_bindings=(
                reporting_snapshot_provenance_binding(
                    authority_kind="academic_period_calendar",
                    reference_kind="academic_period_calendar_reference",
                    reference={
                        "school_year": SCHOOL_YEAR,
                        "calendar_revision": 1,
                    },
                ),
            ),
            created_at=NOW,
        )
        stored_snapshot = write_reporting_snapshot(workspace, snapshot).stored
        select_reporting_snapshot(
            workspace,
            stored_snapshot.reference,
            actor=ReportingActor("teacher", "teacher_local"),
            rationale="Select installed acceptance snapshot.",
            decided_at=NOW + timedelta(minutes=1),
            expected_current=None,
        )
        current_snapshot = load_current_reporting_snapshot(
            workspace,
            CLASS_ID,
            long_reporting_definition_id,
            PERIOD,
            1,
        )
        assert current_snapshot is not None
        assert current_snapshot.snapshot.snapshot_id == long_snapshot_id
        assert len(stored_snapshot.path.stem) == STORAGE_PATH_KEY_MAX_LENGTH
        assert (
            len(stored_snapshot.path.name + ".sha256")
            <= STORAGE_PATH_KEY_JSON_SHA256_FILENAME_MAX_LENGTH
        )

        export_profile = ExportProfileRevision(
            schema_version=EXPORT_PROFILE_SCHEMA_VERSION,
            record_type=EXPORT_PROFILE_RECORD_TYPE,
            source_registry_version=EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
            class_id=CLASS_ID,
            profile_id=long_export_profile_id,
            profile_revision=1,
            supersedes_revision=None,
            title="Long export profile",
            purpose="Installed path qualification",
            columns=(
                ExportColumn("target.student_id", "Student ID"),
                ExportColumn("grade.effective_grade", "Grade"),
            ),
            representation=ExportRepresentation("csv", True, "crlf", True),
            actor=ExportProfileActor("teacher", "teacher_local"),
            rationale=None,
            revised_at=NOW,
        )
        stored_export = write_export_profile_revision(
            workspace,
            export_profile,
        ).stored
        select_export_profile(
            workspace,
            stored_export.reference,
            actor=ExportProfileActor("teacher", "teacher_local"),
            rationale="Select installed acceptance profile.",
            decided_at=NOW + timedelta(minutes=1),
            expected_current=None,
        )
        current_export = load_current_export_profile(
            workspace,
            CLASS_ID,
            long_export_profile_id,
        )
        assert current_export is not None
        assert current_export.profile.profile_id == long_export_profile_id
        assert len(stored_export.path.parent.parent.name) == STORAGE_PATH_KEY_MAX_LENGTH

        forbidden = (
            long_grade_item_id,
            long_work_id,
            long_grade_policy_id,
            long_scale_id,
            long_mapping_profile_id,
            long_student_id,
            long_reporting_definition_id,
            long_snapshot_id,
            long_export_profile_id,
            long_ap_policy_id,
        )
        _assert_meridian_path_budget(workspace, forbidden)
        _assert_fresh_process_determinism(long_grade_item_id)

        after_long_paths = _long_paths_enabled()
        if after_long_paths != before_long_paths:
            raise AssertionError("Issue #102 acceptance changed Windows path policy.")

        print("Issue #102 installed deep-path acceptance passed.", flush=True)
    finally:
        temporary.cleanup()


if __name__ == "__main__":
    main()
