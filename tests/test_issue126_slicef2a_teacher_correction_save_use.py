"""#126-F2A: one explicit teacher correction; synthetic source and no real pupils."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from test_issue126_sliceb_attempt_inventory import _build, _case
from test_issue126_slicef1_assessment_corrections_queue import _prepared, _setup

from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptPolicyPreset,
)
from meridian.menu_teacher_correction_decision import (
    CorrectionDecisionPorts,
    run_teacher_correction_decision_menu,
)
from meridian.menu_teacher_corrections import CorrectionsMenuPorts


class Scripted:
    def __init__(self, *responses: str) -> None:
        self.responses = iter(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        try:
            return next(self.responses)
        except StopIteration as error:
            raise AssertionError("Unexpected prompt") from error


class Action:
    def __init__(
        self, *, status: str = "applied_current", raises: bool = False
    ) -> None:
        self.status = status
        self.raises = raises
        self.calls: list[bool] = []

    def apply(self, *, confirmed: bool):
        self.calls.append(confirmed)
        if self.raises:
            raise RuntimeError("Write may have occurred")
        success = self.status in {"applied_current", "already_current"}
        return NS(
            status=self.status,
            exact_current=success,
            continue_to_standards_review=success,
        )


def _rig(
    tmp_path: Path,
    *responses: str,
    action: Action | None = None,
    inventory=None,
    dependencies=None,
):
    view = _build(_case()) if inventory is None else inventory
    actor = NS(actor_id="saved_teacher", profile_sha256="a" * 64)
    output = StringIO()
    scripted = Scripted(*responses)
    execution = action or Action()
    observed: list[tuple[str, object]] = []

    def prepare(root, *, prepared, interpretation, preset, actor, dependencies):
        assert root == tmp_path
        assert prepared is not None
        assert preset.minimum_selected == preset.maximum_selected == 1
        assert actor.actor_id == "saved_teacher"
        assert interpretation.treatment == "teacher_reviewed_correction"
        assert len(interpretation.intended_selected_attempts) == 1
        assert interpretation.original_attempt is not None
        assert (
            interpretation.original_attempt
            != interpretation.intended_selected_attempts[0]
        )
        observed.append(("prepare", interpretation))
        return execution

    ports = CorrectionDecisionPorts(
        actor_loader=lambda: actor,
        resolution_preparer=prepare,
        resolution_renderer=lambda *_args: "Reviewed original and corrected attempt",
    )
    active_deps = dependencies or GuidedAttemptDependencies()

    def run(row=None, services=None):
        return run_teacher_correction_decision_menu(
            tmp_path,
            _prepared(),
            view,
            view.students[0] if row is None else row,
            active_deps,
            scripted,
            output,
            lambda: None,
            ports=ports if services is None else services,
        )

    return NS(
        run=run,
        output=output,
        input=scripted,
        action=execution,
        observed=observed,
        view=view,
    )


def test_explicit_original_and_corrected_result_are_teacher_reviewed(tmp_path):
    s = _rig(tmp_path, "1", "1", "Paper comparison confirmed a scan error.", "1", "")
    assert s.run() is True
    assert s.action.calls == [True]
    interpretation = s.observed[0][1]
    assert interpretation.original_attempt.native.sequence == 1
    assert interpretation.intended_selected_attempts[0].native.sequence == 2
    assert (
        interpretation.teacher_rationale == "Paper comparison confirmed a scan error."
    )
    assert interpretation.needs_reassessment_decision is False
    text = s.output.getvalue()
    assert "producer-certified" in text
    assert "Save and Use This Decision" in text
    assert "Current Verified" in text
    assert "No ScoreForm result" in text
    assert "synthetic_student_01" not in text


def test_current_selected_does_not_certify_correction_cause(tmp_path):
    s = _rig(tmp_path, "1", "1", "Teacher inspected original.", "1", "")
    s.run()
    assert "teacher testimony, NOT producer-certified" in s.output.getvalue()
    assert "Current-use result" in s.output.getvalue()


@pytest.mark.parametrize(
    "responses",
    [
        ("b",),
        ("1", "b"),
        ("1", "1", ""),
        ("1", "1", "Checked paper", "2"),
        ("1", "1", "Checked paper", "b"),
    ],
)
def test_cancel_at_every_stage_never_prepares_or_applies(tmp_path, responses):
    s = _rig(tmp_path, *responses)
    s.run()
    assert s.action.calls == []
    assert s.observed == [] or responses[-1].casefold() in {"2", "b"}


def test_confirmation_case_is_strict_and_not_an_unqualified_apply(tmp_path):
    s = _rig(tmp_path, "1", "1", "Checked", "apply")
    s.run()
    assert s.action.calls == []
    assert "Cancelled before writing" in s.output.getvalue()


def test_policy_setup_is_separate_no_implicit_write(tmp_path):
    other = GuidedAttemptPolicyPreset(
        "Multi", "Multiple", "teacher_guided_one_or_more", 1, None
    )
    s = _rig(tmp_path, dependencies=GuidedAttemptDependencies(policies=(other,)))
    s.run()
    assert "Policy Needed" in s.output.getvalue()
    assert s.observed == []


def test_no_eligible_distinct_replacement_never_prepares(tmp_path):
    view = _build(_case())
    first = view.students[0]
    changed = replace(
        first,
        attempts=tuple(replace(a, operative_eligible=False) for a in first.attempts),
    )
    swapped = replace(view, students=(changed, *view.students[1:]))
    s = _rig(tmp_path, inventory=swapped)
    s.run()
    assert "Review Unavailable" in s.output.getvalue()
    assert s.observed == []


def test_same_original_and_corrected_attempt_cannot_be_chosen(tmp_path):
    s = _rig(tmp_path, "2")  # Pick the only eligible attempt as original.
    s.run()
    assert "No Eligible Replacement" in s.output.getvalue()
    assert s.action.calls == []


def test_nonoperative_or_stale_context_never_prepares(tmp_path):
    view = _build(_case())
    row = replace(view.students[0], selection_status="stale")
    s = _rig(tmp_path)
    s.run(row=row)
    assert "Review Unavailable" in s.output.getvalue()
    assert s.observed == []


def test_teacher_profile_failure_is_no_write(tmp_path):
    s = _rig(tmp_path, "1", "1", "Checked paper")

    def fail():
        raise ValueError("Saved actor unavailable")

    services = CorrectionDecisionPorts(actor_loader=fail)
    s.run(services=services)
    assert "Refresh Required" in s.output.getvalue()
    assert s.action.calls == []


def test_preparation_conflict_is_no_write(tmp_path):
    s = _rig(tmp_path, "1", "1", "Checked paper")

    def fail(*args, **kwargs):
        raise ValueError("Policy changed")

    services = CorrectionDecisionPorts(
        actor_loader=lambda: NS(actor_id="saved_teacher"),
        resolution_preparer=fail,
    )
    s.run(services=services)
    assert "Refresh Required" in s.output.getvalue()
    assert s.action.calls == []


def test_rationale_notes_token_is_literal_text(tmp_path):
    s = _rig(tmp_path, "1", "1", ":notes is not an invoked command", "1", "")
    s.run()
    interpretation = s.observed[0][1]
    assert interpretation.teacher_rationale.startswith(":notes")


def test_uncertain_after_action_is_never_called_again(tmp_path):
    execution = Action(raises=True)
    s = _rig(tmp_path, "1", "1", "Checked", "1", action=execution)
    s.run()
    assert execution.calls == [True]
    assert "Outcome Uncertain" in s.output.getvalue()
    assert "Do not press Save again" in s.output.getvalue()


@pytest.mark.parametrize(
    "state",
    [
        "written_not_current",
        "conflict_requires_review",
        "recovery_required",
        "current_unverified",
    ],
)
def test_partial_or_unverified_status_cannot_claim_success(tmp_path, state):
    s = _rig(tmp_path, "1", "1", "Checked", "1", "", action=Action(status=state))
    s.run()
    assert s.action.calls == [True]
    assert "Recovery/Review Required" in s.output.getvalue()
    assert "Current Verified" not in s.output.getvalue()


@pytest.mark.parametrize("value, expected", [("m", ReturnToMainMenu), ("q", QuitPDS)])
def test_core_navigation_unwinds_during_choice(tmp_path, value, expected):
    s = _rig(tmp_path, value)
    with pytest.raises(expected):
        s.run()


def test_f1_student_route_dispatches_single_review_and_refresh(tmp_path):
    s = _setup(tmp_path, "1", "c", "b")
    calls = []
    services = CorrectionsMenuPorts(
        grade_items_loader=s.services.grade_items_loader,
        inventory_loader=s.services.inventory_loader,
        correction_handler=lambda *args: calls.append(args) or True,
    )
    s.run(ports=services)
    assert len(calls) == 1
    assert calls[0][3].student_id == "synthetic_student_01"
    assert s.calls == ["read", "read"]  # fresh projection after student action
    label = "C. Use a corrected result (original scan or entry was wrong)"
    assert label in s.output.getvalue()


def test_plain_student_history_remains_available_in_f1(tmp_path):
    s = _setup(tmp_path, "1", "h", "", "b", "b")
    s.run()
    assert "Attempt History (READ ONLY)" in s.output.getvalue()
