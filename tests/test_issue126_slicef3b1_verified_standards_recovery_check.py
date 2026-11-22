"""#126-F3B1: synthetic fresh-current Standards gate and safe #31 diagnosis."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from test_issue126_sliceb_attempt_inventory import (
    _CACHE,
    _DIGEST,
    _PUB,
    _WORK,
    _build,
    _case,
)

from meridian.assessment_eligibility_review import AssessmentEligibilityReview
from meridian.menu_teacher_correction_history import CorrectionHistory, HistoryRow
from meridian.menu_teacher_verified_continuation import (
    VerifiedContinuationError,
    VerifiedContinuationPorts,
    run_read_only_reassessment_recovery_check,
    run_verified_standards_continuation,
    verify_student_current_use,
)
from meridian.teacher_evidence_review import (
    TeacherEvidenceReview,
    TeacherEvidenceReviewItem,
    TeacherEvidenceStudent,
)
from meridian.teacher_session import TeacherSessionContext


class Input:
    def __init__(self, *entries: str) -> None:
        self.entries = iter(entries)

    def __call__(self, prompt: str) -> str:
        try:
            return next(self.entries)
        except StopIteration as error:
            raise AssertionError("Unexpected F3B1 teacher input") from error


def _prepared() -> NS:
    return NS(
        authorized=NS(
            assessment=NS(reusable_for_current_use=True),
            current_context=NS(publication=NS(work=_WORK, publication_id=_PUB)),
            stored=NS(cache_key=_CACHE, snapshot_digest=_DIGEST),
        ),
    )


def _history(*, pair: bool = False, source: bool = True) -> CorrectionHistory:
    return CorrectionHistory(
        student_label="Synthetic Student 01",
        attempt_rows=(
            HistoryRow(
                kind="attempt",
                revision=1,
                sha256="d" * 64,
                pointer_selected=True,
                source_is_reviewed_publication=source,
                description="one explicitly selected",
            ),
        ),
        reassessment_rows=(
            (
                HistoryRow(
                    kind="reassessment",
                    revision=1,
                    sha256="e" * 64,
                    pointer_selected=True,
                    source_is_reviewed_publication=None,
                    description="retain",
                    linked_attempt_revision=1,
                ),
            )
            if pair
            else ()
        ),
        stored_attempt_pointer=1,
        stored_reassessment_pointer=1 if pair else None,
    )


def _fixture(*, pair: bool = False):
    case = _case()
    inventory = _build(case)
    row = inventory.students[0]
    if pair:
        # Both exact selected attempts must have operative included items.
        first = case.review.students[0]
        updated = replace(
            first,
            items=tuple(replace(item, operative_included=True) for item in first.items),
        )
        case = replace(
            case,
            review=replace(case.review, students=(updated, *case.review.students[1:])),
        )
        # Synthetic two-selected variant on a student with two native attempts:
        # no accidental reliance on score/sequence ordering.
        row = replace(
            row,
            attempts=tuple(
                replace(item, current_selected=True, operative_eligible=True)
                for item in row.attempts
            ),
            reassessment_status="resolved",
        )
        inventory = replace(inventory, students=(row, *inventory.students[1:]))
    first_included = tuple(
        item for item in case.review.students[0].items if item.operative_included
    )
    assert first_included
    evidence = TeacherEvidenceReviewItem(
        item_id=first_included[0].source.item_id,
        student_id=row.student_id,
        evidence_label="Synthetic selected result",
        value_label="6 / 6",
        result_kind_label="Attempt points",
        standard_ids=("RL.TS.11-12.4",),
    )
    view = TeacherEvidenceReview(
        class_id=_WORK.class_id,
        work=_WORK,
        publication_id=_PUB,
        students=(
            TeacherEvidenceStudent(
                student_id=row.student_id,
                display_label=row.display_label,
                period="1",
                items=(evidence,),
            ),
        ),
        shared_items=(),
    )
    result = []
    ports = VerifiedContinuationPorts(
        fresh_projection=lambda *args: _prepared(),
        inventory=lambda *args: inventory,
        history=lambda *args: _history(pair=pair),
        eligibility=lambda *args: case.review,
        evidence=lambda *args: view,
        standards=lambda *args: result.append(args),
    )
    session = TeacherSessionContext()
    session.select_work(_WORK)
    session.select_publication(_PUB)
    session.select_grade_item(inventory.grade_item_id)
    session.select_student(row.student_id)
    return inventory, row, case.review, ports, session, result


def test_fresh_authorized_single_current_use_passes_without_31(tmp_path: Path) -> None:
    inv, row, _, ports, _, _ = _fixture()
    verified = verify_student_current_use(tmp_path, _prepared(), inv, row, ports=ports)
    assert verified.selected_attempt_count == 1
    assert verified.row.student_id == row.student_id
    assert verified.included_item_ids


def test_verified_multi_pair_requires_exact_31_history(tmp_path: Path) -> None:
    inv, row, _, ports, _, _ = _fixture(pair=True)
    assert (
        verify_student_current_use(
            tmp_path, _prepared(), inv, row, ports=ports
        ).selected_attempt_count
        == 2
    )
    broken = replace(ports, history=lambda *args: _history(pair=False))
    with pytest.raises(VerifiedContinuationError, match="#31"):
        verify_student_current_use(tmp_path, _prepared(), inv, row, ports=broken)


def test_unauthorized_student_in_updated_roster_fails_closed(tmp_path: Path) -> None:
    inv, row, _, ports, _, _ = _fixture()
    removed = replace(inv, students=inv.students[1:])
    bad = replace(ports, inventory=lambda *args: removed)
    with pytest.raises(VerifiedContinuationError, match="uniquely authorized"):
        verify_student_current_use(tmp_path, _prepared(), inv, row, ports=bad)


def test_fresh_source_or_authorization_changes_fails_closed(tmp_path: Path) -> None:
    inv, row, _, ports, _, _ = _fixture()
    unauthorized = _prepared()
    unauthorized.authorized.assessment.reusable_for_current_use = False
    bad = replace(ports, fresh_projection=lambda *args: unauthorized)
    with pytest.raises(VerifiedContinuationError, match="authorized/current"):
        verify_student_current_use(tmp_path, _prepared(), inv, row, ports=bad)
    other = replace(inv, snapshot_digest="0" * 64)
    bad = replace(ports, inventory=lambda *args: other)
    with pytest.raises(VerifiedContinuationError, match="source differs"):
        verify_student_current_use(tmp_path, _prepared(), inv, row, ports=bad)


def test_stale_canonical_current_decision_or_historical_source_fails_closed(
    tmp_path: Path,
) -> None:
    inv, row, _, ports, _, _ = _fixture()
    altered = replace(row, selected_decision_revision=2)
    broken = replace(inv, students=(altered, *inv.students[1:]))
    with pytest.raises(VerifiedContinuationError, match="pointer differs"):
        verify_student_current_use(
            tmp_path,
            _prepared(),
            broken,
            altered,
            ports=replace(ports, inventory=lambda *args: broken),
        )
    with pytest.raises(VerifiedContinuationError, match="historical source"):
        verify_student_current_use(
            tmp_path,
            _prepared(),
            inv,
            row,
            ports=replace(ports, history=lambda *args: _history(source=False)),
        )


def test_ineligible_evidence_never_enters_standards_choices(tmp_path: Path) -> None:
    inv, row, review, ports, _, _ = _fixture()
    student = review.students[0]
    no_includes = replace(
        student,
        items=tuple(replace(item, operative_included=False) for item in student.items),
    )
    denied: AssessmentEligibilityReview = replace(
        review, students=(no_includes, *review.students[1:])
    )
    with pytest.raises(VerifiedContinuationError, match="No operative included"):
        verify_student_current_use(
            tmp_path,
            _prepared(),
            inv,
            row,
            ports=replace(ports, eligibility=lambda *args: denied),
        )


def test_existing_standards_handler_gets_exact_selected_evidence_only(
    tmp_path: Path,
) -> None:
    inv, row, _, ports, session, forwarded = _fixture()
    output = StringIO()
    assert run_verified_standards_continuation(
        tmp_path,
        _prepared(),
        inv,
        row,
        session,
        Input("1"),
        output,
        lambda: None,
        ports=ports,
    )
    assert len(forwarded) == 1
    exact = forwarded[0]
    assert exact[2].student_id == row.student_id
    assert exact[2].item_id in {
        item_id
        for attempt in row.attempts
        if attempt.current_selected
        for item_id in attempt.item_ids
    }
    assert "independently verified selected attempts" in output.getvalue()


def test_cancel_before_standards_does_not_invoke_action(tmp_path: Path) -> None:
    inv, row, _, ports, session, forwarded = _fixture()
    assert run_verified_standards_continuation(
        tmp_path,
        _prepared(),
        inv,
        row,
        session,
        Input("b"),
        StringIO(),
        lambda: None,
        ports=ports,
    )
    assert forwarded == []


@pytest.mark.parametrize(
    ("key", "error"),
    [("m", ReturnToMainMenu), ("q", QuitPDS)],
)
def test_standards_preserves_core_navigation(
    tmp_path: Path, key: str, error: type[Exception]
) -> None:
    inv, row, _, ports, session, _ = _fixture()
    with pytest.raises(error):
        run_verified_standards_continuation(
            tmp_path,
            _prepared(),
            inv,
            row,
            session,
            Input(key),
            StringIO(),
            lambda: None,
            ports=ports,
        )


def test_read_only_recovery_describes_missing_pair_without_resume(
    tmp_path: Path,
) -> None:
    inv, row, _, ports, session, forwarded = _fixture(pair=True)
    unresolved = replace(row, reassessment_status="no_decision")
    inv = replace(inv, students=(unresolved, *inv.students[1:]))
    ports = replace(
        ports,
        inventory=lambda *args: inv,
        history=lambda *args: _history(pair=False),
    )
    out = StringIO()
    assert run_read_only_reassessment_recovery_check(
        tmp_path,
        _prepared(),
        inv,
        unresolved,
        session,
        Input(""),
        out,
        lambda: None,
        ports=ports,
    )
    assert "No exact operative" in out.getvalue()
    assert "no original-receipt restart is performed" in out.getvalue()
    assert not forwarded


def test_invalid_session_context_blocks_standards_and_does_not_call_handler(
    tmp_path: Path,
) -> None:
    inv, row, _, ports, session, forwarded = _fixture()
    session.clear_student()
    output = StringIO()
    assert run_verified_standards_continuation(
        tmp_path,
        _prepared(),
        inv,
        row,
        session,
        Input(""),
        output,
        lambda: None,
        ports=ports,
    )
    assert "Refresh Required" in output.getvalue()
    assert not forwarded


def test_student_menu_v_and_x_are_bound_without_implicit_save(tmp_path: Path) -> None:
    from meridian.guided_attempts import GuidedAttemptDependencies
    from meridian.menu_teacher_corrections import _show_student

    inv, row, _, _, session, _ = _fixture()
    calls: list[tuple[str, tuple[object, ...]]] = []

    def standards(*args: object) -> bool:
        calls.append(("standards", args))
        return True

    def recovery(*args: object) -> bool:
        calls.append(("recovery", args))
        return True

    for key, expected in (("v", "standards"), ("x", "recovery")):
        assert _show_student(
            StringIO(),
            Input(key),
            lambda: None,
            inv,
            row,
            workspace_root=tmp_path,
            prepared=_prepared(),
            attempt_dependencies=GuidedAttemptDependencies(),
            correction_handler=lambda *args: False,
            reassessment_handler=lambda *args: False,
            decision_history_handler=lambda *args: None,
            recovery_handler=lambda *args: None,
            session_context=session,
            standards_handler=standards,
            reassessment_recovery_handler=recovery,
        )
        assert calls[-1][0] == expected
        assert calls[-1][1][3].student_id == row.student_id


def test_unbound_student_standards_and_recovery_fail_closed(tmp_path: Path) -> None:
    from meridian.guided_attempts import GuidedAttemptDependencies
    from meridian.menu_teacher_corrections import _show_student

    inv, row, _, _, _, _ = _fixture()
    for key in ("v", "x"):
        out = StringIO()
        assert _show_student(
            out,
            Input(key),
            lambda: None,
            inv,
            row,
            workspace_root=tmp_path,
            prepared=_prepared(),
            attempt_dependencies=GuidedAttemptDependencies(),
            correction_handler=lambda *args: False,
            reassessment_handler=lambda *args: False,
        )
        assert "requires a bound class session" in out.getvalue()


def test_each_selected_attempt_requires_its_own_included_evidence(
    tmp_path: Path,
) -> None:
    inv, row, _, ports, _, _ = _fixture(pair=True)
    original = _case().review  # earlier scan attempt was excluded
    with pytest.raises(VerifiedContinuationError, match="lacks its own"):
        verify_student_current_use(
            tmp_path,
            _prepared(),
            inv,
            row,
            ports=replace(ports, eligibility=lambda *args: original),
        )
