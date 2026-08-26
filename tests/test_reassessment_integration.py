from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.reassessment_storage as storage
from meridian.attempt_selection import (
    AttemptNativeIdentity,
    AttemptObservationReference,
    AttemptProjectionReference,
    AttemptTargetReference,
)
from meridian.attempt_selection_storage import AttemptSelectionResolution
from meridian.reassessment import (
    AttemptSelectionDecisionReference,
    ReassessmentActor,
    ReassessmentDecision,
    ReassessmentPolicy,
    ReassessmentPolicyReference,
    ReplacementRelationship,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
ATTEMPT_DIGEST = "4" * 64
POLICY_DIGEST = "5" * 64
NOW = datetime(2026, 8, 26, 4, tzinfo=UTC)


def attempt(number: int) -> AttemptObservationReference:
    return AttemptObservationReference(
        source_snapshot=AttemptProjectionReference(
            work=WORK,
            publication_id=PUBLICATION_ID,
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
        ),
        student_id="student_1",
        target=AttemptTargetReference(
            target_kind="attempt",
            target_id=f"attempt_{number}",
            owning_system=None,
            contract_version=None,
        ),
        native=AttemptNativeIdentity(identifier=None, sequence=number),
    )


def policy(*, modes: tuple[str, ...] = ("replace",)) -> ReassessmentPolicy:
    return ReassessmentPolicy(
        schema_version="1",
        record_type="meridian_reassessment_policy",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        policy_id="teacher_reassessment",
        policy_revision=1,
        supersedes_revision=None,
        relationship_basis="explicit",
        allowed_modes=modes,  # type: ignore[arg-type]
        actor=ReassessmentActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def decision() -> ReassessmentDecision:
    return ReassessmentDecision(
        schema_version="1",
        record_type="meridian_reassessment_decision",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        student_id="student_1",
        attempt_selection=AttemptSelectionDecisionReference(1, ATTEMPT_DIGEST),
        policy=ReassessmentPolicyReference(
            "teacher_reassessment", 1, POLICY_DIGEST
        ),
        mode="replace",
        contributing_attempts=(attempt(2),),
        replacement_relationships=(
            ReplacementRelationship(attempt(2), (attempt(1),)),
        ),
        combinations=(),
        recency_order=(),
        decision_revision=1,
        supersedes_revision=None,
        actor=ReassessmentActor("teacher", "teacher_local"),
        rationale=None,
        decided_at=NOW,
    )


def upstream(
    *,
    status: str = "selected",
    operative: bool = True,
    revision: int = 1,
    digest: str = ATTEMPT_DIGEST,
    selected_attempts: tuple[AttemptObservationReference, ...] = (
        attempt(1),
        attempt(2),
    ),
) -> AttemptSelectionResolution:
    selected = SimpleNamespace(
        decision=SimpleNamespace(
            decision_revision=revision,
            selected_attempts=selected_attempts,
        ),
        decision_sha256=digest,
    )
    return AttemptSelectionResolution(
        status=status,  # type: ignore[arg-type]
        selected=selected,  # type: ignore[arg-type]
        current_policy=None,
        current_candidates=(),
        operative_selection=operative,
    )


def install_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    upstream_value: AttemptSelectionResolution | None = None,
    exact_digest: str = ATTEMPT_DIGEST,
    policy_value: ReassessmentPolicy | None = None,
    policy_digest: str = POLICY_DIGEST,
) -> None:
    source = upstream() if upstream_value is None else upstream_value
    monkeypatch.setattr(
        storage,
        "load_attempt_selection_decision_revision",
        lambda *args: SimpleNamespace(
            decision=SimpleNamespace(selected_attempts=(attempt(1), attempt(2))),
            decision_sha256=exact_digest,
        ),
    )
    monkeypatch.setattr(
        storage, "resolve_current_attempt_selection", lambda *args, **kwargs: source
    )
    selected_policy = policy() if policy_value is None else policy_value
    stored_policy = SimpleNamespace(
        policy=selected_policy,
        policy_sha256=policy_digest,
    )
    monkeypatch.setattr(
        storage, "load_reassessment_policy_revision", lambda *args: stored_policy
    )
    monkeypatch.setattr(
        storage, "load_current_reassessment_policy", lambda *args: stored_policy
    )


def test_dependency_validation_binds_exact_attempt_selection_and_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_dependencies(monkeypatch)
    result = storage._validate_decision_dependencies(
        tmp_path,
        decision(),
        object(),  # type: ignore[arg-type]
        require_current_policy=True,
    )
    assert result.status == "selected"
    assert result.operative_selection


def test_dependency_validation_rejects_attempt_selection_digest_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_dependencies(monkeypatch, exact_digest="9" * 64)
    with pytest.raises(storage.ReassessmentDependencyError, match="digest"):
        storage._validate_decision_dependencies(
            tmp_path,
            decision(),
            object(),  # type: ignore[arg-type]
            require_current_policy=True,
        )


def test_dependency_validation_rejects_nonoperative_or_changed_upstream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_dependencies(
        monkeypatch,
        upstream_value=upstream(status="policy_stale", operative=False),
    )
    with pytest.raises(storage.ReassessmentStorageConflictError, match="not operative"):
        storage._validate_decision_dependencies(
            tmp_path,
            decision(),
            object(),  # type: ignore[arg-type]
            require_current_policy=True,
        )

    install_dependencies(monkeypatch, upstream_value=upstream(revision=2))
    with pytest.raises(storage.ReassessmentStorageConflictError, match="changed"):
        storage._validate_decision_dependencies(
            tmp_path,
            decision(),
            object(),  # type: ignore[arg-type]
            require_current_policy=True,
        )


def test_dependency_validation_rejects_mode_not_authorized_by_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_dependencies(monkeypatch, policy_value=policy(modes=("retain",)))
    with pytest.raises(storage.ReassessmentDependencyError, match="not allowed"):
        storage._validate_decision_dependencies(
            tmp_path,
            decision(),
            object(),  # type: ignore[arg-type]
            require_current_policy=True,
        )


def test_dependency_validation_rejects_policy_digest_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_dependencies(monkeypatch, policy_digest="9" * 64)
    with pytest.raises(storage.ReassessmentDependencyError, match="policy digest"):
        storage._validate_decision_dependencies(
            tmp_path,
            decision(),
            object(),  # type: ignore[arg-type]
            require_current_policy=True,
        )


def test_changed_selected_set_invalidates_reassessment_relationship(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_dependencies(
        monkeypatch,
        upstream_value=upstream(selected_attempts=(attempt(1), attempt(3))),
    )
    with pytest.raises(
        storage.ReassessmentDependencyError, match="only exact selected"
    ):
        storage._validate_decision_dependencies(
            tmp_path,
            decision(),
            object(),  # type: ignore[arg-type]
            require_current_policy=True,
        )


def test_quillan_and_concord_nonattempt_contracts_pass_through_not_applicable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # #30 owns producer applicability. #31 must not reinterpret native correction,
    # score supersession, moderation supersession, or publication revisions.
    non_attempt = upstream(status="not_applicable", operative=False)
    monkeypatch.setattr(
        storage, "load_current_reassessment_decision", lambda *args: None
    )
    monkeypatch.setattr(
        storage,
        "resolve_current_attempt_selection",
        lambda *args, **kwargs: non_attempt,
    )
    result = storage.resolve_current_reassessment(
        tmp_path,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert result.status == "not_applicable"
    assert result.selected is None
    assert result.contributing_attempts == ()
    assert not result.operative_reassessment


def test_no_native_value_or_timestamp_drives_relationship_choice() -> None:
    source = Path("meridian/reassessment_storage.py").read_text(encoding="utf-8")
    forbidden = (
        "max(score",
        "max(points",
        "latest(recorded_at",
        "max(attempt_number",
        "NativeStateValue",
    )
    for text in forbidden:
        assert text not in source
    # The reverse sequence direction is valid because preference is explicit.
    reverse = replace(
        decision(),
        contributing_attempts=(attempt(1),),
        replacement_relationships=(
            ReplacementRelationship(attempt(1), (attempt(2),)),
        ),
    )
    storage._validate_relationships_against_selected(
        reverse, (attempt(1), attempt(2))
    )
