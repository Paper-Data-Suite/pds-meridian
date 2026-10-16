"""#117 Slice 4: truthful preflight readiness, no protected evidence reads."""
from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import cast

import pytest
from test_teacher_evidence_inbox_issue110 import (
    _diagnostic,
    _observation,
    _ready_support,
    _work,
)

import meridian.teacher_evidence_inbox as inbox_module
from meridian.diagnostics import (
    DiagnosticsDependencies,
    build_builtin_adapter_registry,
)
from meridian.ingestion import (
    PublicationAuthorizationDecision,
    PublicationAuthorizationRequest,
    PublicationAuthorizer,
)
from meridian.menu_teacher_evidence import (
    _render_class_list,
    _status_explanation,
)
from meridian.publication_authorization import (
    PublicationAuthorizationGrant,
    TeacherLocalPublicationAuthorizer,
)
from meridian.teacher_evidence_inbox import (
    load_teacher_evidence_inbox,
    project_teacher_evidence_inbox,
)
from meridian.teacher_session import TeacherSessionContext


def _dataset(producer: str):
    return _diagnostic(
        _observation(
            ordinal=0,
            work=_work(module_id=producer),
            publication_id="pub_11111111111111111111111111111111",
        )
    )


def _teacher_grant(
    root: Path, producer: str, *, student_ids: tuple[str, ...] = (),
    class_id: str = "english_12_pd2",
) -> TeacherLocalPublicationAuthorizer:
    return TeacherLocalPublicationAuthorizer(
        root, "teacher_local", "1",
        (
            PublicationAuthorizationGrant(
                class_id=class_id,
                operations=("project_evidence", "read_projection_cache"),
                purpose_ids=("review_evidence", "teacher_reporting"),
                producer_module_ids=(producer,),
                publication_ids=(),
                student_ids=student_ids,
            ),
        ),
    )


@pytest.mark.parametrize("producer", ["scoreform", "quillan", "concord"])
def test_no_provider_never_claims_teacher_ready(producer: str) -> None:
    item = project_teacher_evidence_inbox(
        _dataset(producer), authorizer=None,
    ).items[0]
    assert item.actionability == "blocked"
    assert item.status_code == "access_not_configured"
    assert item.status_label == "Evidence access not configured"


@pytest.mark.parametrize("producer", ["scoreform", "quillan", "concord"])
def test_exact_whole_assignment_grant_is_preflight_ready(
    tmp_path: Path, producer: str,
) -> None:
    local = _teacher_grant(tmp_path, producer)
    item = project_teacher_evidence_inbox(
        _dataset(producer), authorizer=local,
    ).items[0]
    assert item.actionability == "ready"
    assert item.status_code == "ready_to_review"


@pytest.mark.parametrize("producer", ["scoreform", "quillan", "concord"])
def test_student_restricted_grant_cannot_preflight_whole_assignment(
    tmp_path: Path, producer: str,
) -> None:
    local = _teacher_grant(tmp_path, producer, student_ids=("student_1",))
    item = project_teacher_evidence_inbox(
        _dataset(producer), authorizer=local,
    ).items[0]
    assert item.status_code == "access_not_granted"
    assert item.actionability == "blocked"


@pytest.mark.parametrize("producer", ["scoreform", "quillan", "concord"])
def test_unrelated_class_grant_does_not_preflight_ready(
    tmp_path: Path, producer: str,
) -> None:
    local = _teacher_grant(tmp_path, producer, class_id="other_class")
    assert project_teacher_evidence_inbox(
        _dataset(producer), authorizer=local,
    ).items[0].status_code == "access_not_granted"


def test_preflight_requests_exact_review_scope_without_reading_manifest() -> None:
    seen: list[PublicationAuthorizationRequest] = []

    class Recorder:
        def authorize(
            self, request: PublicationAuthorizationRequest
        ) -> PublicationAuthorizationDecision:
            seen.append(request)
            return PublicationAuthorizationDecision(True, "local", "1")

    item = project_teacher_evidence_inbox(
        _dataset("quillan"), authorizer=Recorder(),
    ).items[0]
    assert item.status_code == "ready_to_review"
    assert [request.operation for request in seen] == [
        "project_evidence",
        "read_projection_cache",
    ]
    assert all(r.purpose_id == "review_evidence" for r in seen)
    assert all(r.requested_student_ids == () for r in seen)
    assert seen[0].operation == "project_evidence"
    assert seen[0].purpose_id == "review_evidence"
    assert seen[0].requested_student_ids == ()
    assert seen[0].publication.work.module_id == "quillan"


@pytest.mark.parametrize("failure", ["exception", "wrong_return"])
def test_faulty_provider_fails_closed_without_breaking_inbox(failure: str) -> None:
    class Faulty:
        def authorize(self, request: PublicationAuthorizationRequest) -> object:
            if failure == "exception":
                raise RuntimeError("do not leak protected information")
            return {"allowed": True}

    item = project_teacher_evidence_inbox(
        _dataset("scoreform"),
        authorizer=cast(PublicationAuthorizer, Faulty()),
    ).items[0]
    assert item.actionability == "blocked"
    assert item.status_code == "access_check_unavailable"


def test_reader_incompatibility_is_not_misdiagnosed_as_authorization() -> None:
    original = _dataset("scoreform").observations[0]
    unavailable = replace(
        _ready_support("scoreform"),
        reader_state="unavailable", overall_state="support_unavailable",
        installed_reader_version=None,
    )
    item = project_teacher_evidence_inbox(
        _diagnostic(replace(original, support=unavailable)),
        authorizer=None,
    ).items[0]
    assert item.status_code == "reader_unavailable"


def test_legacy_pure_projection_preserves_compatibility_diagnostics() -> None:
    assert project_teacher_evidence_inbox(
        _dataset("concord")
    ).items[0].status_code == "ready_to_review"


def test_installed_inbox_loader_carries_authorizer_into_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _dataset("concord")
    calls: list[object] = []

    def discovery(root: Path, request: object, deps: object):
        calls.append((root, request, deps))
        return catalog

    monkeypatch.setattr(inbox_module, "list_publication_diagnostics", discovery)
    diagnostics = DiagnosticsDependencies(
        producer_registry=None,
        adapter_registry=build_builtin_adapter_registry(),
        authorizer=None,
        producer_registry_state="discovery_failed",
        producer_registry_reason_code="diagnostics.profile_discovery_failed",
    )
    inbox = load_teacher_evidence_inbox(tmp_path, diagnostics)
    assert len(calls) == 1
    assert inbox.items[0].status_code == "access_not_configured"


def test_teacher_menu_explains_actionable_recovery_without_opaque_ids() -> None:
    inbox = project_teacher_evidence_inbox(
        _dataset("scoreform"), authorizer=None,
    )
    output = StringIO()
    _render_class_list(output, inbox, TeacherSessionContext())
    assert "return to Main Menu (M) and select A" in output.getvalue()
    explanation = " ".join(_status_explanation(inbox.items[0]))
    assert "A. Set Up Evidence Access" in explanation
    assert "pub_" not in explanation
    assert "student_1" not in explanation


def test_denied_scope_has_specific_guided_recovery(
    tmp_path: Path,
) -> None:
    blocked = project_teacher_evidence_inbox(
        _dataset("quillan"),
        authorizer=_teacher_grant(tmp_path, "quillan", student_ids=("student_1",)),
    ).items[0]
    message = " ".join(_status_explanation(blocked))
    assert "whole-assignment review access" in message
    assert "Main Menu" in message
