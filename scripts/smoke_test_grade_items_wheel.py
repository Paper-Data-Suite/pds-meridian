"""Smoke-test v0.2 interpretation layers from an installed Meridian wheel."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import textwrap
import venv
from pathlib import Path


def _environment() -> dict[str, str]:
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    for variable in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        environment.pop(variable, None)
    return environment


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=_environment(),
    )


def smoke_test(meridian_wheel: Path, core_wheel: Path) -> None:
    """Install only Core and Meridian, then exercise v0.2 interpretation state."""
    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-grade-item-smoke-"
    ) as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")

        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(core_wheel.resolve()),
                str(meridian_wheel.resolve()),
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)
        code = textwrap.dedent(
            """
            import hashlib
            import pathlib
            import shutil
            import sys
            import tempfile
            from datetime import UTC, date, datetime
            from decimal import Decimal

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
            from pds_core.publication_records import PublicationRecord
            from pds_core.publication_storage import write_publication_record
            from pds_core.routes import class_metadata_path, module_work_dir
            from pds_core.routing_models import ModuleWorkRef
            from pds_core.standards import (
                StandardDefinition,
                StandardsFrameworkMetadata,
                StandardsLibrary,
                write_workspace_standards_library,
            )

            from meridian.adapters import AdapterKey
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
            from meridian.attempt_selection_storage import (
                derive_attempt_candidates,
                get_current_attempt_selection_decision_revision,
                get_current_attempt_selection_policy_revision,
                resolve_current_attempt_selection,
                select_attempt_selection_decision_revision,
                select_attempt_selection_policy_revision,
                write_attempt_selection_decision_revision,
                write_attempt_selection_policy_revision,
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
            from meridian.reassessment_storage import (
                get_current_reassessment_decision_revision,
                get_current_reassessment_policy_revision,
                resolve_current_reassessment,
                select_reassessment_decision_revision,
                select_reassessment_policy_revision,
                write_reassessment_decision_revision,
                write_reassessment_policy_revision,
            )
            from meridian.evidence import (
                EvidenceInventory,
                EvidenceItem,
                EvidenceProvenance,
                EvidenceTarget,
                NativePointValue,
                NativeProvenance,
                NativeReference,
                NativeScalarValue,
                NativeScale,
                NativeScaledValue,
                NativeScaleLevel,
                NativeStateValue,
                StudentSubject,
            )
            from meridian.evidence_eligibility import (
                EVIDENCE_ELIGIBILITY_RECORD_TYPE,
                EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
                EvidenceDecisionActor,
                EvidenceEligibilityDecision,
                EvidenceEligibilityPolicyReference,
                EvidenceSourceReference,
            )
            from meridian.evidence_eligibility_storage import (
                get_current_evidence_eligibility_revision,
                load_current_evidence_eligibility_decision,
                observe_evidence_source_state,
                resolve_current_evidence_eligibility,
                select_evidence_eligibility_revision,
                write_evidence_eligibility_revision,
            )
            from meridian.grade_item_membership_storage import (
                load_current_grade_item_membership_decision,
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
                GradeItemWeightingMetadata,
                GradeItemWorkReference,
                grade_item_revision_from_json_bytes,
                grade_item_revision_to_json_bytes,
            )
            from meridian.ingestion import (
                CanonicalPublicationContext,
                PublicationAuthorizationDecision,
                PublicationSeriesMember,
                PublicationSeriesObservation,
            )
            from meridian.proficiency_mapping import (
                NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
                NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
                PROFICIENCY_SCALE_RECORD_TYPE,
                PROFICIENCY_SCALE_SCHEMA_VERSION,
                MappingActor,
                NativeValueMappingProfile,
                NativeValueSourceSignature,
                PointRangeMappingRule,
                ProficiencyLevel,
                ProficiencyScale,
                ScalarMappingRule,
                ScaledLevelMappingRule,
                map_native_value,
                proficiency_scale_reference,
            )
            from meridian.proficiency_mapping_storage import (
                get_current_mapping_profile_revision,
                get_current_proficiency_scale_revision,
                load_mapping_profile_revision,
                select_mapping_profile_revision,
                select_proficiency_scale_revision,
                write_mapping_profile_revision,
                write_proficiency_scale_revision,
            )
            from meridian.projection_cache import (
                PROJECTION_SNAPSHOT_RECORD_TYPE,
                PROJECTION_SNAPSHOT_SCHEMA_VERSION,
                AuthorizedProjectionSnapshot,
                ProjectionAuthorizationObservation,
                ProjectionCacheAssessment,
                ProjectionCacheIdentity,
                ProjectionExecutionIdentity,
                ProjectionSnapshot,
                ProjectionSourceObservation,
                StoredProjectionSnapshot,
                projection_cache_key,
                projection_cache_path,
                projection_cache_relative_path,
                projection_snapshot_to_json_bytes,
            )
            from meridian.standards_evidence import (
                STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
                STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
                GradeItemAggregationBasis,
                ResolvedStandardAggregationCandidate,
                StandardEvidenceActor,
                StandardEvidenceAssociationDecision,
                build_standard_aggregation_inputs,
                standard_aggregation_inputs_from_json_bytes,
                standard_aggregation_inputs_to_json_bytes,
            )
            from meridian.standards_evidence_storage import (
                StandardAggregationCandidateBinding,
                get_current_standard_evidence_association_revision,
                load_standard_evidence_association_revision,
                resolve_current_standard_evidence_association,
                resolve_standard_aggregation_inputs,
                select_standard_evidence_association_revision,
                write_standard_evidence_association_revision,
            )

            workspace = pathlib.Path(tempfile.mkdtemp(prefix="meridian-membership-"))
            try:
                class_id = "synthetic_class"
                school_year = "2026-2027"
                now = datetime(2026, 8, 25, tzinfo=UTC)
                metadata = ClassMetadata(
                    class_id=class_id,
                    school_year=school_year,
                    created_at=now,
                    updated_at=now,
                    module_details={},
                )
                write_class_metadata(class_metadata_path(workspace, class_id), metadata)

                standard_id = "urn:state:ELA/9-10:RL.1?edition=2026"
                second_standard_id = "urn:state:ELA/9-10:RL.2?edition=2026"
                standards_library = StandardsLibrary(
                    standards=(
                        StandardDefinition(
                            standard_id=standard_id,
                            code="RL.1",
                            source="state-ela-2026",
                            short_name="Cite evidence",
                            description="Cite strong and thorough textual evidence.",
                            subject="ELA",
                            grade_band="9-10",
                            active=True,
                        ),
                        StandardDefinition(
                            standard_id=second_standard_id,
                            code="RL.2",
                            source="state-ela-2026",
                            short_name="Determine theme",
                            description="Determine a theme or central idea.",
                            subject="ELA",
                            grade_band="9-10",
                            active=True,
                        ),
                    ),
                    frameworks=(
                        StandardsFrameworkMetadata(
                            framework_id="state-ela-2026",
                            source="state-ela-2026",
                            title="State ELA Standards 2026",
                            authority="Synthetic State Education Agency",
                            version="2026",
                        ),
                    ),
                )
                write_workspace_standards_library(workspace, standards_library)

                # #32: define teacher-owned ordinal proficiency policy first.
                proficiency_scale = ProficiencyScale(
                    schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
                    record_type=PROFICIENCY_SCALE_RECORD_TYPE,
                    class_id=class_id,
                    scale_id="teacher_proficiency",
                    scale_revision=1,
                    supersedes_revision=None,
                    title="Teacher proficiency",
                    description="Synthetic criterion-referenced scale.",
                    levels=(
                        ProficiencyLevel(
                            "starting", 1, "Starting", "Initial evidence."
                        ),
                        ProficiencyLevel(
                            "growing", 2, "Growing", "Partial evidence."
                        ),
                        ProficiencyLevel(
                            "ready", 3, "Ready", "Meets the criterion."
                        ),
                        ProficiencyLevel(
                            "extending", 4, "Extending", "Extends criterion."
                        ),
                    ),
                    proficiency_threshold_level_id="ready",
                    actor=MappingActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                scale_write = write_proficiency_scale_revision(
                    workspace, proficiency_scale
                )
                assert scale_write.disposition == "created"
                assert (
                    get_current_proficiency_scale_revision(
                        workspace, class_id, proficiency_scale.scale_id
                    )
                    is None
                )
                select_proficiency_scale_revision(
                    workspace,
                    class_id,
                    proficiency_scale.scale_id,
                    1,
                    expected_current_scale_revision=None,
                )

                # Exact nonconsecutive producer-native scale; 2 is intentionally
                # unmapped to prove there is no ordinal interpolation.
                native_024 = NativeScale(
                    scale_id="synthetic_024",
                    levels=(
                        NativeScaleLevel(0, "Low", "Limited evidence"),
                        NativeScaleLevel(2, "Middle", "Developing evidence"),
                        NativeScaleLevel(4, "High", "Strong evidence"),
                    ),
                )
                native_signature = NativeValueSourceSignature(
                    producer_module_id="syntheticproducer",
                    publication_kind="academic_result_set",
                    manifest_contract_version="synthetic_manifest_v1",
                    producer_contract_version="synthetic_work_v1",
                    projection_id="synthetic.academic_result",
                    projection_contract_version="1",
                    producer_reader_distribution="synthetic-producer",
                    producer_reader_version="1.0.0",
                    result_kind="native_rating",
                    target_kind="standard",
                )
                native_profile = NativeValueMappingProfile(
                    schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
                    record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
                    class_id=class_id,
                    scale_id=proficiency_scale.scale_id,
                    profile_id="native_024",
                    profile_revision=1,
                    supersedes_revision=None,
                    target_scale=proficiency_scale_reference(proficiency_scale),
                    source_signature=native_signature,
                    mapping_kind="exact_native_scale",
                    native_scale=native_024,
                    points_possible=None,
                    mapping_rules=(
                        ScaledLevelMappingRule(0, "starting"),
                        ScaledLevelMappingRule(4, "extending"),
                    ),
                    actor=MappingActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                native_profile_write = write_mapping_profile_revision(
                    workspace, native_profile
                )
                assert native_profile_write.disposition == "created"
                assert (
                    get_current_mapping_profile_revision(
                        workspace,
                        class_id,
                        proficiency_scale.scale_id,
                        native_profile.profile_id,
                    )
                    is None
                )
                select_mapping_profile_revision(
                    workspace,
                    class_id,
                    proficiency_scale.scale_id,
                    native_profile.profile_id,
                    1,
                    expected_current_profile_revision=None,
                )
                assert map_native_value(
                    NativeScaledValue(0, native_024),
                    native_signature,
                    native_profile,
                    proficiency_scale,
                ).proficiency_level_id == "starting"
                assert (
                    map_native_value(
                        NativeScaledValue(2, native_024),
                        native_signature,
                        native_profile,
                        proficiency_scale,
                    ).status
                    == "unmapped"
                )
                changed_native = NativeScale(
                    scale_id=native_024.scale_id,
                    levels=(
                        NativeScaleLevel(0, "LOW", "Different meaning"),
                        native_024.levels[1],
                        native_024.levels[2],
                    ),
                )
                assert (
                    map_native_value(
                        NativeScaledValue(0, changed_native),
                        native_signature,
                        native_profile,
                        proficiency_scale,
                    ).status
                    == "unsupported"
                )
                assert (
                    map_native_value(
                        NativeStateValue("unrated"),
                        native_signature,
                        native_profile,
                        proficiency_scale,
                    ).status
                    == "native_state"
                )

                points_signature = NativeValueSourceSignature(
                    producer_module_id="syntheticproducer",
                    publication_kind="academic_result_set",
                    manifest_contract_version="synthetic_manifest_v1",
                    producer_contract_version="synthetic_work_v1",
                    projection_id="synthetic.academic_result",
                    projection_contract_version="1",
                    producer_reader_distribution="synthetic-producer",
                    producer_reader_version="1.0.0",
                    result_kind="attempt_points",
                    target_kind="attempt",
                )
                points_profile = NativeValueMappingProfile(
                    schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
                    record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
                    class_id=class_id,
                    scale_id=proficiency_scale.scale_id,
                    profile_id="points_10",
                    profile_revision=1,
                    supersedes_revision=None,
                    target_scale=proficiency_scale_reference(proficiency_scale),
                    source_signature=points_signature,
                    mapping_kind="raw_points",
                    native_scale=None,
                    points_possible=10,
                    mapping_rules=(
                        PointRangeMappingRule(
                            0, True, 8, False, "growing"
                        ),
                        PointRangeMappingRule(
                            8, True, 10, True, "ready"
                        ),
                    ),
                    actor=MappingActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                write_mapping_profile_revision(workspace, points_profile)
                assert map_native_value(
                    NativePointValue(8, 10),
                    points_signature,
                    points_profile,
                    proficiency_scale,
                ).proficiency_level_id == "ready"
                assert (
                    map_native_value(
                        NativePointValue(8, 12),
                        points_signature,
                        points_profile,
                        proficiency_scale,
                    ).status
                    == "unsupported"
                )

                scalar_signature = NativeValueSourceSignature(
                    producer_module_id="syntheticproducer",
                    publication_kind="academic_result_set",
                    manifest_contract_version="synthetic_manifest_v1",
                    producer_contract_version="synthetic_work_v1",
                    projection_id="synthetic.academic_result",
                    projection_contract_version="1",
                    producer_reader_distribution="synthetic-producer",
                    producer_reader_version="1.0.0",
                    result_kind="question_correctness",
                    target_kind="question",
                )
                scalar_profile = NativeValueMappingProfile(
                    schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
                    record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
                    class_id=class_id,
                    scale_id=proficiency_scale.scale_id,
                    profile_id="boolean_correctness",
                    profile_revision=1,
                    supersedes_revision=None,
                    target_scale=proficiency_scale_reference(proficiency_scale),
                    source_signature=scalar_signature,
                    mapping_kind="exact_scalar",
                    native_scale=None,
                    points_possible=None,
                    mapping_rules=(ScalarMappingRule(True, "ready"),),
                    actor=MappingActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                write_mapping_profile_revision(workspace, scalar_profile)
                assert map_native_value(
                    NativeScalarValue(True),
                    scalar_signature,
                    scalar_profile,
                    proficiency_scale,
                ).status == "mapped"
                assert map_native_value(
                    NativeScalarValue(1),
                    scalar_signature,
                    scalar_profile,
                    proficiency_scale,
                ).status == "unmapped"

                native_profile_v2 = NativeValueMappingProfile(
                    schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
                    record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
                    class_id=class_id,
                    scale_id=proficiency_scale.scale_id,
                    profile_id=native_profile.profile_id,
                    profile_revision=2,
                    supersedes_revision=1,
                    target_scale=proficiency_scale_reference(proficiency_scale),
                    source_signature=native_signature,
                    mapping_kind="exact_native_scale",
                    native_scale=native_024,
                    points_possible=None,
                    mapping_rules=(
                        ScaledLevelMappingRule(0, "starting"),
                        ScaledLevelMappingRule(2, "ready"),
                        ScaledLevelMappingRule(4, "extending"),
                    ),
                    actor=MappingActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                write_mapping_profile_revision(workspace, native_profile_v2)
                assert (
                    get_current_mapping_profile_revision(
                        workspace,
                        class_id,
                        proficiency_scale.scale_id,
                        native_profile.profile_id,
                    )
                    == 1
                )
                historic = load_mapping_profile_revision(
                    workspace,
                    class_id,
                    proficiency_scale.scale_id,
                    native_profile.profile_id,
                    1,
                ).profile
                assert map_native_value(
                    NativeScaledValue(2, native_024),
                    native_signature,
                    historic,
                    proficiency_scale,
                ).status == "unmapped"

                work = ModuleWorkRef(
                    module_id="scoreform",
                    class_id=class_id,
                    work_id="essay_1",
                )
                module_work_dir(workspace, work).mkdir(parents=True, exist_ok=True)
                registration = AcademicWorkRegistration(
                    schema_version="1",
                    record_type="academic_work_registration",
                    work=work,
                    registration_revision=1,
                    producer_contract_version="v1",
                    title="Synthetic Essay",
                    work_kind="assessment",
                    academic_intent="summative",
                    lifecycle="active",
                    created_at=now,
                    updated_at=now,
                    source_records=(),
                )
                write_academic_work_registration(
                    workspace,
                    registration,
                    expected_current_revision=None,
                )

                calendar = AcademicPeriodCalendar(
                    schema_version="1",
                    record_type="academic_period_calendar",
                    school_year=school_year,
                    calendar_revision=1,
                    created_at=now,
                    updated_at=now,
                    periods=(
                        AcademicPeriod(
                            period_id="mp1",
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

                item = GradeItemRevision(
                    schema_version=GRADE_ITEM_SCHEMA_VERSION,
                    record_type=GRADE_ITEM_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id="essay_grade_item",
                    grade_item_revision=1,
                    supersedes_revision=None,
                    title="Synthetic Essay",
                    purpose="standards_proficiency",
                    status="active",
                    weighting=GradeItemWeightingMetadata(
                        relative_weight=Decimal("1.5")
                    ),
                    created_at=now,
                    revised_at=now,
                )
                data = grade_item_revision_to_json_bytes(item)
                assert grade_item_revision_from_json_bytes(data) == item
                stored_item = write_grade_item_revision(workspace, item).stored
                select_grade_item_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    item.grade_item_revision,
                    expected_current_revision=None,
                )

                membership = GradeItemMembershipDecision(
                    schema_version=GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
                    record_type=GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
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
                        period=AcademicPeriodRef(
                            school_year=school_year,
                            period_id="mp1",
                        ),
                        calendar_revision=1,
                    ),
                    actor_id="teacher_local",
                    rationale=None,
                    decided_at=now,
                )
                written = write_grade_item_membership_revision(
                    workspace, membership
                )
                assert written.disposition == "created"
                selected = select_grade_item_membership_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    1,
                    expected_current_membership_revision=None,
                )
                assert selected.disposition == "created"
                current = load_current_grade_item_membership_decision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                )
                assert current is not None
                assert current.decision == membership

                manifest_bytes = b'{"schema_version":"synthetic_manifest_v1"}\\n'
                manifest_relative = (
                    f"classes/{class_id}/modules/{work.module_id}/work/"
                    f"{work.work_id}/exports/manifests/academic_results/1.json"
                )
                manifest_path = workspace.joinpath(*manifest_relative.split("/"))
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.write_bytes(manifest_bytes)
                publication_id = "pub_11111111111111111111111111111111"
                publication = PublicationRecord(
                    schema_version="1",
                    record_type="publication_record",
                    publication_id=publication_id,
                    work=work,
                    source_record=None,
                    publication_kind="academic_result_set",
                    capabilities=("points", "multiple_attempts"),
                    record_set_id="academic_results",
                    record_set_revision=1,
                    manifest_contract_version="synthetic_manifest_v1",
                    manifest_path=manifest_relative,
                    manifest_digest_algorithm="sha256",
                    manifest_digest=hashlib.sha256(manifest_bytes).hexdigest(),
                    published_at=now,
                    academic_work_registration_revision=1,
                    supersedes_publication_id=None,
                )
                write_publication_record(workspace, publication)

                series = PublicationSeriesObservation(
                    members=(PublicationSeriesMember(publication, None),),
                    target_publication_id=publication_id,
                    target_index=0,
                    head_publication_id=publication_id,
                    target_state="current_selectable",
                    successor_publication_id=None,
                )
                context = CanonicalPublicationContext(
                    publication=publication,
                    referenced_registration=registration,
                    current_registration=registration,
                    series=series,
                    withdrawal=None,
                )
                projection_source = ProjectionSourceObservation.from_context(context)
                projection = ProjectionExecutionIdentity(
                    adapter_key=AdapterKey(
                        producer_module_id=work.module_id,
                        publication_kind="academic_result_set",
                        manifest_contract_version="synthetic_manifest_v1",
                        producer_contract_version="v1",
                        source_record_kind=None,
                        source_record_contract_version=None,
                    ),
                    adapter_id="synthetic.eligibility",
                    adapter_interface_version="1",
                    projection_contract_version="1",
                    producer_reader_distribution="synthetic-reader",
                    producer_reader_version="1.0.0",
                )
                projection_authorization = ProjectionAuthorizationObservation(
                    operation="project_evidence",
                    purpose_id="grading_import",
                    requested_student_ids=("student_1",),
                    policy_id="district_policy",
                    policy_version="1",
                )
                cache_identity = ProjectionCacheIdentity(
                    schema_version=PROJECTION_SNAPSHOT_SCHEMA_VERSION,
                    source=projection_source,
                    projection=projection,
                    authorization=projection_authorization,
                )
                cache_key = projection_cache_key(cache_identity)
                evidence_1 = EvidenceItem(
                    item_id="evidence_1",
                    subject=StudentSubject("student_1"),
                    target=EvidenceTarget(
                        "attempt", "attempt_1", standard_ids=(standard_id,)
                    ),
                    result_kind="synthetic_result",
                    value=NativeScalarValue(1),
                    provenance=EvidenceProvenance(
                        publication=publication,
                        registration=registration,
                        withdrawal=None,
                        projection=projection.evidence_projection_identity,
                        native=NativeProvenance(
                            (NativeReference("attempt", sequence=1),)
                        ),
                    ),
                )
                evidence_2 = EvidenceItem(
                    item_id="evidence_2",
                    subject=StudentSubject("student_1"),
                    target=EvidenceTarget(
                        "attempt", "attempt_2", standard_ids=(standard_id,)
                    ),
                    result_kind="synthetic_result",
                    value=NativeScalarValue(99),
                    provenance=EvidenceProvenance(
                        publication=publication,
                        registration=registration,
                        withdrawal=None,
                        projection=projection.evidence_projection_identity,
                        native=NativeProvenance(
                            (NativeReference("attempt", sequence=2),)
                        ),
                    ),
                )
                snapshot = ProjectionSnapshot(
                    schema_version=PROJECTION_SNAPSHOT_SCHEMA_VERSION,
                    record_type=PROJECTION_SNAPSHOT_RECORD_TYPE,
                    cache_key=cache_key,
                    captured_at=now,
                    source=projection_source,
                    projection=projection,
                    authorization=projection_authorization,
                    inventory=EvidenceInventory((evidence_1, evidence_2)),
                )
                snapshot_content = projection_snapshot_to_json_bytes(snapshot)
                snapshot_digest = hashlib.sha256(snapshot_content).hexdigest()
                snapshot_relative = projection_cache_relative_path(
                    publication_id, cache_key, snapshot_digest
                )
                stored_snapshot = StoredProjectionSnapshot(
                    snapshot=snapshot,
                    cache_key=cache_key,
                    snapshot_digest=snapshot_digest,
                    path=projection_cache_path(
                        workspace, publication_id, cache_key, snapshot_digest
                    ),
                    relative_path=snapshot_relative,
                    content=snapshot_content,
                )
                allowed = PublicationAuthorizationDecision(
                    allowed=True,
                    policy_id="district_policy",
                    policy_version="1",
                    reason_codes=(),
                )
                authorized = AuthorizedProjectionSnapshot(
                    stored=stored_snapshot,
                    current_context=context,
                    cache_read_authorization=allowed,
                    current_projection_authorization=allowed,
                    assessment=ProjectionCacheAssessment(
                        source_status="current",
                        reuse_status="reusable",
                        reason_codes=(),
                        observed_canonical_state="current_selectable",
                        current_canonical_state="current_selectable",
                        observed_head_publication_id=publication_id,
                        current_head_publication_id=publication_id,
                        observed_current_registration_revision=1,
                        current_registration_revision=1,
                    ),
                )
                sources = tuple(
                    EvidenceSourceReference(
                        work=work,
                        publication_id=publication_id,
                        cache_key=cache_key,
                        snapshot_digest=snapshot_digest,
                        item_id=evidence.item_id,
                    )
                    for evidence in (evidence_1, evidence_2)
                )
                source_state = observe_evidence_source_state(workspace, sources[0])
                assert source_state.state == "current"

                unresolved_inputs = resolve_standard_aggregation_inputs(
                    workspace,
                    GradeItemAggregationBasis(
                        class_id,
                        item.grade_item_id,
                        item.grade_item_revision,
                        stored_item.revision_sha256,
                    ),
                    "student_1",
                    standard_id,
                    proficiency_scale_reference(proficiency_scale),
                    (StandardAggregationCandidateBinding(sources[0], authorized),),
                    standards_library=standards_library,
                )
                assert unresolved_inputs.entries[0].exclusion_reason == (
                    "association_unresolved"
                )

                association = StandardEvidenceAssociationDecision(
                    schema_version=STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
                    record_type=STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
                    source=sources[0],
                    standard_id=standard_id,
                    association_revision=1,
                    supersedes_revision=None,
                    disposition="associated",
                    basis="producer_declared",
                    actor=StandardEvidenceActor("teacher", "teacher_local"),
                    rationale="Honor the producer-declared durable standard ID.",
                    decided_at=now,
                )
                association_write = write_standard_evidence_association_revision(
                    workspace,
                    association,
                    authorized_snapshot=authorized,
                    standards_library=standards_library,
                )
                assert association_write.disposition == "created"
                assert get_current_standard_evidence_association_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    sources[0],
                    standard_id,
                ) is None
                association_select = select_standard_evidence_association_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    sources[0],
                    standard_id,
                    1,
                    expected_current_association_revision=None,
                )
                assert association_select.disposition == "created"
                association_resolution = (
                    resolve_current_standard_evidence_association(
                        workspace,
                        class_id,
                        item.grade_item_id,
                        sources[0],
                        standard_id,
                        authorized_snapshot=authorized,
                        standards_library=standards_library,
                    )
                )
                assert association_resolution.status == "associated"
                assert association_resolution.operative_associated is True
                assert association_resolution.standard_resolution.active is True
                assert (
                    association_resolution.standard_resolution.frameworks[0].version
                    == "2026"
                )

                original_standard_ids = evidence_1.target.standard_ids
                explicit_association = StandardEvidenceAssociationDecision(
                    schema_version=STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
                    record_type=STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
                    source=sources[0],
                    standard_id=second_standard_id,
                    association_revision=1,
                    supersedes_revision=None,
                    disposition="associated",
                    basis="explicit",
                    actor=StandardEvidenceActor("policy", "curriculum_policy"),
                    rationale="A separate teacher-approved relationship.",
                    decided_at=now,
                )
                write_standard_evidence_association_revision(
                    workspace,
                    explicit_association,
                    authorized_snapshot=authorized,
                    standards_library=standards_library,
                )
                select_standard_evidence_association_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    sources[0],
                    second_standard_id,
                    1,
                    expected_current_association_revision=None,
                )
                assert evidence_1.target.standard_ids == original_standard_ids
                assert second_standard_id not in evidence_1.target.standard_ids

                for source in sources:
                    eligibility = EvidenceEligibilityDecision(
                        schema_version=EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
                        record_type=EVIDENCE_ELIGIBILITY_RECORD_TYPE,
                        class_id=class_id,
                        grade_item_id=item.grade_item_id,
                        source=source,
                        membership_revision=1,
                        membership_revision_sha256=written.stored.decision_sha256,
                        eligibility_revision=1,
                        supersedes_revision=None,
                        disposition="included",
                        actor=EvidenceDecisionActor("teacher", "teacher_local"),
                        policy=EvidenceEligibilityPolicyReference(
                            "eligibility_policy", "1"
                        ),
                        reason_codes=(),
                        rationale=None,
                        source_state=source_state,
                        decided_at=now,
                    )
                    eligibility_write = write_evidence_eligibility_revision(
                        workspace, eligibility, authorized_snapshot=authorized
                    )
                    assert eligibility_write.disposition == "created"
                    assert get_current_evidence_eligibility_revision(
                        workspace, class_id, item.grade_item_id, source
                    ) is None
                    eligibility_select = select_evidence_eligibility_revision(
                        workspace,
                        class_id,
                        item.grade_item_id,
                        source,
                        1,
                        authorized_snapshot=authorized,
                        expected_current_eligibility_revision=None,
                    )
                    assert eligibility_select.disposition == "created"
                    eligibility_current = load_current_evidence_eligibility_decision(
                        workspace, class_id, item.grade_item_id, source
                    )
                    assert eligibility_current is not None
                    assert eligibility_current.decision == eligibility
                    resolution = resolve_current_evidence_eligibility(
                        workspace,
                        class_id,
                        item.grade_item_id,
                        source,
                        authorized_snapshot=authorized,
                    )
                    assert resolution.status == "included"
                    assert resolution.operative_included is True

                derived = derive_attempt_candidates(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    "student_1",
                    authorized,
                )
                assert derived.status == "applicable"
                assert tuple(
                    candidate.attempt.native.sequence
                    for candidate in derived.candidates
                ) == (1, 2)

                selection_policy = AttemptSelectionPolicy(
                    schema_version=ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
                    record_type=ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
                    work=work,
                    policy_id="explicit_attempts",
                    policy_revision=1,
                    supersedes_revision=None,
                    selection_basis="explicit",
                    minimum_selected=0,
                    maximum_selected=2,
                    actor=AttemptSelectionActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                policy_write = write_attempt_selection_policy_revision(
                    workspace, selection_policy
                )
                assert policy_write.disposition == "created"
                assert get_current_attempt_selection_policy_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    selection_policy.policy_id,
                ) is None
                policy_select = select_attempt_selection_policy_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    selection_policy.policy_id,
                    1,
                    expected_current_policy_revision=None,
                )
                assert policy_select.disposition == "created"

                attempt_decision = AttemptSelectionDecision(
                    schema_version=ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
                    record_type=ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
                    work=work,
                    student_id="student_1",
                    membership_revision=1,
                    membership_revision_sha256=written.stored.decision_sha256,
                    policy=AttemptSelectionPolicyReference(
                        policy_id=selection_policy.policy_id,
                        policy_revision=1,
                        policy_revision_sha256=policy_write.stored.policy_sha256,
                    ),
                    source_snapshot=derived.source_snapshot,
                    candidates=derived.candidates,
                    selected_attempts=(
                        derived.candidates[0].attempt,
                        derived.candidates[1].attempt,
                    ),
                    decision_revision=1,
                    supersedes_revision=None,
                    actor=AttemptSelectionActor("teacher", "teacher_local"),
                    rationale=None,
                    decided_at=now,
                )
                decision_write = write_attempt_selection_decision_revision(
                    workspace, attempt_decision, authorized_snapshot=authorized
                )
                assert decision_write.disposition == "created"
                assert get_current_attempt_selection_decision_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    "student_1",
                ) is None
                decision_select = select_attempt_selection_decision_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    "student_1",
                    1,
                    authorized_snapshot=authorized,
                    expected_current_decision_revision=None,
                )
                assert decision_select.disposition == "created"
                selection_resolution = resolve_current_attempt_selection(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    "student_1",
                    authorized_snapshot=authorized,
                )
                assert selection_resolution.status == "selected"
                assert selection_resolution.operative_selection is True
                assert selection_resolution.selected is not None
                assert tuple(
                    selected.native.sequence
                    for selected in (
                        selection_resolution.selected.decision.selected_attempts
                    )
                ) == (1, 2)

                before_reassessment = resolve_current_reassessment(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    "student_1",
                    authorized_snapshot=authorized,
                )
                assert before_reassessment.status == "no_decision"
                assert before_reassessment.operative_reassessment is False

                reassessment_policy = ReassessmentPolicy(
                    schema_version=REASSESSMENT_POLICY_SCHEMA_VERSION,
                    record_type=REASSESSMENT_POLICY_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
                    work=work,
                    policy_id="explicit_reassessment",
                    policy_revision=1,
                    supersedes_revision=None,
                    relationship_basis="explicit",
                    allowed_modes=("replace",),
                    actor=ReassessmentActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                reassessment_policy_write = write_reassessment_policy_revision(
                    workspace, reassessment_policy
                )
                assert reassessment_policy_write.disposition == "created"
                assert get_current_reassessment_policy_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    reassessment_policy.policy_id,
                ) is None
                reassessment_policy_select = select_reassessment_policy_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    reassessment_policy.policy_id,
                    1,
                    expected_current_policy_revision=None,
                )
                assert reassessment_policy_select.disposition == "created"

                # Deliberately let the lower-valued/lower-sequence attempt replace
                # the 99-valued later attempt. #31 must not rank by value or number.
                reassessment_decision = ReassessmentDecision(
                    schema_version=REASSESSMENT_DECISION_SCHEMA_VERSION,
                    record_type=REASSESSMENT_DECISION_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
                    work=work,
                    student_id="student_1",
                    attempt_selection=AttemptSelectionDecisionReference(
                        decision_revision=1,
                        decision_sha256=decision_write.stored.decision_sha256,
                    ),
                    policy=ReassessmentPolicyReference(
                        policy_id=reassessment_policy.policy_id,
                        policy_revision=1,
                        policy_revision_sha256=(
                            reassessment_policy_write.stored.policy_sha256
                        ),
                    ),
                    mode="replace",
                    contributing_attempts=(derived.candidates[0].attempt,),
                    replacement_relationships=(
                        ReplacementRelationship(
                            replacement_attempt=derived.candidates[0].attempt,
                            replaced_attempts=(derived.candidates[1].attempt,),
                        ),
                    ),
                    combinations=(),
                    recency_order=(),
                    decision_revision=1,
                    supersedes_revision=None,
                    actor=ReassessmentActor("teacher", "teacher_local"),
                    rationale=None,
                    decided_at=now,
                )
                reassessment_write = write_reassessment_decision_revision(
                    workspace,
                    reassessment_decision,
                    authorized_snapshot=authorized,
                )
                assert reassessment_write.disposition == "created"
                assert get_current_reassessment_decision_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    "student_1",
                ) is None
                reassessment_select = select_reassessment_decision_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    "student_1",
                    1,
                    authorized_snapshot=authorized,
                    expected_current_decision_revision=None,
                )
                assert reassessment_select.disposition == "created"
                reassessment_resolution = resolve_current_reassessment(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    "student_1",
                    authorized_snapshot=authorized,
                )
                assert reassessment_resolution.status == "resolved"
                assert reassessment_resolution.operative_reassessment is True
                assert tuple(
                    selected.native.sequence
                    for selected in reassessment_resolution.contributing_attempts
                ) == (1,)
                assert (
                    reassessment_resolution.replacement_relationships[
                        0
                    ].replaced_attempts[0].native.sequence
                    == 2
                )

                aggregation_inputs = resolve_standard_aggregation_inputs(
                    workspace,
                    GradeItemAggregationBasis(
                        class_id,
                        item.grade_item_id,
                        item.grade_item_revision,
                        stored_item.revision_sha256,
                    ),
                    "student_1",
                    standard_id,
                    proficiency_scale_reference(proficiency_scale),
                    (
                        StandardAggregationCandidateBinding(
                            sources[0], authorized, mapping_profile=None
                        ),
                    ),
                    standards_library=standards_library,
                )
                assert len(aggregation_inputs.entries) == 1
                assert aggregation_inputs.entries[0].status == "excluded"
                assert (
                    aggregation_inputs.entries[0].exclusion_reason
                    == "mapping_not_supplied"
                )
                aggregation_bytes = standard_aggregation_inputs_to_json_bytes(
                    aggregation_inputs
                )
                assert standard_aggregation_inputs_from_json_bytes(
                    aggregation_bytes
                ) == aggregation_inputs
                assert aggregation_inputs.sha256 == hashlib.sha256(
                    aggregation_bytes
                ).hexdigest()

                mapped_outcome = map_native_value(
                    NativePointValue(8, 10),
                    points_signature,
                    points_profile,
                    proficiency_scale,
                )

                def resolved_candidate(
                    outcome,
                    *,
                    eligibility="included",
                    attempt="selected",
                    reassessment="contributing",
                    subject_kind="student",
                    student_id="student_1",
                ):
                    return ResolvedStandardAggregationCandidate(
                        source=sources[0],
                        standard_id=standard_id,
                        result_kind="attempt_points",
                        target_kind="attempt",
                        subject_kind=subject_kind,
                        subject_student_id=student_id,
                        association_state="associated",
                        eligibility_state=eligibility,
                        attempt_state=attempt,
                        reassessment_state=reassessment,
                        membership_reference=(
                            aggregation_inputs.entries[0].membership_reference
                        ),
                        eligibility_reference=(
                            aggregation_inputs.entries[0].eligibility_reference
                        ),
                        attempt_selection_reference=(
                            aggregation_inputs.entries[0].attempt_selection_reference
                            if attempt in {"selected", "not_selected"}
                            else None
                        ),
                        reassessment_reference=(
                            aggregation_inputs.entries[0].reassessment_reference
                            if reassessment in {"contributing", "noncontributing"}
                            else None
                        ),
                        association_reference=association_resolution.reference,
                        mapping_outcome=outcome,
                    )

                def pure_inputs(candidate):
                    return build_standard_aggregation_inputs(
                        GradeItemAggregationBasis(
                            class_id,
                            item.grade_item_id,
                            item.grade_item_revision,
                            stored_item.revision_sha256,
                        ),
                        "student_1",
                        standard_id,
                        proficiency_scale_reference(proficiency_scale),
                        (candidate,),
                    )

                mapped_entry = pure_inputs(
                    resolved_candidate(mapped_outcome)
                ).entries[0]
                assert mapped_entry.status == "performance"
                assert mapped_entry.proficiency_level_id == "ready"
                assert not hasattr(
                    pure_inputs(resolved_candidate(mapped_outcome)), "proficiency"
                )

                native_outcome = type(mapped_outcome)(
                    "native_state",
                    mapped_outcome.profile,
                    mapped_outcome.target_scale,
                    native_state=NativeStateValue("unrated"),
                )
                native_entry = pure_inputs(
                    resolved_candidate(native_outcome)
                ).entries[0]
                assert native_entry.status == "native_state"
                assert native_entry.native_state == NativeStateValue("unrated")

                unmapped_outcome = type(mapped_outcome)(
                    "unmapped", mapped_outcome.profile, mapped_outcome.target_scale
                )
                assert pure_inputs(
                    resolved_candidate(unmapped_outcome)
                ).entries[0].exclusion_reason == "mapping_unmapped"
                unsupported_outcome = type(mapped_outcome)(
                    "unsupported",
                    mapped_outcome.profile,
                    mapped_outcome.target_scale,
                    unsupported_reason="value_kind_mismatch",
                )
                assert pure_inputs(
                    resolved_candidate(unsupported_outcome)
                ).entries[0].exclusion_reason == "mapping_unsupported"
                mismatched_scale = type(mapped_outcome.target_scale)(
                    class_id,
                    proficiency_scale.scale_id,
                    1,
                    "f" * 64,
                )
                mismatch_outcome = type(mapped_outcome)(
                    "mapped",
                    mapped_outcome.profile,
                    mismatched_scale,
                    proficiency_level_id="ready",
                )
                assert pure_inputs(
                    resolved_candidate(mismatch_outcome)
                ).entries[0].exclusion_reason == "scale_mismatch"
                assert pure_inputs(
                    resolved_candidate(None)
                ).entries[0].exclusion_reason == "mapping_not_supplied"
                assert pure_inputs(
                    resolved_candidate(mapped_outcome, eligibility="not_included")
                ).entries[0].exclusion_reason == "eligibility_not_included"
                assert pure_inputs(
                    resolved_candidate(mapped_outcome, attempt="not_selected")
                ).entries[0].exclusion_reason == "attempt_not_selected"
                assert pure_inputs(
                    resolved_candidate(
                        mapped_outcome, reassessment="noncontributing"
                    )
                ).entries[0].exclusion_reason == "reassessment_noncontributing"
                assert pure_inputs(
                    resolved_candidate(
                        mapped_outcome,
                        subject_kind="nonstudent",
                        student_id=None,
                    )
                ).entries[0].exclusion_reason == "nonstudent_target"

                association_v2 = StandardEvidenceAssociationDecision(
                    schema_version=STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
                    record_type=STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
                    source=sources[0],
                    standard_id=standard_id,
                    association_revision=2,
                    supersedes_revision=1,
                    disposition="not_associated",
                    basis="producer_declared",
                    actor=StandardEvidenceActor("teacher", "teacher_local"),
                    rationale="Synthetic historical revision.",
                    decided_at=now,
                )
                write_standard_evidence_association_revision(
                    workspace,
                    association_v2,
                    authorized_snapshot=authorized,
                    standards_library=standards_library,
                )
                assert get_current_standard_evidence_association_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    sources[0],
                    standard_id,
                ) == 1
                assert load_standard_evidence_association_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    sources[0],
                    standard_id,
                    1,
                ).decision == association

                reassessment_policy_v2 = ReassessmentPolicy(
                    schema_version=REASSESSMENT_POLICY_SCHEMA_VERSION,
                    record_type=REASSESSMENT_POLICY_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
                    work=work,
                    policy_id=reassessment_policy.policy_id,
                    policy_revision=2,
                    supersedes_revision=1,
                    relationship_basis="explicit",
                    allowed_modes=("retain", "replace"),
                    actor=ReassessmentActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                write_reassessment_policy_revision(
                    workspace, reassessment_policy_v2
                )
                select_reassessment_policy_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    reassessment_policy.policy_id,
                    2,
                    expected_current_policy_revision=1,
                )
                reassessment_policy_stale = resolve_current_reassessment(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    "student_1",
                    authorized_snapshot=authorized,
                )
                assert reassessment_policy_stale.status == "policy_stale"
                assert reassessment_policy_stale.operative_reassessment is False
                select_reassessment_policy_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    reassessment_policy.policy_id,
                    1,
                    expected_current_policy_revision=2,
                )

                attempt_decision_v2 = AttemptSelectionDecision(
                    schema_version=ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
                    record_type=ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
                    work=work,
                    student_id="student_1",
                    membership_revision=1,
                    membership_revision_sha256=written.stored.decision_sha256,
                    policy=AttemptSelectionPolicyReference(
                        policy_id=selection_policy.policy_id,
                        policy_revision=1,
                        policy_revision_sha256=policy_write.stored.policy_sha256,
                    ),
                    source_snapshot=derived.source_snapshot,
                    candidates=derived.candidates,
                    selected_attempts=(derived.candidates[1].attempt,),
                    decision_revision=2,
                    supersedes_revision=1,
                    actor=AttemptSelectionActor("teacher", "teacher_local"),
                    rationale=None,
                    decided_at=now,
                )
                write_attempt_selection_decision_revision(
                    workspace,
                    attempt_decision_v2,
                    authorized_snapshot=authorized,
                )
                select_attempt_selection_decision_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    "student_1",
                    2,
                    authorized_snapshot=authorized,
                    expected_current_decision_revision=1,
                )
                reassessment_attempt_stale = resolve_current_reassessment(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    "student_1",
                    authorized_snapshot=authorized,
                )
                assert reassessment_attempt_stale.status == "attempt_selection_stale"
                assert reassessment_attempt_stale.operative_reassessment is False

                policy_v2 = AttemptSelectionPolicy(
                    schema_version=ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
                    record_type=ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
                    work=work,
                    policy_id=selection_policy.policy_id,
                    policy_revision=2,
                    supersedes_revision=1,
                    selection_basis="explicit",
                    minimum_selected=0,
                    maximum_selected=2,
                    actor=AttemptSelectionActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                write_attempt_selection_policy_revision(workspace, policy_v2)
                select_attempt_selection_policy_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    selection_policy.policy_id,
                    2,
                    expected_current_policy_revision=1,
                )
                stale = resolve_current_attempt_selection(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    "student_1",
                    authorized_snapshot=authorized,
                )
                assert stale.status == "policy_stale"
                assert stale.operative_selection is False
            finally:
                shutil.rmtree(workspace)

            import meridian
            import pds_core

            prefix = pathlib.Path(sys.prefix).resolve()
            assert pathlib.Path(meridian.__file__).resolve().is_relative_to(prefix)
            assert pathlib.Path(pds_core.__file__).resolve().is_relative_to(prefix)
            assert not (
                {"scoreform", "quillan", "concord", "portia", "vitrine"}
                & set(sys.modules)
            )
            """
        )
        smoke_program = root / "installed_interpretation_smoke.py"
        smoke_program.write_bytes(code.encode("utf-8"))
        _run([str(python), str(smoke_program)], outside)
        if list(outside.iterdir()):
            raise RuntimeError(
                "Grade Item/eligibility smoke test left working-directory residue."
            )


def main(argv: list[str] | None = None) -> int:
    """Parse wheel paths and run the installed interpretation smoke test."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(args.meridian_wheel, args.core_wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
