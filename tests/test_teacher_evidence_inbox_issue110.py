from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from pds_core.academic_catalog import CatalogPublication
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import PublicationRecord
from pds_core.routing_models import ModuleWorkRef

from meridian.diagnostics import (
    PublicationListDiagnostic,
    PublicationObservationDiagnostic,
    PublicationSupportDiagnostic,
)
from meridian.ingestion import (
    CanonicalPublicationContext,
    PublicationCandidate,
    PublicationDiscoveryRequest,
    PublicationSeriesMember,
    PublicationSeriesObservation,
)
from meridian.teacher_evidence_inbox import (
    project_teacher_evidence_inbox,
    teacher_evidence_discovery_request,
)

NOW = datetime(2026, 10, 7, 20, tzinfo=UTC)


def _work(
    *,
    module_id: str = "scoreform",
    class_id: str = "english_12_pd2",
    work_id: str = "memory_snapshot",
) -> ModuleWorkRef:
    return ModuleWorkRef(module_id, class_id, work_id)


def _registration(work: ModuleWorkRef, title: str) -> AcademicWorkRegistration:
    return AcademicWorkRegistration(
        "1",
        "academic_work_registration",
        work,
        1,
        f"{work.module_id}_academic_work_v1",
        title,
        "assignment",
        "formative",
        "active",
        NOW,
        NOW,
        (),
    )


def _publication(
    *,
    publication_id: str,
    work: ModuleWorkRef,
    record_set_id: str = "academic_results",
) -> PublicationRecord:
    return PublicationRecord(
        "1",
        "publication_record",
        publication_id,
        work,
        None,
        "academic_result_set",
        ("standards_ratings",),
        record_set_id,
        1,
        f"{work.module_id}_academic_result_manifest_v1",
        (
            f"classes/{work.class_id}/modules/{work.module_id}/work/"
            f"{work.work_id}/exports/manifests/{record_set_id}/1.json"
        ),
        "sha256",
        "a" * 64,
        NOW,
        1,
        None,
    )


def _context(
    publication: PublicationRecord,
    *,
    title: str,
    state: str = "current_selectable",
) -> CanonicalPublicationContext:
    registration = _registration(publication.work, title)
    series = PublicationSeriesObservation(
        members=(PublicationSeriesMember(publication, None),),
        target_publication_id=publication.publication_id,
        target_index=0,
        head_publication_id=publication.publication_id,
        target_state=state,
        successor_publication_id=None,
    )
    return CanonicalPublicationContext(
        publication,
        registration,
        registration,
        series,
        None,
    )


def _catalog_row(publication: PublicationRecord) -> CatalogPublication:
    return CatalogPublication(
        "2026-2027",
        publication.publication_id,
        publication.work,
        publication.source_record,
        publication.publication_kind,
        publication.capabilities,
        publication.record_set_id,
        publication.record_set_revision,
        publication.manifest_contract_version,
        publication.manifest_path,
        publication.manifest_digest_algorithm,
        publication.manifest_digest,
        publication.published_at,
        publication.academic_work_registration_revision,
        "active",
        1,
        "active",
        publication.supersedes_publication_id,
        True,
        False,
        None,
        True,
    )


def _ready_support(module_id: str = "scoreform") -> PublicationSupportDiagnostic:
    versions = {
        "scoreform": ("0.12.1",),
        "quillan": ("0.10.5",),
        "concord": ("0.3.0",),
    }
    distributions = {
        "scoreform": "scoreform",
        "quillan": "quillan",
        "concord": "pds-concord",
    }
    installed = versions[module_id][0]
    return PublicationSupportDiagnostic(
        profile_state="available",
        compatibility_state="compatible",
        compatibility_codes=(),
        adapter_state="supported",
        adapter_key=None,
        adapter_id=f"{module_id}.academic_result",
        adapter_interface_version="1",
        projection_contract_version="1",
        adapter_supported_capabilities=("standards_ratings",),
        reader_state="ready",
        reader_distribution=distributions[module_id],
        installed_reader_version=installed,
        supported_reader_versions=versions[module_id],
        overall_state="support_ready",
        reason_codes=(),
    )


def _observation(
    *,
    ordinal: int,
    publication_id: str,
    work: ModuleWorkRef | None = None,
    title: str = "Memory Snapshot",
    support: PublicationSupportDiagnostic | None = None,
    canonical_error_code: str | None = None,
    drift_fields: tuple[str, ...] = (),
    context_available: bool = True,
    record_set_id: str = "academic_results",
) -> PublicationObservationDiagnostic:
    selected_work = _work() if work is None else work
    publication = _publication(
        publication_id=publication_id,
        work=selected_work,
        record_set_id=record_set_id,
    )
    context = (
        _context(publication, title=title)
        if context_available
        else None
    )
    return PublicationObservationDiagnostic(
        candidate=PublicationCandidate(_catalog_row(publication), ordinal),
        canonical_context=context,
        canonical_error_code=canonical_error_code,
        drift_fields=drift_fields,  # type: ignore[arg-type]
        support=(
            (_ready_support(selected_work.module_id) if support is None else support)
            if context_available
            else None
        ),
    )


def _diagnostic(
    *observations: PublicationObservationDiagnostic,
) -> PublicationListDiagnostic:
    request: PublicationDiscoveryRequest = teacher_evidence_discovery_request()
    return PublicationListDiagnostic(request, observations)


def test_discovery_request_is_bounded_to_current_academic_results() -> None:
    request = teacher_evidence_discovery_request(
        school_year="2026-2027",
        class_id="english_12_pd2",
        limit=25,
    )

    assert request.query.school_year == "2026-2027"
    assert request.query.class_id == "english_12_pd2"
    assert request.query.publication_kind == "academic_result_set"
    assert request.query.state == "current"
    assert request.query.limit == 25


def test_ready_item_uses_class_id_as_practical_teacher_class_label() -> None:
    observation = _observation(
        ordinal=0,
        publication_id="pub_11111111111111111111111111111111",
    )

    inbox = project_teacher_evidence_inbox(_diagnostic(observation))

    assert inbox.ready_count == 1
    assert inbox.blocked_count == 0
    assert len(inbox.groups) == 1
    group = inbox.groups[0]
    item = group.items[0]

    assert group.class_label == "english_12_pd2"
    assert item.class_label == "english_12_pd2"
    assert item.work_title == "Memory Snapshot"
    assert item.producer_label == "ScoreForm"
    assert item.status_label == "Ready to review"

    assert group.class_id == "english_12_pd2"
    assert item.work.work_id == "memory_snapshot"
    assert item.publication_id == "pub_11111111111111111111111111111111"


def test_reader_unavailable_remains_visible_but_blocked() -> None:
    support = replace(
        _ready_support(),
        reader_state="unavailable",
        installed_reader_version=None,
        overall_state="support_unavailable",
        reason_codes=("adapters.reader_unavailable",),
    )
    observation = _observation(
        ordinal=0,
        publication_id="pub_33333333333333333333333333333333",
        support=support,
    )

    inbox = project_teacher_evidence_inbox(_diagnostic(observation))
    item = inbox.items[0]

    assert item.actionability == "blocked"
    assert item.status_code == "reader_unavailable"
    assert item.status_label == "Reader unavailable"
    assert item.support_reason_codes == ("adapters.reader_unavailable",)


def test_reader_version_mismatch_is_not_hidden() -> None:
    support = replace(
        _ready_support(),
        reader_state="version_unsupported",
        installed_reader_version="0.12.2",
        overall_state="support_unsupported",
        reason_codes=("adapters.reader_version_unsupported",),
    )
    observation = _observation(
        ordinal=0,
        publication_id="pub_44444444444444444444444444444444",
        support=support,
    )

    inbox = project_teacher_evidence_inbox(_diagnostic(observation))

    assert inbox.items[0].status_code == "reader_not_compatible"
    assert inbox.items[0].status_label == "Reader not compatible"


def test_candidate_drift_becomes_refresh_needed_not_ready() -> None:
    observation = _observation(
        ordinal=0,
        publication_id="pub_55555555555555555555555555555555",
        canonical_error_code="ingestion.candidate_drift",
        drift_fields=("series_head",),
    )

    inbox = project_teacher_evidence_inbox(_diagnostic(observation))

    item = inbox.items[0]
    assert item.status_code == "refresh_needed"
    assert item.status_label == "Refresh needed"
    assert item.drift_fields == ("series_head",)


def test_missing_canonical_publication_stays_visible_without_work_id_title() -> None:
    observation = _observation(
        ordinal=0,
        publication_id="pub_66666666666666666666666666666666",
        context_available=False,
        canonical_error_code="ingestion.candidate_missing",
    )

    inbox = project_teacher_evidence_inbox(_diagnostic(observation))

    item = inbox.items[0]
    assert item.actionability == "blocked"
    assert item.status_code == "publication_unavailable"
    assert item.class_label == "english_12_pd2"
    assert item.work_title == "Assignment name unavailable"
    assert item.work.work_id not in item.work_title


def test_groups_preserve_catalog_order_and_exact_class_boundaries() -> None:
    first = _observation(
        ordinal=0,
        publication_id="pub_77777777777777777777777777777777",
        work=_work(),
        title="Memory Snapshot",
    )
    second = _observation(
        ordinal=1,
        publication_id="pub_88888888888888888888888888888888",
        work=_work(
            module_id="quillan",
            class_id="english_10_pd4",
            work_id="desirees_baby",
        ),
        title="Désirée's Baby Analysis",
    )

    inbox = project_teacher_evidence_inbox(_diagnostic(first, second))

    assert tuple(group.class_label for group in inbox.groups) == (
        "english_12_pd2",
        "english_10_pd4",
    )
    assert tuple(item.work_title for item in inbox.items) == (
        "Memory Snapshot",
        "Désirée's Baby Analysis",
    )
    assert tuple(item.producer_label for item in inbox.items) == (
        "ScoreForm",
        "Quillan",
    )


def test_indistinguishable_ready_publications_fail_closed_for_teacher_choice() -> None:
    first = _observation(
        ordinal=0,
        publication_id="pub_99999999999999999999999999999999",
        record_set_id="academic_results_a",
    )
    second = _observation(
        ordinal=1,
        publication_id="pub_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        record_set_id="academic_results_b",
    )

    inbox = project_teacher_evidence_inbox(_diagnostic(first, second))

    assert inbox.ready_count == 0
    assert inbox.blocked_count == 2
    assert all(
        item.status_code == "ambiguous_presentation"
        for item in inbox.items
    )
    assert all(
        item.status_label == "Needs a clearer display label"
        for item in inbox.items
    )
