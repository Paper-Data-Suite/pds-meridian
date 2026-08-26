"""Smoke-test Grade Item, membership, and eligibility from an installed wheel."""

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

            from meridian.adapters import AdapterKey
            from meridian.evidence import (
                EvidenceInventory,
                EvidenceItem,
                EvidenceProvenance,
                EvidenceTarget,
                NativeProvenance,
                NativeReference,
                NativeScalarValue,
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
            from meridian.grade_item_storage import write_grade_item_revision
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
                    capabilities=("points",),
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
                evidence = EvidenceItem(
                    item_id="evidence_1",
                    subject=StudentSubject("student_1"),
                    target=EvidenceTarget("attempt", "attempt_1"),
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
                snapshot = ProjectionSnapshot(
                    schema_version=PROJECTION_SNAPSHOT_SCHEMA_VERSION,
                    record_type=PROJECTION_SNAPSHOT_RECORD_TYPE,
                    cache_key=cache_key,
                    captured_at=now,
                    source=projection_source,
                    projection=projection,
                    authorization=projection_authorization,
                    inventory=EvidenceInventory((evidence,)),
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
                source = EvidenceSourceReference(
                    work=work,
                    publication_id=publication_id,
                    cache_key=cache_key,
                    snapshot_digest=snapshot_digest,
                    item_id=evidence.item_id,
                )
                source_state = observe_evidence_source_state(workspace, source)
                assert source_state.state == "current"

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
        _run([str(python), "-c", code], outside)
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
