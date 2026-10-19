"""#122 Core-only installed-wheel, separate-interpreter restart/failure acceptance.

This exercises the REAL installed action kernel and durable journal with an
intentionally synthetic canonical record port. It does not claim that fake
academic records qualify every domain adapter or any protected evidence read.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

import meridian
from meridian.teacher_action_contract import (
    ActionKind,
    SelectionDisposition,
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_orchestration import (
    TeacherActionConflictError,
    apply_reviewed_teacher_action,
    resume_exact_teacher_selection,
)
from meridian.teacher_action_receipts import (
    CanonicalActionObservation,
    TeacherActionReceiptStore,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64
CLASS = "synthetic_class"


def _require_installed() -> None:
    if not Path(meridian.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise AssertionError("#122 must import Meridian from installed wheel")


def _preview() -> TeacherActionPreview:
    return TeacherActionPreview(
        action_id="ab" * 16,
        kind="eligibility",
        scope=TeacherActionScope(A, CLASS, "synthetic_item"),
        actor=TeacherActionActor("synthetic_teacher", A, "saved"),
        target=TeacherActionTarget("eligibility", D, 1, C, None, None),
        basis=(
            TeacherActionBasis("actor_profile", A, B),
            TeacherActionBasis("canonical_source", C, D),
        ),
        reviewed_decision_sha256=C,
    )


def _load(root: Path) -> dict[str, Any]:
    decoded: object = json.loads(
        (root / "synthetic_canonical.json").read_text(encoding="utf-8")
    )
    if not isinstance(decoded, dict):
        raise AssertionError("Synthetic canonical state is not an object")
    return cast(dict[str, Any], decoded)


def _write(root: Path, state: dict[str, Any]) -> None:
    target = root / "synthetic_canonical.json"
    stage = root / ".synthetic_canonical.tmp"
    stage.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(stage, target)


class SyntheticCanonicalPort:
    """Deterministic persisted observations, never reads the receipt."""

    kind: ActionKind = "eligibility"

    def __init__(self, root: Path, *, interrupt_after_write: bool = False) -> None:
        self.root = root
        self.interrupt_after_write = interrupt_after_write

    def revalidate_basis(self, preview: TeacherActionPreview) -> None:
        assert preview == _preview()
        if _load(self.root)["basis"] != "current":
            raise TeacherActionConflictError("Source authority changed")

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation:
        self.revalidate_basis(preview)
        state = _load(self.root)
        return CanonicalActionObservation(
            target_sha256=state["target"],
            current_revision=state["current_revision"],
            current_sha256=state["current_sha256"],
            current_basis=state["basis"],
        )

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord:
        state = _load(self.root)
        if state["target"] is not None:
            raise AssertionError("Immutable authoring was repeated")
        state["target"] = preview.target.candidate_sha256
        state["writes"] += 1
        _write(self.root, state)
        if self.interrupt_after_write:
            raise OSError("Injected crash after immutable write")
        return TeacherActionRecord(
            preview.kind,
            preview.target.identity_sha256,
            preview.target.revision,
            preview.target.candidate_sha256,
            "created",
        )

    def select_exact(
        self, preview: TeacherActionPreview, record: TeacherActionRecord
    ) -> SelectionDisposition:
        assert record.matches_target(preview.target)
        state = _load(self.root)
        if state["current_revision"] != preview.target.expected_current_revision:
            raise TeacherActionConflictError("Synthetic CAS mismatch")
        if state["current_sha256"] != preview.target.expected_current_sha256:
            raise TeacherActionConflictError("Synthetic CAS digest mismatch")
        state["current_revision"] = preview.target.revision
        state["current_sha256"] = preview.target.candidate_sha256
        state["selections"] += 1
        _write(self.root, state)
        return "created"


def _seed(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / "classes" / CLASS).mkdir(parents=True)
    _write(
        root,
        dict(
            target=None,
            current_revision=None,
            current_sha256=None,
            basis="current",
            writes=0,
            selections=0,
        ),
    )


def run(mode: str, root: Path) -> None:
    _require_installed()
    preview = _preview()
    if mode == "seed":
        _seed(root)
        return
    store = TeacherActionReceiptStore(root, CLASS)
    port = SyntheticCanonicalPort(root, interrupt_after_write=mode == "interrupt")
    if mode == "cancel":
        result = apply_reviewed_teacher_action(
            preview, port, store, confirmation="CANCEL"
        )
        assert result.status == "blocked_before_write"
        assert _load(root)["writes"] == _load(root)["selections"] == 0
        assert store.load(preview.action_id) is None
    elif mode == "one_save":
        result = apply_reviewed_teacher_action(
            preview, port, store, confirmation="APPLY"
        )
        assert result.status == "applied" and result.succeeded
        assert (_load(root)["writes"], _load(root)["selections"]) == (1, 1)
    elif mode == "interrupt":
        result = apply_reviewed_teacher_action(
            preview, port, store, confirmation="APPLY"
        )
        assert result.status == "written_not_current" and not result.succeeded
        assert (_load(root)["writes"], _load(root)["selections"]) == (1, 0)
        assert store.load(preview.action_id) is not None
    elif mode == "replay_blocked":
        result = apply_reviewed_teacher_action(
            preview, port, store, confirmation="APPLY"
        )
        assert result.status == "written_not_current"
        assert (_load(root)["writes"], _load(root)["selections"]) == (1, 0)
    elif mode == "resume":
        result = resume_exact_teacher_selection(
            preview, port, store, confirmation="RESUME"
        )
        assert result.succeeded and result.status == "applied"
        assert (_load(root)["writes"], _load(root)["selections"]) == (1, 1)
    elif mode == "verify":
        result = resume_exact_teacher_selection(
            preview, port, store, confirmation="RESUME"
        )
        assert result.status == "already_applied"
        assert (_load(root)["writes"], _load(root)["selections"]) == (1, 1)
    elif mode == "supersede":
        state = _load(root)
        state["current_revision"] = 2
        state["current_sha256"] = E
        _write(root, state)
    elif mode == "reject_superseded":
        result = resume_exact_teacher_selection(
            preview, port, store, confirmation="RESUME"
        )
        assert not result.succeeded
        assert result.status in ("conflict_requires_review", "recovery_required")
        assert (_load(root)["writes"], _load(root)["selections"]) == (1, 0)
    elif mode == "corrupt_receipt":
        store.path_for(preview.action_id).write_bytes(b"not a canonical receipt\n")
    elif mode == "reject_corrupt_receipt":
        result = resume_exact_teacher_selection(
            preview, port, store, confirmation="RESUME"
        )
        assert not result.succeeded
        assert result.status == "recovery_required"
        assert (_load(root)["writes"], _load(root)["selections"]) == (1, 0)
    else:
        raise AssertionError(f"Unknown #122 acceptance phase: {mode}")
    print(f"#122 installed multi-process phase {mode}: PASS", flush=True)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: smoke_program_issue122_multi_process.py PHASE WORKSPACE"
        )
    run(sys.argv[1], Path(sys.argv[2]).resolve())


if __name__ == "__main__":
    main()
