"""Issue #117: student restrictions cannot authorize whole-assignment reads.

Synthetic Core model fixtures exercise the one consumer-side scope rule for
ScoreForm, Quillan, and Concord without importing any producer package.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import PublicationRecord
from pds_core.routing_models import ModuleWorkRef

from meridian.ingestion import PublicationAuthorizationRequest
from meridian.publication_authorization import (
    AUTHORIZATION_POLICY_RECORD_TYPE,
    AUTHORIZATION_POLICY_SCHEMA_VERSION,
    PublicationAuthorizationGrant,
    TeacherLocalPublicationAuthorizer,
    load_publication_authorizer,
)

NOW = datetime(2026, 10, 14, tzinfo=UTC)
PRODUCERS = ("scoreform", "quillan", "concord")
OPERATIONS = ("project_evidence", "read_projection_cache")
PRODUCER_CAPABILITIES = {
    "scoreform": "points",
    "quillan": "standards_ratings",
    "concord": "criterion_scores",
}


def _request(
    producer: str,
    operation: str,
    requested_students: tuple[str, ...],
    *,
    purpose: str = "review_evidence",
    class_id: str = "class_1",
) -> PublicationAuthorizationRequest:
    work = ModuleWorkRef(producer, class_id, "assessment_1")
    registration = AcademicWorkRegistration(
        "1",
        "academic_work_registration",
        work,
        1,
        f"{producer}_assignment_v1",
        "Benchmark",
        "assessment",
        "summative",
        "active",
        NOW,
        NOW,
        (),
    )
    publication = PublicationRecord(
        "1",
        "publication_record",
        "pub_11111111111111111111111111111111",
        work,
        None,
        "academic_result_set",
        (PRODUCER_CAPABILITIES[producer],),
        "results",
        1,
        f"{producer}_academic_result_manifest_v1",
        f"classes/{class_id}/modules/{producer}/work/assessment_1/result.json",
        "sha256",
        "a" * 64,
        NOW,
        1,
        None,
    )
    return PublicationAuthorizationRequest(
        publication,
        registration,
        None,
        "current_selectable",
        operation,
        purpose,
        requested_students,
    )


def _authorizer(
    root: Path,
    *,
    grants: tuple[PublicationAuthorizationGrant, ...] | None = None,
) -> TeacherLocalPublicationAuthorizer:
    if grants is None:
        grants = (
            PublicationAuthorizationGrant(
                class_id="class_1",
                operations=OPERATIONS,
                purpose_ids=("review_evidence",),
                producer_module_ids=("concord", "quillan", "scoreform"),
                student_ids=("student_1",),
            ),
        )
    return TeacherLocalPublicationAuthorizer(root, "teacher_local", "1", grants)


@pytest.mark.parametrize("producer", PRODUCERS)
@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    ("scope", "expected"),
    (
        ((), False),  # Empty request is WHOLE assignment, not zero students.
        (("student_1",), True),
        (("student_2",), False),
        (("student_1", "student_2"), False),
    ),
)
def test_student_limited_grant_never_widens_request(
    tmp_path: Path,
    producer: str,
    operation: str,
    scope: tuple[str, ...],
    expected: bool,
) -> None:
    decision = _authorizer(tmp_path).authorize(_request(producer, operation, scope))
    assert decision.allowed is expected
    assert decision.reason_codes == (
        () if expected else ("authorization.grant_not_found",)
    )


@pytest.mark.parametrize("producer", PRODUCERS)
@pytest.mark.parametrize("operation", OPERATIONS)
def test_explicit_unrestricted_grant_permits_whole_assignment(
    tmp_path: Path,
    producer: str,
    operation: str,
) -> None:
    unrestricted = PublicationAuthorizationGrant(
        class_id="class_1",
        operations=OPERATIONS,
        purpose_ids=("review_evidence",),
        producer_module_ids=("concord", "quillan", "scoreform"),
        student_ids=(),
    )
    decision = _authorizer(tmp_path, grants=(unrestricted,)).authorize(
        _request(producer, operation, ())
    )
    assert decision.allowed is True


@pytest.mark.parametrize("operation", OPERATIONS)
def test_multiple_narrow_grants_do_not_join_into_wide_authority(
    tmp_path: Path, operation: str
) -> None:
    grants = tuple(
        PublicationAuthorizationGrant(
            class_id="class_1",
            operations=OPERATIONS,
            purpose_ids=("review_evidence",),
            student_ids=(student_id,),
        )
        for student_id in ("student_1", "student_2")
    )
    authorizer = _authorizer(tmp_path, grants=grants)
    assert not authorizer.authorize(_request("quillan", operation, ())).allowed
    assert not authorizer.authorize(
        _request("quillan", operation, ("student_1", "student_2"))
    ).allowed
    assert authorizer.authorize(
        _request("quillan", operation, ("student_2",))
    ).allowed


@pytest.mark.parametrize("operation", OPERATIONS)
def test_narrow_grant_preserves_class_purpose_and_producer_boundaries(
    tmp_path: Path, operation: str
) -> None:
    grant = PublicationAuthorizationGrant(
        class_id="class_1",
        operations=OPERATIONS,
        purpose_ids=("review_evidence",),
        producer_module_ids=("quillan",),
        student_ids=("student_1",),
    )
    authorizer = _authorizer(tmp_path, grants=(grant,))
    assert not authorizer.authorize(
        _request("scoreform", operation, ("student_1",))
    ).allowed
    assert not authorizer.authorize(
        _request("quillan", operation, ("student_1",), purpose="teacher_reporting")
    ).allowed
    assert not authorizer.authorize(
        _request("quillan", operation, ("student_1",), class_id="class_2")
    ).allowed


@pytest.mark.parametrize("operation", OPERATIONS)
def test_loaded_student_restricted_policy_denies_whole_assignment(
    tmp_path: Path, operation: str
) -> None:
    policy_path = tmp_path / "authorization-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": AUTHORIZATION_POLICY_SCHEMA_VERSION,
                "record_type": AUTHORIZATION_POLICY_RECORD_TYPE,
                "policy_id": "teacher_local",
                "policy_version": "1",
                "workspace_root": str(tmp_path.resolve()),
                "grants": [
                    {
                        "class_id": "class_1",
                        "operations": list(OPERATIONS),
                        "purpose_ids": ["review_evidence"],
                        "producer_module_ids": ["concord", "quillan", "scoreform"],
                        "publication_ids": [],
                        "student_ids": ["student_1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    authorizer = load_publication_authorizer(policy_path, workspace_root=tmp_path)
    assert not authorizer.authorize(_request("concord", operation, ())).allowed
    assert authorizer.authorize(
        _request("concord", operation, ("student_1",))
    ).allowed
