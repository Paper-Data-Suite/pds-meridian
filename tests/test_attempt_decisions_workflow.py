from __future__ import annotations

from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.attempt_decisions_workflow as workflow
from meridian.attempt_selection import (
    AttemptNativeIdentity,
    AttemptObservationReference,
    AttemptProjectionReference,
    AttemptTargetReference,
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


def _attempt(sequence: int) -> AttemptObservationReference:
    return AttemptObservationReference(
        source_snapshot=AttemptProjectionReference(
            work=WORK,
            publication_id=PUBLICATION_ID,
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
        ),
        student_id=STUDENT_ID,
        target=AttemptTargetReference(
            target_kind="attempt",
            target_id=f"attempt_{sequence}",
            owning_system="scoreform",
            contract_version="v1",
        ),
        native=AttemptNativeIdentity(
            identifier=None,
            sequence=sequence,
        ),
    )


def _candidate(sequence: int, evidence_count: int = 2) -> object:
    return SimpleNamespace(
        attempt=_attempt(sequence),
        eligible_evidence=tuple(object() for _ in range(evidence_count)),
    )


def _authorized_snapshot() -> object:
    publication = SimpleNamespace(
        work=WORK,
        publication_id=PUBLICATION_ID,
    )
    return SimpleNamespace(
        stored=SimpleNamespace(
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
            snapshot=SimpleNamespace(
                source=SimpleNamespace(publication=publication),
            ),
        )
    )


def _resolution(
    status: str,
    *,
    candidates: tuple[object, ...] = (),
    selected: object | None = None,
    current_policy: object | None = None,
    operative: bool = False,
) -> object:
    return SimpleNamespace(
        status=status,
        selected=selected,
        current_policy=current_policy,
        current_candidates=candidates,
        operative_selection=operative,
    )


def _install_authorized_type(monkeypatch: pytest.MonkeyPatch) -> object:
    snapshot = _authorized_snapshot()
    monkeypatch.setattr(
        workflow,
        "AuthorizedProjectionSnapshot",
        type(snapshot),
    )
    return snapshot


def test_no_decision_projects_candidates_without_ranking_or_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _install_authorized_type(monkeypatch)
    candidates = (_candidate(1, 3), _candidate(2, 1))
    monkeypatch.setattr(
        workflow,
        "resolve_current_attempt_selection",
        lambda *args, **kwargs: _resolution(
            "no_decision",
            candidates=candidates,
        ),
    )

    projection = workflow.project_attempt_decisions(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        authorized_snapshot=snapshot,  # type: ignore[arg-type]
    )

    assert projection.status == "no_decision"
    assert projection.resolution_status == "no_decision"
    assert projection.candidate_count == 2
    assert [row.native_sequence for row in projection.candidates] == [1, 2]
    assert [row.eligible_evidence_count for row in projection.candidates] == [3, 1]
    assert not any(
        row.selected_in_reviewed_decision for row in projection.candidates
    )
    assert projection.reviewed_selected_attempts == ()
    assert projection.operative_selection is False


def test_selected_projection_marks_only_explicit_reviewed_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _install_authorized_type(monkeypatch)
    first = _candidate(1)
    second = _candidate(2)
    selected_attempt = second.attempt
    selected = SimpleNamespace(
        decision=SimpleNamespace(
            decision_revision=4,
            selected_attempts=(selected_attempt,),
        ),
        decision_sha256="4" * 64,
    )
    policy = SimpleNamespace(
        policy=SimpleNamespace(
            policy_id="explicit_one",
            policy_revision=2,
            minimum_selected=1,
            maximum_selected=1,
        ),
        policy_sha256="5" * 64,
    )
    monkeypatch.setattr(
        workflow,
        "resolve_current_attempt_selection",
        lambda *args, **kwargs: _resolution(
            "selected",
            candidates=(first, second),
            selected=selected,
            current_policy=policy,
            operative=True,
        ),
    )

    projection = workflow.project_attempt_decisions(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        authorized_snapshot=snapshot,  # type: ignore[arg-type]
    )

    assert projection.status == "selected"
    assert projection.selected_decision_revision == 4
    assert projection.selected_decision_sha256 == "4" * 64
    assert projection.reviewed_selected_attempts == (selected_attempt,)
    assert [
        row.selected_in_reviewed_decision for row in projection.candidates
    ] == [False, True]
    assert projection.current_policy_id == "explicit_one"
    assert projection.current_policy_revision == 2
    assert projection.minimum_selected == 1
    assert projection.maximum_selected == 1
    assert projection.operative_selection is True


def test_selected_none_remains_distinct_from_no_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _install_authorized_type(monkeypatch)
    selected = SimpleNamespace(
        decision=SimpleNamespace(
            decision_revision=1,
            selected_attempts=(),
        ),
        decision_sha256="6" * 64,
    )
    monkeypatch.setattr(
        workflow,
        "resolve_current_attempt_selection",
        lambda *args, **kwargs: _resolution(
            "selected_none",
            candidates=(_candidate(1),),
            selected=selected,
            operative=True,
        ),
    )

    projection = workflow.project_attempt_decisions(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        authorized_snapshot=snapshot,  # type: ignore[arg-type]
    )

    assert projection.status == "selected_none"
    assert projection.reviewed_selected_count == 0
    assert projection.selected_decision_revision == 1
    assert projection.operative_selection is True


@pytest.mark.parametrize(
    "resolution_status",
    [
        "policy_stale",
        "membership_stale",
        "eligibility_stale",
        "candidate_set_stale",
        "source_unverifiable",
    ],
)
def test_nonoperative_dependency_states_normalize_to_stale_with_reason(
    monkeypatch: pytest.MonkeyPatch,
    resolution_status: str,
) -> None:
    snapshot = _install_authorized_type(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "resolve_current_attempt_selection",
        lambda *args, **kwargs: _resolution(
            resolution_status,
            candidates=(_candidate(1),),
            operative=False,
        ),
    )

    projection = workflow.project_attempt_decisions(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        authorized_snapshot=snapshot,  # type: ignore[arg-type]
    )

    assert projection.status == "stale"
    assert projection.resolution_status == resolution_status
    assert projection.stale_reason == resolution_status
    assert projection.operative_selection is False


@pytest.mark.parametrize(
    "resolution_status",
    ["not_applicable", "unsupported_attempt_shape"],
)
def test_applicability_states_remain_exact(
    monkeypatch: pytest.MonkeyPatch,
    resolution_status: str,
) -> None:
    snapshot = _install_authorized_type(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "resolve_current_attempt_selection",
        lambda *args, **kwargs: _resolution(resolution_status),
    )

    projection = workflow.project_attempt_decisions(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        authorized_snapshot=snapshot,  # type: ignore[arg-type]
    )

    assert projection.status == resolution_status
    assert projection.stale_reason is None
    assert projection.candidate_count == 0


def test_invalid_authorized_snapshot_is_rejected() -> None:
    with pytest.raises(
        workflow.AttemptDecisionWorkflowScopeError,
        match="AuthorizedProjectionSnapshot",
    ):
        workflow.project_attempt_decisions(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            STUDENT_ID,
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )
