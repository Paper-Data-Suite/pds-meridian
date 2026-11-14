"""#125-H3D6: independent-process canonical lock and integrity adversity.

Only synthetic workspace files are touched. The lock holder is a separate Python
process; these tests do not simulate a lock by monkeypatching the storage API.
An interrupted apply may create a receipt even when current selection is absent.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest
from test_evidence_eligibility_storage import (
    CLASS_ID,
    GRADE_ITEM_ID,
    allow_dependencies,
    decision,
    root,
    source,
)

import meridian.evidence_eligibility_storage as storage

_NATIVE = os.environ.get("PDS_ISSUE125_H3D6_NATIVE_TEST") == "1"

# A different interpreter process owns the real O_EXCL file until a second
# independently visible file releases it. Both files live in synthetic temp.
_HOLDER = r"""
import os, pathlib, sys, time
lock, ready, release = (pathlib.Path(x) for x in sys.argv[1:])
with lock.open('xb') as f:
    f.write(b'foreign-process-owner\n')
    f.flush()
    os.fsync(f.fileno())
ready.write_text('ready', encoding='ascii')
deadline = time.monotonic() + 25
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.025)
if not release.exists():
    raise RuntimeError('Host did not release lock within deadline')
lock.unlink()
"""


@contextmanager
def foreign_lock(lock: Path, signals: Path) -> Iterator[None]:
    """Hold a real cross-process exclusive lock, with bounded teardown."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    signals.mkdir(parents=True, exist_ok=True)
    ready, release = signals / "ready", signals / "release"
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", _HOLDER, str(lock), str(ready), str(release)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.is_file():
            if child.poll() is not None:
                output, errors = child.communicate(timeout=2)
                pytest.fail(
                    f"Foreign lock owner exited {child.returncode}: "
                    f"{(output + errors)[-800:]}"
                )
            if time.monotonic() >= deadline:
                pytest.fail("Foreign lock owner did not establish lock")
            time.sleep(0.025)
        assert child.poll() is None and lock.is_file()
        yield
    finally:
        release.write_text("release", encoding="ascii")
        try:
            output, errors = child.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate(timeout=5)
            pytest.fail("Foreign lock holder failed bounded teardown")
        assert child.returncode == 0, (output, errors)
        assert not lock.exists(), "Foreign writer left a canonical lock"


def test_independent_process_blocks_immutable_revision_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    initial = storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()
    ).stored
    relation = storage.evidence_eligibility_source_directory(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    )
    with foreign_lock(relation / ".write.lock", tmp_path / "signals"):
        with pytest.raises(storage.EvidenceEligibilityStorageLockError):
            storage.write_evidence_eligibility_revision(
                workspace,
                decision(revision=2, disposition="excluded"),
                authorized_snapshot=object(),
            )
        assert storage.list_evidence_eligibility_revisions(
            workspace, CLASS_ID, GRADE_ITEM_ID, source()
        ) == (1,)
        assert initial.path.read_bytes() == initial.content
    updated = storage.write_evidence_eligibility_revision(
        workspace,
        decision(revision=2, disposition="excluded"),
        authorized_snapshot=object(),
    )
    assert updated.disposition == "created"
    assert (
        storage.get_current_evidence_eligibility_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, source()
        )
        is None
    )


def test_independent_process_blocks_current_selector_without_pointer_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    initial = storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()
    ).stored
    relation = initial.path.parent
    with foreign_lock(relation / ".write.lock", tmp_path / "signals"):
        with pytest.raises(storage.EvidenceEligibilityStorageLockError):
            storage.select_evidence_eligibility_revision(
                workspace,
                CLASS_ID,
                GRADE_ITEM_ID,
                source(),
                1,
                authorized_snapshot=object(),
                expected_current_eligibility_revision=None,
            )
        assert not (relation / "current.json").exists()
    selected = storage.select_evidence_eligibility_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        source(),
        1,
        authorized_snapshot=object(),
        expected_current_eligibility_revision=None,
    )
    assert selected.disposition == "created"
    assert (
        storage.get_current_evidence_eligibility_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, source()
        )
        == 1
    )


def test_corrupt_selected_pointer_fails_closed_and_is_not_healed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    initial = storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()
    ).stored
    storage.select_evidence_eligibility_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        source(),
        1,
        authorized_snapshot=object(),
        expected_current_eligibility_revision=None,
    )
    pointer = initial.path.parent / "current.json"
    corrupt = b'{"incomplete":'
    pointer.write_bytes(corrupt)
    with pytest.raises(storage.EvidenceEligibilityStorageError):
        storage.get_current_evidence_eligibility_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, source()
        )
    with pytest.raises(storage.EvidenceEligibilityStorageError):
        storage.select_evidence_eligibility_revision(
            workspace,
            CLASS_ID,
            GRADE_ITEM_ID,
            source(),
            1,
            authorized_snapshot=object(),
            expected_current_eligibility_revision=1,
        )
    assert pointer.read_bytes() == corrupt
    assert initial.path.read_bytes() == initial.content


def test_corrupt_revision_digest_prevents_current_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    initial = storage.write_evidence_eligibility_revision(
        workspace, decision(), authorized_snapshot=object()
    ).stored
    digest_path = initial.path.with_name(initial.path.name + ".sha256")
    assert digest_path.is_file()
    digest_path.write_text("0" * 64 + "\n", encoding="ascii")
    before = digest_path.read_bytes()
    with pytest.raises(storage.EvidenceEligibilityStorageError):
        storage.select_evidence_eligibility_revision(
            workspace,
            CLASS_ID,
            GRADE_ITEM_ID,
            source(),
            1,
            authorized_snapshot=object(),
            expected_current_eligibility_revision=None,
        )
    assert digest_path.read_bytes() == before
    assert not (initial.path.parent / "current.json").exists()
    assert hashlib.sha256(initial.path.read_bytes()).hexdigest() == (
        initial.decision_sha256
    )


@pytest.mark.skipif(not _NATIVE, reason="Requires isolated official producer wheels")
@pytest.mark.parametrize("target", (0, 1, 2))
def test_native_batch_stops_at_foreign_canonical_lock_without_later_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: int
) -> None:
    from test_issue124_slicee2g3k_composite_canonical import CLASS, _all_bytes
    from test_issue125_h3b2_native_write_isolation import _eligible_rows
    from test_issue125_sliceg2a_canonical_batch_acceptance import (
        _build_plan,
        _ready_native,
    )

    from meridian.assessment_eligibility_progress import (
        execute_batch_with_sealed_progress,
    )
    from meridian.teacher_action_receipts import TeacherActionReceiptStore

    workspace, grade_id, prepared, review, deps, grade_item, _, actor = _ready_native(
        tmp_path, monkeypatch, "scoreform"
    )
    candidates = _eligible_rows(review, "scoreform")[:3]
    selected = tuple(row.source.item_id for row in candidates)
    plan = _build_plan(workspace, prepared, review, deps, actor, selected)
    assert plan.action_count == 3
    current_before = _all_bytes(workspace)
    receipts = TeacherActionReceiptStore(workspace, CLASS)
    receipt_before = {x.action_id for x in receipts.list_receipts()}
    relation = storage.evidence_eligibility_source_directory(
        workspace, CLASS, grade_id, plan.items[target].source
    )
    with foreign_lock(relation / ".write.lock", tmp_path / "foreign-signals"):
        outcome = execute_batch_with_sealed_progress(
            workspace,
            plan,
            confirmed=True,
            prepared=prepared,
            grade_item=grade_item,
            dependencies=deps,
        )
    statuses = tuple(item.status for item in outcome.items)
    assert outcome.stopped and len(statuses) == 3
    assert outcome.verified_current_count == target, (target, statuses)
    assert statuses[:target] == ("applied",) * target
    assert statuses[target] not in {"applied", "already_applied"}, statuses
    assert statuses[target + 1 :] == ("not_attempted",) * (2 - target)
    for index, row in enumerate(candidates):
        current = storage.load_current_evidence_eligibility_decision(
            workspace, CLASS, grade_id, row.source
        )
        if index < target:
            assert current is not None and current.decision.disposition == "included"
        else:
            assert current is None
    receipt_after = {x.action_id for x in receipts.list_receipts()}
    assert target <= len(receipt_after - receipt_before) <= target + 1
    current_after = _all_bytes(workspace)
    changed = {
        key
        for key in set(current_before) | set(current_after)
        if current_before.get(key) != current_after.get(key)
    }
    prefix = f"classes/{CLASS}/modules/meridian/"
    allowed = (
        prefix + "elig/",
        prefix + "teacher_action_receipts/",
        prefix + "assessment_eligibility_progress/",
    )
    assert all(name.startswith(allowed) for name in changed), sorted(changed)[:8]
    print(
        f"H3D6_NATIVE_LOCK target={target + 1}/3 statuses={statuses} "
        f"selected_current={target} collateral=0",
        flush=True,
    )
