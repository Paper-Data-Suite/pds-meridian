from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.attempt_decision_selection_workflow as workflow
from meridian.attempt_selection import (
    AttemptProjectionReference,
    AttemptSelectionActor,
    AttemptSelectionDecision,
    AttemptSelectionPolicyReference,
    attempt_selection_decision_to_json_bytes,
)
from meridian.attempt_selection_storage import (
    AttemptCandidateDerivation,
    AttemptSelectionDecisionSelectionResult,
    StoredAttemptSelectionDecision,
    attempt_selection_decision_revision_relative_path,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="test_1",
)
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
DECIDED_AT = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)


def _decision(revision: int) -> AttemptSelectionDecision:
    source = AttemptProjectionReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
    )
    return AttemptSelectionDecision(
        schema_version="1",
        record_type="meridian_attempt_selection_decision",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        student_id=STUDENT_ID,
        membership_revision=3,
        membership_revision_sha256="a" * 64,
        policy=AttemptSelectionPolicyReference(
            policy_id="explicit_one",
            policy_revision=2,
            policy_revision_sha256="b" * 64,
        ),
        source_snapshot=source,
        candidates=(),
        selected_attempts=(),
        decision_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        actor=AttemptSelectionActor(
            kind="teacher",
            actor_id="teacher_local",
        ),
        rationale=None,
        decided_at=DECIDED_AT,
    )


def _stored(revision: int) -> StoredAttemptSelectionDecision:
    decision = _decision(revision)
    content = attempt_selection_decision_to_json_bytes(decision)
    digest = hashlib.sha256(content).hexdigest()
    return StoredAttemptSelectionDecision(
        decision=decision,
        decision_sha256=digest,
        path=Path(f"{revision}.json"),
        relative_path=attempt_selection_decision_revision_relative_path(
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            STUDENT_ID,
            revision,
        ),
        content=content,
    )


def _membership() -> object:
    return SimpleNamespace(
        decision=SimpleNamespace(
            decision="included",
            membership_revision=3,
        ),
        decision_sha256="a" * 64,
    )


def _policy() -> object:
    return SimpleNamespace(
        policy=SimpleNamespace(policy_revision=2),
        policy_sha256="b" * 64,
    )


def _derivation(stored: StoredAttemptSelectionDecision) -> AttemptCandidateDerivation:
    return AttemptCandidateDerivation(
        status="applicable",
        source_snapshot=stored.decision.source_snapshot,
        student_id=STUDENT_ID,
        candidates=stored.decision.candidates,
    )


def _install_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current: int | None = 2,
) -> dict[int, StoredAttemptSelectionDecision]:
    stored = {1: _stored(1), 2: _stored(2)}
    monkeypatch.setattr(
        workflow,
        "list_attempt_selection_decision_revisions",
        lambda *args: (1, 2),
    )
    monkeypatch.setattr(
        workflow,
        "load_attempt_selection_decision_revision",
        lambda *args: stored[args[-1]],
    )
    monkeypatch.setattr(
        workflow,
        "get_current_attempt_selection_decision_revision",
        lambda *args: current,
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args: _membership(),
    )
    monkeypatch.setattr(
        workflow,
        "load_current_attempt_selection_policy",
        lambda *args: _policy(),
    )
    monkeypatch.setattr(
        workflow,
        "derive_attempt_candidates",
        lambda *args: _derivation(stored[1]),
    )
    return stored


def test_preview_allows_exact_live_historical_revision_without_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _install_state(monkeypatch, current=2)
    monkeypatch.setattr(
        workflow,
        "select_attempt_selection_decision_revision",
        lambda *args, **kwargs: pytest.fail("preview must not select"),
    )

    preview = workflow.preview_attempt_decision_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        1,
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )

    assert preview.target is stored[1]
    assert preview.target_revision == 1
    assert preview.history == (1, 2)
    assert preview.latest_revision == 2
    assert preview.target_is_latest is False
    assert preview.expected_current_decision_revision == 2


def test_preview_rejects_missing_or_nonpositive_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch)

    with pytest.raises(
        workflow.AttemptDecisionSelectionScopeError,
        match="positive integer",
    ):
        workflow.preview_attempt_decision_selection(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            STUDENT_ID,
            0,
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )

    with pytest.raises(
        workflow.AttemptDecisionSelectionScopeError,
        match="not present",
    ):
        workflow.preview_attempt_decision_selection(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            STUDENT_ID,
            3,
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )


def test_preview_rejects_historical_target_with_stale_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_current_attempt_selection_policy",
        lambda *args: SimpleNamespace(
            policy=SimpleNamespace(policy_revision=3),
            policy_sha256="c" * 64,
        ),
    )

    with pytest.raises(
        workflow.AttemptDecisionSelectionStaleError,
        match="policy basis",
    ):
        workflow.preview_attempt_decision_selection(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            STUDENT_ID,
            1,
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )


def test_preview_rejects_changed_candidate_or_eligibility_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "derive_attempt_candidates",
        lambda *args: AttemptCandidateDerivation(
            status="applicable",
            source_snapshot=AttemptProjectionReference(
                work=WORK,
                publication_id=PUBLICATION_ID,
                cache_key=CACHE_KEY,
                snapshot_digest="4" * 64,
            ),
            student_id=STUDENT_ID,
            candidates=(),
        ),
    )

    with pytest.raises(
        workflow.AttemptDecisionSelectionStaleError,
        match="candidate or eligibility",
    ):
        workflow.preview_attempt_decision_selection(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            STUDENT_ID,
            1,
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )


def test_commit_delegates_exact_target_and_current_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _install_state(monkeypatch, current=2)
    preview = workflow.preview_attempt_decision_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        1,
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []
    authorized = object()

    def select(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return AttemptSelectionDecisionSelectionResult(
            disposition="updated",
            stored=stored[1],
            derivation=_derivation(stored[1]),
        )

    monkeypatch.setattr(
        workflow,
        "select_attempt_selection_decision_revision",
        select,
    )

    result = workflow.commit_attempt_decision_selection_preview(
        "workspace",
        preview,
        authorized_snapshot=authorized,  # type: ignore[arg-type]
    )

    assert observed == [
        (
            (
                "workspace",
                CLASS_ID,
                GRADE_ITEM_ID,
                WORK,
                STUDENT_ID,
                1,
            ),
            {
                "authorized_snapshot": authorized,
                "expected_current_decision_revision": 2,
            },
        )
    ]
    assert result.previous_current_decision_revision == 2
    assert result.selected_revision == 1
    assert result.selected_decision_sha256 == stored[1].decision_sha256
    assert result.selection_disposition == "updated"
    assert result.authoring_action == "not_performed"


def test_commit_rejects_changed_current_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch, current=2)
    preview = workflow.preview_attempt_decision_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        1,
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        workflow,
        "get_current_attempt_selection_decision_revision",
        lambda *args: 1,
    )
    monkeypatch.setattr(
        workflow,
        "select_attempt_selection_decision_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not select"),
    )

    with pytest.raises(
        workflow.AttemptDecisionSelectionStaleError,
        match="selector",
    ):
        workflow.commit_attempt_decision_selection_preview(
            "workspace",
            preview,
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )


def test_commit_rejects_changed_history_before_selector_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch)
    preview = workflow.preview_attempt_decision_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        1,
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        workflow,
        "list_attempt_selection_decision_revisions",
        lambda *args: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "select_attempt_selection_decision_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not select"),
    )

    with pytest.raises(
        workflow.AttemptDecisionSelectionStaleError,
        match="history",
    ):
        workflow.commit_attempt_decision_selection_preview(
            "workspace",
            preview,
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )
