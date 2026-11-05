"""#124 E2E: explicit exact-selection-only recovery through #122."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian import assessment_setup_exact_resume as exact
from meridian.assessment_setup_correlation import (
    AssessmentSetupCorrelation,
    create_assessment_setup_correlation,
)
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_restart import AssessmentSetupRestartInspection
from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionResult,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_guided import PreparedGuidedAction, _identity
from meridian.teacher_action_receipts import (
    TeacherActionReceipt,
    TeacherActionReceiptStore,
    TeacherActionRecoveryAssessment,
)

SHA = "a" * 64


def setup_preview(kind: str = "create_and_link") -> AssessmentSetupPreview:
    return AssessmentSetupPreview(
        kind=cast(Any, kind),
        review_sha256=SHA,
        work=ModuleWorkRef("scoreform", "english12", "scene"),
        class_id="english12",
        school_year="2026-2027",
        registration_revision=2,
        registration_lifecycle="active",
        assessment_title="Scene",
        producer_label="ScoreForm",
        publication_label="Published results",
        publication_id="pub_" + "b" * 32,
        grade_item_id="gi_scene",
        grade_item_title="Scene Grade",
        grade_item_purpose="standards_proficiency",
        selected_grade_item_revision=None,
        marking_period_id="mp1",
        marking_period_label="MP1",
        calendar_revision=3,
        actor_attribution="teacher",
        rationale=None,
        operations=(),
        weighting_message="Not configured",
    )


def saved_actor() -> TeacherActionActor:
    return TeacherActionActor("teacher", SHA, "saved")


def original_action(root: Path, family: str) -> PreparedGuidedAction:
    a = saved_actor()
    target = TeacherActionTarget(
        family=cast(Any, family),
        identity_sha256="f" * 64,
        revision=1,
        candidate_sha256="d" * 64,
        expected_current_revision=None,
        expected_current_sha256=None,
    )
    scope = TeacherActionScope(
        workspace_sha256=_identity("workspace", str(root.resolve())),
        class_id="english12",
        grade_item_id="gi_scene",
        school_year="2026-2027" if family == "grade_item_membership" else None,
        academic_period_id="mp1" if family == "grade_item_membership" else None,
        calendar_sha256="c" * 64 if family == "grade_item_membership" else None,
        work_identity_sha256=(
            _identity("work", "english12", "scoreform", "scene")
            if family == "grade_item_membership"
            else None
        ),
    )
    p = TeacherActionPreview(
        action_id=("b" if family == "grade_item" else "c") * 32,
        kind=cast(Any, family),
        scope=scope,
        actor=a,
        target=target,
        basis=(TeacherActionBasis("context", SHA, SHA),),
        reviewed_decision_sha256=SHA,
    )
    store = TeacherActionReceiptStore(root, "english12")
    return PreparedGuidedAction(
        preview=p,
        port=cast(Any, SimpleNamespace(observe=lambda _: None)),
        store=store,
    )


def original_record(
    root: Path, plan: AssessmentSetupPreview, action: PreparedGuidedAction
) -> AssessmentSetupCorrelation:
    base = create_assessment_setup_correlation(root, plan, saved_actor())
    if action.preview.kind == "grade_item":
        return replace(
            base,
            grade_action_id=action.preview.action_id,
            grade_target_sha256=action.preview.target.candidate_sha256,
        )
    return replace(
        base,
        membership_action_id=action.preview.action_id,
        membership_target_sha256=action.preview.target.candidate_sha256,
    )


def restart(
    record: AssessmentSetupCorrelation, family: str, state: str
) -> AssessmentSetupRestartInspection:
    return AssessmentSetupRestartInspection(
        disposition=cast(Any, state),
        reason="fixture",
        intent_sha256=record.intent_sha256,
        grade_action_id=record.grade_action_id,
        membership_action_id=record.membership_action_id,
        canonical_state=(
            "grade_item_written_not_selected"
            if state == "original_grade_action_pending"
            else "membership_written_not_selected"
            if state == "original_membership_action_pending"
            else "grade_item_selected_link_missing"
            if state == "original_membership_action_pending_after_grade"
            else "ready_verified"
        ),
    )


def successful(action: PreparedGuidedAction) -> TeacherActionResult:
    p = action.preview
    record = TeacherActionRecord(
        p.kind,
        p.target.identity_sha256,
        p.target.revision,
        p.target.candidate_sha256,
        "existing",
    )
    return TeacherActionResult(
        action_id=p.action_id,
        intent_sha256=p.intent_sha256,
        target=p.target,
        status="applied",
        persisted=(record,),
        current_state="matches",
        current_record=record,
        selection_disposition="created",
    )


class Scenario:
    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        family: str = "grade_item",
    ) -> None:
        self.root = tmp_path
        self.family = family
        self.plan = setup_preview(
            "use_existing" if family == "grade_item_membership" else "create_and_link"
        )
        self.action = original_action(tmp_path, family)
        self.record = original_record(tmp_path, self.plan, self.action)
        self.events: list[str] = []
        self.pending = (
            "original_grade_action_pending"
            if family == "grade_item"
            else "original_membership_action_pending"
        )
        self.inspections = [
            restart(self.record, family, self.pending),
            restart(self.record, family, self.pending),
        ]
        after = (
            AssessmentSetupRestartInspection(
                "original_membership_action_pending",
                "fixture",
                self.record.intent_sha256,
                self.record.grade_action_id,
                self.record.membership_action_id,
                "grade_item_selected_link_missing",
            )
            if family == "grade_item"
            else restart(self.record, family, "ready_verified")
        )
        self.inspections.append(after)
        self.eligible = True
        self.receipt_generation = 1
        self.result: TeacherActionResult = successful(self.action)
        monkeypatch.setattr(
            AssessmentSetupCorrelationStore, "load", lambda _self, _id: self.record
        )

        def stored(_self: TeacherActionReceiptStore, _id: str) -> TeacherActionReceipt:
            one = object.__new__(TeacherActionReceipt)
            object.__setattr__(one, "preview", self.action.preview)
            object.__setattr__(one, "generation", 1)
            return one

        monkeypatch.setattr(TeacherActionReceiptStore, "load", stored)

        def inspect(*args: object) -> AssessmentSetupRestartInspection:
            self.events.append("inspect")
            return self.inspections.pop(0)

        monkeypatch.setattr(exact, "inspect_stored_assessment_setup_restart", inspect)

        def assess(*args: object) -> TeacherActionRecoveryAssessment:
            self.events.append("assess")
            return TeacherActionRecoveryAssessment(
                "written_not_current" if self.eligible else "recovery_required",
                "eligible_to_resume" if self.eligible else "target_absent",
                self.eligible,
                self.receipt_generation,
                self.eligible,
            )

        monkeypatch.setattr(exact, "assess_teacher_action_recovery", assess)

        def resume(
            _self: PreparedGuidedAction, *, confirmed: bool
        ) -> TeacherActionResult:
            self.events.append("resume")
            assert confirmed
            return self.result

        monkeypatch.setattr(PreparedGuidedAction, "resume", resume)

    def call(
        self, confirmation: str = "RESUME"
    ) -> exact.AssessmentSetupExactResumeResult:
        return exact.resume_original_assessment_setup_selection(
            self.root,
            self.plan,
            saved_actor(),
            original_action=self.action,
            confirmation=confirmation,
        )


@pytest.mark.parametrize(
    "family,expected",
    [
        ("grade_item", "original_grade_selected"),
        ("grade_item_membership", "ready_verified"),
    ],
)
def test_exact_original_resume_requires_independent_postcondition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    expected: str,
) -> None:
    s = Scenario(tmp_path, monkeypatch, family)
    result = s.call()
    assert result.disposition == expected
    assert result.action_result == s.result
    assert s.events == ["inspect", "assess", "inspect", "resume", "inspect"]
    assert not result.may_resume_automatically
    assert not result.may_author_immutable_revision


def test_cancel_performs_zero_reads_and_zero_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = Scenario(tmp_path, monkeypatch)
    assert s.call("CANCEL").disposition == "cancelled"
    assert s.events == []


@pytest.mark.parametrize(
    "error",
    [
        "wrong_action_id",
        "wrong_target",
        "wrong_profile",
        "wrong_family",
        "wrong_store",
        "wrong_workspace",
        "wrong_review",
        "missing_record",
        "wrong_restart",
        "wrong_canonical",
        "not_eligible",
        "generation_drift",
        "moving_restart",
        "post_not_ready",
    ],
)
def test_conflicting_or_unproven_resume_stops_or_remains_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: str,
) -> None:
    s = Scenario(tmp_path, monkeypatch)
    if error == "wrong_action_id":
        s.record = replace(s.record, grade_action_id="9" * 32)
    elif error == "wrong_target":
        s.record = replace(s.record, grade_target_sha256="9" * 64)
    elif error == "wrong_profile":
        s.record = replace(s.record, actor_profile_sha256="9" * 64)
    elif error == "wrong_family":
        s.action = original_action(tmp_path, "grade_item_membership")
    elif error == "wrong_store":
        s.action = replace(
            s.action, store=TeacherActionReceiptStore(tmp_path, "otherclass")
        )
    elif error == "wrong_workspace":
        s.action = replace(
            s.action, store=TeacherActionReceiptStore(tmp_path / "wrong", "english12")
        )
    elif error == "wrong_review":
        s.plan = replace(s.plan, review_sha256="9" * 64)
    elif error == "missing_record":
        monkeypatch.setattr(AssessmentSetupCorrelationStore, "load", lambda *_: None)
    elif error == "wrong_restart":
        s.inspections[0] = replace(s.inspections[0], disposition="requires_review")
    elif error == "wrong_canonical":
        s.inspections[0] = replace(
            s.inspections[0], canonical_state="grade_item_selected_link_missing"
        )
    elif error == "not_eligible":
        s.eligible = False
    elif error == "generation_drift":
        s.receipt_generation = 7
    elif error == "moving_restart":
        s.inspections[1] = replace(s.inspections[1], reason="changed")
    else:
        s.inspections[2] = replace(s.inspections[2], disposition="requires_review")
    result = s.call()
    if error == "post_not_ready":
        assert result.disposition == "current_unverified"
        assert s.events.count("resume") == 1
    else:
        assert result.disposition == "requires_review"
        assert "resume" not in s.events


def test_resume_exception_never_claims_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = Scenario(tmp_path, monkeypatch)

    def broken(_self: PreparedGuidedAction, *, confirmed: bool) -> TeacherActionResult:
        raise RuntimeError("uncertain CAS selection")

    monkeypatch.setattr(PreparedGuidedAction, "resume", broken)
    assert s.call().disposition == "requires_review"


def test_122_non_success_cannot_be_reported_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = Scenario(tmp_path, monkeypatch)
    s.result = TeacherActionResult(
        action_id=s.action.preview.action_id,
        intent_sha256=s.action.preview.intent_sha256,
        target=s.action.preview.target,
        status="blocked_before_write",
        persisted=(),
        current_state="not_checked",
        current_record=None,
        selection_disposition="not_attempted",
        reason_code="preflight_stale",
    )
    result = s.call()
    assert result.disposition == "requires_review"
    assert not result.ready


def test_no_immutable_authoring_or_fresh_action_preparation_in_resume_module() -> None:
    source = Path(exact.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "commit_new_grade_item(",
        "commit_membership_link(",
        "prepare_grade_item_action(",
        "prepare_membership_action(",
        ".apply(confirmed=True)",
        "persist_exact(",
        "select_exact(",
    ):
        assert forbidden not in source
    assert "PreparedGuidedAction.resume(original_action, confirmed=True)" in source


@pytest.mark.parametrize("mismatch", ["intent", "target", "action_id"])
def test_mismatched_122_success_result_never_reports_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    s = Scenario(tmp_path, monkeypatch)
    if mismatch == "intent":
        s.result = replace(s.result, intent_sha256="9" * 64)
    elif mismatch == "target":
        other_target = replace(s.action.preview.target, candidate_sha256="9" * 64)
        other_record = replace(s.result.current_record, sha256="9" * 64)
        s.result = replace(
            s.result,
            target=other_target,
            persisted=(other_record,),
            current_record=other_record,
        )
    else:
        s.result = replace(s.result, action_id="9" * 32)
    result = s.call()
    assert result.disposition == "requires_review"
    assert not result.ready
