from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.attempt_policy_selection_workflow as workflow
from meridian.attempt_selection import (
    AttemptSelectionActor,
    AttemptSelectionPolicy,
    attempt_selection_policy_to_json_bytes,
)
from meridian.attempt_selection_storage import (
    AttemptSelectionPolicySelectionResult,
    StoredAttemptSelectionPolicy,
    attempt_selection_policy_revision_relative_path,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
POLICY_ID = "explicit_one"
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="test_1",
)
REVISED_AT = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


def _policy(revision: int) -> AttemptSelectionPolicy:
    return AttemptSelectionPolicy(
        schema_version="1",
        record_type="meridian_attempt_selection_policy",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        policy_id=POLICY_ID,
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        selection_basis="explicit",
        minimum_selected=0,
        maximum_selected=1,
        actor=AttemptSelectionActor(
            kind="teacher",
            actor_id="teacher_local",
        ),
        rationale=None,
        revised_at=REVISED_AT,
    )


def _stored(revision: int) -> StoredAttemptSelectionPolicy:
    policy = _policy(revision)
    content = attempt_selection_policy_to_json_bytes(policy)
    digest = hashlib.sha256(content).hexdigest()
    return StoredAttemptSelectionPolicy(
        policy=policy,
        policy_sha256=digest,
        path=Path(f"{revision}.json"),
        relative_path=attempt_selection_policy_revision_relative_path(
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            POLICY_ID,
            revision,
        ),
        content=content,
    )


def _install_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    history: tuple[int, ...] = (1, 2),
    current: int | None = 2,
) -> dict[int, StoredAttemptSelectionPolicy]:
    stored = {revision: _stored(revision) for revision in history}
    monkeypatch.setattr(
        workflow,
        "list_attempt_selection_policy_revisions",
        lambda *args: history,
    )
    monkeypatch.setattr(
        workflow,
        "load_attempt_selection_policy_revision",
        lambda *args: stored[args[-1]],
    )
    monkeypatch.setattr(
        workflow,
        "get_current_attempt_selection_policy_revision",
        lambda *args: current,
    )
    return stored


def test_preview_targets_exact_historical_revision_without_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _install_state(monkeypatch, current=2)
    monkeypatch.setattr(
        workflow,
        "select_attempt_selection_policy_revision",
        lambda *args, **kwargs: pytest.fail("preview must not select"),
    )

    preview = workflow.preview_attempt_policy_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        POLICY_ID,
        1,
    )

    assert preview.target is stored[1]
    assert preview.target_revision == 1
    assert preview.history == (1, 2)
    assert preview.latest_revision == 2
    assert preview.target_is_latest is False
    assert preview.expected_current_policy_revision == 2


def test_preview_rejects_missing_or_nonpositive_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch)

    with pytest.raises(
        workflow.AttemptPolicySelectionScopeError,
        match="positive integer",
    ):
        workflow.preview_attempt_policy_selection(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            POLICY_ID,
            0,
        )

    with pytest.raises(
        workflow.AttemptPolicySelectionScopeError,
        match="not present",
    ):
        workflow.preview_attempt_policy_selection(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            POLICY_ID,
            3,
        )


def test_commit_delegates_exact_target_and_current_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _install_state(monkeypatch, current=2)
    preview = workflow.preview_attempt_policy_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        POLICY_ID,
        1,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def select(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return AttemptSelectionPolicySelectionResult(
            disposition="updated",
            stored=stored[1],
        )

    monkeypatch.setattr(
        workflow,
        "select_attempt_selection_policy_revision",
        select,
    )

    result = workflow.commit_attempt_policy_selection_preview(
        "workspace",
        preview,
    )

    assert observed == [
        (
            (
                "workspace",
                CLASS_ID,
                GRADE_ITEM_ID,
                WORK,
                POLICY_ID,
                1,
            ),
            {"expected_current_policy_revision": 2},
        )
    ]
    assert result.previous_current_policy_revision == 2
    assert result.selected_revision == 1
    assert result.selected_policy_sha256 == stored[1].policy_sha256
    assert result.selection_disposition == "updated"
    assert result.authoring_action == "not_performed"


def test_commit_rejects_changed_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch)
    preview = workflow.preview_attempt_policy_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        POLICY_ID,
        1,
    )
    monkeypatch.setattr(
        workflow,
        "list_attempt_selection_policy_revisions",
        lambda *args: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "select_attempt_selection_policy_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not select"),
    )

    with pytest.raises(
        workflow.AttemptPolicySelectionStaleError,
        match="history",
    ):
        workflow.commit_attempt_policy_selection_preview(
            "workspace",
            preview,
        )


def test_commit_rejects_changed_target_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _install_state(monkeypatch)
    preview = workflow.preview_attempt_policy_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        POLICY_ID,
        1,
    )
    changed = _stored(1)
    object.__setattr__(changed, "policy_sha256", "f" * 64)
    monkeypatch.setattr(
        workflow,
        "load_attempt_selection_policy_revision",
        lambda *args: changed if args[-1] == 1 else stored[args[-1]],
    )
    monkeypatch.setattr(
        workflow,
        "select_attempt_selection_policy_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not select"),
    )

    with pytest.raises(
        workflow.AttemptPolicySelectionStaleError,
        match="Target",
    ):
        workflow.commit_attempt_policy_selection_preview(
            "workspace",
            preview,
        )


def test_commit_rejects_changed_current_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch, current=2)
    preview = workflow.preview_attempt_policy_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        POLICY_ID,
        1,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_attempt_selection_policy_revision",
        lambda *args: 1,
    )
    monkeypatch.setattr(
        workflow,
        "select_attempt_selection_policy_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not select"),
    )

    with pytest.raises(
        workflow.AttemptPolicySelectionStaleError,
        match="selector",
    ):
        workflow.commit_attempt_policy_selection_preview(
            "workspace",
            preview,
        )
