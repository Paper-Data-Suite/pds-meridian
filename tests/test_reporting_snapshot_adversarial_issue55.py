from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.publication_storage import publication_record_path

import meridian.current_grade_preview as current_preview
import meridian.reporting_snapshot_freeze as freeze_module
import tests.test_issue50_cross_producer_acceptance as issue50
import tests.test_issue51_cross_producer_acceptance as issue51
import tests.test_reporting_snapshot_grade_families_issue55 as family55
import tests.test_reporting_snapshot_override_states_issue55 as state55
from meridian.academic_period_proficiency_storage import (
    academic_period_proficiency_result_revision_path,
)
from meridian.attempt_selection_storage import (
    attempt_selection_decision_revision_path,
)
from meridian.conventional_grade_storage import conventional_grade_result_revision_path
from meridian.evidence_eligibility_storage import evidence_eligibility_revision_path
from meridian.grade_item_membership_storage import grade_item_membership_revision_path
from meridian.grade_policy_storage import grade_policy_revision_path
from meridian.grade_preview_explanation import (
    GradePreviewCurrentnessConflictError,
    GradePreviewTarget,
)
from meridian.grade_report_preview import GradeReportPreviewRequest
from meridian.reassessment_storage import reassessment_decision_revision_path
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionRevision,
)
from meridian.reporting_snapshot_freeze import (
    ReportingSnapshotCurrentnessConflictError,
    ReportingSnapshotFreezeIntegrityError,
    freeze_reporting_snapshot,
)
from meridian.reporting_snapshot_record import (
    reporting_snapshot_build_request_from_preview_requests,
)
from meridian.reporting_snapshot_storage import (
    list_reporting_snapshot_ids,
    write_reporting_definition_revision,
)
from meridian.teacher_grade_override_lifecycle import (
    commit_teacher_grade_override_selection_preview,
    preview_teacher_grade_override_selection,
)
from meridian.teacher_grade_override_storage import teacher_grade_override_revision_path
from meridian.teacher_grade_override_workflow import (
    commit_teacher_grade_override_authoring_preview,
    preview_teacher_grade_override_authoring,
)
from tests.cross_producer_proficiency_support import ACTOR_ID, source_reference
from tests.cross_producer_test_support import SHARED_STANDARD_ID, SHARED_STUDENT_ID
from tests.cross_producer_workspace_support import CLASS_ID, SCOREFORM_WORK

NOW = datetime(2026, 9, 21, 13, 0, tzinfo=UTC)


def _target(family: str) -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=SHARED_STUDENT_ID,
        target_period=issue51.PERIOD,
        calendar_revision=1,
        calculation_family=family,  # type: ignore[arg-type]
    )


def _prepare_freeze(
    root: Path,
    *,
    suffix: str,
    family: str,
    work_evidence=None,
):
    definition = ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS_ID,
        definition_id=f"issue55_adversarial_{suffix}",
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose="issue55_adversarial_acceptance",
        title=f"Issue 55 adversarial {suffix}",
        target_period=issue51.PERIOD,
        intended_audience="teacher",
        actor=ReportingActor("teacher", ACTOR_ID),
        rationale="Issue #55 BI-BL adversarial qualification.",
        revised_at=NOW,
    )
    stored_definition = write_reporting_definition_revision(root, definition).stored
    request = GradeReportPreviewRequest(
        _target(family),
        work_evidence=work_evidence,
    )
    build = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=stored_definition.reference,
        requests=(request,),
        actor=ReportingActor("teacher", ACTOR_ID),
        requested_at=NOW + timedelta(minutes=1),
        rationale="Adversarial ReportingSnapshot freeze.",
    )
    return request, build


def _freeze_expected_to_fail(
    root: Path,
    *,
    snapshot_id: str,
    request: GradeReportPreviewRequest,
    build,
    error_type: type[Exception] = ReportingSnapshotFreezeIntegrityError,
):
    with pytest.raises(error_type):
        freeze_reporting_snapshot(
            root,
            snapshot_id=snapshot_id,
            build_request=build,
            preview_requests=(request,),
            created_at=NOW + timedelta(minutes=2),
        )
    assert snapshot_id not in list_reporting_snapshot_ids(root, CLASS_ID)


def _corrupt_temporarily(path: Path):
    original = path.read_bytes()
    path.write_bytes(b"{}\n")
    return original


def test_row_level_movement_reuses_issue54_currentness_and_commits_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, root = family55._setup_standards(tmp_path)
    request, build = _prepare_freeze(
        root,
        suffix="row_movement",
        family="standards_based",
    )
    original_capture = current_preview._capture_current_state
    calls = 0

    def moving_capture(*args, **kwargs):
        nonlocal calls
        state = original_capture(*args, **kwargs)
        calls += 1
        if calls == 2:
            return SimpleNamespace(snapshot=state.snapshot, witness=object())
        return state

    monkeypatch.setattr(current_preview, "_capture_current_state", moving_capture)

    with pytest.raises(ReportingSnapshotFreezeIntegrityError) as raised:
        freeze_reporting_snapshot(
            root,
            snapshot_id="issue55_row_movement_snapshot",
            build_request=build,
            preview_requests=(request,),
            created_at=NOW + timedelta(minutes=2),
        )
    assert isinstance(raised.value.__cause__, GradePreviewCurrentnessConflictError)
    assert list_reporting_snapshot_ids(root, CLASS_ID) == ()


def test_report_level_movement_after_candidate_is_currentness_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, root = family55._setup_standards(tmp_path)
    request, build = _prepare_freeze(
        root,
        suffix="report_movement",
        family="standards_based",
    )
    original_report = freeze_module.explain_grade_report_preview
    calls = 0

    def moving_report(*args, **kwargs):
        nonlocal calls
        preview = original_report(*args, **kwargs)
        calls += 1
        if calls == 1:
            state55._activate_later_standards_policy(root)
        return preview

    monkeypatch.setattr(freeze_module, "explain_grade_report_preview", moving_report)

    _freeze_expected_to_fail(
        root,
        snapshot_id="issue55_report_movement_snapshot",
        request=request,
        build=build,
        error_type=ReportingSnapshotCurrentnessConflictError,
    )


def test_broken_core_publication_or_projection_provenance_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, root, evidence, _ = family55._setup_conventional(tmp_path, monkeypatch)
    request, build = _prepare_freeze(
        root,
        suffix="broken_core",
        family="conventional",
        work_evidence=evidence,
    )
    authorized = scenario.authorized["scoreform"]
    publication = scenario.mixed.publications["scoreform"]
    manifest_path = root.joinpath(*publication.manifest_path.split("/"))
    cases = (
        ("projection_cache", authorized.stored.path),
        (
            "publication_record",
            publication_record_path(root, publication.publication_id),
        ),
        ("publication_manifest", manifest_path),
    )

    for name, path in cases:
        original = _corrupt_temporarily(path)
        try:
            _freeze_expected_to_fail(
                root,
                snapshot_id=f"issue55_broken_core_{name}",
                request=request,
                build=build,
            )
        finally:
            path.write_bytes(original)


def _selected_source_for_eligibility(scenario):
    projection = scenario.projected["scoreform"]
    item = next(
        value
        for value in projection.inventory.items
        if value.subject is not None
        and value.subject.student_id == SHARED_STUDENT_ID
    )
    return source_reference(projection, item)


def test_broken_conventional_meridian_provenance_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, root, evidence, _ = family55._setup_conventional(tmp_path, monkeypatch)
    authoring = preview_teacher_grade_override_authoring(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue51.PERIOD,
        1,
        "conventional",
        replacement_grade=Decimal("93.5"),
        actor_id=ACTOR_ID,
        rationale="Issue #55 BL exact override provenance.",
        decided_at=NOW,
        work_evidence=evidence,
    )
    authored = commit_teacher_grade_override_authoring_preview(root, authoring)
    selection = preview_teacher_grade_override_selection(
        root, authored.stored_reference
    )
    commit_teacher_grade_override_selection_preview(root, selection)

    request, build = _prepare_freeze(
        root,
        suffix="broken_meridian",
        family="conventional",
        work_evidence=evidence,
    )
    source = _selected_source_for_eligibility(scenario)
    paths = {
        "membership": grade_item_membership_revision_path(
            root,
            CLASS_ID,
            issue50.GRADE_ITEM_ID,
            SCOREFORM_WORK,
            1,
        ),
        "eligibility": evidence_eligibility_revision_path(
            root,
            CLASS_ID,
            issue50.GRADE_ITEM_ID,
            source,
            1,
        ),
        "attempt": attempt_selection_decision_revision_path(
            root,
            CLASS_ID,
            issue50.GRADE_ITEM_ID,
            SCOREFORM_WORK,
            SHARED_STUDENT_ID,
            1,
        ),
        "reassessment": reassessment_decision_revision_path(
            root,
            CLASS_ID,
            issue50.GRADE_ITEM_ID,
            SCOREFORM_WORK,
            SHARED_STUDENT_ID,
            1,
        ),
        "policy": grade_policy_revision_path(
            root,
            CLASS_ID,
            family55.TWO_ITEM_POLICY_ID,
            1,
        ),
        "grade_result": conventional_grade_result_revision_path(
            root,
            CLASS_ID,
            SHARED_STUDENT_ID,
            issue51.PERIOD,
            1,
            1,
        ),
        "override": teacher_grade_override_revision_path(
            root,
            CLASS_ID,
            SHARED_STUDENT_ID,
            issue51.PERIOD,
            1,
            "conventional",
            1,
        ),
    }

    for name, path in paths.items():
        original = _corrupt_temporarily(path)
        try:
            _freeze_expected_to_fail(
                root,
                snapshot_id=f"issue55_broken_meridian_{name}",
                request=request,
                build=build,
            )
        finally:
            path.write_bytes(original)


def test_broken_proficiency_provenance_fails_closed(tmp_path: Path) -> None:
    _, root = family55._setup_standards(tmp_path)
    request, build = _prepare_freeze(
        root,
        suffix="broken_proficiency",
        family="standards_based",
    )
    path = academic_period_proficiency_result_revision_path(
        root,
        CLASS_ID,
        issue51.SCHOOL_YEAR,
        issue51.PERIOD_ID,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        1,
    )
    original = _corrupt_temporarily(path)
    try:
        _freeze_expected_to_fail(
            root,
            snapshot_id="issue55_broken_proficiency",
            request=request,
            build=build,
        )
    finally:
        path.write_bytes(original)
