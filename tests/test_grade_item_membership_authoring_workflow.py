from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.routing_models import ModuleWorkRef

import meridian.grade_item_membership_authoring_workflow as workflow
from meridian.grade_item_memberships import GradeItemAcademicPeriodAssignment

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="test_1",
)
DECIDED = datetime(2026, 9, 1, 13, 0, tzinfo=UTC)
DIGEST = "a" * 64


def _grade_item() -> object:
    return SimpleNamespace(
        revision=SimpleNamespace(
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            grade_item_revision=2,
            status="active",
        ),
        revision_sha256=DIGEST,
    )


def _assignment() -> GradeItemAcademicPeriodAssignment:
    return GradeItemAcademicPeriodAssignment(
        period=AcademicPeriodRef(
            school_year="2026-2027",
            period_id="mp1",
        ),
        calendar_revision=3,
    )


def _stored_decision(
    decision: object,
    *,
    digest: str | None = None,
) -> object:
    actual = digest or hashlib.sha256(repr(decision).encode()).hexdigest()
    return SimpleNamespace(
        decision=decision,
        decision_sha256=actual,
        path=Path("membership.json"),
    )


def _install_base(
    monkeypatch: pytest.MonkeyPatch,
    *,
    history: tuple[int, ...] = (),
    current_membership: int | None = None,
    previous: object | None = None,
) -> None:
    monkeypatch.setattr(
        workflow,
        "get_current_grade_item_revision",
        lambda *args: 2,
    )
    monkeypatch.setattr(
        workflow,
        "load_grade_item_revision",
        lambda *args: _grade_item(),
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_revisions",
        lambda *args: history,
    )
    if previous is not None:
        monkeypatch.setattr(
            workflow,
            "load_grade_item_membership_revision",
            lambda *args: previous,
        )
    monkeypatch.setattr(
        workflow,
        "get_current_grade_item_membership_revision",
        lambda *args: current_membership,
    )
    monkeypatch.setattr(
        workflow,
        "validate_grade_item_membership_dependencies",
        lambda *args: SimpleNamespace(),
    )


def test_create_preview_is_read_only_and_binds_exact_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_base(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "write_grade_item_membership_revision",
        lambda *args: pytest.fail("preview must not write"),
    )

    preview = workflow.preview_grade_item_membership_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        operation="create",
        grade_item_revision=2,
        registration_revision=7,
        decision="included",
        actor_id="teacher_local",
        decided_at=DECIDED,
        academic_period=_assignment(),
        rationale="Counts toward Unit 1.",
    )

    candidate = preview.candidate
    assert preview.operation == "create"
    assert preview.history == ()
    assert preview.membership_revision == 1
    assert preview.decision == "included"
    assert candidate.grade_item_revision == 2
    assert candidate.grade_item_revision_sha256 == DIGEST
    assert candidate.work_reference.work == WORK
    assert candidate.work_reference.registration_revision == 7
    assert candidate.actor_id == "teacher_local"
    assert candidate.academic_period == _assignment()
    assert preview.expected_current_membership_revision is None


def test_authoring_requires_exact_explicit_grade_item_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_base(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "get_current_grade_item_revision",
        lambda *args: None,
    )
    with pytest.raises(
        workflow.GradeItemMembershipAuthoringScopeError,
        match="explicitly selected",
    ):
        workflow.preview_grade_item_membership_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            operation="create",
            grade_item_revision=2,
            registration_revision=1,
            decision="excluded",
            actor_id="teacher_local",
            decided_at=DECIDED,
            academic_period=None,
        )

    monkeypatch.setattr(
        workflow,
        "get_current_grade_item_revision",
        lambda *args: 1,
    )
    with pytest.raises(
        workflow.GradeItemMembershipAuthoringScopeError,
        match="not the explicitly selected",
    ):
        workflow.preview_grade_item_membership_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            operation="create",
            grade_item_revision=2,
            registration_revision=1,
            decision="excluded",
            actor_id="teacher_local",
            decided_at=DECIDED,
            academic_period=None,
        )


def test_revise_uses_latest_persisted_history_not_selected_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = workflow.GradeItemMembershipDecision(
        schema_version="1",
        record_type="meridian_grade_item_membership",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=2,
        grade_item_revision_sha256=DIGEST,
        work_reference=workflow.GradeItemWorkReference(
            work=WORK,
            registration_revision=1,
        ),
        membership_revision=1,
        supersedes_revision=None,
        decision="included",
        academic_period=_assignment(),
        actor_id="teacher_local",
        rationale=None,
        decided_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    previous = _stored_decision(first, digest="b" * 64)
    _install_base(
        monkeypatch,
        history=(1,),
        current_membership=None,
        previous=previous,
    )

    preview = workflow.preview_grade_item_membership_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        operation="revise",
        grade_item_revision=2,
        registration_revision=2,
        decision="excluded",
        actor_id="teacher_local",
        decided_at=DECIDED,
        academic_period=None,
    )

    assert preview.history == (1,)
    assert preview.membership_revision == 2
    assert preview.candidate.supersedes_revision == 1
    assert preview.candidate.work_reference.registration_revision == 2
    assert preview.candidate.decision == "excluded"
    assert preview.latest_persisted_decision_sha256 == "b" * 64
    assert preview.expected_current_membership_revision is None


def test_create_and_revise_preconditions_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = SimpleNamespace(
        decision=SimpleNamespace(decided_at=DECIDED),
        decision_sha256="b" * 64,
    )
    _install_base(monkeypatch, history=(1,), previous=previous)
    with pytest.raises(
        workflow.GradeItemMembershipAuthoringScopeError,
        match="Create requires",
    ):
        workflow.preview_grade_item_membership_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            operation="create",
            grade_item_revision=2,
            registration_revision=1,
            decision="excluded",
            actor_id="teacher_local",
            decided_at=DECIDED,
            academic_period=None,
        )

    _install_base(monkeypatch, history=())
    with pytest.raises(
        workflow.GradeItemMembershipAuthoringScopeError,
        match="Revise requires",
    ):
        workflow.preview_grade_item_membership_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            operation="revise",
            grade_item_revision=2,
            registration_revision=1,
            decision="excluded",
            actor_id="teacher_local",
            decided_at=DECIDED,
            academic_period=None,
        )


def test_commit_revalidates_and_writes_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_base(monkeypatch, current_membership=None)
    preview = workflow.preview_grade_item_membership_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        operation="create",
        grade_item_revision=2,
        registration_revision=1,
        decision="included",
        actor_id="teacher_local",
        decided_at=DECIDED,
        academic_period=_assignment(),
    )
    observed: dict[str, object] = {}

    def write(*args: object) -> object:
        observed["args"] = args
        stored = SimpleNamespace(decision=preview.candidate)
        return SimpleNamespace(disposition="created", stored=stored)

    monkeypatch.setattr(workflow, "write_grade_item_membership_revision", write)

    result = workflow.commit_grade_item_membership_authoring_preview(
        "workspace",
        preview,
    )

    assert observed["args"] == ("workspace", preview.candidate)
    assert result.written_revision == 1
    assert result.written_decision == "included"
    assert result.write_disposition == "created"
    assert result.previous_current_membership_revision is None
    assert result.selection_action == "not_performed"


def test_commit_fails_if_reviewed_state_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_base(monkeypatch, current_membership=None)
    preview = workflow.preview_grade_item_membership_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        operation="create",
        grade_item_revision=2,
        registration_revision=1,
        decision="excluded",
        actor_id="teacher_local",
        decided_at=DECIDED,
        academic_period=None,
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_revisions",
        lambda *args: (1,),
    )
    monkeypatch.setattr(
        workflow,
        "write_grade_item_membership_revision",
        lambda *args: pytest.fail("stale preview must not write"),
    )

    with pytest.raises(
        workflow.GradeItemMembershipAuthoringStaleError,
        match="history",
    ):
        workflow.commit_grade_item_membership_authoring_preview(
            "workspace",
            preview,
        )


def test_commit_fails_if_membership_selector_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_base(monkeypatch, current_membership=None)
    preview = workflow.preview_grade_item_membership_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        operation="create",
        grade_item_revision=2,
        registration_revision=1,
        decision="excluded",
        actor_id="teacher_local",
        decided_at=DECIDED,
        academic_period=None,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_grade_item_membership_revision",
        lambda *args: 1,
    )
    monkeypatch.setattr(
        workflow,
        "write_grade_item_membership_revision",
        lambda *args: pytest.fail("stale preview must not write"),
    )

    with pytest.raises(
        workflow.GradeItemMembershipAuthoringStaleError,
        match="selection",
    ):
        workflow.commit_grade_item_membership_authoring_preview(
            "workspace",
            preview,
        )
