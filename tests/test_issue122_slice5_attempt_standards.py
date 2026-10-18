"""#122 Slice 5: synthetic canonical adapter and menu contract regression tests.

No district workspace or student evidence is opened. Each canonical dependency
is replaced by an explicit synthetic observation, retaining the actual adapter.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import meridian.teacher_action_attempt_standards as adapters
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_orchestration import TeacherActionConflictError

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


def ns(**values: object) -> SimpleNamespace:
    return SimpleNamespace(**values)


def _common(monkeypatch: pytest.MonkeyPatch) -> tuple[SimpleNamespace, object]:
    work = ns(class_id="class_a", module_id="scoreform", work_id="assessment")
    assignment = ns(
        period=ns(school_year="2026-2027", period_id="mp1"), calendar_revision=1
    )
    member = ns(
        decision=ns(
            decision="included", membership_revision=2, academic_period=assignment
        ),
        decision_sha256=A,
    )
    monkeypatch.setattr(
        adapters, "load_current_grade_item_membership_decision", lambda *_: member
    )
    monkeypatch.setattr(
        adapters, "validate_grade_item_membership_dependencies", lambda *_: None
    )
    monkeypatch.setattr(adapters, "_calendar_digest", lambda *_: D)
    monkeypatch.setattr(adapters, "_actor_now", lambda *_: None)
    # Return the actual guarded domain port, with no journal initialization.
    monkeypatch.setattr(adapters, "_prepare", lambda **values: values["port"])
    return work, member


def test_attempt_exact_write_select_and_live_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work, _ = _common(monkeypatch)
    source = ns(publication_id="pub_" + "a" * 32, cache_key=B, snapshot_digest=C)
    candidate = ns(
        class_id="class_a",
        grade_item_id="gi",
        work=work,
        student_id="student_1",
        actor=ns(kind="teacher", actor_id="actor"),
        membership_revision=2,
        membership_revision_sha256=A,
        decision_revision=2,
        policy=ns(policy_id="policy", policy_revision_sha256=B),
        source_snapshot=source,
        candidates=("one",),
        selected_attempts=("one",),
    )
    authoring = ns(
        candidate=candidate, history=(1,), reviewed_current_decision_revision=1
    )
    # The immutable candidate digest is derived from canonical serialization.
    monkeypatch.setattr(
        adapters, "attempt_selection_decision_to_json_bytes", lambda _: b"candidate"
    )
    expected_digest = adapters._hash(b"candidate")
    memory: dict[str, object] = {"written": False, "revision": 1, "policy": B}
    calls: list[str] = []
    old = ns(decision=ns(decision_revision=1), decision_sha256=D)

    def read_current(*_: object) -> object:
        if memory["revision"] == 2:
            return ns(decision=ns(decision_revision=2), decision_sha256=expected_digest)
        return old

    monkeypatch.setattr(
        adapters, "load_current_attempt_selection_decision", read_current
    )
    monkeypatch.setattr(
        adapters,
        "list_attempt_selection_decision_revisions",
        lambda *_: (1, 2) if memory["written"] else (1,),
    )
    monkeypatch.setattr(
        adapters,
        "load_attempt_selection_decision_revision",
        lambda *_: ns(decision_sha256=expected_digest),
    )
    monkeypatch.setattr(
        adapters,
        "load_current_attempt_selection_policy",
        lambda *_: ns(policy_sha256=memory["policy"]),
    )
    monkeypatch.setattr(
        adapters,
        "derive_attempt_candidates",
        lambda *_: ns(status="applicable", source_snapshot=source, candidates=("one",)),
    )

    def write(*_: object, **__: object) -> SimpleNamespace:
        calls.append("write")
        memory["written"] = True
        return ns(write_disposition="created")

    def select(*_: object, **__: object) -> SimpleNamespace:
        calls.append("select")
        memory["revision"] = 2
        return ns(
            selected_decision_sha256=expected_digest, selection_disposition="updated"
        )

    monkeypatch.setattr(adapters, "commit_guided_attempt_decision", write)
    monkeypatch.setattr(
        adapters,
        "preview_guided_attempt_selection",
        lambda *_a, **_k: ns(
            target_sha256=expected_digest,
            expected_current_decision_revision=1,
        ),
    )
    monkeypatch.setattr(adapters, "commit_guided_attempt_selection", select)
    port = adapters.prepare_attempt_decision_action(
        tmp_path,
        cast(object, ns(authorized=object())),
        cast(object, authoring),
        TeacherActionActor("actor", A, "saved"),
        cast(object, ns()),
    )
    port._revalidate()
    assert port._read()[0] is None
    assert port._write() == "created"
    assert port._read()[0] == expected_digest
    assert port._select() == "updated"
    assert port._read()[1:3] == (2, expected_digest)
    assert calls == ["write", "select"]
    memory["policy"] = C
    with pytest.raises(TeacherActionConflictError, match="policy"):
        port._revalidate()


def test_standard_exact_write_select_and_stale_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work, _ = _common(monkeypatch)
    source = ns(
        work=work,
        publication_id="pub_" + "b" * 32,
        item_id="item",
        cache_key=B,
        snapshot_digest=C,
    )
    decision = ns(
        class_id="class_a",
        grade_item_id="gi",
        source=source,
        standard_id="njsls-ela:RL.TS.11-12.4",
        association_revision=2,
        actor=ns(kind="teacher", actor_id="actor"),
    )
    authoring = ns(
        candidate=decision,
        history=(1,),
        expected_current_association_revision=1,
        grade_item_revision=2,
        grade_item_revision_sha256=B,
        membership_revision=2,
        membership_revision_sha256=A,
        standard_resolved=True,
        standard_active=True,
        projection=ns(),
    )
    monkeypatch.setattr(
        adapters, "standard_evidence_association_to_json_bytes", lambda _: b"standard"
    )
    digest = adapters._hash(b"standard")
    current: dict[str, object] = {"written": False, "revision": 1, "active": True}
    monkeypatch.setattr(
        adapters,
        "load_current_standard_evidence_association_decision",
        lambda *_: ns(
            decision=ns(association_revision=current["revision"]),
            decision_sha256=digest if current["revision"] == 2 else D,
        ),
    )
    monkeypatch.setattr(
        adapters,
        "list_standard_evidence_association_revisions",
        lambda *_: (1, 2) if current["written"] else (1,),
    )
    monkeypatch.setattr(
        adapters,
        "load_standard_evidence_association_revision",
        lambda *_: ns(decision_sha256=digest),
    )
    monkeypatch.setattr(
        adapters,
        "validate_standard_evidence_association_dependencies",
        lambda *_: ns(
            grade_item=ns(revision=ns(grade_item_revision=2), revision_sha256=B),
            membership=ns(decision_sha256=A),
            standard_resolution=ns(resolved=True, active=current["active"]),
        ),
    )

    def write(*_: object, **__: object) -> SimpleNamespace:
        current["written"] = True
        return ns(write_result=ns(disposition="created"))

    def select(*_: object, **__: object) -> SimpleNamespace:
        current["revision"] = 2
        return ns(selected_decision_sha256=digest, selection_disposition="updated")

    monkeypatch.setattr(adapters, "commit_guided_standard_association", write)
    monkeypatch.setattr(
        adapters,
        "preview_guided_standard_selection",
        lambda *_a, **_k: ns(
            target_sha256=digest,
            expected_current_association_revision=1,
        ),
    )
    monkeypatch.setattr(adapters, "commit_guided_standard_selection", select)
    port = adapters.prepare_standard_association_action(
        tmp_path,
        cast(object, ns(authorized=object())),
        cast(object, authoring),
        TeacherActionActor("actor", A, "saved"),
        cast(object, ns()),
    )
    port._revalidate()
    assert port._write() == "created"
    assert port._select() == "updated"
    assert port._read()[1:3] == (2, digest)
    current["active"] = False
    with pytest.raises(TeacherActionConflictError, match="Standard"):
        port._revalidate()


def test_menu_sources_have_single_ordinary_review() -> None:
    root = Path(__file__).resolve().parents[1] / "meridian"
    for name, old_header in (
        ("menu_teacher_attempts.py", "Make Attempt Decision Current"),
        ("menu_teacher_standards.py", "Make Standard Association Current"),
    ):
        content = (root / name).read_text(encoding="utf-8")
        assert old_header not in content
        assert content.count("    if not _review_apply(") == 1
        assert content.count('"1. Save and make current"') == 1
