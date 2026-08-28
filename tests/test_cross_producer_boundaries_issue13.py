from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pds_core.academic_catalog import PublicationCatalogQuery, rebuild_academic_catalog
from pds_core.academic_period_storage import (
    load_current_academic_period_calendar,
    write_academic_period_calendar,
)
from pds_core.academic_periods import (
    ACADEMIC_PERIOD_CALENDAR_RECORD_TYPE,
    ACADEMIC_PERIOD_CALENDAR_SCHEMA_VERSION,
    AcademicPeriod,
    AcademicPeriodCalendar,
)

import meridian.diagnostics as diagnostics
import meridian.ingestion as ingestion
from meridian.projection_cache import load_authorized_projection_snapshot
from tests.cross_producer_test_support import exact_reader_version
from tests.cross_producer_workspace_support import (
    CLASS_ID,
    build_mixed_workspace,
    prepare_all,
    project_and_cache_all,
)

SCHOOL_YEAR = "2026-2027"
CALENDAR_CREATED = datetime(2026, 8, 18, 12, tzinfo=UTC)


def _calendar(revision: int) -> AcademicPeriodCalendar:
    q2_label = "Quarter 2" if revision == 1 else "Quarter 2 revised"
    return AcademicPeriodCalendar(
        schema_version=ACADEMIC_PERIOD_CALENDAR_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_CALENDAR_RECORD_TYPE,
        school_year=SCHOOL_YEAR,
        calendar_revision=revision,
        created_at=CALENDAR_CREATED,
        updated_at=CALENDAR_CREATED.replace(hour=12 + revision),
        periods=(
            AcademicPeriod(
                period_id="period_q1",
                period_type="quarter",
                label="Quarter 1",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 11, 6),
                parent_period_id=None,
                sequence=1,
                lifecycle="active",
            ),
            AcademicPeriod(
                period_id="period_q2",
                period_type="quarter",
                label=q2_label,
                start_date=date(2026, 11, 9),
                end_date=date(2027, 1, 22),
                parent_period_id=None,
                sequence=2,
                lifecycle="planned",
            ),
        ),
    )


def test_multiple_period_calendar_and_revision_do_not_change_raw_projection_cache(
    tmp_path: Path,
) -> None:
    mixed = build_mixed_workspace(tmp_path)
    write_academic_period_calendar(
        mixed.root,
        _calendar(1),
        expected_current_revision=None,
    )
    rebuild_academic_catalog(mixed.root)

    current = load_current_academic_period_calendar(mixed.root, SCHOOL_YEAR)
    assert current is not None
    assert current.calendar_revision == 1
    assert {period.period_id for period in current.periods} == {
        "period_q1",
        "period_q2",
    }

    projected = project_and_cache_all(mixed, prepare_all(mixed))
    original = {
        module_id: (
            value.cached.stored.cache_key,
            value.cached.stored.content,
        )
        for module_id, value in projected.items()
    }
    for value in projected.values():
        assert all(
            not hasattr(item, "period_id")
            and not hasattr(item, "academic_period")
            for item in value.inventory.items
        )

    write_academic_period_calendar(
        mixed.root,
        _calendar(2),
        expected_current_revision=1,
    )
    rebuild_academic_catalog(mixed.root)
    changed = load_current_academic_period_calendar(mixed.root, SCHOOL_YEAR)
    assert changed is not None
    assert changed.calendar_revision == 2
    assert next(
        period.label
        for period in changed.periods
        if period.period_id == "period_q2"
    ) == "Quarter 2 revised"

    for module_id, value in projected.items():
        cache_key, content = original[module_id]
        loaded = load_authorized_projection_snapshot(
            mixed.root,
            mixed.publications[module_id].publication_id,
            cache_key,
            authorizer=mixed.authorizer,
            authorization_purpose_id="grading_import",
            producer_registry=mixed.producer_registry,
            adapter_registry=mixed.adapter_registry,
            distribution_version_resolver=exact_reader_version,
        )
        assert loaded.assessment.source_status == "current"
        assert loaded.assessment.reuse_status == "reusable"
        assert loaded.assessment.reason_codes == ()
        assert loaded.stored.cache_key == cache_key
        assert loaded.stored.content == content


def test_mixed_diagnostics_keep_reader_failure_local_to_one_publication(
    tmp_path: Path,
) -> None:
    mixed = build_mixed_workspace(tmp_path)

    versions = {
        "scoreform": "0.11.0",
        "quillan": "0.10.1",
        "pds-concord": "0.2.0",
    }
    dependencies = diagnostics.DiagnosticsDependencies(
        producer_registry=mixed.producer_registry,
        adapter_registry=mixed.adapter_registry,
        distribution_version_resolver=versions.__getitem__,
    )
    request = ingestion.PublicationDiscoveryRequest(
        PublicationCatalogQuery(
            class_id=CLASS_ID,
            publication_kind="academic_result_set",
            state="current",
            limit=10,
        )
    )
    result = diagnostics.list_publication_diagnostics(
        mixed.root,
        request,
        dependencies,
    )
    by_module = {
        observation.candidate.catalog_publication.module_id: observation
        for observation in result.observations
    }
    assert set(by_module) == {"scoreform", "quillan", "concord"}

    scoreform = by_module["scoreform"].support
    quillan = by_module["quillan"].support
    concord = by_module["concord"].support
    assert scoreform is not None
    assert quillan is not None
    assert concord is not None

    assert scoreform.overall_state == "support_ready"
    assert scoreform.reader_state == "ready"
    assert scoreform.installed_reader_version == "0.11.0"

    assert quillan.overall_state == "support_unsupported"
    assert quillan.reader_state == "version_unsupported"
    assert quillan.installed_reader_version == "0.10.1"
    assert quillan.reason_codes == ("adapters.reader_version_unsupported",)

    assert concord.overall_state == "support_ready"
    assert concord.reader_state == "ready"
    assert concord.installed_reader_version == "0.2.0"


class DenyQuillanProjection:
    def authorize(
        self,
        request: ingestion.PublicationAuthorizationRequest,
    ) -> ingestion.PublicationAuthorizationDecision:
        if request.publication.work.module_id == "quillan":
            return ingestion.PublicationAuthorizationDecision(
                False,
                "cross_producer_selective_policy",
                "1",
                ("authorization.synthetic_denied",),
            )
        return ingestion.PublicationAuthorizationDecision(
            True,
            "cross_producer_selective_policy",
            "1",
            (),
        )


def test_authorization_denial_is_local_and_precedes_manifest_access(
    tmp_path: Path,
) -> None:
    mixed = build_mixed_workspace(tmp_path)
    authorizer = DenyQuillanProjection()

    quillan_candidate = mixed.candidates["quillan"]
    quillan_manifest = mixed.root.joinpath(
        *quillan_candidate.catalog_publication.manifest_path.split("/")
    )
    quillan_manifest.unlink()

    with pytest.raises(ingestion.PublicationAuthorizationDeniedError) as caught:
        ingestion.prepare_publication_invocation(
            mixed.root,
            quillan_candidate,
            producer_registry=mixed.producer_registry,
            adapter_registry=mixed.adapter_registry,
            authorizer=authorizer,
            authorization_purpose_id="grading_import",
            distribution_version_resolver=exact_reader_version,
        )
    assert caught.value.publication_id == mixed.publications["quillan"].publication_id
    assert caught.value.reason_codes == ("authorization.synthetic_denied",)

    for module_id in ("scoreform", "concord"):
        prepared = ingestion.prepare_publication_invocation(
            mixed.root,
            mixed.candidates[module_id],
            producer_registry=mixed.producer_registry,
            adapter_registry=mixed.adapter_registry,
            authorizer=authorizer,
            authorization_purpose_id="grading_import",
            distribution_version_resolver=exact_reader_version,
        )
        assert prepared.authorization.allowed is True
        assert prepared.canonical_context.publication.work.module_id == module_id
