"""#117 Slice 5: ready means both protected review operations are allowed."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from test_teacher_evidence_inbox_issue110 import _diagnostic, _observation, _work

from meridian.ingestion import (
    PublicationAuthorizationDecision,
    PublicationAuthorizationRequest,
    PublicationAuthorizer,
)
from meridian.publication_authorization import (
    PublicationAuthorizationGrant,
    TeacherLocalPublicationAuthorizer,
)
from meridian.teacher_evidence_inbox import project_teacher_evidence_inbox


@pytest.mark.parametrize("producer", ["scoreform", "quillan", "concord"])
@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("project_evidence", "access_not_granted"),
        ("read_projection_cache", "access_not_granted"),
    ],
)
def test_partial_operation_grants_are_not_ready(
    tmp_path: Path, producer: str, operation: str, expected: str,
) -> None:
    authorizer = TeacherLocalPublicationAuthorizer(
        tmp_path,
        "synthetic_policy",
        "1",
        (
            PublicationAuthorizationGrant(
                class_id="english_12_pd2",
                operations=(operation,),
                purpose_ids=("review_evidence",),
                producer_module_ids=(producer,),
                publication_ids=(),
                student_ids=(),
            ),
        ),
    )
    observation = _observation(
        ordinal=0,
        work=_work(module_id=producer),
        publication_id="pub_11111111111111111111111111111111",
    )
    item = project_teacher_evidence_inbox(
        _diagnostic(observation), authorizer=authorizer,
    ).items[0]
    assert item.status_code == expected
    assert item.actionability == "blocked"


def test_both_operations_checked_with_exact_whole_assignment_scope() -> None:
    seen: list[PublicationAuthorizationRequest] = []

    class Recorder:
        def authorize(
            self, request: PublicationAuthorizationRequest,
        ) -> PublicationAuthorizationDecision:
            seen.append(request)
            return PublicationAuthorizationDecision(True, "synthetic_policy", "1")

    item = project_teacher_evidence_inbox(
        _diagnostic(
            _observation(
                ordinal=0,
                work=_work(module_id="concord"),
                publication_id="pub_22222222222222222222222222222222",
            )
        ),
        authorizer=cast(PublicationAuthorizer, Recorder()),
    ).items[0]
    assert item.status_code == "ready_to_review"
    assert [request.operation for request in seen] == [
        "project_evidence", "read_projection_cache"
    ]
    assert all(request.purpose_id == "review_evidence" for request in seen)
    assert all(request.requested_student_ids == () for request in seen)
    assert seen[0].publication == seen[1].publication


@pytest.mark.parametrize("failure", ["deny", "exception", "invalid_return"])
def test_second_authorization_failure_fails_closed(failure: str) -> None:
    seen: list[str] = []

    class Selective:
        def authorize(self, request: PublicationAuthorizationRequest) -> object:
            seen.append(request.operation)
            if request.operation == "project_evidence":
                return PublicationAuthorizationDecision(True, "synthetic_policy", "1")
            if failure == "deny":
                return PublicationAuthorizationDecision(
                    False, "synthetic_policy", "1", ("authorization.grant_not_found",)
                )
            if failure == "exception":
                raise RuntimeError("sensitive provider detail")
            return {"allowed": True}

    item = project_teacher_evidence_inbox(
        _diagnostic(
            _observation(
                ordinal=0,
                publication_id="pub_33333333333333333333333333333333",
            )
        ),
        authorizer=cast(PublicationAuthorizer, Selective()),
    ).items[0]
    assert seen == ["project_evidence", "read_projection_cache"]
    assert item.actionability == "blocked"
    assert item.status_code == (
        "access_not_granted" if failure == "deny" else "access_check_unavailable"
    )


def test_denied_first_operation_does_not_call_cache_authorizer() -> None:
    seen: list[str] = []

    class Deny:
        def authorize(
            self, request: PublicationAuthorizationRequest,
        ) -> PublicationAuthorizationDecision:
            seen.append(request.operation)
            return PublicationAuthorizationDecision(
                False, "synthetic_policy", "1", ("authorization.grant_not_found",)
            )

    result = project_teacher_evidence_inbox(
        _diagnostic(
            _observation(
                ordinal=0,
                publication_id="pub_44444444444444444444444444444444",
            )
        ),
        authorizer=cast(PublicationAuthorizer, Deny()),
    ).items[0]
    assert result.status_code == "access_not_granted"
    assert seen == ["project_evidence"]
