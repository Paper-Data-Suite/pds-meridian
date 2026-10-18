"""#122 Slice 6: synthetic exact-current proficiency action and menu regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import meridian.teacher_action_proficiency as adapters
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_orchestration import TeacherActionConflictError

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


def ns(**values: object) -> SimpleNamespace:
    return SimpleNamespace(**values)


def fixture_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[object, dict[str, object]]:
    work = ns(class_id="class_a", module_id="scoreform", work_id="quiz")
    source = ns(
        work=work,
        publication_id="pub_" + "a" * 32,
        item_id="source_1",
        cache_key=A,
        snapshot_digest=B,
    )
    academic = ns(
        period=ns(school_year="2026-2027", period_id="mp1"), calendar_revision=1
    )
    member = ns(
        decision=ns(decision="included", academic_period=academic),
        decision_sha256=C,
    )
    policy_ref = ns(policy_id="policy_one", policy_sha256=A)
    scale_ref = ns(scale_id="scale_one", scale_sha256=B)
    basis = ns(grade_item_revision_sha256=D)
    reviewed = ns(
        class_id="class_a",
        grade_item_id="grade_one",
        student_id="student_one",
        standard_id="std:english",
        inputs=ns(target_scale=scale_ref),
        bindings=(ns(source=source),),
        grade_item_basis=basis,
        source_keys=("source",),
        calculation=ns(
            outcome=ns(status="calculated"),
            policy_reference=policy_ref,
        ),
    )
    candidate = ns(
        class_id="class_a",
        grade_item_id="grade_one",
        student_id="student_one",
        standard_id="std:english",
        result_revision=1,
        inputs=reviewed.inputs,
        outcome=reviewed.calculation.outcome,
        inputs_sha256=A,
        calculation_fingerprint=B,
        policy_reference=policy_ref,
        target_scale=scale_ref,
    )
    authoring = ns(
        candidate=candidate,
        reviewed=reviewed,
        actor_id="teacher_one",
        history_before=(),
        selected_revision_before=None,
        latest_result_sha256_before=None,
    )
    memory: dict[str, object] = {
        "written": False,
        "current": False,
        "policy": policy_ref,
        "scale": scale_ref,
        "member": member,
        "fresh": reviewed,
    }
    digest = adapters.hashlib.sha256(b"exact-result").hexdigest()
    monkeypatch.setattr(
        adapters,
        "standard_proficiency_result_snapshot_to_json_bytes",
        lambda _: b"exact-result",
    )
    monkeypatch.setattr(adapters, "_actor_now", lambda _: None)
    monkeypatch.setattr(adapters, "_calendar_digest", lambda *_: D)
    monkeypatch.setattr(adapters, "_prepare", lambda **values: values["port"])
    monkeypatch.setattr(
        adapters, "validate_grade_item_membership_dependencies", lambda *_: None
    )
    monkeypatch.setattr(
        adapters,
        "load_current_grade_item_membership_decision",
        lambda *_: memory["member"],
    )
    monkeypatch.setattr(
        adapters, "load_current_grade_item_revision", lambda *_: ns(revision_sha256=D)
    )
    monkeypatch.setattr(
        adapters,
        "load_current_standard_proficiency_policy",
        lambda *_: ns(reference=memory["policy"]),
    )
    monkeypatch.setattr(
        adapters,
        "load_current_proficiency_scale",
        lambda *_: ns(reference=memory["scale"]),
    )
    monkeypatch.setattr(
        adapters, "build_bounded_calculation_preview", lambda *_: memory["fresh"]
    )
    monkeypatch.setattr(
        adapters,
        "list_standard_proficiency_result_revisions",
        lambda *_: (1,) if memory["written"] else (),
    )
    monkeypatch.setattr(
        adapters,
        "load_standard_proficiency_result_revision",
        lambda *_: ns(result_sha256=digest),
    )
    monkeypatch.setattr(
        adapters,
        "load_current_standard_proficiency_result",
        lambda *_: (
            ns(snapshot=candidate, result_sha256=digest) if memory["current"] else None
        ),
    )

    def write(*_args: object, **_kw: object) -> SimpleNamespace:
        memory["written"] = True
        return ns(written_result_sha256=digest, write_result=ns(disposition="created"))

    def select(*_args: object, **_kw: object) -> SimpleNamespace:
        memory["current"] = True
        return ns(selected_result_sha256=digest, selection_disposition="created")

    monkeypatch.setattr(adapters, "commit_guided_proficiency_result", write)
    monkeypatch.setattr(
        adapters,
        "preview_guided_proficiency_selection",
        lambda *_a, **_k: ns(
            target_result_sha256=digest,
            expected_current_result_revision=None,
        ),
    )
    monkeypatch.setattr(adapters, "commit_guided_proficiency_selection", select)
    port = adapters.prepare_proficiency_result_action(
        tmp_path,
        cast(object, authoring),
        TeacherActionActor("teacher_one", A, "saved"),
        cast(object, ns()),
    )
    return port, memory


def test_proficiency_exact_write_select_verify(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    port, memory = fixture_port(monkeypatch, tmp_path)
    port._revalidate()
    assert port._read()[0] is None
    assert port._write() == "created"
    assert port._read()[0] == adapters.hashlib.sha256(b"exact-result").hexdigest()
    assert port._select() == "created"
    assert port._read()[1] == 1
    assert memory["current"] is True


def test_proficiency_live_policy_change_blocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    port, memory = fixture_port(monkeypatch, tmp_path)
    memory["policy"] = ns(policy_id="changed")
    with pytest.raises(TeacherActionConflictError, match="policy"):
        port._revalidate()


def test_proficiency_changed_calculation_blocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    port, memory = fixture_port(monkeypatch, tmp_path)
    memory["fresh"] = ns(
        grade_item_basis=ns(grade_item_revision_sha256=D),
        source_keys=("source",),
        inputs=ns(target_scale=ns()),
        calculation=ns(
            policy_reference=ns(policy_id="policy_one"), outcome=ns(status="calculated")
        ),
    )
    with pytest.raises(TeacherActionConflictError, match="calculation"):
        port._revalidate()


def test_proficiency_wrong_cas_digest_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    port, _ = fixture_port(monkeypatch, tmp_path)
    monkeypatch.setattr(
        adapters,
        "preview_guided_proficiency_selection",
        lambda *_a, **_k: ns(
            target_result_sha256="0" * 64,
            expected_current_result_revision=None,
        ),
    )
    with pytest.raises(TeacherActionConflictError, match="selection baseline"):
        port._select()


def test_proficiency_menu_single_save_contract() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "meridian" / "menu_teacher_proficiency.py"
    ).read_text(encoding="utf-8")
    assert "Make Proficiency Result Current" not in source
    assert '"1. Save and make current"' in source
    assert source.count("    if not _review_apply(") == 1
    assert "Current canonical proficiency state was reloaded" in source
    assert "Teacher name for attribution:" in source
