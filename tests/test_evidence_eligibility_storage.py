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

import meridian.evidence_eligibility_storage as storage
from meridian.evidence_eligibility import (
    EvidenceDecisionActor,
    EvidenceEligibilityDecision,
    EvidenceEligibilityPolicyReference,
    EvidenceSourceReference,
    EvidenceSourceStateObservation,
    evidence_source_key,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
MEMBERSHIP_DIGEST = "4" * 64
NOW = datetime(2026, 8, 25, 19, tzinfo=UTC)


def source() -> EvidenceSourceReference:
    return EvidenceSourceReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        item_id="scoreform_item_1",
    )


def source_state(name: str = "current") -> EvidenceSourceStateObservation:
    if name == "current":
        return EvidenceSourceStateObservation(
            state="current",
            head_publication_id=PUBLICATION_ID,
            successor_publication_id=None,
            withdrawn_at=None,
        )
    if name == "superseded":
        successor = "pub_" + "5" * 32
        return EvidenceSourceStateObservation(
            state="superseded",
            head_publication_id=successor,
            successor_publication_id=successor,
            withdrawn_at=None,
        )
    if name == "withdrawn":
        return EvidenceSourceStateObservation(
            state="withdrawn",
            head_publication_id=PUBLICATION_ID,
            successor_publication_id=None,
            withdrawn_at=NOW,
        )
    successor = "pub_" + "5" * 32
    return EvidenceSourceStateObservation(
        state="withdrawn_superseded",
        head_publication_id=successor,
        successor_publication_id=successor,
        withdrawn_at=NOW,
    )


def decision(
    *,
    revision: int = 1,
    disposition: str = "included",
    state: EvidenceSourceStateObservation | None = None,
) -> EvidenceEligibilityDecision:
    if state is None:
        state = (
            source_state("superseded")
            if disposition == "superseded"
            else source_state("withdrawn")
            if disposition == "withdrawn"
            else source_state()
        )
    system = disposition in {"superseded", "withdrawn"}
    return EvidenceEligibilityDecision(
        schema_version="1",
        record_type="meridian_evidence_eligibility_decision",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        source=source(),
        membership_revision=1,
        membership_revision_sha256=MEMBERSHIP_DIGEST,
        eligibility_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        disposition=disposition,  # type: ignore[arg-type]
        actor=EvidenceDecisionActor(
            kind="system" if system else "teacher",
            actor_id="core_lifecycle" if system else "teacher_local",
        ),
        policy=(
            None
            if system
            else EvidenceEligibilityPolicyReference(
                policy_id="teacher_local_eligibility",
                policy_version="1",
            )
        ),
        reason_codes=(
            ()
            if disposition == "included"
            else (f"eligibility.{disposition}",)
        ),
        rationale=None,
        source_state=state,
        decided_at=NOW + timedelta(minutes=revision),
    )


def root(tmp_path: Path) -> Path:
    value = tmp_path / "workspace"
    value.mkdir()
    return value


def allow_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        storage,
        "validate_evidence_eligibility_dependencies",
        lambda *args, **kwargs: object(),
    )


def test_canonical_storage_path_uses_deterministic_source_key(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    path = storage.evidence_eligibility_revision_path(
        workspace, CLASS_ID, GRADE_ITEM_ID, source(), 1
    )
    assert path.as_posix().endswith(
        "/classes/synthetic_class_2026/modules/meridian/grade_items/"
        "unit1_assessment/memberships/scoreform/test_1/evidence_eligibility/"
        f"{evidence_source_key(source())}/revisions/1.json"
    )


def test_revision_write_is_immutable_idempotent_and_not_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    first = storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    second = storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert first.stored.content == second.stored.content
    assert storage.get_current_evidence_eligibility_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    ) is None
    assert first.stored.path.read_bytes() == first.stored.content
    assert (
        hashlib.sha256(first.stored.content).hexdigest()
        == first.stored.decision_sha256
    )


def test_same_revision_identity_with_different_content_conflicts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    changed = replace(decision(), rationale="Teacher reviewed this evidence.")
    with pytest.raises(storage.EvidenceEligibilityStorageConflictError):
        storage.write_evidence_eligibility_revision(
            workspace, changed, authorized_snapshot=object()  # type: ignore[arg-type]
        )


def test_contiguous_history_and_explicit_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    first_selection = storage.select_evidence_eligibility_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        source(),
        1,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        expected_current_eligibility_revision=None,
    )
    assert first_selection.disposition == "created"
    second_decision = decision(revision=2, disposition="excluded")
    storage.write_evidence_eligibility_revision(
        workspace,
        second_decision,
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert storage.list_evidence_eligibility_revisions(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    ) == (1, 2)
    assert storage.get_current_evidence_eligibility_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    ) == 1
    second_selection = storage.select_evidence_eligibility_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        source(),
        2,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        expected_current_eligibility_revision=1,
    )
    assert second_selection.disposition == "updated"
    assert storage.load_current_evidence_eligibility_decision(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    ).decision.disposition == "excluded"  # type: ignore[union-attr]


def test_historical_reselection_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    for value in (decision(), decision(revision=2, disposition="excluded")):
        storage.write_evidence_eligibility_revision(
            workspace, value, authorized_snapshot=object()  # type: ignore[arg-type]
        )
    storage.select_evidence_eligibility_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        source(),
        2,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        expected_current_eligibility_revision=None,
    )
    result = storage.select_evidence_eligibility_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        source(),
        1,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        expected_current_eligibility_revision=2,
    )
    assert result.selection.eligibility_revision == 1


def test_stale_compare_and_swap_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    storage.select_evidence_eligibility_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        source(),
        1,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        expected_current_eligibility_revision=None,
    )
    with pytest.raises(
        storage.EvidenceEligibilityStorageConflictError, match="Expected"
    ):
        storage.select_evidence_eligibility_revision(
            workspace,
            CLASS_ID,
            GRADE_ITEM_ID,
            source(),
            1,
            authorized_snapshot=object(),  # type: ignore[arg-type]
            expected_current_eligibility_revision=None,
        )


def test_tampered_revision_and_digest_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    stored = storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    ).stored
    stored.path.write_bytes(stored.content.replace(b'"included"', b'"excluded"'))
    with pytest.raises(
        storage.EvidenceEligibilityStorageIntegrityError, match="digest"
    ):
        storage.load_evidence_eligibility_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, source(), 1
        )

    stored.path.write_bytes(stored.content)
    digest_path = storage.evidence_eligibility_revision_digest_path(
        workspace, CLASS_ID, GRADE_ITEM_ID, source(), 1
    )
    digest_path.write_bytes(("0" * 64 + "\n").encode())
    with pytest.raises(
        storage.EvidenceEligibilityStorageIntegrityError, match="digest"
    ):
        storage.load_evidence_eligibility_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, source(), 1
        )


def test_crlf_digest_sidecar_is_noncanonical(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    stored = storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    ).stored
    digest_path = storage.evidence_eligibility_revision_digest_path(
        workspace, CLASS_ID, GRADE_ITEM_ID, source(), 1
    )
    digest_path.write_bytes((stored.decision_sha256 + "\r\n").encode())
    with pytest.raises(
        storage.EvidenceEligibilityStorageIntegrityError, match="canonical"
    ):
        storage.load_evidence_eligibility_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, source(), 1
        )


def test_pointer_digest_tamper_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    storage.select_evidence_eligibility_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        source(),
        1,
        authorized_snapshot=object(),  # type: ignore[arg-type]
        expected_current_eligibility_revision=None,
    )
    pointer = storage.evidence_eligibility_current_path(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    )
    payload = json.loads(pointer.read_text())
    payload["decision_sha256"] = "9" * 64
    pointer.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    with pytest.raises(
        storage.EvidenceEligibilityStorageIntegrityError, match="digest"
    ):
        storage.load_current_evidence_eligibility_decision(
            workspace, CLASS_ID, GRADE_ITEM_ID, source()
        )


def test_unexpected_visible_entry_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    stored = storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    ).stored
    relation = stored.path.parent.parent
    (relation / "unexpected.txt").write_text("unexpected\n")
    with pytest.raises(
        storage.EvidenceEligibilityStorageIntegrityError, match="unexpected"
    ):
        storage.list_evidence_eligibility_revisions(
            workspace, CLASS_ID, GRADE_ITEM_ID, source()
        )


def test_lock_conflict_fails_without_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    relation = storage.evidence_eligibility_source_directory(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    )
    (relation / ".write.lock").write_text("held\n")
    with pytest.raises(storage.EvidenceEligibilityStorageLockError):
        storage.write_evidence_eligibility_revision(
            workspace,
            decision(revision=2, disposition="excluded"),
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )


def test_bounded_read_rejects_oversized_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    )
    with pytest.raises(storage.EvidenceEligibilityStorageTooLargeError):
        storage.load_evidence_eligibility_revision(
            workspace,
            CLASS_ID,
            GRADE_ITEM_ID,
            source(),
            1,
            maximum_revision_bytes=16,
        )


def test_source_histories_are_listed_deterministically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    first = decision()
    storage.write_evidence_eligibility_revision(
        workspace, first, authorized_snapshot=object()  # type: ignore[arg-type]
    )
    other_source = replace(source(), item_id="scoreform_item_2")
    other = replace(first, source=other_source)
    storage.write_evidence_eligibility_revision(
        workspace, other, authorized_snapshot=object()  # type: ignore[arg-type]
    )
    listed = storage.list_evidence_eligibility_sources(
        workspace, CLASS_ID, GRADE_ITEM_ID, WORK
    )
    assert set(listed) == {source(), other_source}
    assert tuple(evidence_source_key(item) for item in listed) == tuple(
        sorted(evidence_source_key(item) for item in listed)
    )


def test_observe_source_state_distinguishes_current_superseded_and_withdrawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    import pds_core.publication_storage as publication_storage

    current_pub = SimpleNamespace(
        publication_id=PUBLICATION_ID,
        work=WORK,
        publication_kind="academic_result_set",
        record_set_id="results",
    )
    successor_id = "pub_" + "5" * 32
    successor = SimpleNamespace(publication_id=successor_id)
    monkeypatch.setattr(
        publication_storage,
        "load_publication_record",
        lambda root, publication_id: current_pub,
    )
    monkeypatch.setattr(
        publication_storage,
        "list_publication_record_set",
        lambda *args: (current_pub,),
    )
    monkeypatch.setattr(
        publication_storage,
        "load_publication_withdrawal",
        lambda *args: None,
    )
    assert storage.observe_evidence_source_state(workspace, source()).state == "current"

    monkeypatch.setattr(
        publication_storage,
        "list_publication_record_set",
        lambda *args: (current_pub, successor),
    )
    assert (
        storage.observe_evidence_source_state(workspace, source()).state
        == "superseded"
    )

    withdrawal = SimpleNamespace(withdrawn_at=NOW)
    monkeypatch.setattr(
        publication_storage,
        "load_publication_withdrawal",
        lambda *args: withdrawal,
    )
    assert (
        storage.observe_evidence_source_state(workspace, source()).state
        == "withdrawn_superseded"
    )


def test_symlinked_revision_is_rejected_when_supported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    stored = storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()  # type: ignore[arg-type]
    ).stored
    original = stored.path
    replacement = original.with_name("replacement.json")
    replacement.write_bytes(original.read_bytes())
    original.unlink()
    try:
        os.symlink(replacement, original)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")
    with pytest.raises(
        storage.EvidenceEligibilityStorageIntegrityError, match="symlink"
    ):
        storage.load_evidence_eligibility_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, source(), 1
        )
