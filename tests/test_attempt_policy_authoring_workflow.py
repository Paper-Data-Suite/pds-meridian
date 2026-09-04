from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.attempt_policy_authoring_workflow as workflow
from meridian.attempt_selection import (
    ATTEMPT_SELECTION_BASIS,
    AttemptSelectionActor,
    AttemptSelectionPolicy,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
POLICY_ID = "explicit_one"
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="test_1",
)
REVISED = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


def _policy(
    revision: int,
    *,
    minimum_selected: int = 1,
    maximum_selected: int | None = 1,
) -> AttemptSelectionPolicy:
    return AttemptSelectionPolicy(
        schema_version="1",
        record_type="meridian_attempt_selection_policy",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        policy_id=POLICY_ID,
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        selection_basis=ATTEMPT_SELECTION_BASIS,
        minimum_selected=minimum_selected,
        maximum_selected=maximum_selected,
        actor=AttemptSelectionActor(
            kind="teacher",
            actor_id="teacher_local",
        ),
        rationale=None,
        revised_at=REVISED,
    )


def _stored(
    policy: AttemptSelectionPolicy,
    *,
    digest: str = "a" * 64,
) -> object:
    return SimpleNamespace(
        policy=policy,
        policy_sha256=digest,
        path=Path(f"{policy.policy_revision}.json"),
    )


def _install_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    history: tuple[int, ...] = (),
    previous: object | None = None,
    current: int | None = None,
) -> None:
    monkeypatch.setattr(
        workflow,
        "list_attempt_selection_policy_revisions",
        lambda *args: history,
    )
    if previous is not None:
        monkeypatch.setattr(
            workflow,
            "load_attempt_selection_policy_revision",
            lambda *args: previous,
        )
    monkeypatch.setattr(
        workflow,
        "get_current_attempt_selection_policy_revision",
        lambda *args: current,
    )


def test_create_preview_is_read_only_and_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "write_attempt_selection_policy_revision",
        lambda *args: pytest.fail("preview must not write"),
    )

    preview = workflow.preview_attempt_policy_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        POLICY_ID,
        operation="create",
        minimum_selected=1,
        maximum_selected=1,
        actor_id="teacher_local",
        revised_at=REVISED,
        rationale="Teacher chooses exactly one attempt.",
    )

    candidate = preview.candidate
    assert preview.operation == "create"
    assert preview.history == ()
    assert preview.policy_revision == 1
    assert candidate.selection_basis == "explicit"
    assert candidate.minimum_selected == 1
    assert candidate.maximum_selected == 1
    assert candidate.actor.kind == "teacher"
    assert candidate.actor.actor_id == "teacher_local"
    assert candidate.rationale == "Teacher chooses exactly one attempt."
    assert preview.reviewed_current_policy_revision is None


def test_revise_uses_latest_persisted_policy_not_selected_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _stored(_policy(2), digest="b" * 64)
    _install_state(
        monkeypatch,
        history=(1, 2),
        previous=previous,
        current=1,
    )

    preview = workflow.preview_attempt_policy_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        POLICY_ID,
        operation="revise",
        minimum_selected=0,
        maximum_selected=None,
        actor_id="teacher_local",
        revised_at=REVISED,
    )

    assert preview.history == (1, 2)
    assert preview.policy_revision == 3
    assert preview.candidate.supersedes_revision == 2
    assert preview.candidate.minimum_selected == 0
    assert preview.candidate.maximum_selected is None
    assert preview.latest_persisted_policy_sha256 == "b" * 64
    assert preview.reviewed_current_policy_revision == 1


def test_create_and_revise_preconditions_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(
        monkeypatch,
        history=(1,),
        previous=_stored(_policy(1)),
    )
    with pytest.raises(
        workflow.AttemptPolicyAuthoringScopeError,
        match="Create requires",
    ):
        workflow.preview_attempt_policy_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            POLICY_ID,
            operation="create",
            minimum_selected=1,
            maximum_selected=1,
            actor_id="teacher_local",
            revised_at=REVISED,
        )

    _install_state(monkeypatch)
    with pytest.raises(
        workflow.AttemptPolicyAuthoringScopeError,
        match="Revise requires",
    ):
        workflow.preview_attempt_policy_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            POLICY_ID,
            operation="revise",
            minimum_selected=1,
            maximum_selected=1,
            actor_id="teacher_local",
            revised_at=REVISED,
        )


def test_invalid_cardinality_is_translated_to_workflow_scope_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch)

    with pytest.raises(
        workflow.AttemptPolicyAuthoringScopeError,
        match="minimum_selected",
    ):
        workflow.preview_attempt_policy_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            POLICY_ID,
            operation="create",
            minimum_selected=2,
            maximum_selected=1,
            actor_id="teacher_local",
            revised_at=REVISED,
        )


def test_commit_revalidates_history_and_writes_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch, current=None)
    preview = workflow.preview_attempt_policy_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        POLICY_ID,
        operation="create",
        minimum_selected=0,
        maximum_selected=1,
        actor_id="teacher_local",
        revised_at=REVISED,
    )
    observed: list[tuple[object, ...]] = []

    def write(*args: object) -> object:
        observed.append(args)
        return SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(policy=preview.candidate),
        )

    monkeypatch.setattr(
        workflow,
        "write_attempt_selection_policy_revision",
        write,
    )

    result = workflow.commit_attempt_policy_authoring_preview(
        "workspace",
        preview,
    )

    assert observed == [("workspace", preview.candidate)]
    assert result.written_revision == 1
    assert result.write_disposition == "created"
    assert result.selection_action == "not_performed"


def test_commit_fails_if_policy_history_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch)
    preview = workflow.preview_attempt_policy_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        POLICY_ID,
        operation="create",
        minimum_selected=1,
        maximum_selected=1,
        actor_id="teacher_local",
        revised_at=REVISED,
    )
    monkeypatch.setattr(
        workflow,
        "list_attempt_selection_policy_revisions",
        lambda *args: (1,),
    )
    monkeypatch.setattr(
        workflow,
        "write_attempt_selection_policy_revision",
        lambda *args: pytest.fail("stale preview must not write"),
    )

    with pytest.raises(
        workflow.AttemptPolicyAuthoringStaleError,
        match="history",
    ):
        workflow.commit_attempt_policy_authoring_preview(
            "workspace",
            preview,
        )


def test_commit_fails_if_latest_policy_digest_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _stored(_policy(1), digest="b" * 64)
    _install_state(
        monkeypatch,
        history=(1,),
        previous=previous,
        current=1,
    )
    preview = workflow.preview_attempt_policy_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        POLICY_ID,
        operation="revise",
        minimum_selected=0,
        maximum_selected=2,
        actor_id="teacher_local",
        revised_at=REVISED,
    )
    changed = _stored(_policy(1), digest="c" * 64)
    monkeypatch.setattr(
        workflow,
        "load_attempt_selection_policy_revision",
        lambda *args: changed,
    )
    monkeypatch.setattr(
        workflow,
        "write_attempt_selection_policy_revision",
        lambda *args: pytest.fail("stale preview must not write"),
    )

    with pytest.raises(
        workflow.AttemptPolicyAuthoringStaleError,
        match="digest",
    ):
        workflow.commit_attempt_policy_authoring_preview(
            "workspace",
            preview,
        )
