from __future__ import annotations

from datetime import timedelta

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.report_export_roster import (
    build_export_roster_observation,
    export_roster_observation_to_json_bytes,
)
from meridian.reporting_snapshot import (
    ReportingActor,
    ReportingSnapshotValidationError,
    reporting_definition_revision_from_dict,
    reporting_definition_revision_to_dict,
)
from meridian.reporting_snapshot_record import (
    ReportingSnapshotBuildRequest,
    ReportingSnapshotGradeRequest,
    ReportingSnapshotProjectionInputReference,
    ReportingSnapshotWorkEvidenceRequest,
    reporting_snapshot_build_request_to_json_bytes,
)
from tests import test_report_export_roster_issue56 as roster_support
from tests import test_reporting_snapshot_contract_issue55 as contract_support
from tests import test_reporting_snapshot_record_issue55 as record_support
from tests import test_v02_release_audit_privacy_export as privacy_support


def test_issue61_authorization_precedes_protected_projection_read() -> None:
    tree = privacy_support._module_tree("projection_cache.py")
    function = privacy_support._function(
        tree,
        "load_authorized_projection_snapshot",
    )

    authorization = privacy_support._called_name_lines(function, "_authorize")
    protected_reads = privacy_support._called_name_lines(
        function,
        "_stored_from_path",
    )

    assert len(authorization) == 2
    assert len(protected_reads) == 1
    assert authorization[0] < protected_reads[0] < authorization[1]


def test_issue61_base_proficiency_explanation_does_not_open_protected_detail() -> None:
    tree = privacy_support._module_tree("grade_item_proficiency_explanation.py")
    base = privacy_support._function(tree, "explain_grade_item_proficiency")

    forbidden = {
        "inspect_evidence_diagnostic",
        "load_authorized_projection_snapshot",
        "_resolve_authorized_evidence_detail",
    }
    observed = {
        node.func.id
        for node in privacy_support.ast.walk(base)
        if isinstance(node, privacy_support.ast.Call)
        and isinstance(node.func, privacy_support.ast.Name)
    }

    assert observed.isdisjoint(forbidden)


@pytest.mark.parametrize("audience", ("student", "guardian"))
def test_issue61_reporting_definition_remains_teacher_only(
    audience: str,
) -> None:
    data = reporting_definition_revision_to_dict(contract_support.definition())
    data["intended_audience"] = audience

    with pytest.raises(
        ReportingSnapshotValidationError,
        match="intended_audience must be teacher",
    ):
        reporting_definition_revision_from_dict(data)


def test_issue61_reporting_build_request_keeps_projection_identity_not_payload(
) -> None:
    projection = ReportingSnapshotProjectionInputReference(
        "pub_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "1" * 64,
        "2" * 64,
    )
    evidence = ReportingSnapshotWorkEvidenceRequest(
        grade_item_id="quiz_1",
        work=ModuleWorkRef(
            "scoreform",
            record_support.CLASS_ID,
            "quiz_1",
        ),
        status="available",
        projection_snapshots=(projection,),
    )
    grade_request = ReportingSnapshotGradeRequest(
        target=record_support._target(family="conventional"),
        work_evidence=(evidence,),
    )
    request = ReportingSnapshotBuildRequest(
        schema_version="1",
        definition_reference=record_support._definition_ref(),
        grade_requests=(grade_request,),
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Freeze exact authorized projection identity.",
        requested_at=record_support.NOW + timedelta(minutes=1),
        predecessor=None,
    )

    encoded = reporting_snapshot_build_request_to_json_bytes(request)

    assert projection.publication_id.encode("utf-8") in encoded
    assert projection.cache_key.encode("ascii") in encoded
    assert projection.snapshot_digest.encode("ascii") in encoded
    for forbidden in (
        b"source_path",
        b"manifest_bytes",
        b"submission",
        b"producer_private",
        b"raw_evidence",
    ):
        assert forbidden not in encoded


def test_issue61_roster_observation_is_student_and_field_minimized(
    tmp_path,
) -> None:
    root = roster_support._workspace(tmp_path)
    roster_support._write_roster(root)

    observation = build_export_roster_observation(
        root,
        roster_support._profile("roster.first_name"),
        ("student_001",),
    )
    assert observation is not None
    encoded = export_roster_observation_to_json_bytes(observation)

    assert b"student_001" in encoded
    assert b"Avery" in encoded
    assert b"student_002" not in encoded
    assert b"student_999" not in encoded
    assert b"Chen" not in encoded
    assert b"avery@example.test" not in encoded
    assert b"roster.csv" not in encoded
    assert b"source_path" not in encoded


@pytest.mark.parametrize(
    "module_name",
    (
        "reporting_snapshot_freeze.py",
        "report_export_preview.py",
        "report_export_commit.py",
    ),
)
def test_issue61_reporting_and_export_do_not_import_producer_private_packages(
    module_name: str,
) -> None:
    imports = privacy_support._imported_modules(
        privacy_support._module_tree(module_name)
    )
    forbidden_prefixes = (
        "scoreform",
        "pds_scoreform",
        "quillan",
        "concord",
        "pds_concord",
    )

    assert not any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for imported in imports
        for prefix in forbidden_prefixes
    )
