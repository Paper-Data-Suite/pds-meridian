"""#126-F3A read-only canonical histories and guarded #122 entry (synthetic)."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef
from test_issue126_sliceb_attempt_inventory import (
    _CACHE,
    _DIGEST,
    _PUB,
    _WORK,
    _build,
    _case,
    _source,
)
from test_issue126_slicef1_assessment_corrections_queue import _setup

import meridian.menu_teacher_correction_history as history
from meridian.teacher_session import TeacherSessionContext


class Input:
    def __init__(self, *keys: str) -> None:
        self.keys = iter(keys)
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        try:
            return next(self.keys)
        except StopIteration as error:
            raise AssertionError("Unexpected F3A input prompt") from error


def _prepared() -> NS:
    return NS(
        authorized=NS(
            assessment=NS(reusable_for_current_use=True),
            current_context=NS(
                publication=NS(work=_WORK, publication_id=_PUB),
            ),
            stored=NS(cache_key=_CACHE, snapshot_digest=_DIGEST),
        )
    )


def _ports(*, attempts=(1,), relationships=(1,), source=None):
    snapshot = _source() if source is None else source
    attempt_digests = {revision: f"{revision:064x}" for revision in attempts}
    linked_revision = attempts[0] if attempts else 1
    linked_digest = attempt_digests.get(linked_revision, "f" * 64)
    events: list[str] = []

    def attempt(revision):
        events.append(f"read30:{revision}")
        return NS(
            decision_sha256=attempt_digests[revision],
            decision=NS(
                class_id=_WORK.class_id,
                grade_item_id="synthetic_grade_item_126",
                work=_WORK,
                student_id="synthetic_student_01",
                decision_revision=revision,
                source_snapshot=snapshot,
                selected_attempts=(object(),),
            ),
        )

    def relation(revision):
        events.append(f"read31:{revision}")
        return NS(
            decision_sha256=f"{revision + 256:064x}",
            decision=NS(
                class_id=_WORK.class_id,
                grade_item_id="synthetic_grade_item_126",
                work=_WORK,
                student_id="synthetic_student_01",
                decision_revision=revision,
                attempt_selection=NS(
                    decision_revision=linked_revision,
                    decision_sha256=linked_digest,
                ),
                mode="retain",
                contributing_attempts=(object(), object()),
            ),
        )

    ports = history.CorrectionHistoryPorts(
        list_attempts=lambda *args: tuple(attempts),
        read_attempt=lambda *args: attempt(args[-1]),
        current_attempt=lambda *args: attempt(attempts[0]) if attempts else None,
        list_reassessments=lambda *args: tuple(relationships),
        read_reassessment=lambda *args: relation(args[-1]),
        current_reassessment=(
            lambda *args: relation(relationships[0]) if relationships else None
        ),
    )
    return ports, events


@pytest.fixture
def case(monkeypatch):
    monkeypatch.setattr(history, "GuidedProjectionResult", NS)
    inventory = _build(_case())
    return inventory, inventory.students[0]


def test_historical_decisions_keep_immutable_provenance_and_pointer_distinction(
    tmp_path: Path, case
):
    inventory, row = case
    ports, events = _ports()
    result = history.load_correction_decision_history(
        tmp_path, _prepared(), inventory, row, ports=ports
    )
    assert result.stored_attempt_pointer == 1
    assert result.stored_reassessment_pointer == 1
    assert result.attempt_rows[0].source_is_reviewed_publication
    assert result.reassessment_rows[0].linked_attempt_revision == 1
    assert "read30:1" in events and "read31:1" in events
    output = StringIO()
    history._present(output, result, page=0, technical=False)
    text = output.getvalue()
    assert "stored pointer is NOT an operative" in text
    assert "#30 Attempt decision, revision 1" in text
    assert "#31 Reassessment, revision 1" in text
    assert result.attempt_rows[0].sha256 not in text
    assert "synthetic_student_01" not in text


def test_historical_source_drift_is_labeled_not_treated_as_current(
    tmp_path: Path, case
):
    inventory, row = case
    older = replace(_source(), snapshot_digest="e" * 64)
    ports, _ = _ports(source=older)
    result = history.load_correction_decision_history(
        tmp_path, _prepared(), inventory, row, ports=ports
    )
    output = StringIO()
    history._present(output, result, page=0, technical=False)
    assert "Different historical source snapshot" in output.getvalue()


def test_technical_details_require_explicit_toggle(tmp_path: Path, case):
    inventory, row = case
    ports, _ = _ports()
    output = StringIO()
    history.run_teacher_corrections_history_menu(
        tmp_path,
        _prepared(),
        inventory,
        row,
        Input("t", "b"),
        output,
        lambda: None,
        ports=ports,
    )
    text = output.getvalue()
    assert "Exact digest:" in text
    assert "Decision History (READ ONLY)" in text


def test_stale_ui_pointer_cannot_display_current_claim(tmp_path: Path, case):
    inventory, row = case
    ports, _ = _ports(attempts=(1, 2), relationships=())
    changed = replace(ports, current_attempt=lambda *a: ports.read_attempt(*a, 2))
    with pytest.raises(history.CorrectionHistoryError, match="pointer changed"):
        history.load_correction_decision_history(
            tmp_path, _prepared(), inventory, row, ports=changed
        )


def test_unknown_canonical_history_fails_closed_without_partial_display(
    tmp_path: Path, case
):
    inventory, row = case
    ports, _ = _ports()
    corrupt = replace(
        ports,
        read_reassessment=lambda *args: (_ for _ in ()).throw(OSError("corrupt")),
    )
    output = StringIO()
    history.run_teacher_corrections_history_menu(
        tmp_path,
        _prepared(),
        inventory,
        row,
        Input(""),
        output,
        lambda: None,
        ports=corrupt,
    )
    text = output.getvalue()
    assert "Refresh Required" in text
    assert "Verified immutable records" not in text
    assert "Nothing was selected" in text


def test_unknown_linked_30_digest_fails_closed(tmp_path: Path, case):
    inventory, row = case
    ports, _ = _ports()

    def wrong(*args):
        original = ports.read_reassessment(*args)
        link = NS(decision_revision=1, decision_sha256="a" * 64)
        return NS(
            decision_sha256=original.decision_sha256,
            decision=NS(**{**vars(original.decision), "attempt_selection": link}),
        )

    wrong_ports = replace(ports, read_reassessment=wrong)
    with pytest.raises(history.CorrectionHistoryError, match="missing or different"):
        history.load_correction_decision_history(
            tmp_path, _prepared(), inventory, row, ports=wrong_ports
        )


def test_authorization_scope_mismatch_is_rejected(tmp_path: Path, case):
    inventory, row = case
    ports, _ = _ports()
    outside = replace(row, student_id="outside_scope")
    with pytest.raises(history.CorrectionHistoryError, match="outside"):
        history.load_correction_decision_history(
            tmp_path, _prepared(), inventory, outside, ports=ports
        )


def test_unusable_projection_is_rejected(tmp_path: Path, case):
    inventory, row = case
    ports, _ = _ports()
    prepared = _prepared()
    prepared.authorized.assessment.reusable_for_current_use = False
    with pytest.raises(history.CorrectionHistoryError, match="Source"):
        history.load_correction_decision_history(
            tmp_path, prepared, inventory, row, ports=ports
        )


def test_nonabsolute_workspace_refused(tmp_path: Path, case):
    inventory, row = case
    ports, _ = _ports()
    with pytest.raises(history.CorrectionHistoryError, match="Absolute"):
        history.load_correction_decision_history(
            Path("relative"), _prepared(), inventory, row, ports=ports
        )


def test_bounded_history_refuses_truncated_or_unbounded_enumeration(
    tmp_path: Path, case
):
    inventory, row = case
    ports, _ = _ports()
    for invalid in ((1, 3), tuple(range(1, 130))):
        modified = replace(ports, list_attempts=lambda *args: invalid)
        with pytest.raises(history.CorrectionHistoryError, match="history"):
            history.load_correction_decision_history(
                tmp_path, _prepared(), inventory, row, ports=modified
            )


def test_history_pagination_shows_second_page(tmp_path: Path, case):
    inventory, row = case
    ports, _ = _ports(relationships=tuple(range(1, 14)))
    output = StringIO()
    history.run_teacher_corrections_history_menu(
        tmp_path,
        _prepared(),
        inventory,
        row,
        Input("n", "b"),
        output,
        lambda: None,
        ports=ports,
    )
    assert "page 2/2" in output.getvalue()


@pytest.mark.parametrize("key, expected", [("m", ReturnToMainMenu), ("q", QuitPDS)])
def test_history_navigation_unwinds_using_core(tmp_path: Path, case, key, expected):
    inventory, row = case
    ports, _ = _ports()
    with pytest.raises(expected):
        history.run_teacher_corrections_history_menu(
            tmp_path,
            _prepared(),
            inventory,
            row,
            Input(key),
            StringIO(),
            lambda: None,
            ports=ports,
        )


def _session() -> TeacherSessionContext:
    session = TeacherSessionContext()
    session.select_work(_WORK)
    session.select_publication(_PUB)
    session.select_grade_item("synthetic_grade_item_126")
    return session


def test_recovery_requires_explicit_entry_and_preserves_bound_workspace(
    tmp_path: Path, case, monkeypatch
):
    inventory, _ = case
    calls: list[object] = []
    monkeypatch.setattr(
        history,
        "run_teacher_action_recovery_menu",
        lambda **kwargs: calls.append(kwargs),
    )
    history.run_bound_teacher_recovery_menu(
        tmp_path,
        _prepared(),
        inventory,
        _session(),
        Input("1"),
        StringIO(),
        lambda: None,
    )
    assert len(calls) == 1
    assert calls[0]["workspace_resolver"]() == tmp_path
    assert calls[0]["session_context"].active_class_id == _WORK.class_id


def test_recovery_cancel_does_not_open_receipts(tmp_path: Path, case, monkeypatch):
    inventory, _ = case
    monkeypatch.setattr(
        history,
        "run_teacher_action_recovery_menu",
        lambda **kwargs: pytest.fail("Must not open receipt journal on cancel"),
    )
    history.run_bound_teacher_recovery_menu(
        tmp_path,
        _prepared(),
        inventory,
        _session(),
        Input("2"),
        StringIO(),
        lambda: None,
    )


def test_recovery_rejects_stale_session_class(tmp_path: Path, case):
    inventory, _ = case
    session = _session()
    session.select_work(ModuleWorkRef("scoreform", "another", "x"))
    output = StringIO()
    history.run_bound_teacher_recovery_menu(
        tmp_path,
        _prepared(),
        inventory,
        session,
        Input(""),
        output,
        lambda: None,
    )
    assert "Refresh Required" in output.getvalue()


def test_f1_student_decision_history_route_refreshes_queue(tmp_path: Path):
    fixture = _setup(tmp_path, "1", "d", "b")
    calls: list[tuple[object, ...]] = []
    ports = replace(
        fixture.services,
        decision_history_handler=lambda *args: calls.append(args),
    )
    fixture.run(ports=ports)
    assert len(calls) == 1
    assert calls[0][3].student_id == "synthetic_student_01"
    assert fixture.calls == ["read", "read"]


def test_f1_queue_recovery_route_refreshes_without_student_selection(
    tmp_path: Path,
):
    fixture = _setup(tmp_path, "i", "b")
    calls: list[tuple[object, ...]] = []
    ports = replace(fixture.services, recovery_handler=lambda *a: calls.append(a))
    fixture.run(ports=ports)
    assert len(calls) == 1
    assert fixture.session.active_student_id is None
    assert fixture.calls == ["read", "read"]


def test_f1_student_recovery_route_remains_class_wide(tmp_path: Path):
    fixture = _setup(tmp_path, "1", "i", "b")
    calls: list[tuple[object, ...]] = []
    ports = replace(fixture.services, recovery_handler=lambda *a: calls.append(a))
    fixture.run(ports=ports)
    assert len(calls) == 1
    assert calls[0][3].active_class_id == _WORK.class_id
    assert fixture.calls == ["read", "read"]


def test_f3a_keeps_source_history_and_correction_actions_distinct(tmp_path: Path):
    fixture = _setup(tmp_path, "1", "h", "", "b", "b")
    fixture.run()
    text = fixture.output.getvalue()
    assert "Source Attempt History" in text
    assert "Canonical #30/#31 decision history" in text
    assert "Review teacher-verified correction" in text
    assert "Review genuine reassessment" in text
