"""#126-F2B: teacher choice/navigation and guarded #30/#31 handoff (synthetic)."""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from types import SimpleNamespace as NS
from typing import cast

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from test_issue126_sliceb_attempt_inventory import _build, _case

from meridian.assessment_attempt_inventory import AssessmentAttemptInventory
from meridian.attempt_correction_interpretation import preview_attempt_interpretation
from meridian.guided_attempts import GuidedAttemptDependencies, GuidedAttemptPolicyPlan
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_teacher_corrections import _show_student
from meridian.menu_teacher_reassessment_decision import (
    ReassessmentDecisionPorts,
    _multi_preset,
    _numbers,
    run_teacher_reassessment_decision_menu,
)


class Input:
    def __init__(self, *choices: str):
        self.choices = iter(choices)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self.choices)


@dataclass
class World:
    actor_calls: int = 0
    authoring_calls: int = 0
    preview_calls: int = 0
    coordinator_calls: int = 0
    applies: int = 0
    rel: object | None = None
    rationale: str | None = None
    timestamp: object | None = None
    status: str = "applied_current"
    exact: bool = True
    standards: bool = True
    error: bool = False
    policy_ready: bool = True
    policy_present: bool = True
    actor_ok: bool = True
    policy_identity: str | None = None
    clock_consistent: bool = True
    history_ok: bool = True


def _context():
    inventory: AssessmentAttemptInventory = _build(_case(size=2))
    row = inventory.students[1]  # two independently eligible synthetic sittings
    assert len(row.attempts) == 2
    assert all(item.operative_eligible for item in row.attempts)
    return inventory, row


def _run(
    tmp_path: Path,
    *responses: str,
    world: World | None = None,
    inventory: AssessmentAttemptInventory | None = None,
    row: object | None = None,
):
    w = world or World()
    expected, student = _context()
    inv = inventory or expected
    subject = row or student
    stream = StringIO()
    scripted = Input(*responses)
    deps = GuidedAttemptDependencies()

    def actor():
        w.actor_calls += 1
        if not w.actor_ok:
            raise ValueError("No verified teacher attribution")
        return NS(actor_id="teacher_synthetic", profile_sha256="a" * 64)

    def intent(*args, **kwargs):
        w.rationale = kwargs["teacher_rationale"]
        return preview_attempt_interpretation(*args, **kwargs)

    def plan(*args, **kwargs):
        return GuidedAttemptPolicyPlan(
            "ready" if w.policy_ready else "create", kwargs["preset"], None
        )

    def author(*args, **kwargs):
        w.authoring_calls += 1
        w.timestamp = kwargs["dependencies"].clock()
        return NS()

    def policy(*args):
        w.policy_identity = args[-1]
        return NS() if w.policy_present else None

    def history(*args):
        if not w.history_ok:
            raise OSError("History unreadable")
        return ()

    def preview(**kwargs):
        w.preview_calls += 1
        w.rel = kwargs["choice"]
        w.clock_consistent = w.timestamp == kwargs["decided_at"]
        return NS()

    def prepare(*args, **kwargs):
        w.coordinator_calls += 1
        w.clock_consistent &= kwargs["dependencies"].clock() == w.timestamp

        class Action:
            def apply(self, *, confirmed: bool):
                assert confirmed is True
                w.applies += 1
                if w.error:
                    raise OSError("Unknown after possible selection")
                return NS(
                    status=w.status,
                    exact_pair_current=w.exact,
                    continue_to_standards_review=w.standards,
                )

        return Action()

    ports = ReassessmentDecisionPorts(
        actor_loader=actor,
        intention_previewer=intent,
        policy_planner=plan,
        authoring_previewer=author,
        reassessment_policy_loader=policy,
        history_loader=history,
        current_loader=lambda *args: None,
        reassessment_previewer=preview,
        coordinator_preparer=prepare,
        coordinator_renderer=lambda action: "Reviewed exact pair — no implicit Grade",
    )
    returned = run_teacher_reassessment_decision_menu(
        tmp_path,
        cast(GuidedProjectionResult, NS()),
        inv,
        subject,  # type: ignore[arg-type]
        deps,
        scripted,
        stream,
        lambda: None,
        ports=ports,
    )
    return w, stream.getvalue(), scripted, returned


@pytest.mark.parametrize(
    ("relationship_inputs", "mode"),
    [
        (("1",), "retain"),
        (("2", "2", "1"), "replace"),
        (("3", "1,2"), "combine"),
        (("4", "2,1", "2"), "recency"),
    ],
)
def test_each_mode_is_explicit_and_no_automatic_grade(
    tmp_path: Path, relationship_inputs: tuple[str, ...], mode: str
) -> None:
    w, display, _scripted, reload = _run(
        tmp_path,
        "1,2",
        *relationship_inputs,
        "Two independent sittings",
        "1",
        "",
    )
    assert reload
    assert w.applies == 1
    assert w.rel is not None
    assert w.rel.mode == mode  # type: ignore[union-attr]
    assert w.rationale == "Two independent sittings"
    assert w.clock_consistent
    assert w.policy_identity == "teacher_reassessment"
    assert "Both Decisions Current Verified" in display
    assert "no Grade" in display or "no Grade" in display.lower()


def test_explicit_replace_identifies_source_not_score(tmp_path: Path) -> None:
    w, _, _, _ = _run(tmp_path, "1,2", "2", "1", "1", "Teacher saw a retake", "1", "")
    relation = w.rel.replacements[0]  # type: ignore[union-attr]
    assert relation.replacement_attempt.native.sequence == 1
    assert tuple(x.native.sequence for x in relation.replaced_attempts) == (2,)


def test_explicit_recency_order_and_contributors(tmp_path: Path) -> None:
    w, _, _, _ = _run(tmp_path, "1,2", "4", "2,1", "1", "Teacher evidence", "1", "")
    assert tuple(x.native.sequence for x in w.rel.recency_order) == (2, 1)  # type: ignore[union-attr]
    assert tuple(x.native.sequence for x in w.rel.recency_contributors) == (1,)  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "raw", ("", "1,1", "0,1", "-1,2", "a,2", "1,3", "1,,2", "1;2", " 1.2 ", "１,２")
)
def test_invalid_number_sets_are_never_silent(raw: str) -> None:
    assert _numbers(raw, 2, min_count=2) is None


def test_explicit_selection_recovers_after_invalid_duplicate(tmp_path: Path) -> None:
    w, display, _, _ = _run(tmp_path, "1,1", "1,2", "1", "teacher verified", "1", "")
    assert "Select distinct displayed attempts" in display
    assert w.applies == 1


@pytest.mark.parametrize(
    "choices",
    (
        ("",),
        ("b",),
        (
            "1,2",
            "",
        ),
        (
            "1,2",
            "1",
            "",
        ),
    ),
)
def test_cancel_before_preparation_does_not_call_writer(
    tmp_path: Path, choices: tuple[str, ...]
) -> None:
    w, _, _, _ = _run(tmp_path, *choices)
    assert w.authoring_calls == 0
    assert w.coordinator_calls == 0
    assert w.applies == 0


def test_cancel_at_final_review_does_not_apply(tmp_path: Path) -> None:
    w, display, _, _ = _run(tmp_path, "1,2", "1", "Teacher testimony", "2")
    assert w.coordinator_calls == 1
    assert w.applies == 0
    assert "Cancelled" in display


@pytest.mark.parametrize(
    "field", ("policy_ready", "policy_present", "actor_ok", "history_ok")
)
def test_unqualified_dependent_state_blocks_before_writer(
    tmp_path: Path, field: str
) -> None:
    w = World()
    setattr(w, field, False)
    w, display, _, _ = _run(tmp_path, "1,2", "1", "Teacher account", world=w)
    assert w.coordinator_calls == 0
    assert w.applies == 0
    assert "Current Review Unavailable" in display


def test_uncertain_immutable_write_result_never_retries(tmp_path: Path) -> None:
    w = World(error=True)
    w, display, _, _ = _run(tmp_path, "1,2", "1", "Teacher testimony", "1", world=w)
    assert w.applies == 1
    assert "Outcome Uncertain" in display
    assert "Do not retry" in display


def test_incomplete_pair_does_not_claim_standards_ready(tmp_path: Path) -> None:
    w = World(
        status="upstream_current_reassessment_incomplete", exact=False, standards=False
    )
    w, display, _, _ = _run(tmp_path, "1,2", "1", "Teacher account", "1", "", world=w)
    assert w.applies == 1
    assert "Recovery or Review Required" in display
    assert "Both Decisions Current Verified" not in display


def test_literal_notes_command_is_rationale_not_navigation(tmp_path: Path) -> None:
    w, _, prompts, _ = _run(
        tmp_path, "1,2", "1", ":notes is a literal example", "1", ""
    )
    assert w.rationale == ":notes is a literal example"
    assert w.applies == 1
    assert any("Teacher explanation" in prompt for prompt in prompts.prompts)


@pytest.mark.parametrize("command,expected", (("m", ReturnToMainMenu), ("q", QuitPDS)))
def test_core_navigation_propagates(
    tmp_path: Path, command: str, expected: type[Exception]
) -> None:
    with pytest.raises(expected):
        _run(tmp_path, command)


def test_student_menu_wires_reassessment_without_implicit_save(tmp_path: Path) -> None:
    inv, student = _context()
    captured: list[tuple[object, ...]] = []

    def handler(*args):
        captured.append(args)
        return True

    result = _show_student(
        StringIO(),
        Input("s"),
        lambda: None,
        inv,
        student,
        workspace_root=tmp_path,
        prepared=cast(GuidedProjectionResult, NS()),
        attempt_dependencies=GuidedAttemptDependencies(),
        correction_handler=lambda *a: False,
        reassessment_handler=handler,
    )
    assert result is True
    assert len(captured) == 1
    assert captured[0][3].student_id == student.student_id


def test_scope_or_eligibility_ineligible_without_action(tmp_path: Path) -> None:
    inv, student = _context()
    from dataclasses import replace as dc_replace

    stale = dc_replace(inv, source_status="not_current")
    w, display, _, _ = _run(tmp_path, world=World(), inventory=stale, row=student)
    assert w.applies == 0
    assert "Refresh Required" in display


def test_fewer_than_two_eligible_blocks(tmp_path: Path) -> None:
    inv, student = _context()
    from dataclasses import replace as dc_replace

    attempts = (
        dc_replace(student.attempts[0], operative_eligible=False),
        student.attempts[1],
    )
    changed = dc_replace(student, attempts=attempts)
    updated = dc_replace(inv, students=(inv.students[0], changed))
    w, display, _, _ = _run(tmp_path, world=World(), inventory=updated, row=changed)
    assert w.applies == 0
    assert "Not Ready" in display


def test_qualified_preset_does_not_claim_policy_ready(tmp_path: Path) -> None:
    deps = GuidedAttemptDependencies()
    preset = _multi_preset(deps)
    assert preset is not None
    assert preset.minimum_selected == 1
    assert preset.maximum_selected is None
