"""#126-F3B2: original #31 receipt only; no new academic authoring or replay."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from test_issue126_slicee2a_exact_restart import _ports, _setup

from meridian.assessment_attempt_inventory import (
    AssessmentAttemptInventory,
    NativeAttemptInventoryRow,
    StudentAttemptInventoryRow,
)
from meridian.attempt_pair_restart import prepare_exact_pair_restart
from meridian.menu_teacher_correction_history import CorrectionHistory, HistoryRow
from meridian.menu_teacher_corrections import _show_student
from meridian.menu_teacher_pair_restart import (
    PairRestartContextPorts,
    PairRestartMenuError,
    PairRestartMenuPorts,
    load_exact_written_pair,
    run_teacher_exact_pair_restart_menu,
)
from meridian.teacher_action_guided import _identity
from meridian.teacher_session import TeacherSessionContext


class Input:
    def __init__(self, *values: str) -> None:
        self.values = iter(values)

    def __call__(self, prompt: str = "") -> str:
        try:
            return next(self.values)
        except StopIteration as error:
            raise AssertionError("Unexpected F3B2 input") from error


def _case(tmp_path: Path):
    world = _setup(tmp_path)
    first = world.authoring.candidate
    source = first.source_snapshot
    rows = tuple(
        NativeAttemptInventoryRow(
            attempt=attempt,
            item_ids=(f"synthetic-{index}",),
            point_result=None,
            result_origin=None,
            scan_review_failure_reference=False,
            operative_eligible=True,
            current_selected=True,
        )
        for index, attempt in enumerate(first.selected_attempts, 1)
    )
    row = StudentAttemptInventoryRow(
        student_id=first.student_id,
        display_label="Synthetic Teacher Review",
        attempts=rows,
        selection_status="selected",
        selection_resolution_status="selected",
        selected_decision_revision=first.decision_revision,
        reassessment_status="no_decision",
        projected_item_count=len(rows),
        attention=(),
    )
    inventory = AssessmentAttemptInventory(
        class_id=first.class_id,
        grade_item_id=first.grade_item_id,
        work_module_id=first.work.module_id,
        work_id=first.work.work_id,
        publication_id=source.publication_id,
        cache_key=source.cache_key,
        snapshot_digest=source.snapshot_digest,
        source_status="current",
        membership_state="included",
        class_label="Synthetic Class",
        assessment_title="Synthetic Assessment",
        students=(row,),
        shared_item_count=0,
        unmatched_item_count=0,
        outside_requested_authorization_scope_count=0,
        unresolved_global_exception_codes=(),
    )
    fresh = NS(
        authorized=NS(
            assessment=NS(reusable_for_current_use=True),
            current_context=NS(
                publication=NS(work=first.work, publication_id=source.publication_id)
            ),
            stored=NS(
                cache_key=source.cache_key,
                snapshot_digest=source.snapshot_digest,
            ),
        )
    )
    history = CorrectionHistory(
        student_label=row.display_label,
        attempt_rows=(
            HistoryRow("attempt", 1, "a" * 64, False, True, "prior selection"),
            HistoryRow(
                "attempt",
                first.decision_revision,
                world.review.upstream_decision_sha256,
                True,
                True,
                "two selected",
            ),
        ),
        reassessment_rows=(
            HistoryRow(
                "reassessment",
                world.review.decision.decision_revision,
                world.review.reassessment_decision_sha256,
                False,
                None,
                "retain",
                first.decision_revision,
            ),
        ),
        stored_attempt_pointer=first.decision_revision,
        stored_reassessment_pointer=None,
    )
    session = TeacherSessionContext()
    session.select_work(first.work)
    session.select_publication(source.publication_id)
    session.select_grade_item(first.grade_item_id)
    session.select_student(first.student_id)
    ports = PairRestartMenuPorts(
        fresh_projection=lambda *args: fresh,
        inventory=lambda *args: inventory,
        history=lambda *args: history,
        actor=lambda: world.actor,
        pair=lambda *args: (world.authoring, world.review),
        restart=lambda *args, **kwargs: prepare_exact_pair_restart(
            *args, **kwargs, ports=_ports(world)
        ),
    )
    return world, inventory, row, fresh, history, session, ports


def _run(tmp_path: Path, *inputs: str, ports: PairRestartMenuPorts | None = None):
    world, inventory, row, fresh, history, session, default = _case(tmp_path)
    output = StringIO()
    result = run_teacher_exact_pair_restart_menu(
        tmp_path,
        fresh,
        inventory,
        row,
        session,
        Input(*inputs),
        output,
        lambda: None,
        ports=ports or default,
    )
    return world, result, output.getvalue()


def test_original_receipt_resume_is_selection_only(tmp_path: Path) -> None:
    world, result, text = _run(tmp_path, "RESUME", "")
    assert result is True
    assert world.selections == 1
    assert world.immutable_writes == 0
    assert world.resumes == 1
    assert "Both original decisions" in text
    assert "Standards review" in text


def test_cancel_does_not_issue_resume(tmp_path: Path) -> None:
    world, _, text = _run(tmp_path, "2")
    assert world.selections == world.resumes == world.immutable_writes == 0
    assert "Cancelled" in text


@pytest.mark.parametrize("command", ["", "NO", "resumE", "another"])
def test_exact_word_required_for_resume(tmp_path: Path, command: str) -> None:
    world, _, _ = _run(tmp_path, command)
    assert world.resumes == world.selections == 0


@pytest.mark.parametrize(
    "choice,expected",
    [
        ("m", ReturnToMainMenu),
        ("q", QuitPDS),
    ],
)
def test_core_navigation_preserved(tmp_path: Path, choice, expected) -> None:
    with pytest.raises(expected):
        _run(tmp_path, choice)


def test_session_drift_blocks_before_original_receipt_resume(tmp_path: Path) -> None:
    world, inventory, row, fresh, _, session, ports = _case(tmp_path)
    session.select_student("different-student")
    output = StringIO()
    assert run_teacher_exact_pair_restart_menu(
        tmp_path,
        fresh,
        inventory,
        row,
        session,
        Input(""),
        output,
        lambda: None,
        ports=ports,
    )
    assert "Unavailable" in output.getvalue()
    assert world.resumes == 0


def test_changed_current_source_blocks_recovery(tmp_path: Path) -> None:
    world, inv, row, fresh, _, session, ports = _case(tmp_path)
    fresh.authorized.assessment.reusable_for_current_use = False
    output = StringIO()
    assert run_teacher_exact_pair_restart_menu(
        tmp_path, fresh, inv, row, session, Input(""), output, lambda: None, ports=ports
    )
    assert "Unavailable" in output.getvalue()
    assert world.resumes == 0


def test_missing_updated_roster_student_blocks_recovery(tmp_path: Path) -> None:
    world, inv, row, fresh, _, session, ports = _case(tmp_path)
    removed = replace(inv, students=())
    changed = replace(ports, inventory=lambda *args: removed)
    output = StringIO()
    assert run_teacher_exact_pair_restart_menu(
        tmp_path,
        fresh,
        inv,
        row,
        session,
        Input(""),
        output,
        lambda: None,
        ports=changed,
    )
    assert "Unavailable" in output.getvalue()
    assert world.resumes == 0


def test_identity_mismatch_blocks_before_action(tmp_path: Path) -> None:
    world, inv, row, fresh, _, session, ports = _case(tmp_path)
    wrong = replace(ports, actor=lambda: NS(actor_id="different"))
    output = StringIO()
    assert run_teacher_exact_pair_restart_menu(
        tmp_path, fresh, inv, row, session, Input(""), output, lambda: None, ports=wrong
    )
    assert "Unavailable" in output.getvalue()
    assert world.resumes == 0


def test_missing_receipt_rejected_without_new_write(tmp_path: Path) -> None:
    world, inv, row, fresh, history, _, _ = _case(tmp_path)
    first = world.authoring.candidate
    second = world.review.decision
    digest = world.review.upstream_decision_sha256
    readers = PairRestartContextPorts(
        attempt_history=lambda *a: (1, first.decision_revision),
        read_attempt=lambda *a: NS(
            decision=first,
            decision_sha256=(digest if a[-1] == first.decision_revision else "a" * 64),
        ),
        current_attempt=lambda *a: NS(decision_sha256=digest),
        reassessment_history=lambda *a: (second.decision_revision,),
        read_reassessment=lambda *a: NS(
            decision=second, decision_sha256=world.review.reassessment_decision_sha256
        ),
        current_reassessment=lambda *a: None,
        receipts=lambda *a: (),
    )
    with pytest.raises(PairRestartMenuError, match="receipt"):
        load_exact_written_pair(
            tmp_path, fresh, inv, row, history, world.actor, ports=readers
        )


def test_original_receipt_reconstruction_matches_exact_canonical_pair(
    tmp_path: Path,
) -> None:
    world, inv, row, fresh, history, _, _ = _case(tmp_path)
    first = world.authoring.candidate
    second = world.review.decision
    digest = world.review.upstream_decision_sha256
    original30 = NS(
        preview=NS(
            kind="attempt_decision",
            actor=world.actor,
            target=NS(
                candidate_sha256=digest,
                revision=first.decision_revision,
                expected_current_revision=(
                    world.authoring.reviewed_current_decision_revision
                ),
                identity_sha256=_identity(
                    "attempt_decision",
                    first.class_id,
                    first.grade_item_id,
                    first.work.module_id,
                    first.work.work_id,
                    first.student_id,
                ),
            ),
        )
    )
    readers = PairRestartContextPorts(
        attempt_history=lambda *a: (1, first.decision_revision),
        read_attempt=lambda *a: NS(
            decision=first,
            decision_sha256=(digest if a[-1] == first.decision_revision else "a" * 64),
        ),
        current_attempt=lambda *a: NS(decision_sha256=digest),
        reassessment_history=lambda *a: (second.decision_revision,),
        read_reassessment=lambda *a: NS(
            decision=second, decision_sha256=world.review.reassessment_decision_sha256
        ),
        current_reassessment=lambda *a: None,
        receipts=lambda *a: (original30, world.receipt),
    )
    authoring, review = load_exact_written_pair(
        tmp_path, fresh, inv, row, history, world.actor, ports=readers
    )
    assert authoring.candidate == first
    assert review.decision == second
    assert review.upstream_decision_sha256 == digest
    assert review.history_before == ()
    assert authoring.history == (1,)
    assert authoring.latest_persisted_decision_sha256 == "a" * 64


def test_ambiguous_original_receipts_are_rejected(tmp_path: Path) -> None:
    world, inv, row, fresh, history, _, _ = _case(tmp_path)
    first = world.authoring.candidate
    second = world.review.decision
    original30 = NS(
        preview=NS(
            kind="attempt_decision",
            actor=world.actor,
            target=NS(
                candidate_sha256=world.review.upstream_decision_sha256,
                revision=first.decision_revision,
                expected_current_revision=None,
                identity_sha256="a" * 64,
            ),
        )
    )
    readers = PairRestartContextPorts(
        attempt_history=lambda *a: (1, first.decision_revision),
        read_attempt=lambda *a: NS(
            decision=first,
            decision_sha256=(
                world.review.upstream_decision_sha256
                if a[-1] == first.decision_revision
                else "a" * 64
            ),
        ),
        current_attempt=lambda *a: NS(
            decision_sha256=world.review.upstream_decision_sha256
        ),
        reassessment_history=lambda *a: (second.decision_revision,),
        read_reassessment=lambda *a: NS(
            decision=second, decision_sha256=world.review.reassessment_decision_sha256
        ),
        current_reassessment=lambda *a: None,
        receipts=lambda *a: (original30, world.receipt, world.receipt),
    )
    with pytest.raises(PairRestartMenuError, match="ambiguous"):
        load_exact_written_pair(
            tmp_path, fresh, inv, row, history, world.actor, ports=readers
        )


def test_student_menu_z_routes_without_implicit_write(tmp_path: Path) -> None:
    world, inv, row, fresh, _, session, _ = _case(tmp_path)
    received = []

    def restart(*args):
        received.append(args)
        return True

    assert _show_student(
        StringIO(),
        Input("z"),
        lambda: None,
        inv,
        row,
        workspace_root=tmp_path,
        prepared=fresh,
        attempt_dependencies=NS(),
        correction_handler=lambda *a: False,
        reassessment_handler=lambda *a: False,
        session_context=session,
        pair_restart_handler=restart,
    )
    assert len(received) == 1
    assert received[0][3] == row
    assert world.resumes == 0


def test_unbound_z_fails_closed(tmp_path: Path) -> None:
    _, inv, row, fresh, _, _, _ = _case(tmp_path)
    output = StringIO()
    assert _show_student(
        output,
        Input("z"),
        lambda: None,
        inv,
        row,
        workspace_root=tmp_path,
        prepared=fresh,
        attempt_dependencies=NS(),
        correction_handler=lambda *a: False,
        reassessment_handler=lambda *a: False,
    )
    assert "bound class session" in output.getvalue()
