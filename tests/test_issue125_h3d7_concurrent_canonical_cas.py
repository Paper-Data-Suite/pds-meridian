"""#125-H3D7: true two-process canonical eligibility CAS and immutable-write races.

All workspaces, writers, actors and evidence are synthetic. Independent Python
interpreters cross a shared release barrier and invoke REAL Meridian storage
methods. Only the external authorization/dependency port is stubbed; storage
locks, CAS, file persistence, digest checks and history remain production code.
This is storage-level concurrency, not a claim of batch-level atomicity.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from test_evidence_eligibility_storage import (
    CLASS_ID,
    GRADE_ITEM_ID,
    allow_dependencies,
    decision,
    root,
    source,
)

import meridian
import meridian.evidence_eligibility_storage as storage

_WORKER = r"""
import json
import pathlib
import sys
import time
from dataclasses import replace
from test_evidence_eligibility_storage import CLASS_ID, GRADE_ITEM_ID, decision, source
import meridian.evidence_eligibility_storage as storage

# Source and actor were established by the synthetic parent. This test probes
# the true canonical write/selection CAS, never actual publication authority.
storage.validate_evidence_eligibility_dependencies = lambda *a, **kw: object()
workspace = pathlib.Path(sys.argv[1])
signals = pathlib.Path(sys.argv[2])
mode, tag, revision, expected, item_id = sys.argv[3:8]
revision = int(revision)
ref = replace(source(), item_id=item_id)
(signals / (tag + '.ready')).write_text('ready', encoding='ascii')
deadline = time.monotonic() + 25
while not (signals / 'START').exists():
    if time.monotonic() >= deadline:
        raise RuntimeError('Concurrent-writer release barrier timed out')
    time.sleep(0.01)
result = {'tag': tag, 'mode': mode, 'revision': revision, 'status': None}
try:
    if mode == 'select':
        changed = storage.select_evidence_eligibility_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, ref, revision,
            authorized_snapshot=object(),
            expected_current_eligibility_revision=(
                None if expected == 'none' else int(expected)
            ),
        )
        result['status'] = changed.disposition
    elif mode == 'write':
        candidate = replace(
            decision(revision=revision, disposition='excluded'),
            source=ref, rationale='synthetic-independent-writer-' + tag,
        )
        changed = storage.write_evidence_eligibility_revision(
            workspace, candidate, authorized_snapshot=object()
        )
        result['status'] = changed.disposition
    else:
        raise RuntimeError('Unexpected synthetic worker mode')
except storage.EvidenceEligibilityStorageConflictError as error:
    result['status'] = 'conflict'
    result['error_type'] = type(error).__name__
except storage.EvidenceEligibilityStorageError as error:
    result['status'] = 'storage_error'
    result['error_type'] = type(error).__name__
(signals / (tag + '.json')).write_text(
    json.dumps(result, sort_keys=True), encoding='ascii'
)
"""


def _race(
    tmp_path: Path,
    workspace: Path,
    actions: tuple[tuple[str, str, int, str, str], ...],
) -> tuple[dict[str, object], ...]:
    """Release independent interpreters together; enforce bounded teardown."""
    signals = tmp_path / "race-signals"
    signals.mkdir()
    procs: list[subprocess.Popen[str]] = []
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    env.pop("PYTHONPATH", None)
    repo_root = Path(__file__).resolve().parents[1]
    module_origin = Path(meridian.__file__).resolve()
    if module_origin.is_relative_to(repo_root):
        # The ordinary source gate has no installed Meridian wheel; make the
        # source package available to child interpreters from a temporary cwd.
        env["PYTHONPATH"] = str(repo_root)
    tests_dir = str(Path(__file__).resolve().parent)
    try:
        for tag, mode, revision, expected, item_id in actions:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    "import sys; sys.path.insert(0, sys.argv.pop(1)); " + _WORKER,
                    tests_dir,
                    str(workspace),
                    str(signals),
                    mode,
                    tag,
                    str(revision),
                    expected,
                    item_id,
                ],
                cwd=str(tmp_path),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            procs.append(child)
        deadline = time.monotonic() + 20
        while not all((signals / (tag + ".ready")).is_file() for tag, *_ in actions):
            for process in procs:
                if process.poll() is not None:
                    out, err = process.communicate(timeout=2)
                    pytest.fail("Writer exited before release: " + (out + err)[-1000:])
            if time.monotonic() > deadline:
                pytest.fail("Both independent writers did not reach the barrier")
            time.sleep(0.025)
        assert all(process.poll() is None for process in procs)
        (signals / "START").write_text("go", encoding="ascii")
        results = []
        for (tag, *_), child in zip(actions, procs, strict=True):
            out, err = child.communicate(timeout=30)
            assert child.returncode == 0, (tag, out[-1000:], err[-1000:])
            data = json.loads((signals / (tag + ".json")).read_text(encoding="ascii"))
            assert data["tag"] == tag and data["status"] is not None
            results.append(data)
        return tuple(results)
    finally:
        for child in procs:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)


def _files(relation: Path) -> dict[str, bytes]:
    return {
        entry.name: entry.read_bytes()
        for entry in relation.iterdir()
        if entry.is_file()
    }


def _seed(
    workspace: Path, *revisions: int, selected: int | None = None
) -> tuple[Path, dict[str, bytes]]:
    for revision in revisions:
        disposition = {1: "included", 2: "excluded", 3: "pending"}[revision]
        storage.write_evidence_eligibility_revision(
            workspace,
            decision(revision=revision, disposition=disposition),
            authorized_snapshot=object(),
        )
    if selected is not None:
        storage.select_evidence_eligibility_revision(
            workspace,
            CLASS_ID,
            GRADE_ITEM_ID,
            source(),
            selected,
            authorized_snapshot=object(),
            expected_current_eligibility_revision=None,
        )
    relation = storage.evidence_eligibility_source_directory(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    )
    return relation, _files(relation)


def _assert_single_winner(
    outcomes: tuple[dict[str, object], ...], success: str
) -> dict[str, object]:
    winners = [x for x in outcomes if x["status"] == success]
    losers = [x for x in outcomes if x["status"] == "conflict"]
    assert len(winners) == len(losers) == 1, outcomes
    assert losers[0]["error_type"] in {
        "EvidenceEligibilityStorageLockError",
        "EvidenceEligibilityStorageConflictError",
    }
    return winners[0]


def test_two_processes_race_initial_exact_current_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    relation, before = _seed(workspace, 1, 2)
    outcomes = _race(
        tmp_path,
        workspace,
        (
            ("A", "select", 1, "none", source().item_id),
            ("B", "select", 2, "none", source().item_id),
        ),
    )
    winner = _assert_single_winner(outcomes, "created")
    current = storage.load_current_evidence_eligibility_decision(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    )
    assert current is not None
    assert current.decision.eligibility_revision == winner["revision"]
    assert storage.list_evidence_eligibility_revisions(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    ) == (1, 2)
    after = _files(relation)
    assert set(after) == {*before, "current.json"}
    assert all(after[key] == value for key, value in before.items())
    assert ".write.lock" not in after


def test_two_processes_race_stale_expected_pointer_with_unrelated_source_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    relation, before = _seed(workspace, 1, 2, 3, selected=1)
    unrelated = replace(source(), item_id="synthetic_unrelated_item")
    storage.write_evidence_eligibility_revision(
        workspace, replace(decision(), source=unrelated), authorized_snapshot=object()
    )
    storage.select_evidence_eligibility_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        unrelated,
        1,
        authorized_snapshot=object(),
        expected_current_eligibility_revision=None,
    )
    unrelated_relation = storage.evidence_eligibility_source_directory(
        workspace, CLASS_ID, GRADE_ITEM_ID, unrelated
    )
    unrelated_before = _files(unrelated_relation)
    outcomes = _race(
        tmp_path,
        workspace,
        (
            ("A", "select", 2, "1", source().item_id),
            ("B", "select", 3, "1", source().item_id),
        ),
    )
    winner = _assert_single_winner(outcomes, "updated")
    current = storage.load_current_evidence_eligibility_decision(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    )
    assert current is not None
    assert current.decision.eligibility_revision == winner["revision"]
    assert storage.list_evidence_eligibility_revisions(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    ) == (1, 2, 3)
    after = _files(relation)
    assert set(after) == set(before)
    assert all(
        after[key] == value for key, value in before.items() if key != "current.json"
    )
    assert after["current.json"] != before["current.json"]
    assert ".write.lock" not in after
    assert _files(unrelated_relation) == unrelated_before


def test_two_processes_race_different_immutable_revision_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    relation, before = _seed(workspace, 1)
    outcomes = _race(
        tmp_path,
        workspace,
        (
            ("A", "write", 2, "none", source().item_id),
            ("B", "write", 2, "none", source().item_id),
        ),
    )
    winner = _assert_single_winner(outcomes, "created")
    history = storage.load_evidence_eligibility_revision(
        workspace, CLASS_ID, GRADE_ITEM_ID, source(), 2
    )
    assert history.decision.rationale == (
        "synthetic-independent-writer-" + str(winner["tag"])
    )
    assert storage.list_evidence_eligibility_revisions(
        workspace, CLASS_ID, GRADE_ITEM_ID, source()
    ) == (1, 2)
    assert (
        storage.get_current_evidence_eligibility_revision(
            workspace, CLASS_ID, GRADE_ITEM_ID, source()
        )
        is None
    )
    after = _files(relation)
    assert set(after) == {*before, "2.json", "2.json.sha256"}
    assert all(after[key] == value for key, value in before.items())
    assert ".write.lock" not in after


def test_two_processes_select_distinct_sources_without_global_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_dependencies(monkeypatch)
    workspace = root(tmp_path)
    relation, before = _seed(workspace, 1)
    unrelated = replace(source(), item_id="synthetic_other_source")
    storage.write_evidence_eligibility_revision(
        workspace, replace(decision(), source=unrelated), authorized_snapshot=object()
    )
    outcomes = _race(
        tmp_path,
        workspace,
        (
            ("A", "select", 1, "none", source().item_id),
            ("B", "select", 1, "none", unrelated.item_id),
        ),
    )
    assert sorted(x["status"] for x in outcomes) == ["created", "created"], outcomes
    for ref in (source(), unrelated):
        current = storage.load_current_evidence_eligibility_decision(
            workspace, CLASS_ID, GRADE_ITEM_ID, ref
        )
        assert current is not None and current.decision.eligibility_revision == 1
    after = _files(relation)
    assert set(after) == {*before, "current.json"}
    assert all(after[key] == value for key, value in before.items())
