"""Issue #117: Concord v0.3.2 installed Report 9 teacher acceptance.

Executed only inside the prepared Concord-only installed matrix. All records
are synthetic, and the authorization grant exists only in this smoke process.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.classes import ensure_class_folder, write_class_roster
from pds_core.publication_records import PublicationCapability
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    PublicationManifestRequest,
    publish_manifest_revision,
    register_academic_work,
)
from pds_core.rosters import create_roster
from pds_core.routes import module_work_dir
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef

from meridian.diagnostics import default_diagnostics_dependencies
from meridian.ingestion import (
    PublicationAuthorizationDecision,
    PublicationAuthorizationRequest,
)

if TYPE_CHECKING:
    from scripts.installed_benchmark_helpers import (
        run_installed_benchmark_teacher_journey,
        setup_installed_benchmark_records,
    )
elif __package__:
    # Pytest imports this program through the scripts package.
    from scripts.installed_benchmark_helpers import (
        run_installed_benchmark_teacher_journey,
        setup_installed_benchmark_records,
    )
else:
    # The installed matrix executes this program as a standalone file.
    from installed_benchmark_helpers import (
        run_installed_benchmark_teacher_journey,
        setup_installed_benchmark_records,
    )

_NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)
_CLASS = "english_12_pd2"
_WORK_ID = "concord_benchmark_1"
_STANDARD = "njsls-ela:2023:rl-cr-11-12-1"


def _assert_installed_origin(module: object) -> None:
    candidate = getattr(module, "__file__", None)
    if not isinstance(candidate, str):
        raise AssertionError("Installed package has no file location.")
    if not Path(candidate).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise AssertionError("A source checkout shadowed an installed package.")


class _SyntheticTeacherAuthorization:
    """Explicit local test-only grant. Never installed as a production policy."""

    def authorize(
        self, request: PublicationAuthorizationRequest
    ) -> PublicationAuthorizationDecision:
        if request.purpose_id != "teacher_reporting":
            raise AssertionError("Unexpected reporting authorization purpose.")
        return PublicationAuthorizationDecision(
            allowed=True,
            policy_id="issue117_concord_installed_smoke",
            policy_version="1",
        )


def _manifest(work: ModuleWorkRef) -> tuple[bytes, tuple[PublicationCapability, ...]]:
    """Create a genuine native Concord manifest with individual and shared scores."""
    import concord
    from concord.academic_result_manifest import (
        ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
        ACADEMIC_RESULT_MANIFEST_RECORD_TYPE,
        AcademicResultManifest,
        ActivityContextProjection,
        CriterionProjection,
        CriterionSetProjection,
        ManifestProjection,
        ManifestRecordSet,
        PrivacyProjection,
        PublicActor,
        ScaleLevelProjection,
        ScoreProjection,
        ScoringScaleProjection,
        StandardsResultProjection,
        TargetReferenceProjection,
        academic_result_manifest_to_bytes,
        derive_manifest_capabilities,
        with_semantic_projection_digest,
    )
    from concord.academic_result_reader import read_academic_result_manifest

    _assert_installed_origin(concord)
    if importlib.metadata.version("pds-concord") != "0.3.2":
        raise AssertionError("Installed Concord must be exactly v0.3.2.")
    teacher = PublicActor("authorized_adult", "issue117_teacher", "concord")
    manifest = AcademicResultManifest(
        record_type=ACADEMIC_RESULT_MANIFEST_RECORD_TYPE,
        contract_version=ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
        producer_module_id="concord",
        generated_at=_NOW,
        record_set=ManifestRecordSet("academic_results", 1),
        work=work,
        source_activity=ModuleRecordRef(
            "concord", "activity", work.work_id, "concord_activity_v1"
        ),
        projection=ManifestProjection(
            source_snapshot_revision=1,
            projection_digest_algorithm="sha256",
            projection_digest="0" * 64,
            generated_by=teacher,
            revision_reason="initial",
        ),
        activity_context=ActivityContextProjection(
            activity_id=work.work_id,
            class_id=work.class_id,
            title="Concord installed benchmark and group work",
            scoring_orientation="mixed",
            standards_profile_id=None,
            focus_standard_ids=(_STANDARD,),
            criterion_set_ids=("set_group", "set_student"),
        ),
        criterion_sets=(
            CriterionSetProjection(
                "set_group", "a_group", 1, "local", "activity_specific",
                ("criterion_group",), "active", None, None,
            ),
            CriterionSetProjection(
                "set_student", "b_student", 1, "standard_backed",
                "activity_specific", ("criterion_student",), "active", None,
                None,
            ),
        ),
        criteria=(
            CriterionProjection(
                "criterion_group", "set_group", "collaboration",
                "Collaboration", "Collaborates on group evidence.", "local",
                ("concord_group",), "active", None, (), "scale_group",
            ),
            CriterionProjection(
                "criterion_student", "set_student", "analysis",
                "Analysis", "Cites evidence accurately.", "standard_backed",
                ("core_student",), "active", _STANDARD, (), "scale_student",
            ),
        ),
        scoring_scales=(
            ScoringScaleProjection(
                "scale_group", "a_group", "Group scale", 1, "ordinal",
                (
                    ScaleLevelProjection(
                        "needs_support", "Needs support", "Developing", 1, None
                    ),
                    ScaleLevelProjection(
                        "collaborative", "Collaborative", "Effective", 2, None
                    ),
                ),
                "active", None,
            ),
            ScoringScaleProjection(
                "scale_student", "b_student", "Standards scale", 1, "ordinal",
                (
                    ScaleLevelProjection(
                        "approaching", "Approaching", "Partial", 1, None
                    ),
                    ScaleLevelProjection("meeting", "Meeting", "Achieved", 2, None),
                ),
                "active", None,
            ),
        ),
        scores=(
            ScoreProjection(
                score_record_id="a_group_score", activity_id=work.work_id,
                session_id=None,
                target_reference=TargetReferenceProjection(
                    "concord_group", "group_alpha", "concord", None,
                ),
                criterion_id="criterion_group", score_kind="local",
                standard_id=None, scoring_scale_id="scale_group",
                disposition="scored", value="collaborative",
                basis="professional_judgment", scorer=teacher, scored_at=_NOW,
                moderation_complete=True, status_reason=None,
                supersedes_score_record_id=None, current_state="current",
            ),
            ScoreProjection(
                score_record_id="b_student_score", activity_id=work.work_id,
                session_id=None,
                target_reference=TargetReferenceProjection(
                    "core_student", "student_alpha", "core", None,
                ),
                criterion_id="criterion_student", score_kind="standard_backed",
                standard_id=_STANDARD, scoring_scale_id="scale_student",
                disposition="scored", value="meeting",
                basis="professional_judgment", scorer=teacher, scored_at=_NOW,
                moderation_complete=True, status_reason=None,
                supersedes_score_record_id=None, current_state="current",
            ),
        ),
        score_evidence_links=(),
        moderation_records=(),
        standards_result_projection=(
            StandardsResultProjection("b_student_score", _STANDARD),
        ),
        privacy=PrivacyProjection("teacher_restricted", (), None, None),
    )
    validated = with_semantic_projection_digest(manifest)
    canonical = academic_result_manifest_to_bytes(validated)
    restored = read_academic_result_manifest(canonical)
    if restored != validated:
        raise AssertionError("Installed Concord reader changed native manifest.")
    capabilities = derive_manifest_capabilities(restored)
    if (
        "criterion_scores" not in capabilities
        or "standards_ratings" not in capabilities
    ):
        raise AssertionError("Concord capabilities were not derived correctly.")
    return canonical, capabilities


def _create_publication(
    workspace: Path, work: ModuleWorkRef
) -> str:
    canonical, capabilities = _manifest(work)
    workspace.mkdir(parents=True)
    ensure_class_folder(workspace, work.class_id)
    write_class_roster(
        workspace,
        create_roster(
            work.class_id,
            (
                {
                    "student_id": "student_alpha", "last_name": "Rivera",
                    "first_name": "Alex", "period": "2",
                },
            ),
        ),
    )
    work_root = module_work_dir(workspace, work)
    work_root.mkdir(parents=True, exist_ok=False)
    registered = register_academic_work(
        workspace,
        AcademicWorkRegistrationRequest(
            work=work,
            producer_contract_version="concord_activity_v1",
            title="Installed Concord Benchmark",
            work_kind="assignment",
            academic_intent="summative",
            lifecycle="active",
            source_records=(),
        ),
    )
    if registered.registration.registration_revision != 1:
        raise AssertionError("Expected registration revision 1.")
    manifest_file = work_root / "exports" / "manifests" / "academic_results" / "1.json"
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_bytes(canonical)
    relative = manifest_file.relative_to(workspace).as_posix()
    published = publish_manifest_revision(
        workspace,
        PublicationManifestRequest(
            work=work,
            source_record=None,
            publication_kind="academic_result_set",
            capabilities=capabilities,
            record_set_id="academic_results",
            record_set_revision=1,
            manifest_contract_version="concord_academic_result_manifest_v1",
            manifest_path=relative,
            academic_work_registration_revision=1,
            expected_manifest_digest=hashlib.sha256(canonical).hexdigest(),
        ),
    )
    rebuild_academic_catalog(workspace)
    return published.publication.publication_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args(argv)
    import pds_core

    import meridian

    _assert_installed_origin(meridian)
    _assert_installed_origin(pds_core)
    if importlib.metadata.version("pds-core") != "0.6.6":
        raise AssertionError("Core must be the published v0.6.6 wheel.")
    work = ModuleWorkRef("concord", _CLASS, _WORK_ID)
    publication_id = _create_publication(args.workspace, work)
    setup_installed_benchmark_records(
        args.workspace, work, "Installed Concord Benchmark"
    )
    os.environ["PDS_WORKSPACE_ROOT"] = str(args.workspace)
    diagnostics = default_diagnostics_dependencies(
        authorizer=_SyntheticTeacherAuthorization(),
        workspace_root=args.workspace,
    )
    run_installed_benchmark_teacher_journey(
        args.workspace, work, diagnostics, publication_id=publication_id
    )
    print("Issue #117 Concord installed benchmark journey passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
