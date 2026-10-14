from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import PublicationRecord
from pds_core.routing_models import ModuleWorkRef

from meridian.ingestion import PublicationAuthorizationRequest
from meridian.publication_authorization import (
    AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE,
    AUTHORIZATION_POLICY_RECORD_TYPE,
    AUTHORIZATION_POLICY_SCHEMA_VERSION,
    PublicationAuthorizationConfigurationError,
    default_authorization_policy_path,
    load_publication_authorizer,
    resolve_configured_publication_authorizer,
)

NOW = datetime(2026, 10, 14, tzinfo=UTC)
WORK = ModuleWorkRef("scoreform", "class_1", "assessment_1")


def _registration() -> AcademicWorkRegistration:
    return AcademicWorkRegistration(
        "1",
        "academic_work_registration",
        WORK,
        1,
        "scoreform_assignment_v1",
        "Benchmark",
        "assessment",
        "summative",
        "active",
        NOW,
        NOW,
        (),
    )


def _publication() -> PublicationRecord:
    return PublicationRecord(
        "1",
        "publication_record",
        "pub_11111111111111111111111111111111",
        WORK,
        None,
        "academic_result_set",
        ("points",),
        "results",
        1,
        "scoreform_academic_result_manifest_v1",
        "classes/class_1/modules/scoreform/work/assessment_1/result.json",
        "sha256",
        "a" * 64,
        NOW,
        1,
        None,
    )


def _request(operation="project_evidence", purpose="review_evidence"):
    return PublicationAuthorizationRequest(
        _publication(),
        _registration(),
        None,
        "current_selectable",
        operation,
        purpose,
        ("student_1",),
    )


def _policy(root, *, class_id="class_1"):
    return {
        "schema_version": AUTHORIZATION_POLICY_SCHEMA_VERSION,
        "record_type": AUTHORIZATION_POLICY_RECORD_TYPE,
        "policy_id": "teacher_local",
        "policy_version": "1",
        "workspace_root": str(root.resolve()),
        "grants": [
            {
                "class_id": class_id,
                "operations": ["project_evidence", "read_projection_cache"],
                "purpose_ids": ["review_evidence", "teacher_reporting"],
                "producer_module_ids": ["scoreform"],
                "publication_ids": [],
                "student_ids": ["student_1"],
            }
        ],
    }


def test_configured_authorizer_allows_exact_grant_and_denies_other_scope(
    tmp_path,
) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(_policy(tmp_path)), encoding="utf-8")
    authorizer = load_publication_authorizer(policy, workspace_root=tmp_path)
    assert authorizer.authorize(_request()).allowed
    denied = authorizer.authorize(_request(purpose="unconfigured_purpose"))
    assert not denied.allowed
    assert denied.reason_codes == ("authorization.grant_not_found",)


def test_policy_is_bound_to_exact_workspace(tmp_path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(_policy(other)), encoding="utf-8")
    with pytest.raises(PublicationAuthorizationConfigurationError):
        load_publication_authorizer(policy, workspace_root=tmp_path)


def test_default_resolution_is_absent_fail_closed_and_loads_default(tmp_path) -> None:
    assert resolve_configured_publication_authorizer(workspace_root=tmp_path) is None
    path = default_authorization_policy_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_policy(tmp_path)), encoding="utf-8")
    resolved = resolve_configured_publication_authorizer(workspace_root=tmp_path)
    assert resolved is not None
    assert resolved.authorize(_request(operation="read_projection_cache")).allowed


def test_explicit_missing_policy_is_configuration_error(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE,
        str(tmp_path / "missing-policy.json"),
    )
    with pytest.raises(PublicationAuthorizationConfigurationError):
        resolve_configured_publication_authorizer(workspace_root=tmp_path)
