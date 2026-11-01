"""#124 E2C: durable per-action fencing in a one-confirmation composite."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.assessment_setup_correlated_live as fenced
from meridian.assessment_setup_composite import PreparedAssessmentSetupComposite
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_recovery import AssessmentSetupRecoveryInspection
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import PreparedGuidedAction, _identity


def proposal(kind: str = "create_and_link") -> AssessmentSetupPreview:
    return AssessmentSetupPreview(
        kind=cast(Any, kind),
        work=ModuleWorkRef("scoreform", "english12", "scene"),
        class_id="english12",
        school_year="2026-2027",
        registration_revision=2,
        registration_lifecycle="active",
        assessment_title="Scene Check",
        producer_label="ScoreForm",
        publication_label="Published results",
        publication_id="pub_" + "a" * 32,
        grade_item_id="gi_scene",
        grade_item_title="Scene Grade",
        grade_item_purpose="standards_proficiency",
        selected_grade_item_revision=4 if kind == "use_existing" else None,
        marking_period_id="mp1",
        marking_period_label="MP1",
        calendar_revision=3,
        actor_attribution=None if kind == "already_ready" else "teacher",
        rationale=None,
        operations=(),
        weighting_message="Not configured",
        review_sha256="a" * 64,
    )


class Case:
    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        kind: str = "create_and_link",
    ) -> None:
        self.root = tmp_path
        (tmp_path / "classes" / "english12").mkdir(parents=True)
        self.p = proposal(kind)
        self.kind = kind
        self.grade = kind != "create_and_link"
        self.member = kind == "already_ready"
        self.fail: str | None = None
        self.source_drift = False
        self.log: list[str] = []
        self.actor = (
            None
            if kind == "already_ready"
            else TeacherActionActor("teacher", "a" * 64, "saved")
        )
        self.dependencies = GuidedGradeItemBridgeDependencies()

        def observed(*args: Any, **kwargs: Any) -> AssessmentSetupRecoveryInspection:
            self.log.append("recovery_read")
            if self.source_drift:
                state = "source_changed"
            elif self.member:
                state = "ready_verified"
            elif self.grade:
                state = "grade_item_selected_link_missing"
            else:
                state = "pristine"
            return AssessmentSetupRecoveryInspection(
                state,
                "synthetic",
                self.p.review_sha256,
                self.p.grade_item_id,
                ("b" * 32,) if self.grade and self.kind == "create_and_link" else (),
                ("c" * 32,) if self.member and self.kind != "already_ready" else (),
                (4 if self.kind == "use_existing" else 1) if self.grade else None,
                1 if self.member else None,
            )

        def action(kind_: str) -> PreparedGuidedAction:
            scope = SimpleNamespace(
                workspace_sha256=_identity("workspace", str(tmp_path.resolve())),
                class_id="english12",
                grade_item_id="gi_scene",
                school_year="2026-2027" if kind_ == "grade_item_membership" else None,
                academic_period_id="mp1" if kind_ == "grade_item_membership" else None,
                work_identity_sha256=_identity(
                    "work", "english12", "scoreform", "scene"
                )
                if kind_ == "grade_item_membership"
                else None,
            )
            view = SimpleNamespace(
                kind=kind_,
                action_id=("b" if kind_ == "grade_item" else "c") * 32,
                target=SimpleNamespace(
                    family=kind_, revision=1, candidate_sha256="f" * 64
                ),
                scope=scope,
                actor=self.actor,
            )

            def port(_: Any) -> Any:
                self.log.append("write:" + kind_)
                if self.fail == "source_after_grade" and kind_ == "grade_item":
                    self.source_drift = True
                if self.fail == kind_:
                    return SimpleNamespace(
                        status="recovery_required", action_id=view.action_id
                    )
                if kind_ == "grade_item":
                    self.grade = True
                else:
                    self.member = True
                return SimpleNamespace(status="applied", action_id=view.action_id)

            return PreparedGuidedAction(preview=view, port=port, store=None)

        def binder(*args: Any, **kwargs: Any) -> PreparedAssessmentSetupComposite:
            self.log.append("bind")
            return PreparedAssessmentSetupComposite(
                preview=self.p,
                fresh_review=lambda: self.p,
                after_grade_read=lambda: self.grade,
                verify_ready=lambda: self.member,
                grade_item_action=action("grade_item")
                if kind == "create_and_link"
                else None,
                membership_factory=(lambda: action("grade_item_membership"))
                if kind != "already_ready"
                else None,
            )

        def simulated_122_apply(
            prepared: PreparedGuidedAction, *, confirmed: bool
        ) -> Any:
            if not confirmed:
                return SimpleNamespace(
                    status="cancelled", action_id=prepared.preview.action_id
                )
            correlation = fenced.create_assessment_setup_correlation(
                self.root, self.p, self.actor
            )
            durable = self.store().load(correlation.intent_sha256)
            assert durable is not None
            if prepared.preview.kind == "grade_item":
                assert durable.grade_action_id == prepared.preview.action_id
            else:
                assert durable.membership_action_id == prepared.preview.action_id
            return prepared.port(prepared.preview)

        monkeypatch.setattr(PreparedGuidedAction, "apply", simulated_122_apply)

        monkeypatch.setattr(fenced, "bind_live_assessment_setup", binder)
        monkeypatch.setattr(fenced, "inspect_assessment_setup_recovery", observed)
        monkeypatch.setattr(
            fenced,
            "inspect_assessment_setup_correlation",
            lambda *args: SimpleNamespace(advice="ready_verified"),
        )

    def prepare(self) -> PreparedAssessmentSetupComposite:
        return fenced.bind_correlated_live_assessment_setup(
            self.root, self.p, actor=self.actor, dependencies=self.dependencies
        )

    def store(self) -> AssessmentSetupCorrelationStore:
        return AssessmentSetupCorrelationStore(self.root, "english12")


def test_cancel_has_no_correlation_or_academic_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    runner = c.prepare()
    assert runner.apply(confirmation="CANCEL").state == "cancelled"
    assert c.store().list_records() == ()
    assert "write:grade_item" not in c.log


def test_create_persists_two_bindings_before_each_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    result = c.prepare().apply(confirmation="APPLY")
    assert result.state == "ready"
    (record,) = c.store().list_records()
    assert record.grade_action_id == "b" * 32
    assert record.membership_action_id == "c" * 32
    assert record.stage == "membership_bound"
    assert c.log.count("write:grade_item") == 1
    assert c.log.count("write:grade_item_membership") == 1


def test_existing_grade_item_binds_only_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch, "use_existing")
    assert c.prepare().apply(confirmation="APPLY").state == "ready"
    (record,) = c.store().list_records()
    assert record.grade_action_id is None and record.membership_action_id == "c" * 32
    assert "write:grade_item" not in c.log


def test_grade_failure_preserves_original_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    c.fail = "grade_item"
    result = c.prepare().apply(confirmation="APPLY")
    assert result.state == "grade_item_incomplete"
    (record,) = c.store().list_records()
    assert record.stage == "grade_bound" and record.grade_action_id == "b" * 32
    assert "write:grade_item_membership" not in c.log


def test_membership_failure_preserves_both_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    c.fail = "grade_item_membership"
    result = c.prepare().apply(confirmation="APPLY")
    assert result.state == "membership_incomplete"
    assert c.store().list_records()[0].stage == "membership_bound"
    assert not result.ready


def test_source_drift_blocks_first_academic_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    c.source_drift = True
    result = c.prepare().apply(confirmation="APPLY")
    assert not result.ready
    assert c.store().list_records() == ()
    assert "write:grade_item" not in c.log


def test_restart_does_not_replay_same_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    first = c.prepare().apply(confirmation="APPLY")
    assert first.ready
    second = c.prepare().apply(confirmation="APPLY")
    assert not second.ready
    assert c.log.count("write:grade_item") == 1
    assert c.log.count("write:grade_item_membership") == 1
    assert len(c.store().list_records()) == 1


def test_incomplete_reviewed_record_blocks_new_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    base = fenced.create_assessment_setup_correlation(c.root, c.p, c.actor)
    c.store().create_reviewed(base)
    assert not c.prepare().apply(confirmation="APPLY").ready
    assert "write:grade_item" not in c.log


def test_another_intent_with_same_target_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    old = fenced.create_assessment_setup_correlation(c.root, c.p, c.actor)
    from dataclasses import replace

    c.store().create_reviewed(replace(old, review_sha256="e" * 64))
    assert not c.prepare().apply(confirmation="APPLY").ready
    assert "write:grade_item" not in c.log


def test_temporary_actor_refused_before_correlation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    c.actor = TeacherActionActor("teacher", "a" * 64, "temporary")
    with pytest.raises(fenced.CorrelatedAssessmentSetupError, match="saved"):
        c.prepare()
    assert c.store().list_records() == ()


def test_already_ready_does_not_create_correlation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch, "already_ready")
    assert c.prepare().apply(confirmation="APPLY").ready
    assert c.store().list_records() == ()


def test_final_canonical_failure_must_not_claim_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    monkeypatch.setattr(
        fenced,
        "inspect_assessment_setup_correlation",
        lambda *args: SimpleNamespace(advice="requires_review"),
    )
    result = c.prepare().apply(confirmation="APPLY")
    assert result.state == "current_unverified" and not result.ready
    assert c.store().list_records()[0].stage == "membership_bound"


def test_wrapper_is_genuine_122_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    x = c.prepare()
    assert isinstance(x.grade_item_action, PreparedGuidedAction)
    assert x.grade_item_action is not None
    assert x.grade_item_action.preview.kind == "grade_item"


def test_source_has_no_new_academic_writer() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "meridian"
        / "assessment_setup_correlated_live.py"
    ).read_text(encoding="utf-8")
    for prohibited in (
        "commit_grade_item",
        "commit_membership",
        "persist_exact(",
        "resume_restart_grade_item(",
    ):
        assert prohibited not in source


def test_atomic_storage_rejects_cross_intent_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from meridian.assessment_setup_correlation_storage import (
        AssessmentSetupCorrelationStorageConflict,
    )

    c = Case(tmp_path, monkeypatch)
    old = fenced.create_assessment_setup_correlation(c.root, c.p, c.actor)
    c.store().create_reviewed(old)
    with pytest.raises(AssessmentSetupCorrelationStorageConflict, match="claims"):
        c.store().create_reviewed(replace(old, review_sha256="9" * 64))
    assert c.store().list_records() == (old,)


def test_drift_between_grade_and_membership_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    c.fail = "source_after_grade"
    result = c.prepare().apply(confirmation="APPLY")
    assert result.state == "membership_incomplete"
    assert c.store().list_records()[0].stage == "grade_bound"
    assert "write:grade_item_membership" not in c.log


def test_changed_review_never_creates_correlation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)
    prepared = c.prepare()
    prepared.fresh_review = lambda: proposal("use_existing")
    result = prepared.apply(confirmation="APPLY")
    assert result.state == "conflict_requires_review"
    assert c.store().list_records() == ()
    assert "write:grade_item" not in c.log


def test_stage_cas_failure_prevents_122_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)

    def blocked(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("simulated fsync/CAS failure")

    monkeypatch.setattr(AssessmentSetupCorrelationStore, "advance_exact", blocked)
    result = c.prepare().apply(confirmation="APPLY")
    assert result.state == "grade_item_incomplete"
    assert "write:grade_item" not in c.log
    assert c.store().list_records()[0].stage == "reviewed"


def test_ready_not_claimed_when_stored_correlation_is_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = Case(tmp_path, monkeypatch)

    def invalid(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(advice="requires_review")

    monkeypatch.setattr(fenced, "inspect_assessment_setup_correlation", invalid)
    assert c.prepare().apply(confirmation="APPLY").state == "current_unverified"
