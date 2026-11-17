"""#125-D: synthetic one-confirmation orchestration; no classroom records."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast

import pytest
from test_issue125_slicec_batch_review_plan import (
    ACTOR,
    POLICY,
    ids,
    make_item,
    make_review,
    witnesses,
)
from test_issue125_slicec_batch_review_plan import plan as make_plan

import meridian.assessment_eligibility_execution as execution
from meridian.assessment_eligibility_plan import (
    BatchEligibilitySelection,
    BatchItemException,
)
from meridian.guided_eligibility import GuidedEligibilityGradeItemChoice
from meridian.teacher_action_contract import (
    TeacherActionRecord,
    TeacherActionResult,
    TeacherActionTarget,
)


def action_result(
    status: str = "applied", *, action_id: str = "a" * 32
) -> TeacherActionResult:
    target = TeacherActionTarget("eligibility", "1" * 64, 1, "2" * 64, None, None)
    rec = TeacherActionRecord("eligibility", "1" * 64, 1, "2" * 64, "created")
    if status == "applied":
        return TeacherActionResult(
            action_id,
            "3" * 64,
            target,
            "applied",
            (rec,),
            "matches",
            rec,
            "created",
        )
    if status == "already_applied":
        rec = replace(rec, write_disposition="existing")
        return TeacherActionResult(
            action_id,
            "3" * 64,
            target,
            "already_applied",
            (rec,),
            "matches",
            rec,
            "existing",
        )
    if status == "written_not_current":
        return TeacherActionResult(
            action_id,
            "3" * 64,
            target,
            "written_not_current",
            (rec,),
            "not_current",
            None,
            "not_attempted",
            reason_code="selector_conflict",
        )
    if status == "recovery_required":
        return TeacherActionResult(
            action_id,
            "3" * 64,
            target,
            "recovery_required",
            (),
            "not_checked",
            None,
            "not_attempted",
            reason_code="journal_unknown",
        )
    raise AssertionError(status)


class FakeBatchHarness:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        review: object,
        *,
        statuses: tuple[str, ...] = (),
        failing_step: str | None = None,
    ) -> None:
        self.review = review
        self.events: list[str] = []
        self.statuses = iter(statuses)
        self.failing_step = failing_step
        self.current_witnesses = witnesses
        self.prepared = SimpleNamespace(authorized=object())
        self.dependencies = SimpleNamespace(
            policies=(POLICY,),
            clock=lambda: datetime(2026, 11, 5, tzinfo=timezone.utc),
            authoring_previewer=self.authoring,
        )
        self.grade_item = GuidedEligibilityGradeItemChoice(
            "grade_item_125c", "Synthetic check", None, "Synthetic check"
        )
        monkeypatch.setattr(execution, "GuidedProjectionResult", SimpleNamespace)
        monkeypatch.setattr(execution, "GuidedEligibilityDependencies", SimpleNamespace)
        monkeypatch.setattr(execution, "bind_reviewed_actor", self.bind_actor)
        monkeypatch.setattr(
            execution, "project_assessment_eligibility_review", self.project
        )
        monkeypatch.setattr(execution, "capture_batch_pointer_witnesses", self.capture)
        monkeypatch.setattr(execution, "load_guided_eligibility_context", self.context)
        monkeypatch.setattr(execution, "prepare_eligibility_action", self.prepare)

    def bind_actor(self, *args: object, **kwargs: object) -> object:
        self.events.append("actor")
        return ACTOR

    def project(self, *args: object, **kwargs: object) -> object:
        self.events.append("project")
        if self.failing_step == "project":
            raise RuntimeError("no authorized current view")
        return self.review

    def capture(self, *args: object, **kwargs: object) -> object:
        self.events.append("capture")
        selected = args[3]
        if self.failing_step == "capture":
            raise RuntimeError("pointer lost")
        result = witnesses(self.review, selected)
        if self.failing_step == "drift":
            return tuple(replace(x, membership_sha256="f" * 64) for x in result)
        return result

    def context(self, *args: object, **kwargs: object) -> object:
        self.events.append("context")
        if self.failing_step == "context":
            raise RuntimeError("membership changed")
        item_id = kwargs["item_id"]
        original = next(
            x
            for student in self.review.students
            for x in student.items
            if x.source.item_id == item_id
        )
        return SimpleNamespace(
            row=SimpleNamespace(
                source=original.source,
                selected_eligibility_revision=original.selected_eligibility_revision,
                eligibility_status=original.eligibility_status,
            ),
            review=SimpleNamespace(
                membership_revision=self.review.membership_revision,
                academic_period_id=self.review.academic_period_id,
            ),
        )

    def authoring(self, *args: object) -> object:
        self.events.append("preview")
        if self.failing_step == "preview":
            raise RuntimeError("source superseded")
        (item_id, disposition, actor_id, policy_id, version, reasons, rationale) = args[
            3:10
        ]
        original = next(
            x
            for student in self.review.students
            for x in student.items
            if x.source.item_id == item_id
        )
        return SimpleNamespace(
            decision=SimpleNamespace(
                source=original.source,
                disposition=disposition,
                actor=SimpleNamespace(kind="teacher", actor_id=actor_id),
                policy=SimpleNamespace(policy_id=policy_id, policy_version=version),
                reason_codes=reasons,
                rationale=rationale,
            ),
            selected_revision=original.selected_eligibility_revision,
        )

    def prepare(self, *args: object) -> object:
        self.events.append("prepare")
        if self.failing_step == "prepare":
            raise RuntimeError("CAS changed")

        def apply(*, confirmed: bool) -> TeacherActionResult:
            self.events.append("apply")
            assert confirmed is True
            if self.failing_step == "apply":
                raise RuntimeError("lost process after possible write")
            result = action_result(next(self.statuses, "applied"))
            if self.failing_step == "wrong_action":
                return replace(result, action_id="b" * 32)
            return result

        sample = action_result()
        preview = SimpleNamespace(
            action_id=sample.action_id,
            intent_sha256=sample.intent_sha256,
            target=sample.target,
        )
        return SimpleNamespace(apply=apply, preview=preview)

    def run(self, selected_plan: object, *, confirmed: bool = True):
        return execution.execute_batch_eligibility_plan(
            "synthetic_workspace",
            selected_plan,
            confirmed=confirmed,
            prepared=cast(execution.GuidedProjectionResult, self.prepared),
            grade_item=self.grade_item,
            dependencies=cast(
                execution.GuidedEligibilityDependencies, self.dependencies
            ),
        )


def test_29_by_6_one_confirmation_writes_only_per_item_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=29, questions=6)
    plan = make_plan(review)
    harness = FakeBatchHarness(monkeypatch, review)
    outcome = harness.run(plan)
    assert outcome.confirmed
    assert not outcome.stopped
    assert outcome.verified_current_count == 174
    assert outcome.counts == (("applied", 174),)
    assert harness.events.count("apply") == 174
    assert harness.events.count("preview") == 174
    assert [item.source_item_id for item in outcome.items] == [
        item.source.item_id for item in plan.items
    ]


def test_cancel_produces_no_reads_or_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    review = make_review(student_count=2, questions=3)
    harness = FakeBatchHarness(monkeypatch, review)
    outcome = harness.run(make_plan(review), confirmed=False)
    assert not harness.events
    assert not outcome.confirmed
    assert not outcome.stopped
    assert outcome.counts == (("cancelled", 6),)


@pytest.mark.parametrize("point", ["project", "capture", "drift"])
def test_preflight_failure_writes_nothing_and_reports_all_remaining(
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    review = make_review(student_count=1, questions=3)
    harness = FakeBatchHarness(monkeypatch, review, failing_step=point)
    outcome = harness.run(make_plan(review))
    assert outcome.stopped
    assert outcome.stop_reason == "batch_preflight_failed"
    assert outcome.counts == (("not_attempted", 3),)
    assert "apply" not in harness.events


def test_roster_drift_blocks_whole_batch_before_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=2)
    selected = make_plan(review)
    other = replace(
        review, students=(replace(review.students[0], display_label="Changed"),)
    )
    harness = FakeBatchHarness(monkeypatch, other)
    outcome = harness.run(selected)
    assert outcome.stopped and outcome.verified_current_count == 0
    assert "apply" not in harness.events


def test_digest_tamper_blocks_without_canonical_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=1)
    selected = make_plan(review)
    tampered = replace(selected, items=(replace(selected.items[0], rationale="NEW"),))
    harness = FakeBatchHarness(monkeypatch, review)
    outcome = harness.run(tampered)
    assert outcome.stopped and "apply" not in harness.events


def test_modified_blocked_status_cannot_bypass_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = make_item("student_01", 1, status="excluded", exception="previous_excluded")
    review = make_review(
        student_count=1, questions=1, overrides={("student_01", 1): prior}
    )
    selected = make_plan(review)
    assert selected.blocked_count == 1
    forged = replace(selected, items=(replace(selected.items[0], status="action"),))
    harness = FakeBatchHarness(monkeypatch, review)
    assert harness.run(forged).stopped
    assert "apply" not in harness.events


def test_one_uncertain_action_stops_all_later_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=4)
    harness = FakeBatchHarness(
        monkeypatch, review, statuses=("applied", "written_not_current")
    )
    outcome = harness.run(make_plan(review))
    assert outcome.stopped
    assert outcome.counts == (
        ("applied", 1),
        ("not_attempted", 2),
        ("written_not_current", 1),
    )
    assert harness.events.count("apply") == 2
    assert outcome.items[1].action_id == "a" * 32
    assert outcome.verified_current_count == 1


def test_apply_exception_is_recovery_required_not_prewrite_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=3)
    harness = FakeBatchHarness(monkeypatch, review, failing_step="apply")
    outcome = harness.run(make_plan(review))
    assert outcome.stopped
    assert outcome.counts == (("not_attempted", 2), ("recovery_required", 1))
    assert harness.events.count("apply") == 1
    assert outcome.items[0].action_id == "a" * 32


@pytest.mark.parametrize("point", ["context", "preview", "prepare"])
def test_item_preflight_failure_never_calls_apply(
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    review = make_review(student_count=1, questions=2)
    harness = FakeBatchHarness(monkeypatch, review, failing_step=point)
    outcome = harness.run(make_plan(review))
    assert outcome.stopped
    assert outcome.counts == (("blocked_before_write", 1), ("not_attempted", 1))
    assert "apply" not in harness.events


def test_deferred_and_blocked_are_never_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = make_item("student_01", 1, status="pending", exception="previous_pending")
    review = make_review(
        student_count=1, questions=3, overrides={("student_01", 1): blocked}
    )
    selected_ids = ids(review)
    selection = BatchEligibilitySelection(
        selected_ids,
        "included",
        item_exceptions=(BatchItemException(selected_ids[1], None),),
    )
    selected = make_plan(review, selection)
    assert selected.blocked_count == 1
    assert selected.deferred_count == 1
    harness = FakeBatchHarness(monkeypatch, review)
    outcome = harness.run(selected)
    assert not outcome.stopped
    assert outcome.counts == (("applied", 1), ("blocked", 1), ("deferred", 1))
    assert harness.events.count("apply") == 1


def test_existing_selection_is_not_reauthored_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = make_item("student_01", 1, status="included", operative=True)
    review = make_review(
        student_count=1, questions=2, overrides={("student_01", 1): old}
    )
    harness = FakeBatchHarness(monkeypatch, review)
    outcome = harness.run(make_plan(review))
    assert not outcome.stopped
    assert outcome.counts == (("applied", 1), ("unchanged", 1))
    assert harness.events.count("apply") == 1


def test_nonincluded_reason_passes_unmodified_to_canonical_previewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=1)
    selected = make_plan(
        review,
        BatchEligibilitySelection(
            ids(review), "excluded", ("eligibility.manual",), "Reviewed scan"
        ),
    )
    harness = FakeBatchHarness(monkeypatch, review)
    outcome = harness.run(selected)
    assert not outcome.stopped
    assert outcome.verified_current_count == 1
    assert harness.events.count("preview") == 1


def test_render_includes_incomplete_items_without_hidden_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=2)
    harness = FakeBatchHarness(
        monkeypatch, review, statuses=("applied", "recovery_required")
    )
    outcome = harness.run(make_plan(review))
    text = execution.render_batch_execution_outcome(outcome)
    assert "A partial batch does not make" in text
    assert "Do not blindly replay" in text
    assert "student_01_question_1" not in text
    assert "Sample 1 Student" in text


def test_invalid_confirmation_rejected_before_any_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=1)
    harness = FakeBatchHarness(monkeypatch, review)
    with pytest.raises(execution.BatchEligibilityExecutionError):
        harness.run(make_plan(review), confirmed=cast(bool, "APPLY"))
    assert not harness.events


def test_wrong_receipt_or_action_id_requires_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=2)
    harness = FakeBatchHarness(monkeypatch, review, failing_step="wrong_action")
    outcome = harness.run(make_plan(review))
    assert outcome.stopped
    assert outcome.counts == (("not_attempted", 1), ("recovery_required", 1))
    assert harness.events.count("apply") == 1


def test_unqualified_policy_blocks_before_any_item_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=2)
    harness = FakeBatchHarness(monkeypatch, review)
    harness.dependencies.policies = ()
    outcome = harness.run(make_plan(review))
    assert outcome.stopped
    assert outcome.counts == (("not_attempted", 2),)
    assert "apply" not in harness.events


def test_changed_actor_fingerprint_blocks_before_any_item_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=2)
    harness = FakeBatchHarness(monkeypatch, review)
    monkeypatch.setattr(
        execution,
        "bind_reviewed_actor",
        lambda *a, **kw: replace(ACTOR, profile_sha256="f" * 64),
    )
    outcome = harness.run(make_plan(review))
    assert outcome.stopped
    assert outcome.counts == (("not_attempted", 2),)
    assert "apply" not in harness.events
