"""Real Core workspace support for Meridian issue #13 mixed scenarios."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from concord.academic_result_manifest import (
    academic_result_manifest_to_bytes,
    derive_manifest_capabilities,
    with_semantic_projection_digest,
)
from concord.academic_result_reader import read_academic_result_manifest
from concord.pds_publication import (
    get_publication_producer_profile as concord_profile,
)
from pds_core.academic_catalog import PublicationCatalogQuery, rebuild_academic_catalog
from pds_core.publication_compatibility import PublicationProducerRegistry
from pds_core.publication_records import PublicationRecord
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    PublicationManifestRequest,
    PublicationWithdrawalRequest,
    publish_manifest_revision,
    register_academic_work,
    supersede_manifest_revision,
    withdraw_publication,
)
from pds_core.routes import module_work_dir
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef
from quillan.pds_publication import (
    get_publication_producer_profile as quillan_profile,
)
from scoreform.pds_publication import (
    get_publication_producer_profile as scoreform_profile,
)

import meridian.diagnostics as diagnostics
import meridian.ingestion as ingestion
from meridian.adapters import AdapterRegistry
from meridian.evidence import EvidenceInventory
from meridian.projection_cache import (
    ProjectionCacheWriteResult,
    cache_projected_inventory,
)
from tests.concord_test_support import SOURCE as BASE_CONCORD_SOURCE
from tests.concord_test_support import concord_manifest_bytes
from tests.cross_producer_test_support import (
    SECONDARY_STUDENT_ID,
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
    exact_reader_version,
)
from tests.quillan_test_support import quillan_manifest_bytes
from tests.scoreform_test_support import scoreform_manifest_bytes

CLASS_ID = "synthetic_class_2026"

SCOREFORM_WORK = ModuleWorkRef(
    "scoreform",
    CLASS_ID,
    "synthetic_quiz_alpha",
)
QUILLAN_WORK = ModuleWorkRef(
    "quillan",
    CLASS_ID,
    "synthetic_essay_alpha",
)
CONCORD_WORK = ModuleWorkRef(
    "concord",
    CLASS_ID,
    "activity_1",
)
CONCORD_SOURCE = ModuleRecordRef(
    BASE_CONCORD_SOURCE.module_id,
    BASE_CONCORD_SOURCE.record_kind,
    BASE_CONCORD_SOURCE.record_id,
    BASE_CONCORD_SOURCE.contract_version,
)


class AllowMixedProjection:
    """Synthetic authorizer for repository-only acceptance scenarios."""

    def authorize(
        self,
        request: ingestion.PublicationAuthorizationRequest,
    ) -> ingestion.PublicationAuthorizationDecision:
        return ingestion.PublicationAuthorizationDecision(
            True,
            "cross_producer_synthetic_policy",
            "1",
            (),
        )


@dataclass(frozen=True, slots=True)
class MixedWorkspace:
    root: Path
    publications: dict[str, PublicationRecord]
    candidates: dict[str, ingestion.PublicationCandidate]
    producer_registry: PublicationProducerRegistry
    adapter_registry: AdapterRegistry
    authorizer: AllowMixedProjection


@dataclass(frozen=True, slots=True)
class CachedProjection:
    prepared: ingestion.PreparedPublicationInvocation
    inventory: EvidenceInventory
    cached: ProjectionCacheWriteResult


def producer_registry() -> PublicationProducerRegistry:
    """Return all three released academic producer profiles."""
    return PublicationProducerRegistry(
        (
            scoreform_profile(),
            quillan_profile(),
            concord_profile(),
        )
    )


def adapter_registry() -> AdapterRegistry:
    """Use Meridian's real explicit built-in adapter registry."""
    return diagnostics.build_builtin_adapter_registry()


def _manifest_relative(work: ModuleWorkRef, revision: int) -> str:
    return (
        f"classes/{work.class_id}/modules/{work.module_id}/work/{work.work_id}/"
        f"publications/academic_results/{revision}.json"
    )


def _write_manifest(
    workspace: Path,
    work: ModuleWorkRef,
    revision: int,
    content: bytes,
) -> str:
    relative = _manifest_relative(work, revision)
    path = workspace.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return relative


def scoreform_bytes(*, revision: int = 1) -> bytes:
    return scoreform_manifest_bytes(
        revision=revision,
        primary_student_id=SHARED_STUDENT_ID,
        secondary_student_id=SECONDARY_STUDENT_ID,
        primary_standard_id=SHARED_STANDARD_ID,
    )


def quillan_bytes(*, revision: int = 1) -> bytes:
    return quillan_manifest_bytes(
        revision=revision,
        primary_student_id=SHARED_STUDENT_ID,
        secondary_student_id=SECONDARY_STUDENT_ID,
        evidence_standard_id=SHARED_STANDARD_ID,
        rating_value=2,
    )


def concord_bytes() -> bytes:
    """Rebase the released synthetic Concord manifest onto the shared class."""
    original = read_academic_result_manifest(
        concord_manifest_bytes(
            primary_student_id=SHARED_STUDENT_ID,
            secondary_student_id=SECONDARY_STUDENT_ID,
        )
    )
    changed = replace(
        original,
        work=CONCORD_WORK,
        activity_context=replace(
            original.activity_context,
            class_id=CLASS_ID,
        ),
        projection=replace(
            original.projection,
            projection_digest="0" * 64,
        ),
    )
    return academic_result_manifest_to_bytes(
        with_semantic_projection_digest(changed)
    )


def _register_all(workspace: Path) -> None:
    for work in (SCOREFORM_WORK, QUILLAN_WORK, CONCORD_WORK):
        module_work_dir(workspace, work).mkdir(parents=True, exist_ok=True)

    scoreform = register_academic_work(
        workspace,
        AcademicWorkRegistrationRequest(
            work=SCOREFORM_WORK,
            producer_contract_version="scoreform_academic_work_v1",
            title="Synthetic Quiz Alpha",
            work_kind="assignment",
            academic_intent="formative",
            lifecycle="active",
            source_records=(
                ModuleRecordRef(
                    "scoreform",
                    "assignment",
                    SCOREFORM_WORK.work_id,
                    None,
                ),
            ),
        ),
    )
    quillan = register_academic_work(
        workspace,
        AcademicWorkRegistrationRequest(
            work=QUILLAN_WORK,
            producer_contract_version="quillan_academic_work_v1",
            title="Synthetic Essay Alpha",
            work_kind="assignment",
            academic_intent="formative",
            lifecycle="active",
            source_records=(
                ModuleRecordRef(
                    "quillan",
                    "assignment",
                    QUILLAN_WORK.work_id,
                    "2",
                ),
            ),
        ),
    )
    concord = register_academic_work(
        workspace,
        AcademicWorkRegistrationRequest(
            work=CONCORD_WORK,
            producer_contract_version="concord_academic_work_v1",
            title="Synthetic Collaborative Activity",
            work_kind="collaborative_activity",
            academic_intent="formative",
            lifecycle="active",
            source_records=(CONCORD_SOURCE,),
        ),
    )
    assert scoreform.registration.registration_revision == 1
    assert quillan.registration.registration_revision == 1
    assert concord.registration.registration_revision == 1


def _publish_first(
    workspace: Path,
    *,
    work: ModuleWorkRef,
    manifest_bytes: bytes,
    capabilities: tuple[str, ...],
    manifest_contract: str,
    source_record: ModuleRecordRef | None,
) -> PublicationRecord:
    relative = _write_manifest(workspace, work, 1, manifest_bytes)
    result = publish_manifest_revision(
        workspace,
        PublicationManifestRequest(
            work=work,
            source_record=source_record,
            publication_kind="academic_result_set",
            capabilities=capabilities,
            record_set_id="academic_results",
            record_set_revision=1,
            manifest_contract_version=manifest_contract,
            manifest_path=relative,
            academic_work_registration_revision=1,
        ),
    )
    return result.publication


def build_mixed_workspace(tmp_path: Path) -> MixedWorkspace:
    """Create one Core workspace containing all three exact producer contracts."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _register_all(workspace)

    scoreform_manifest = scoreform_bytes()
    quillan_manifest = quillan_bytes()
    concord_manifest = concord_bytes()
    concord_capabilities = tuple(
        derive_manifest_capabilities(
            read_academic_result_manifest(concord_manifest)
        )
    )

    publications = {
        "scoreform": _publish_first(
            workspace,
            work=SCOREFORM_WORK,
            manifest_bytes=scoreform_manifest,
            capabilities=("points", "question_evidence", "multiple_attempts"),
            manifest_contract="scoreform_academic_result_manifest_v1",
            source_record=None,
        ),
        "quillan": _publish_first(
            workspace,
            work=QUILLAN_WORK,
            manifest_bytes=quillan_manifest,
            capabilities=("standards_ratings",),
            manifest_contract="quillan_academic_result_manifest_v1",
            source_record=None,
        ),
        "concord": _publish_first(
            workspace,
            work=CONCORD_WORK,
            manifest_bytes=concord_manifest,
            capabilities=concord_capabilities,
            manifest_contract="concord_academic_result_manifest_v1",
            source_record=CONCORD_SOURCE,
        ),
    }

    rebuild_academic_catalog(workspace)
    candidates: dict[str, ingestion.PublicationCandidate] = {}
    for module_id in ("scoreform", "quillan", "concord"):
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
        assert len(discovered.candidates) == 1
        candidates[module_id] = discovered.candidates[0]
        assert (
            candidates[module_id].publication_id
            == publications[module_id].publication_id
        )

    return MixedWorkspace(
        root=workspace,
        publications=publications,
        candidates=candidates,
        producer_registry=producer_registry(),
        adapter_registry=adapter_registry(),
        authorizer=AllowMixedProjection(),
    )


def prepare_all(
    mixed: MixedWorkspace,
    *,
    requested_student_ids: Iterable[str] = (),
) -> dict[str, ingestion.PreparedPublicationInvocation]:
    students = tuple(requested_student_ids)
    return {
        module_id: ingestion.prepare_publication_invocation(
            mixed.root,
            mixed.candidates[module_id],
            producer_registry=mixed.producer_registry,
            adapter_registry=mixed.adapter_registry,
            authorizer=mixed.authorizer,
            authorization_purpose_id="grading_import",
            requested_student_ids=students,
            distribution_version_resolver=exact_reader_version,
        )
        for module_id in ("scoreform", "quillan", "concord")
    }


def project_and_cache_all(
    mixed: MixedWorkspace,
    prepared: dict[str, ingestion.PreparedPublicationInvocation],
) -> dict[str, CachedProjection]:
    result: dict[str, CachedProjection] = {}
    for module_id in ("scoreform", "quillan", "concord"):
        value = prepared[module_id]
        inventory = mixed.adapter_registry.invoke(
            value.projection_request,
            exact_reader_version,
        )
        cached = cache_projected_inventory(
            mixed.root,
            value,
            inventory,
            authorizer=mixed.authorizer,
        )
        result[module_id] = CachedProjection(value, inventory, cached)
    return result


def supersede_scoreform(mixed: MixedWorkspace) -> PublicationRecord:
    """Create a canonical ScoreForm record-set revision 2."""
    manifest = scoreform_bytes(revision=2)
    relative = _write_manifest(mixed.root, SCOREFORM_WORK, 2, manifest)
    result = supersede_manifest_revision(
        mixed.root,
        PublicationManifestRequest(
            work=SCOREFORM_WORK,
            source_record=None,
            publication_kind="academic_result_set",
            capabilities=("points", "question_evidence", "multiple_attempts"),
            record_set_id="academic_results",
            record_set_revision=2,
            manifest_contract_version="scoreform_academic_result_manifest_v1",
            manifest_path=relative,
            academic_work_registration_revision=1,
        ),
        expected_current_publication_id=(
            mixed.publications["scoreform"].publication_id
        ),
    )
    return result.publication


def withdraw_quillan(mixed: MixedWorkspace) -> None:
    withdraw_publication(
        mixed.root,
        PublicationWithdrawalRequest(
            mixed.publications["quillan"].publication_id,
            "Synthetic cross-producer withdrawal",
        ),
    )
