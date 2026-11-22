"""#126-F1: synthetic assessment-level entry and read-only exception navigation."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace as NS
from typing import cast

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef
from test_issue126_sliceb_attempt_inventory import (
    _CACHE,
    _DIGEST,
    _GRADE_ITEM,
    _PUB,
    _WORK,
    _build,
    _case,
)

from meridian.guided_eligibility import GuidedEligibilityDependencies
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_teacher_corrections import (
    CorrectionsMenuPorts,
    run_assessment_corrections_menu,
)
from meridian.menu_teacher_evidence import (
    _render_review_summary,
)
from meridian.teacher_session import TeacherSessionContext


class Input:
    def __init__(self, *values: str) -> None:
        self.values = iter(values)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        try:
            return next(self.values)
        except StopIteration as error:
            raise AssertionError("Unexpected input prompt") from error


def _prepared() -> GuidedProjectionResult:
    return cast(
        GuidedProjectionResult,
        NS(
            authorized=NS(
                current_context=NS(
                    publication=NS(work=_WORK, publication_id=_PUB),
                ),
                stored=NS(cache_key=_CACHE, snapshot_digest=_DIGEST),
            )
        ),
    )


def _setup(tmp_path: Path, *keys: str, inventory=None):
    result = _build(_case()) if inventory is None else inventory
    session = TeacherSessionContext()
    session.select_work(_WORK)
    session.select_publication(_PUB)
    output = StringIO()
    entry = Input(*keys)
    calls: list[str] = []
    choice = NS(grade_item_id=_GRADE_ITEM, display_label="Six-Question Check")

    def load(*_args):
        calls.append("read")
        return result

    services = CorrectionsMenuPorts(
        grade_items_loader=lambda *_args: (choice,),
        inventory_loader=load,
    )

    def run(*, root=None, ports=None):
        return run_assessment_corrections_menu(
            workspace_root=tmp_path if root is None else root,
            prepared=_prepared(),
            class_label="English 11",
            assessment_title="Scene, Summary, and Pacing Check",
            session_context=session,
            dependencies=GuidedEligibilityDependencies(),
            input_fn=entry,
            output=output,
            clear_fn=lambda: None,
            ports=services if ports is None else ports,
        )

    return NS(
        run=run,
        output=output,
        input=entry,
        session=session,
        calls=calls,
        inventory=result,
        services=services,
    )


def test_assessment_level_queue_opens_without_manual_ids_or_writes(tmp_path):
    s = _setup(tmp_path, "b")
    s.run()
    text = s.output.getvalue()
    assert "Review Corrections & Attempts" in text
    assert "Synthetic Student 01" in text
    assert "Synthetic Student 02" in text
    assert "Synthetic Student 03" not in text  # exception-first
    assert "Authorized students: 29" in text
    assert "No academic decision is saved" in text
    assert s.calls == ["read"]
    assert len(s.input.prompts) == 1  # no teacher name/ID reentry


def test_one_student_history_and_technical_are_explicit(tmp_path):
    s = _setup(tmp_path, "1", "h", "", "t", "", "b", "b")
    s.run()
    text = s.output.getvalue()
    assert "0/6" in text and "6/6" in text
    assert "Source Attempt History (READ ONLY)" in text
    assert "Scan-review reference exists (not proof of correction cause)" in text
    assert "Technical Details (READ ONLY)" in text
    assert _PUB in text
    assert s.session.active_student_id == "synthetic_student_01"
    assert s.calls == ["read"]


def test_ordinary_student_screen_hides_source_hashes(tmp_path):
    s = _setup(tmp_path, "1", "b", "b")
    s.run()
    output = s.output.getvalue()
    assert "Synthetic Student 01" in output
    assert _PUB not in output
    assert _DIGEST not in output
    assert "synthetic_student_01" not in output


def test_filter_and_page_stay_bounded_and_keep_student_identity(tmp_path):
    s = _setup(tmp_path, "a", "n", "1", "b", "p", "e", "b")
    s.run()
    output = s.output.getvalue()
    assert "ALL AUTHORIZED STUDENTS — page 2/2" in output
    assert "Synthetic Student 21" in output
    assert s.session.active_student_id == "synthetic_student_21"
    assert "ATTENTION NEEDED" in output
    assert s.calls == ["read"]  # pagination never rereads a whole class


def test_r_reloads_full_authorized_projection(tmp_path):
    s = _setup(tmp_path, "r", "b")
    s.run()
    assert s.calls == ["read", "read"]


def test_student_r_returns_to_queue_with_a_fresh_projection(tmp_path):
    s = _setup(tmp_path, "1", "r", "b")
    s.run()
    assert s.calls == ["read", "read"]


@pytest.mark.parametrize(
    "navigation,exception", [("m", ReturnToMainMenu), ("q", QuitPDS)]
)
def test_shared_navigation_propagates_to_parent_menu(tmp_path, navigation, exception):
    s = _setup(tmp_path, navigation)
    with pytest.raises(exception):
        s.run()


@pytest.mark.parametrize(
    "navigation,exception", [("m", ReturnToMainMenu), ("q", QuitPDS)]
)
def test_shared_navigation_propagates_from_student_detail(
    tmp_path, navigation, exception
):
    s = _setup(tmp_path, "1", navigation)
    with pytest.raises(exception):
        s.run()


def test_no_notes_interception_at_nonopted_in_prompt(tmp_path):
    s = _setup(tmp_path, ":notes", "", "b")
    s.run()
    assert "Choose a listed student" in s.output.getvalue()


def test_absent_grade_item_uses_setup_route_without_writes(tmp_path):
    s = _setup(tmp_path, "")
    no_item = CorrectionsMenuPorts(
        grade_items_loader=lambda *_args: (),
        inventory_loader=lambda *_args: pytest.fail("Inventory must not be read"),
    )
    s.run(ports=no_item)
    assert "Use Published Assessment Setup" in s.output.getvalue()


def test_two_grade_items_allow_safe_cancel_without_inventory_read(tmp_path):
    s = _setup(tmp_path, "b")
    choices = (
        NS(grade_item_id=_GRADE_ITEM, display_label="Assessment A"),
        NS(grade_item_id="other_synthetic_grade", display_label="Assessment B"),
    )
    alternate = CorrectionsMenuPorts(
        grade_items_loader=lambda *_args: choices,
        inventory_loader=lambda *_args: pytest.fail("Cancel must not load"),
    )
    s.run(ports=alternate)
    assert "Choose Grade Item" in s.output.getvalue()


@pytest.mark.parametrize(
    "field",
    [
        "publication_id",
        "cache_key",
        "snapshot_digest",
        "grade_item_id",
        "class_id",
        "work_id",
    ],
)
def test_injected_mismatched_inventory_scope_fails_closed(tmp_path, field):
    original = _build(_case())
    mismatched = replace(original, **{field: "wrong_scope"})
    s = _setup(tmp_path, "", inventory=mismatched)
    s.run()
    output = s.output.getvalue()
    assert "Refresh Required" in output
    assert "Synthetic Student 01" not in output


def test_duplicate_roster_identity_fails_closed(tmp_path):
    original = _build(_case())
    mismatched = replace(
        original, students=(original.students[0], original.students[0])
    )
    s = _setup(tmp_path, "", inventory=mismatched)
    s.run()
    assert "Refresh Required" in s.output.getvalue()
    assert "Synthetic Student 01" not in s.output.getvalue()


def test_scope_missing_or_stale_session_refuses_invocation(tmp_path):
    s = _setup(tmp_path, "")
    s.session.select_work(ModuleWorkRef("scoreform", "other_class", "x"))
    s.run()
    assert "Review Unavailable" in s.output.getvalue()
    assert s.calls == []


def test_nonabsolute_root_is_rejected_before_loading_inventory(tmp_path):
    s = _setup(tmp_path, "")
    s.run(root=Path("relative"))
    assert "Review Unavailable" in s.output.getvalue()
    assert s.calls == []


def test_stale_inventory_still_read_only_and_never_authorizes_use(tmp_path):
    original = _build(_case())
    historical = tuple(
        replace(
            row,
            selection_status=None,
            selection_resolution_status=None,
            reassessment_status=None,
        )
        for row in original.students
    )
    stale = replace(
        original,
        source_status="withdrawn",
        membership_state="not_included",
        students=historical,
    )
    s = _setup(tmp_path, "b", inventory=stale)
    s.run()
    assert "Source: withdrawn; Grade Item: not_included" in s.output.getvalue()
    assert "No academic decision is saved" in s.output.getvalue()


def test_control_sequences_are_not_rendered(tmp_path):
    original = _build(_case())
    altered = replace(original.students[0], display_label="\x1b[31mStudent\x07")
    s = _setup(
        tmp_path, "1", "b", "b", inventory=replace(original, students=(altered,))
    )
    s.run()
    output = s.output.getvalue()
    assert "\x1b" not in output
    assert "\x07" not in output
    assert "?" in output


def test_explicit_authorization_scope_excludes_hidden_students(tmp_path):
    source = _case(requested_ids={"synthetic_student_01"})
    s = _setup(tmp_path, "a", "b", inventory=_build(source))
    s.run()
    output = s.output.getvalue()
    assert "Authorized students: 1" in output
    assert "Hidden Student" not in output
    assert "synthetic_student_02" not in output


def test_empty_authorized_class_has_no_zero_or_fabricated_student(tmp_path):
    source = _case(requested_ids=set())
    s = _setup(tmp_path, "b", inventory=_build(source))
    s.run()
    assert "Authorized students: 0" in s.output.getvalue()
    assert "No students in this view" in s.output.getvalue()


def test_projection_read_failure_is_fail_closed(tmp_path):
    s = _setup(tmp_path, "")
    bad = CorrectionsMenuPorts(
        grade_items_loader=s.services.grade_items_loader,
        inventory_loader=lambda *_args: (_ for _ in ()).throw(OSError("secret path")),
    )
    s.run(ports=bad)
    assert "Refresh Required" in s.output.getvalue()
    assert "secret path" not in s.output.getvalue()


def test_evidence_review_action_is_assessment_level_and_optional():
    output = StringIO()
    item = NS(class_label="English 11", work_title="Check", producer_label="ScoreForm")
    review = NS(
        student_count=1,
        evidence_count=8,
        shared_evidence_count=0,
        students=(NS(),),
        shared_items=(),
    )
    actions = _render_review_summary(
        output,
        item,
        review,
        assessment_eligibility_available=True,
        assessment_corrections_available=True,
    )
    assert actions == ("students", "assessment_eligibility", "assessment_corrections")
    assert "3. Review Corrections & Attempts" in output.getvalue()
    omitted = _render_review_summary(StringIO(), item, review)
    assert omitted == ("students",)


def test_assessment_entry_dispatches_without_drilling_into_evidence_row(tmp_path):
    import meridian.menu_teacher_evidence as inbox

    output = StringIO()
    calls = []
    item = NS(class_label="English 11", work_title="Check", producer_label="ScoreForm")
    review = NS(
        student_count=1,
        evidence_count=8,
        shared_evidence_count=0,
        students=(NS(),),
        shared_items=(),
    )
    handlers = NS(
        assessment_eligibility_handler=None,
        assessment_corrections_handler=lambda *args: calls.append(args),
    )
    session = TeacherSessionContext()
    session.select_work(_WORK)
    session.select_publication(_PUB)
    scripted = Input("2", "b")
    inbox._run_teacher_evidence_review(
        root=tmp_path,
        prepared=_prepared(),
        item=item,
        review=review,
        dependencies=handlers,  # type: ignore[arg-type]
        session_context=session,
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
    )
    assert len(calls) == 1
    assert calls[0][2] is item
    assert calls[0][3] is session
    assert "2. Review Corrections & Attempts" in output.getvalue()
