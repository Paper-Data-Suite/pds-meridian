"""#126-I2B: real native #122 teacher Save/Use over the I1 29x6 ScoreForm class.

The only unavailable external input is #121's saved teacher profile.  An
injected synthetic actor and a checked synthetic profile-currentness function
stand in for it; the #29/#30 repositories, #122 port, receipt journal, CAS,
Core publication, ScoreForm reader, inventory and menu are production code.
No real student data, release-wheel claim or physical-scanner claim is made.
"""

from __future__ import annotations

import hashlib
from io import StringIO
from pathlib import Path
from typing import Callable

import pytest
from pds_core.routes import module_work_dir
from test_issue126_slicei1_native_scoreform_29x6 import FIRST, RETAKE, WORK, _read
from test_issue126_slicei2a_native_correction_current import (
    GRADE_ITEM,
    TEACHER,
    _setup,
)

import meridian.teacher_action_attempt_standards as action_service
from meridian.assessment_attempt_inventory import (
    project_assessment_attempt_inventory,
)
from meridian.attempt_selection_storage import (
    get_current_attempt_selection_decision_revision,
    list_attempt_selection_decision_revisions,
    load_current_attempt_selection_decision,
    resolve_current_attempt_selection,
)
from meridian.guided_attempts import GuidedAttemptDependencies
from meridian.menu_teacher_correction_decision import (
    CorrectionDecisionPorts,
    run_teacher_correction_decision_menu,
)
from meridian.menu_teacher_verified_continuation import (
    VerifiedContinuationPorts,
    run_verified_standards_continuation,
    verify_student_current_use,
)
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_session import TeacherSessionContext


class ScriptedTeacher:
    """Exact menu keystrokes; optional mutation occurs before one response."""

    def __init__(
        self,
        *answers: str,
        before_response: Callable[[int], None] | None = None,
    ) -> None:
        self.answers = iter(answers)
        self.before_response = before_response
        self.requests = 0

    def __call__(self, _prompt: str = "") -> str:
        self.requests += 1
        if self.before_response is not None:
            self.before_response(self.requests)
        try:
            return next(self.answers)
        except StopIteration as error:
            raise AssertionError("Unexpected teacher-menu prompt") from error


def _world(tmp_path: Path):
    scenario = _setup(tmp_path / "native")
    inventory = project_assessment_attempt_inventory(
        scenario.root,
        grade_item_id=GRADE_ITEM,
        prepared=scenario.prepared,
        class_label="Synthetic English 11",
        assessment_title="Six-Question Correction Check",
    )
    assert len(inventory.students) == 29
    matching = tuple(row for row in inventory.students if row.student_id == FIRST)
    assert len(matching) == 1
    row = matching[0]
    assert row.selection_status == "no_decision"
    assert tuple(attempt.attempt.native.sequence for attempt in row.attempts) == (1, 2)
    assert row.attempts[1].operative_eligible
    return scenario, inventory, row


def _run(
    monkeypatch: pytest.MonkeyPatch,
    scenario: object,
    inventory: object,
    row: object,
    responses: tuple[str, ...],
    *,
    actor_current: Callable[[TeacherActionActor], None] | None = None,
    before_response: Callable[[int], None] | None = None,
):
    # #121 profile lives outside the isolated synthetic workspace. This is the
    # ONLY mandatory authority seam: preserve the real #122 action and storage.
    actor = TeacherActionActor(TEACHER, "c" * 64, "saved")

    def validate_profile(value: TeacherActionActor) -> None:
        assert value == actor
        if actor_current is not None:
            actor_current(value)

    monkeypatch.setattr(action_service, "_actor_now", validate_profile)
    scripted = ScriptedTeacher(*responses, before_response=before_response)
    output = StringIO()
    assert run_teacher_correction_decision_menu(
        scenario.root,
        scenario.prepared,
        inventory,
        row,
        GuidedAttemptDependencies(),
        scripted,
        output,
        lambda: None,
        ports=CorrectionDecisionPorts(actor_loader=lambda: actor),
    )
    return output.getvalue(), scripted


def _receipt_store(scenario: object) -> TeacherActionReceiptStore:
    return TeacherActionReceiptStore(scenario.root, WORK.class_id)


def _current(scenario: object):
    return load_current_attempt_selection_decision(
        scenario.root, WORK.class_id, GRADE_ITEM, WORK, FIRST
    )


def _history(scenario: object) -> tuple[int, ...]:
    return list_attempt_selection_decision_revisions(
        scenario.root, WORK.class_id, GRADE_ITEM, WORK, FIRST
    )


def test_teacher_menu_save_use_persists_one_original_122_receipt_and_current_30(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scenario, inventory, row = _world(tmp_path)
    assert not _receipt_store(scenario).list_receipts()
    assert _history(scenario) == ()
    content, scripted = _run(
        monkeypatch,
        scenario,
        inventory,
        row,
        (
            "1",  # Original native observation, NOT automatic lowest result.
            "1",  # Only remaining eligible replacement (native attempt 2).
            "Teacher examined the retained source; attempt 2 is the correction.",
            "1",  # Exactly one explicit Save and Use confirmation.
            "",  # Display pause, no further academic confirmation.
        ),
    )
    assert scripted.requests == 5
    assert "Correction Decision — Current Verified" in content
    assert "producer-certified correction provenance" in content
    assert (
        "No ScoreForm result, eligibility, Standard, Grade or report was changed"
        in content
    )
    stored = _current(scenario)
    assert stored is not None
    assert _history(scenario) == (1,)
    assert tuple(a.native.sequence for a in stored.decision.selected_attempts) == (2,)
    assert len(stored.decision.candidates) == 2
    assert stored.decision.actor.actor_id == TEACHER
    (receipt,) = _receipt_store(scenario).list_receipts()
    assert receipt.preview.kind == "attempt_decision"
    assert receipt.preview.actor.actor_id == TEACHER
    assert receipt.preview.scope.class_id == WORK.class_id
    assert receipt.preview.scope.grade_item_id == GRADE_ITEM
    assert receipt.preview.scope.school_year == "2026-2027"
    assert receipt.preview.scope.academic_period_id == "mp1"
    assert receipt.preview.target.revision == 1
    assert receipt.preview.target.expected_current_revision is None
    assert receipt.preview.target.candidate_sha256 == stored.decision_sha256
    assert receipt.checkpoints[-1].stage == "receipt_finalized"
    assert receipt.observed_records
    assert any(
        record.matches_target(receipt.preview.target)
        for record in receipt.observed_records
    )
    resolution = resolve_current_attempt_selection(
        scenario.root,
        WORK.class_id,
        GRADE_ITEM,
        WORK,
        FIRST,
        authorized_snapshot=scenario.prepared.authorized,
    )
    assert resolution.operative_selection and resolution.status == "selected"
    assert (
        get_current_attempt_selection_decision_revision(
            scenario.root, WORK.class_id, GRADE_ITEM, WORK, RETAKE
        )
        is None
    )
    manifest = (
        module_work_dir(scenario.root, WORK)
        / "publications"
        / "academic_results"
        / "1.json"
    )
    assert (
        hashlib.sha256(manifest.read_bytes()).digest()
        == hashlib.sha256(scenario.original_data).digest()
    )


@pytest.mark.parametrize(
    "answers",
    [
        ("b",),
        ("1", "b"),
        ("1", "1", ""),
        ("1", "1", "Reviewed source.", "2"),
        ("1", "1", "Reviewed source.", "APPLY"),
    ],
)
def test_teacher_menu_cancellation_never_writes_30_or_122(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answers: tuple[str, ...]
) -> None:
    scenario, inventory, row = _world(tmp_path)
    content, _ = _run(monkeypatch, scenario, inventory, row, answers)
    assert "Current Verified" not in content
    assert _receipt_store(scenario).list_receipts() == ()
    assert _history(scenario) == ()
    assert _current(scenario) is None


def test_profile_change_after_review_blocks_canonical_save_without_false_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scenario, inventory, row = _world(tmp_path)
    currently_valid = {"value": True}

    def turn_profile_stale(prompt_number: int) -> None:
        if prompt_number == 4:  # Immediately before the teacher confirms Save.
            currently_valid["value"] = False

    def require_current(_actor: TeacherActionActor) -> None:
        if not currently_valid["value"]:
            raise ValueError("Synthetic #121 profile fingerprint changed")

    content, _ = _run(
        monkeypatch,
        scenario,
        inventory,
        row,
        ("1", "1", "Reviewed source.", "1", ""),
        actor_current=require_current,
        before_response=turn_profile_stale,
    )
    assert "Current Verified" not in content
    assert _history(scenario) == ()
    assert _current(scenario) is None


def test_interrupted_native_30_cas_never_claims_save_success_or_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scenario, inventory, row = _world(tmp_path)
    calls: list[str] = []

    def interrupted(*_args: object, **_kwargs: object):
        calls.append("select")
        raise OSError("Synthetic interruption between #30 write and CAS")

    monkeypatch.setattr(action_service, "commit_guided_attempt_selection", interrupted)
    content, _ = _run(
        monkeypatch,
        scenario,
        inventory,
        row,
        ("1", "1", "Teacher inspected source.", "1", ""),
    )
    assert calls == ["select"]
    assert "Current Verified" not in content
    assert "Recovery/Review Required" in content or "Outcome Uncertain" in content
    assert _history(scenario) == (1,)
    assert _current(scenario) is None
    receipts = _receipt_store(scenario).list_receipts()
    assert len(receipts) == 1
    assert receipts[0].preview.kind == "attempt_decision"
    assert receipts[0].preview.target.revision == 1


def test_verified_standards_navigation_includes_only_current_attempt_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scenario, inventory, row = _world(tmp_path)
    content, _ = _run(
        monkeypatch,
        scenario,
        inventory,
        row,
        ("1", "1", "Teacher checked correction source.", "1", ""),
    )
    assert "Current Verified" in content
    current_inventory = project_assessment_attempt_inventory(
        scenario.root,
        grade_item_id=GRADE_ITEM,
        prepared=scenario.prepared,
    )
    (selected_row,) = (
        student for student in current_inventory.students if student.student_id == FIRST
    )
    assert tuple(
        attempt.attempt.native.sequence
        for attempt in selected_row.attempts
        if attempt.current_selected
    ) == (2,)
    ports = VerifiedContinuationPorts(
        fresh_projection=lambda root, _work, publication_id: _read(
            root, publication_id
        ),
    )
    verified = verify_student_current_use(
        scenario.root,
        scenario.prepared,
        current_inventory,
        selected_row,
        ports=ports,
    )
    assert verified.selected_attempt_count == 1
    assert verified.included_item_ids
    assert set(verified.included_item_ids).issubset(
        set(selected_row.attempts[1].item_ids)
    )
    assert not set(verified.included_item_ids).intersection(
        selected_row.attempts[0].item_ids
    )
    forwarded: list[tuple[object, ...]] = []
    ports = VerifiedContinuationPorts(
        fresh_projection=lambda root, _work, publication_id: _read(
            root, publication_id
        ),
        standards=lambda *args: forwarded.append(args),  # No Standards write in I2B.
    )
    session = TeacherSessionContext()
    session.select_work(WORK)
    session.select_publication(scenario.publication_id)
    session.select_grade_item(GRADE_ITEM)
    session.select_student(FIRST)
    output = StringIO()
    assert run_verified_standards_continuation(
        scenario.root,
        scenario.prepared,
        current_inventory,
        selected_row,
        session,
        ScriptedTeacher("1"),
        output,
        lambda: None,
        ports=ports,
    )
    assert "independently verified selected attempts" in output.getvalue()
    assert len(forwarded) == 1
    chosen = forwarded[0][2]
    assert chosen.student_id == FIRST
    assert chosen.item_id in verified.included_item_ids
    assert chosen.item_id not in selected_row.attempts[0].item_ids
    assert _history(scenario) == (1,)
