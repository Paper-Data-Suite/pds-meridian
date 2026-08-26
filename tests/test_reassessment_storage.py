from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
    ReassessmentCombination,
    ReassessmentDecision,
    ReassessmentPolicy,
    ReassessmentPolicyReference,
    ReplacementRelationship,
    reassessment_subject_key,
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


def actor() -> ReassessmentActor:
    return ReassessmentActor("teacher", "teacher_local")


def policy(*, revision: int = 1) -> ReassessmentPolicy:
    return ReassessmentPolicy(
        schema_version="1",
        record_type="meridian_reassessment_policy",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        policy_id="teacher_reassessment",
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        relationship_basis="explicit",
        allowed_modes=("retain", "replace", "combine", "recency"),
        actor=actor(),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def decision(
    *,
    revision: int = 1,
    mode: str = "replace",
    attempt_ref_revision: int = 1,
    attempt_digest: str = ATTEMPT_DIGEST,
    policy_revision: int = 1,
    policy_digest: str = POLICY_DIGEST,
) -> ReassessmentDecision:
    a1, a2, a3 = attempt(1), attempt(2), attempt(3)
    if mode == "retain":
        contributing = (a1, a2)
        replacements: tuple[ReplacementRelationship, ...] = ()
        combinations: tuple[ReassessmentCombination, ...] = ()
        recency: tuple[AttemptObservationReference, ...] = ()
    elif mode == "combine":
        contributing = (a1, a2)
        replacements = ()
        combinations = (ReassessmentCombination("combo_1", (a1, a2)),)
        recency = ()
    elif mode == "recency":
        contributing = (a2, a3)
        replacements = ()
        combinations = ()
        recency = (a1, a2, a3)
    else:
        contributing = (a2,)
        replacements = (ReplacementRelationship(a2, (a1,)),)
        combinations = ()
        recency = ()
    return ReassessmentDecision(
        schema_version="1",
        record_type="meridian_reassessment_decision",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        student_id="student_1",
        attempt_selection=AttemptSelectionDecisionReference(
            attempt_ref_revision, attempt_digest
        ),
        policy=ReassessmentPolicyReference(
            "teacher_reassessment", policy_revision, policy_digest
        ),
        mode=mode,  # type: ignore[arg-type]
        contributing_attempts=contributing,
        replacement_relationships=replacements,
        combinations=combinations,
        recency_order=recency,
        decision_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        actor=actor(),
        rationale=None,
        decided_at=NOW + timedelta(minutes=revision - 1),
    )


def upstream(
    *,
    status: str = "selected",
    selected_attempts: tuple[AttemptObservationReference, ...] = (
        attempt(1),
        attempt(2),
    ),
    revision: int = 1,
    digest: str = ATTEMPT_DIGEST,
    operative: bool = True,
) -> AttemptSelectionResolution:
    selected = None
    if status in {"selected", "selected_none"}:
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


def root(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def allow_policy_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "_require_attempt_selection_root", lambda *args: None)


def allow_decision_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        storage,
        "_validate_decision_dependencies",
        lambda *args, **kwargs: upstream(),
    )


def test_canonical_paths_are_nested_under_attempt_selection(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    path = storage.reassessment_policy_revision_path(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "teacher_reassessment", 1
    )
    assert "attempt_selection/reassessment/policies" in path.as_posix()
    decision_path = storage.reassessment_decision_revision_path(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1", 1
    )
    assert reassessment_subject_key(
        CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    ) in decision_path.as_posix()


def test_policy_write_is_immutable_idempotent_and_not_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    first = storage.write_reassessment_policy_revision(workspace, policy())
    second = storage.write_reassessment_policy_revision(workspace, policy())
    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert first.stored.content == second.stored.content
    assert (
        hashlib.sha256(first.stored.content).hexdigest()
        == first.stored.policy_sha256
    )
    assert storage.get_current_reassessment_policy_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
    ) is None


def test_policy_collision_and_contiguous_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    storage.write_reassessment_policy_revision(workspace, policy())
    with pytest.raises(storage.ReassessmentStorageConflictError):
        storage.write_reassessment_policy_revision(
            workspace, replace(policy(), rationale="different")
        )
    storage.write_reassessment_policy_revision(workspace, policy(revision=2))
    assert storage.list_reassessment_policy_revisions(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
    ) == (1, 2)


def test_policy_selection_is_explicit_cas_and_reselectable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    storage.write_reassessment_policy_revision(workspace, policy())
    storage.write_reassessment_policy_revision(workspace, policy(revision=2))
    selected = storage.select_reassessment_policy_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        policy().policy_id,
        2,
        expected_current_policy_revision=None,
    )
    assert selected.disposition == "created"
    assert storage.get_current_reassessment_policy_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
    ) == 2
    with pytest.raises(storage.ReassessmentStorageConflictError):
        storage.select_reassessment_policy_revision(
            workspace,
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            policy().policy_id,
            1,
            expected_current_policy_revision=None,
        )
    storage.select_reassessment_policy_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        policy().policy_id,
        1,
        expected_current_policy_revision=2,
    )
    assert storage.get_current_reassessment_policy_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
    ) == 1


def test_decision_write_is_immutable_and_does_not_auto_select(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_decision_dependencies(monkeypatch)
    workspace = root(tmp_path)
    first = storage.write_reassessment_decision_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    second = storage.write_reassessment_decision_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert storage.get_current_reassessment_decision_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    ) is None


def test_exact_replay_survives_dependency_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_decision_dependencies(monkeypatch)
    workspace = root(tmp_path)
    storage.write_reassessment_decision_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        storage,
        "_validate_decision_dependencies",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    replay = storage.write_reassessment_decision_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    assert replay.disposition == "existing"


def test_decision_history_and_explicit_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_decision_dependencies(monkeypatch)
    workspace = root(tmp_path)
    storage.write_reassessment_decision_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    storage.write_reassessment_decision_revision(
        workspace,
        replace(
            decision(revision=2),
            rationale="teacher changed treatment",
        ),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert storage.list_reassessment_decision_revisions(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    ) == (1, 2)
    result = storage.select_reassessment_decision_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        2,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        expected_current_decision_revision=None,
    )
    assert result.disposition == "created"
    assert storage.get_current_reassessment_decision_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    ) == 2


def test_resolver_pass_through_states_do_not_require_reassessment_decision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    monkeypatch.setattr(storage, "load_current_reassessment_decision", lambda *a: None)
    cases = (
        (upstream(status="not_applicable", operative=False), "not_applicable"),
        (
            upstream(status="selected_none", selected_attempts=(), operative=True),
            "selected_none",
        ),
        (
            upstream(status="no_decision", operative=False),
            "attempt_selection_unresolved",
        ),
    )
    for source, expected in cases:
        monkeypatch.setattr(
            storage, "resolve_current_attempt_selection", lambda *a, **k: source
        )
        result = storage.resolve_current_reassessment(
            workspace,
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            "student_1",
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )
        assert result.status == expected
        assert not result.operative_reassessment


def test_single_selected_passes_through_without_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    source = upstream(selected_attempts=(attempt(1),))
    monkeypatch.setattr(storage, "load_current_reassessment_decision", lambda *a: None)
    monkeypatch.setattr(
        storage, "resolve_current_attempt_selection", lambda *a, **k: source
    )
    result = storage.resolve_current_reassessment(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert result.status == "single_selected"
    assert result.contributing_attempts == (attempt(1),)
    assert result.operative_reassessment


def test_multiple_selected_without_decision_fails_closed_as_no_decision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    source = upstream()
    monkeypatch.setattr(storage, "load_current_reassessment_decision", lambda *a: None)
    monkeypatch.setattr(
        storage, "resolve_current_attempt_selection", lambda *a, **k: source
    )
    result = storage.resolve_current_reassessment(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert result.status == "no_decision"
    assert result.contributing_attempts == ()
    assert not result.operative_reassessment


def test_resolved_replacement_returns_only_explicit_contributor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    source = upstream()
    stored_decision = SimpleNamespace(decision=decision(), decision_sha256="6" * 64)
    stored_policy = SimpleNamespace(policy=policy(), policy_sha256=POLICY_DIGEST)
    monkeypatch.setattr(
        storage, "load_current_reassessment_decision", lambda *a: stored_decision
    )
    monkeypatch.setattr(
        storage, "resolve_current_attempt_selection", lambda *a, **k: source
    )
    monkeypatch.setattr(
        storage, "load_current_reassessment_policy", lambda *a: stored_policy
    )
    result = storage.resolve_current_reassessment(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert result.status == "resolved"
    assert result.contributing_attempts == (attempt(2),)
    assert result.replacement_relationships[0].replaced_attempts == (attempt(1),)
    assert result.operative_reassessment


def test_changed_attempt_selection_makes_old_decision_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    source = upstream(revision=2, digest="7" * 64)
    stored_decision = SimpleNamespace(decision=decision(), decision_sha256="6" * 64)
    monkeypatch.setattr(
        storage, "load_current_reassessment_decision", lambda *a: stored_decision
    )
    monkeypatch.setattr(
        storage, "resolve_current_attempt_selection", lambda *a, **k: source
    )
    result = storage.resolve_current_reassessment(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert result.status == "attempt_selection_stale"
    assert not result.operative_reassessment


def test_changed_reassessment_policy_makes_old_decision_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    source = upstream()
    stored_decision = SimpleNamespace(decision=decision(), decision_sha256="6" * 64)
    newer = SimpleNamespace(policy=policy(revision=2), policy_sha256="8" * 64)
    monkeypatch.setattr(
        storage, "load_current_reassessment_decision", lambda *a: stored_decision
    )
    monkeypatch.setattr(
        storage, "resolve_current_attempt_selection", lambda *a, **k: source
    )
    monkeypatch.setattr(storage, "load_current_reassessment_policy", lambda *a: newer)
    result = storage.resolve_current_reassessment(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert result.status == "policy_stale"
    assert not result.operative_reassessment


def test_relationship_validation_never_uses_attempt_sequence_as_preference() -> None:
    # Earlier/lower sequence can explicitly replace later/higher sequence.
    selected = (attempt(1), attempt(2))
    reverse = replace(
        decision(),
        contributing_attempts=(attempt(1),),
        replacement_relationships=(
            ReplacementRelationship(attempt(1), (attempt(2),)),
        ),
    )
    storage._validate_relationships_against_selected(reverse, selected)


def test_relationship_validation_rejects_nonselected_attempt() -> None:
    value = replace(
        decision(),
        contributing_attempts=(attempt(2), attempt(3)),
        replacement_relationships=(
            ReplacementRelationship(attempt(3), (attempt(1),)),
        ),
    )
    with pytest.raises(
        storage.ReassessmentDependencyError, match="only exact selected"
    ):
        storage._validate_relationships_against_selected(
            value, (attempt(1), attempt(2))
        )


def test_digest_tamper_and_noncanonical_sidecar_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    written = storage.write_reassessment_policy_revision(workspace, policy()).stored
    digest_path = Path(str(written.path) + ".sha256")
    digest_path.write_text("0" * 64 + "\n", encoding="ascii")
    with pytest.raises(storage.ReassessmentStorageIntegrityError, match="digest"):
        storage.load_reassessment_policy_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id, 1
        )

    digest_path.write_text(
        hashlib.sha256(written.content).hexdigest() + "\r\n", encoding="ascii"
    )
    with pytest.raises(storage.ReassessmentStorageIntegrityError, match="canonical LF"):
        storage.load_reassessment_policy_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id, 1
        )


def test_pointer_tamper_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    storage.write_reassessment_policy_revision(workspace, policy())
    storage.select_reassessment_policy_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        policy().policy_id,
        1,
        expected_current_policy_revision=None,
    )
    pointer = storage.reassessment_policy_current_path(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
    )
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["policy_sha256"] = "0" * 64
    pointer.write_bytes(
        (json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    with pytest.raises(storage.ReassessmentStorageIntegrityError, match="digest"):
        storage.load_current_reassessment_policy(
            workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
        )


def test_unexpected_collection_entry_fails_closed(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    base = storage.reassessment_directory(workspace, CLASS_ID, GRADE_ITEM_ID, WORK)
    base.mkdir(parents=True)
    (base / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(storage.ReassessmentStorageIntegrityError, match="unexpected"):
        storage.list_reassessment_policy_revisions(
            workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "teacher_reassessment"
        )


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unavailable")
def test_symlinked_collection_is_rejected(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    base = storage.reassessment_directory(workspace, CLASS_ID, GRADE_ITEM_ID, WORK)
    base.mkdir(parents=True)
    target = tmp_path / "outside"
    target.mkdir()
    link = base / "policies"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted")
    with pytest.raises(storage.ReassessmentStorageIntegrityError):
        storage.list_reassessment_policy_revisions(
            workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "teacher_reassessment"
        )
