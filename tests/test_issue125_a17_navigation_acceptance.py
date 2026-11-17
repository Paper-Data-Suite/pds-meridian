"""#125-A17: installed navigation and supported Core contract acceptance.

All classroom data are synthetic.  The native walkthrough is gated so the
source suite does not silently substitute editable dependencies for the exact
installed-wheel qualification.
"""

from __future__ import annotations

import os
from dataclasses import replace
from importlib.metadata import version
from io import StringIO
from pathlib import Path

import pytest

_NATIVE = os.environ.get("PDS_ISSUE125_A17_NATIVE_TEST") == "1"


class _ScriptedInput:
    """Return and retain the exact values entered into production prompts."""

    def __init__(self, *answers: str) -> None:
        self._answers = iter(answers)
        self.entered: list[str] = []
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            answer = next(self._answers)
        except StopIteration as error:
            raise AssertionError(
                f"Unexpected teacher prompt: {prompt!r}; entered={self.entered!r}"
            ) from error
        self.entered.append(answer)
        return answer

    def assert_exhausted(self) -> None:
        try:
            extra = next(self._answers)
        except StopIteration:
            return
        raise AssertionError(f"Unused scripted teacher input: {extra!r}")


def test_core_066_public_menu_contract_has_no_header_or_notes_capability() -> None:
    """Record the official public boundary instead of importing Core internals."""
    import pds_core.menu_navigation as navigation

    assert version("pds-core") == "0.6.6"
    assert navigation.navigation_labels() == (
        "B. Back",
        "M. Main Menu",
        "Q. Quit",
    )
    assert navigation.navigation_hint() == "Please choose a listed option, B, M, or Q."
    public = {name for name in vars(navigation) if not name.startswith("_")}
    assert "print_app_header" not in public
    assert "app_header" not in public
    assert not any("note" in name.casefold() for name in public)


@pytest.mark.skipif(
    not _NATIVE, reason="Requires isolated official A17 five-wheel environment"
)
def test_installed_native_cancel_reenter_individual_and_advanced_navigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Walk the real inbox and prove navigation cannot become academic action."""
    from test_issue124_slicee2g3k_composite_canonical import CLASS, _all_bytes
    from test_issue125_sliceg2a_canonical_batch_acceptance import _ready_native

    from meridian.menu_teacher_evidence import (
        default_teacher_evidence_inbox_menu_dependencies,
        run_teacher_evidence_inbox_menu,
    )
    from meridian.teacher_action_receipts import TeacherActionReceiptStore
    from meridian.teacher_session import TeacherSessionContext

    (
        root,
        grade_id,
        prepared,
        assessment_review,
        _eligibility_dependencies,
        _grade_item,
        diagnostics,
        _actor,
    ) = _ready_native(tmp_path, monkeypatch, "scoreform")
    assert assessment_review.projected_item_count == 406
    assert len(assessment_review.students) == 29

    dependencies = replace(
        default_teacher_evidence_inbox_menu_dependencies(diagnostics=diagnostics),
        workspace_resolver=lambda: root,
    )
    session = TeacherSessionContext()
    output = StringIO()
    script = _ScriptedInput(
        "1",  # class
        "1",  # assessment
        "2",  # assessment eligibility
        "1",  # current Grade Item
        "V",  # open complete read-only exception/coverage queue
        "D",  # return to exact selection without applying
        "F",
        "Synthetic Learner001",
        "1",  # toggle one matched display row
        "B",  # cancel the matched filter selection
        "F",
        "no such authorized display label",
        "",  # read failed-filter explanation
        "I",
        "1",  # select stable item 1
        "N",
        "21",  # select stable item 21 on page 2
        "P",
        "B",  # cancel the entire paged selection
        "R",  # Advanced interrupted-save recovery
        "B",  # return from recovery
        ":notes",
        "",  # unsupported command explanation
        "B",  # cancel batch scope
        "1",  # re-enter existing individual review
        "1",  # first represented student
        "1",  # first evidence row
        "B",  # evidence detail
        "B",  # evidence rows
        "B",  # represented students
        "2",  # enter batch again from the same assessment
        "1",  # same current Grade Item
        "B",  # cancel batch scope again
        "B",  # assessment review
        "B",  # assessment list
        "B",  # class list / inbox
    )
    receipts = TeacherActionReceiptStore(root, CLASS)
    receipt_ids_before = tuple(r.action_id for r in receipts.list_receipts())
    bytes_before = _all_bytes(root)

    monkeypatch.setenv("NO_COLOR", "1")
    run_teacher_evidence_inbox_menu(
        dependencies=dependencies,
        session_context=session,
        input_fn=script,
        output=output,
        clear_fn=lambda: None,
    )

    script.assert_exhausted()
    rendered = output.getvalue()
    assert rendered.count("Assessment Exceptions") == 1
    assert rendered.count("Choose Exact Batch Scope") >= 4
    assert "No safe, authorized evidence matches that display label." in rendered
    assert "Filter Safe Evidence" in rendered
    assert "Page 2/" in rendered
    assert "Review Interrupted Saves" in rendered
    assert "Evidence Detail" in rendered
    assert "Current student" in rendered
    assert "Review Exact Batch" not in rendered
    assert "Eligibility Attribution" not in rendered
    assert "\x1b[" not in rendered
    assert "\033" not in rendered

    work = prepared.authorized.current_context.publication.work
    publication_id = prepared.authorized.current_context.publication.publication_id
    assert session.active_class_id == work.class_id
    assert session.active_work == work
    assert session.active_publication_id == publication_id
    assert session.active_grade_item_id == grade_id
    assert session.active_student_id == "student001"

    canonical_ids = {
        grade_id,
        *(
            item.source.item_id
            for student in assessment_review.students
            for item in student.items
        ),
    }
    assert canonical_ids.isdisjoint(script.entered)
    assert grade_id not in rendered
    assert not any(
        item_id in rendered for item_id in canonical_ids if item_id != grade_id
    )
    assert tuple(r.action_id for r in receipts.list_receipts()) == receipt_ids_before
    assert _all_bytes(root) == bytes_before

    print(
        "A17_INSTALLED_NAVIGATION "
        "source_items=406 students=29 batch_entries=2 "
        "failed_filter_selects=0 paged_selection_cancelled=true "
        "advanced_reentry=true individual_reentry=true "
        "manual_canonical_ids=0 ansi_sequences=0 academic_changes=0",
        flush=True,
    )
