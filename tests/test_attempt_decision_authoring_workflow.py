from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.attempt_decision_authoring_workflow as workflow
from meridian.attempt_selection import (
    AttemptCandidate,
    AttemptEligibilityBasis,
    AttemptNativeIdentity,
    AttemptObservationReference,
    AttemptProjectionReference,
    AttemptSelectionActor,
    AttemptSelectionPolicy,
    AttemptTargetReference,
)
from meridian.evidence_eligibility import EvidenceSourceReference

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
POLICY_ID = "explicit_one"
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="test_1",
)
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
DECIDED_AT = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)


def _snapshot_ref() -> AttemptProjectionReference:
    return AttemptProjectionReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
    )


def _attempt(sequence: int) -> AttemptObservationReference:
    return AttemptObservationReference(
        source_snapshot=_snapshot_ref(),
        student_id=STUDENT_ID,
        target=AttemptTargetReference(
            target_kind="attempt",
            target_id=f"attempt_{sequence}",
            owning_system="scoreform",
            contract_version="v1",
        ),
        native=AttemptNativeIdentity(identifier=None, sequence=sequence),
    )


def _candidate(sequence: int) -> AttemptCandidate:
    source = EvidenceSourceReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        item_id=f"attempt_{sequence}_score",
    )
    return AttemptCandidate(
        attempt=_attempt(sequence),
        eligible_evidence=(
            AttemptEligibilityBasis(
                source=source,
                eligibility_revision=1,
                eligibility_decision_sha256=str(sequence) * 64,
            ),
        ),
    )


def _policy() -> AttemptSelectionPolicy:
    return AttemptSelectionPolicy(
        schema_version="1",
        record_type="meridian_attempt_selection_policy",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        policy_id=POLICY_ID,
        policy_revision=2,
        supersedes_revision=1,
        selection_basis="explicit",
        minimum_selected=0,
        maximum_selected=2,
        actor=AttemptSelectionActor(
            kind="teacher",
            actor_id="teacher_local",
        ),
        rationale=None,
        revised_at=DECIDED_AT - timedelta(hours=1),
    )


def _membership() -> object:
    return SimpleNamespace(
        decision=SimpleNamespace(
            decision="included",
            membership_revision=3,
        ),
        decision_sha256="a" * 64,
    )


def _stored_policy() -> object:
    return SimpleNamespace(
        policy=_policy(),
        policy_sha256="b" * 64,
    )


def _derivation() -> object:
    return SimpleNamespace(
        status="applicable",
        source_snapshot=_snapshot_ref(),
        student_id=STUDENT_ID,
        candidates=(_candidate(1), _candidate(2)),
    )


def _install_current_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    history: tuple[int, ...] = (),
    previous: object | None = None,
) -> None:
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args: _membership(),
    )
    monkeypatch.setattr(
        workflow,
        "load_current_attempt_selection_policy",
        lambda *args: _stored_policy(),
    )
    monkeypatch.setattr(
        workflow,
        "derive_attempt_candidates",
        lambda *args: _derivation(),
    )
    monkeypatch.setattr(
        workflow,
        "list_attempt_selection_decision_revisions",
        lambda *args: history,
    )
    if previous is not None:
        monkeypatch.setattr(
            workflow,
            "load_attempt_selection_decision_revision",
            lambda *args: previous,
        )
    monkeypatch.setattr(
        workflow,
        "get_current_attempt_selection_decision_revision",
        lambda *args: None,
    )


def test_preview_is_read_only_and_normalizes_selection_to_candidate_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_current_dependencies(monkeypatch)
    derivation = _derivation()
    monkeypatch.setattr(
        workflow,
        "write_attempt_selection_decision_revision",
        lambda *args, **kwargs: pytest.fail("preview must not write"),
    )

    preview = workflow.preview_attempt_decision_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        POLICY_ID,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        selected_attempts=(
            derivation.candidates[1].attempt,
            derivation.candidates[0].attempt,
        ),
        actor_id="teacher_local",
        decided_at=DECIDED_AT,
        rationale="Use both attempts explicitly.",
    )

    assert preview.decision_revision == 1
    assert preview.history == ()
    assert preview.candidate_count == 2
    assert preview.selected_count == 2
    assert preview.candidate.selected_attempts == tuple(
        candidate.attempt for candidate in derivation.candidates
    )
    assert preview.candidate.membership_revision == 3
    assert preview.candidate.policy.policy_revision == 2
    assert preview.candidate.actor.kind == "teacher"
    assert preview.reviewed_current_decision_revision is None


def test_preview_rejects_unselected_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args: None,
    )

    with pytest.raises(
        workflow.AttemptDecisionAuthoringScopeError,
        match="included Grade Item membership",
    ):
        workflow.preview_attempt_decision_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            STUDENT_ID,
            POLICY_ID,
            authorized_snapshot=object(),  # type: ignore[arg-type]
            selected_attempts=(),
            actor_id="teacher_local",
            decided_at=DECIDED_AT,
        )


def test_preview_rejects_nonapplicable_candidate_derivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_current_dependencies(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "derive_attempt_candidates",
        lambda *args: SimpleNamespace(
            status="unsupported_attempt_shape",
            source_snapshot=_snapshot_ref(),
            candidates=(),
        ),
    )

    with pytest.raises(
        workflow.AttemptDecisionAuthoringScopeError,
        match="unsupported_attempt_shape",
    ):
        workflow.preview_attempt_decision_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            STUDENT_ID,
            POLICY_ID,
            authorized_snapshot=object(),  # type: ignore[arg-type]
            selected_attempts=(),
            actor_id="teacher_local",
            decided_at=DECIDED_AT,
        )


def test_preview_rejects_attempt_not_in_exact_current_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_current_dependencies(monkeypatch)
    foreign = AttemptObservationReference(
        source_snapshot=_snapshot_ref(),
        student_id=STUDENT_ID,
        target=AttemptTargetReference(
            target_kind="attempt",
            target_id="attempt_3",
            owning_system="scoreform",
            contract_version="v1",
        ),
        native=AttemptNativeIdentity(identifier=None, sequence=3),
    )

    with pytest.raises(
        workflow.AttemptDecisionAuthoringScopeError,
        match="exact current candidate set",
    ):
        workflow.preview_attempt_decision_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            STUDENT_ID,
            POLICY_ID,
            authorized_snapshot=object(),  # type: ignore[arg-type]
            selected_attempts=(foreign,),
            actor_id="teacher_local",
            decided_at=DECIDED_AT,
        )


def test_preview_enforces_current_policy_cardinality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_current_dependencies(monkeypatch)
    policy = _policy()
    object.__setattr__(policy, "maximum_selected", 1)
    monkeypatch.setattr(
        workflow,
        "load_current_attempt_selection_policy",
        lambda *args: SimpleNamespace(
            policy=policy,
            policy_sha256="b" * 64,
        ),
    )
    derivation = _derivation()

    with pytest.raises(
        workflow.AttemptDecisionAuthoringScopeError,
        match="cardinality",
    ):
        workflow.preview_attempt_decision_authoring(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            STUDENT_ID,
            POLICY_ID,
            authorized_snapshot=object(),  # type: ignore[arg-type]
            selected_attempts=tuple(
                candidate.attempt for candidate in derivation.candidates
            ),
            actor_id="teacher_local",
            decided_at=DECIDED_AT,
        )


def test_preview_appends_latest_persisted_history_not_current_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_current_dependencies(monkeypatch)
    first = workflow.preview_attempt_decision_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        POLICY_ID,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        selected_attempts=(),
        actor_id="teacher_local",
        decided_at=DECIDED_AT - timedelta(minutes=10),
    )
    previous = SimpleNamespace(
        decision=replace(
            first.candidate,
            decision_revision=2,
            supersedes_revision=1,
            decided_at=DECIDED_AT - timedelta(minutes=5),
        ),
        decision_sha256="c" * 64,
    )
    _install_current_dependencies(
        monkeypatch,
        history=(1, 2),
        previous=previous,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_attempt_selection_decision_revision",
        lambda *args: 1,
    )

    preview = workflow.preview_attempt_decision_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        POLICY_ID,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        selected_attempts=(),
        actor_id="teacher_local",
        decided_at=DECIDED_AT,
    )

    assert preview.decision_revision == 3
    assert preview.candidate.supersedes_revision == 2
    assert preview.latest_persisted_decision_sha256 == "c" * 64
    assert preview.reviewed_current_decision_revision == 1


def test_commit_revalidates_dependencies_and_writes_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_current_dependencies(monkeypatch)
    preview = workflow.preview_attempt_decision_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        POLICY_ID,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        selected_attempts=(),
        actor_id="teacher_local",
        decided_at=DECIDED_AT,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def write(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(decision=preview.candidate),
        )

    monkeypatch.setattr(
        workflow,
        "write_attempt_selection_decision_revision",
        write,
    )
    authorized = object()

    result = workflow.commit_attempt_decision_authoring_preview(
        "workspace",
        preview,
        authorized_snapshot=authorized,  # type: ignore[arg-type]
    )

    assert observed == [
        (
            ("workspace", preview.candidate),
            {"authorized_snapshot": authorized},
        )
    ]
    assert result.written_revision == 1
    assert result.write_disposition == "created"
    assert result.selection_action == "not_performed"


def test_commit_rejects_changed_candidate_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_current_dependencies(monkeypatch)
    preview = workflow.preview_attempt_decision_authoring(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        STUDENT_ID,
        POLICY_ID,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        selected_attempts=(),
        actor_id="teacher_local",
        decided_at=DECIDED_AT,
    )
    changed = _derivation()
    changed.candidates = (_candidate(1),)
    monkeypatch.setattr(
        workflow,
        "derive_attempt_candidates",
        lambda *args: changed,
    )
    monkeypatch.setattr(
        workflow,
        "write_attempt_selection_decision_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not write"),
    )

    with pytest.raises(
        workflow.AttemptDecisionAuthoringStaleError,
        match="candidate",
    ):
        workflow.commit_attempt_decision_authoring_preview(
            "workspace",
            preview,
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )
