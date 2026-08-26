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

import meridian.attempt_selection_storage as storage
from meridian.attempt_selection import (
    AttemptCandidate,
    AttemptEligibilityBasis,
    AttemptNativeIdentity,
    AttemptObservationReference,
    AttemptProjectionReference,
    AttemptSelectionActor,
    AttemptSelectionDecision,
    AttemptSelectionPolicy,
    AttemptSelectionPolicyReference,
    AttemptTargetReference,
    attempt_subject_key,
)
from meridian.evidence_eligibility import EvidenceSourceReference

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
MEMBERSHIP_DIGEST = "4" * 64
ELIGIBILITY_DIGEST = "6" * 64
NOW = datetime(2026, 8, 26, 1, tzinfo=UTC)


def root(tmp_path: Path) -> Path:
    value = tmp_path / "workspace"
    value.mkdir()
    return value


def projection() -> AttemptProjectionReference:
    return AttemptProjectionReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
    )


def attempt(number: int) -> AttemptObservationReference:
    return AttemptObservationReference(
        source_snapshot=projection(),
        student_id="student_1",
        target=AttemptTargetReference(
            target_kind="attempt",
            target_id=f"attempt_{number}",
            owning_system=None,
            contract_version=None,
        ),
        native=AttemptNativeIdentity(identifier=None, sequence=number),
    )


def basis(number: int) -> AttemptEligibilityBasis:
    return AttemptEligibilityBasis(
        source=EvidenceSourceReference(
            work=WORK,
            publication_id=PUBLICATION_ID,
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
            item_id=f"scoreform_item_{number}",
        ),
        eligibility_revision=1,
        eligibility_decision_sha256=ELIGIBILITY_DIGEST,
    )


def candidates() -> tuple[AttemptCandidate, ...]:
    return (
        AttemptCandidate(attempt=attempt(1), eligible_evidence=(basis(1),)),
        AttemptCandidate(attempt=attempt(2), eligible_evidence=(basis(2),)),
    )


def policy(
    *, revision: int = 1, minimum: int = 0, maximum: int | None = 1
) -> AttemptSelectionPolicy:
    return AttemptSelectionPolicy(
        schema_version="1",
        record_type="meridian_attempt_selection_policy",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        policy_id="teacher_explicit_attempts",
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        selection_basis="explicit",
        minimum_selected=minimum,
        maximum_selected=maximum,
        actor=AttemptSelectionActor(kind="teacher", actor_id="teacher_local"),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def policy_reference(
    stored: storage.StoredAttemptSelectionPolicy,
) -> AttemptSelectionPolicyReference:
    return AttemptSelectionPolicyReference(
        policy_id=stored.policy.policy_id,
        policy_revision=stored.policy.policy_revision,
        policy_revision_sha256=stored.policy_sha256,
    )


def decision(
    policy_ref: AttemptSelectionPolicyReference,
    *,
    revision: int = 1,
    selected: tuple[AttemptObservationReference, ...] | None = None,
    values: tuple[AttemptCandidate, ...] | None = None,
) -> AttemptSelectionDecision:
    available = candidates() if values is None else values
    chosen = (available[0].attempt,) if selected is None else selected
    return AttemptSelectionDecision(
        schema_version="1",
        record_type="meridian_attempt_selection_decision",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        student_id="student_1",
        membership_revision=1,
        membership_revision_sha256=MEMBERSHIP_DIGEST,
        policy=policy_ref,
        source_snapshot=projection(),
        candidates=available,
        selected_attempts=chosen,
        decision_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        actor=AttemptSelectionActor(kind="teacher", actor_id="teacher_local"),
        rationale=None,
        decided_at=NOW + timedelta(minutes=revision - 1),
    )


def allow_policy_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "_require_membership_history", lambda *args: None)


def derivation(
    values: tuple[AttemptCandidate, ...] | None = None,
) -> storage.AttemptCandidateDerivation:
    return storage.AttemptCandidateDerivation(
        status="applicable",
        source_snapshot=projection(),
        student_id="student_1",
        candidates=candidates() if values is None else values,
    )


def test_policy_path_is_nested_under_membership_relation(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    path = storage.attempt_selection_policy_revision_path(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "teacher_explicit_attempts", 1
    )
    assert path.as_posix().endswith(
        "/classes/synthetic_class_2026/modules/meridian/grade_items/"
        "unit1_assessment/memberships/scoreform/test_1/attempt_selection/"
        "policies/teacher_explicit_attempts/revisions/1.json"
    )


def test_subject_path_uses_deterministic_hash(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    path = storage.attempt_selection_decision_revision_path(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1", 1
    )
    key = attempt_subject_key(CLASS_ID, GRADE_ITEM_ID, WORK, "student_1")
    assert f"/students/{key}/revisions/1.json" in path.as_posix()
    assert "student_1" not in path.parent.parent.name


def test_policy_write_is_immutable_and_does_not_auto_select(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    first = storage.write_attempt_selection_policy_revision(workspace, policy())
    second = storage.write_attempt_selection_policy_revision(workspace, policy())
    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert first.stored.content == second.stored.content
    assert storage.get_current_attempt_selection_policy_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
    ) is None
    assert (
        hashlib.sha256(first.stored.content).hexdigest()
        == first.stored.policy_sha256
    )


def test_policy_revision_collision_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    storage.write_attempt_selection_policy_revision(workspace, policy())
    with pytest.raises(storage.AttemptSelectionStorageConflictError):
        storage.write_attempt_selection_policy_revision(
            workspace, replace(policy(), rationale="Different semantics")
        )


def test_policy_history_selection_and_historical_reselection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    storage.write_attempt_selection_policy_revision(workspace, policy())
    storage.write_attempt_selection_policy_revision(
        workspace, policy(revision=2, minimum=1, maximum=2)
    )
    assert storage.list_attempt_selection_policy_revisions(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
    ) == (1, 2)
    first = storage.select_attempt_selection_policy_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        policy().policy_id,
        2,
        expected_current_policy_revision=None,
    )
    assert first.disposition == "created"
    assert storage.get_current_attempt_selection_policy_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
    ) == 2
    second = storage.select_attempt_selection_policy_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        policy().policy_id,
        1,
        expected_current_policy_revision=2,
    )
    assert second.disposition == "updated"
    assert storage.get_current_attempt_selection_policy_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
    ) == 1


def test_policy_selection_stale_cas_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    storage.write_attempt_selection_policy_revision(workspace, policy())
    storage.select_attempt_selection_policy_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        policy().policy_id,
        1,
        expected_current_policy_revision=None,
    )
    with pytest.raises(
        storage.AttemptSelectionStorageConflictError, match="Expected current"
    ):
        storage.select_attempt_selection_policy_revision(
            workspace,
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            policy().policy_id,
            1,
            expected_current_policy_revision=None,
        )


def prepared_policy(
    monkeypatch: pytest.MonkeyPatch,
    workspace: Path,
) -> storage.StoredAttemptSelectionPolicy:
    allow_policy_root(monkeypatch)
    stored = storage.write_attempt_selection_policy_revision(workspace, policy()).stored
    storage.select_attempt_selection_policy_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        policy().policy_id,
        1,
        expected_current_policy_revision=None,
    )
    return stored


def test_decision_write_is_immutable_and_not_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    stored_policy = prepared_policy(monkeypatch, workspace)
    value = decision(policy_reference(stored_policy))
    monkeypatch.setattr(
        storage,
        "_validate_decision_dependencies",
        lambda *args, **kwargs: derivation(),
    )
    first = storage.write_attempt_selection_decision_revision(
        workspace, value, authorized_snapshot=object()  # type: ignore[arg-type]
    )
    second = storage.write_attempt_selection_decision_revision(
        workspace, value, authorized_snapshot=object()  # type: ignore[arg-type]
    )
    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert storage.get_current_attempt_selection_decision_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    ) is None


def test_decision_rejects_candidate_change_before_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    stored_policy = prepared_policy(monkeypatch, workspace)
    value = decision(policy_reference(stored_policy))
    monkeypatch.setattr(
        storage,
        "_validate_decision_dependencies",
        lambda *args, **kwargs: derivation((candidates()[0],)),
    )
    with pytest.raises(storage.AttemptSelectionStorageConflictError, match="candidate"):
        storage.write_attempt_selection_decision_revision(
            workspace, value, authorized_snapshot=object()  # type: ignore[arg-type]
        )


def test_decision_history_explicit_selection_and_historical_reselection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    stored_policy = prepared_policy(monkeypatch, workspace)
    ref = policy_reference(stored_policy)
    monkeypatch.setattr(
        storage,
        "_validate_decision_dependencies",
        lambda *args, **kwargs: derivation(),
    )
    storage.write_attempt_selection_decision_revision(
        workspace, decision(ref), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    storage.write_attempt_selection_decision_revision(
        workspace,
        decision(ref, revision=2, selected=()),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert storage.list_attempt_selection_decision_revisions(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    ) == (1, 2)
    first = storage.select_attempt_selection_decision_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        2,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        expected_current_decision_revision=None,
    )
    assert first.disposition == "created"
    assert storage.load_current_attempt_selection_decision(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    ).decision.selected_attempts == ()  # type: ignore[union-attr]
    second = storage.select_attempt_selection_decision_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        1,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        expected_current_decision_revision=2,
    )
    assert second.disposition == "updated"


def test_policy_pointer_digest_tamper_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    prepared_policy(monkeypatch, workspace)
    pointer = storage.attempt_selection_policy_current_path(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
    )
    payload = json.loads(pointer.read_bytes())
    payload["policy_sha256"] = "9" * 64
    pointer.write_bytes(
        (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    with pytest.raises(storage.AttemptSelectionStorageIntegrityError, match="digest"):
        storage.load_current_attempt_selection_policy(
            workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
        )


def test_decision_pointer_noncanonical_crlf_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    stored_policy = prepared_policy(monkeypatch, workspace)
    monkeypatch.setattr(
        storage,
        "_validate_decision_dependencies",
        lambda *args, **kwargs: derivation(),
    )
    storage.write_attempt_selection_decision_revision(
        workspace,
        decision(policy_reference(stored_policy)),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    storage.select_attempt_selection_decision_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        1,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        expected_current_decision_revision=None,
    )
    pointer = storage.attempt_selection_decision_current_path(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    )
    pointer.write_bytes(pointer.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(
        storage.AttemptSelectionStorageIntegrityError, match="canonically"
    ):
        storage.load_current_attempt_selection_decision(
            workspace, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
        )


def test_revision_digest_tamper_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    stored = prepared_policy(monkeypatch, workspace)
    digest = Path(str(stored.path) + ".sha256")
    digest.write_bytes(("9" * 64 + "\n").encode("ascii"))
    with pytest.raises(storage.AttemptSelectionStorageIntegrityError, match="digest"):
        storage.load_attempt_selection_policy_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id, 1
        )


def test_lock_conflict_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    relation = storage.attempt_selection_policy_directory(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id
    )
    (relation / "revisions").mkdir(parents=True)
    (relation / ".write.lock").write_bytes(b"busy\n")
    with pytest.raises(storage.AttemptSelectionStorageLockError):
        storage.write_attempt_selection_policy_revision(workspace, policy())


def test_symlinked_policy_revision_is_rejected_when_supported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    stored = storage.write_attempt_selection_policy_revision(workspace, policy()).stored
    target = tmp_path / "target.json"
    target.write_bytes(stored.content)
    stored.path.unlink()
    try:
        os.symlink(target, stored.path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")
    with pytest.raises(storage.AttemptSelectionStorageIntegrityError, match="symlink"):
        storage.load_attempt_selection_policy_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, WORK, policy().policy_id, 1
        )


def test_exact_decision_retry_does_not_revalidate_stale_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    stored_policy = prepared_policy(monkeypatch, workspace)
    value = decision(policy_reference(stored_policy))
    monkeypatch.setattr(
        storage,
        "_validate_decision_dependencies",
        lambda *args, **kwargs: derivation(),
    )
    first = storage.write_attempt_selection_decision_revision(
        workspace, value, authorized_snapshot=object()  # type: ignore[arg-type]
    )

    def stale(*args: object, **kwargs: object) -> storage.AttemptCandidateDerivation:
        raise storage.AttemptSelectionStorageConflictError("policy is now stale")

    monkeypatch.setattr(storage, "_validate_decision_dependencies", stale)
    retry = storage.write_attempt_selection_decision_revision(
        workspace, value, authorized_snapshot=object()  # type: ignore[arg-type]
    )
    assert first.disposition == "created"
    assert retry.disposition == "existing"
    assert retry.stored.content == first.stored.content


def test_attempt_selection_collection_rejects_unexpected_policy_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    policies = storage.attempt_selection_policies_directory(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK
    )
    policies.mkdir(parents=True)
    (policies / "unexpected.txt").write_bytes(b"bad\n")
    with pytest.raises(
        storage.AttemptSelectionStorageIntegrityError, match="policy collection"
    ):
        storage.write_attempt_selection_policy_revision(workspace, policy())


def test_attempt_selection_collection_rejects_invalid_subject_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_policy_root(monkeypatch)
    workspace = root(tmp_path)
    students = storage.attempt_selection_students_directory(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK
    )
    (students / "student_1").mkdir(parents=True)
    with pytest.raises(
        storage.AttemptSelectionStorageIntegrityError, match="subject key"
    ):
        storage.write_attempt_selection_policy_revision(workspace, policy())


def fake_membership() -> SimpleNamespace:
    return SimpleNamespace(
        decision=SimpleNamespace(
            decision="included",
            membership_revision=1,
        ),
        decision_sha256=MEMBERSHIP_DIGEST,
    )


def test_resolution_distinguishes_policy_eligibility_and_candidate_staleness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    stored_policy = SimpleNamespace(
        policy=policy(),
        policy_sha256="5" * 64,
    )
    value = decision(
        AttemptSelectionPolicyReference(
            policy_id=policy().policy_id,
            policy_revision=1,
            policy_revision_sha256="5" * 64,
        )
    )
    selected = SimpleNamespace(decision=value, decision_sha256="8" * 64)
    monkeypatch.setattr(
        storage, "load_current_attempt_selection_decision", lambda *args: selected
    )
    monkeypatch.setattr(
        storage,
        "load_current_grade_item_membership_decision",
        lambda *args: fake_membership(),
    )
    monkeypatch.setattr(
        storage, "load_current_attempt_selection_policy", lambda *args: stored_policy
    )
    monkeypatch.setattr(
        storage, "derive_attempt_candidates", lambda *args, **kwargs: derivation()
    )
    result = storage.resolve_current_attempt_selection(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert result.status == "selected"
    assert result.operative_selection is True

    changed_basis = replace(
        candidates()[0],
        eligible_evidence=(replace(basis(1), eligibility_revision=2),),
    )
    monkeypatch.setattr(
        storage,
        "derive_attempt_candidates",
        lambda *args, **kwargs: derivation((changed_basis, candidates()[1])),
    )
    assert storage.resolve_current_attempt_selection(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        authorized_snapshot=object(),  # type: ignore[arg-type]
    ).status == "eligibility_stale"

    monkeypatch.setattr(
        storage,
        "derive_attempt_candidates",
        lambda *args, **kwargs: derivation((candidates()[0],)),
    )
    assert storage.resolve_current_attempt_selection(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "student_1",
        authorized_snapshot=object(),  # type: ignore[arg-type]
    ).status == "candidate_set_stale"
