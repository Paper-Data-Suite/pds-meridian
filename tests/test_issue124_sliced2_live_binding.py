"""#124 D2: live canonical binder, injected read/prepare ports, no producer reads."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.assessment_setup_live as live
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.teacher_action_contract import TeacherActionActor

WORK = ModuleWorkRef("scoreform", "english12", "scene")
ROOT = Path("/synthetic")


def proposal(kind: str) -> AssessmentSetupPreview:
    return AssessmentSetupPreview(
        kind=cast(Any, kind),
        work=WORK,
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
        selected_grade_item_revision=4 if kind != "create_and_link" else None,
        marking_period_id="mp1",
        marking_period_label="Marking Period 1",
        calendar_revision=3,
        actor_attribution=None if kind == "already_ready" else "teacher_test",
        rationale=None,
        operations=(),
        weighting_message="Not configured",
        review_sha256="a" * 64,
    )


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
        self.kind = kind
        self.preview = proposal(kind)
        self.log: list[str] = []
        self.status = (
            "needs_create"
            if kind == "create_and_link"
            else ("ready" if kind == "already_ready" else "choose_existing")
        )
        self.grade_selected = kind != "create_and_link"
        self.member_selected = kind == "already_ready"
        self.fail: str | None = None
        self.mismatch: str | None = None
        self.dependencies = GuidedGradeItemBridgeDependencies()
        self.actor = (
            None
            if kind == "already_ready"
            else TeacherActionActor("teacher_test", "a" * 64, "temporary")
        )
        root = Path.cwd()
        self.root = root

        def fresh(*args: Any, **kwargs: Any) -> AssessmentSetupPreview:
            self.log.append("fresh")
            if self.mismatch == "review":
                return proposal("already_ready")
            return self.preview

        def choices(*args: Any, **kwargs: Any) -> Any:
            self.log.append("catalog")
            c = self.preview
            return SimpleNamespace(
                items=(
                    SimpleNamespace(
                        candidate=SimpleNamespace(
                            work=WORK,
                            school_year=c.school_year,
                            registration_revision=c.registration_revision,
                            lifecycle=c.registration_lifecycle,
                            title=c.assessment_title,
                            period_id=c.marking_period_id,
                            calendar_revision=c.calendar_revision,
                            publication_id=(
                                c.publication_id
                                if self.mismatch != "publication"
                                else None
                            ),
                            setup_state="ready"
                            if self.member_selected
                            else self.status,
                        ),
                        publication_state="current_results_verified",
                    ),
                )
            )

        def bridge(*args: Any, **kwargs: Any) -> Any:
            self.log.append("bridge")
            return SimpleNamespace(
                work=WORK,
                work_title="Scene Check",
                registration_revision=2,
                existing_grade_items=(
                    SimpleNamespace(
                        grade_item_id="gi_scene",
                        title="Scene Grade",
                        purpose="standards_proficiency",
                        selected_revision=(
                            1
                            if self.grade_selected and kind == "create_and_link"
                            else 4
                        ),
                    ),
                )
                if self.grade_selected
                else (),
                periods=(
                    SimpleNamespace(
                        period_type="marking_period",
                        display_label="Marking Period 1",
                        assignment=SimpleNamespace(
                            period=SimpleNamespace(
                                school_year="2026-2027", period_id="mp1"
                            ),
                            calendar_revision=3,
                        ),
                    ),
                ),
                existing_grade_item_ids=(
                    () if not self.grade_selected else ("gi_scene",)
                ),
            )

        def new_grade(*args: Any, **kwargs: Any) -> Any:
            self.log.append("preview_grade")
            return SimpleNamespace(
                actor_id="teacher_test",
                candidate=SimpleNamespace(
                    class_id="english12",
                    grade_item_id="gi_scene",
                    title="Scene Grade",
                    purpose="standards_proficiency",
                    status="active",
                    grade_item_revision=1,
                ),
            )

        def membership(*args: Any, **kwargs: Any) -> Any:
            self.log.append("preview_membership")
            _root, context, grade, period = args[:4]
            return SimpleNamespace(
                candidate=SimpleNamespace(
                    class_id="english12",
                    grade_item_id="gi_scene",
                    grade_item_revision=grade.selected_revision,
                    work_reference=SimpleNamespace(work=WORK, registration_revision=2),
                    decision="included",
                    actor_id="teacher_test",
                    academic_period=period.assignment,
                )
            )

        def grade_action(*args: Any, **kwargs: Any) -> Any:
            self.log.append("prepare_grade_action")
            return self.action("grade_item")

        def member_action(*args: Any, **kwargs: Any) -> Any:
            self.log.append("prepare_member_action")
            return self.action("grade_item_membership")

        monkeypatch.setattr(live, "load_assessment_setup_preview", fresh)
        monkeypatch.setattr(live, "load_named_assessment_choices", choices)
        monkeypatch.setattr(live, "load_guided_grade_item_bridge_context", bridge)
        monkeypatch.setattr(live, "preview_new_grade_item", new_grade)
        monkeypatch.setattr(live, "preview_membership_link", membership)
        monkeypatch.setattr(live, "prepare_grade_item_action", grade_action)
        monkeypatch.setattr(live, "prepare_membership_action", member_action)

    def action(self, kind: str) -> Any:
        def apply(*, confirmed: bool) -> Any:
            assert confirmed
            self.log.append("apply:" + kind)
            if self.fail == kind:
                return SimpleNamespace(status="recovery_required", action_id="a" * 32)
            if kind == "grade_item":
                self.grade_selected = True
            else:
                self.member_selected = True
            return SimpleNamespace(status="applied", action_id="b" * 32)

        return SimpleNamespace(
            preview=SimpleNamespace(
                kind=kind,
                target=SimpleNamespace(family=kind),
                scope=SimpleNamespace(
                    class_id="english12",
                    grade_item_id="gi_scene",
                    school_year="2026-2027",
                    academic_period_id="mp1",
                ),
                actor=SimpleNamespace(actor_id="teacher_test"),
            ),
            apply=apply,
        )

    def bind(self) -> Any:
        return live.bind_live_assessment_setup(
            self.root, self.preview, actor=self.actor, dependencies=self.dependencies
        )


def test_create_and_link_prepares_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = Harness(monkeypatch, "create_and_link")
    bound = h.bind()
    assert h.log == ["fresh", "bridge", "preview_grade", "prepare_grade_action"]
    assert bound.apply(confirmation="CANCEL").state == "cancelled"
    assert h.log == ["fresh", "bridge", "preview_grade", "prepare_grade_action"]


def test_create_and_link_reloads_live_sources_between_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = Harness(monkeypatch, "create_and_link")
    result = h.bind().apply(confirmation="APPLY")
    assert result.ready and result.state == "ready"
    assert h.log.count("catalog") >= 3
    assert h.log.index("apply:grade_item") < h.log.index("preview_membership")
    assert h.log.index("preview_membership") < h.log.index(
        "apply:grade_item_membership"
    )


def test_use_existing_never_authors_grade_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = Harness(monkeypatch, "use_existing")
    result = h.bind().apply(confirmation="APPLY")
    assert result.ready
    assert "preview_grade" not in h.log
    assert "apply:grade_item" not in h.log


def test_already_ready_no_action_or_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    h = Harness(monkeypatch, "already_ready")
    result = h.bind().apply(confirmation="APPLY")
    assert result.state == "already_ready"
    assert "preview_grade" not in h.log
    assert "preview_membership" not in h.log


@pytest.mark.parametrize("kind", ["create_and_link", "use_existing"])
def test_changed_review_aborts_before_write(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    h = Harness(monkeypatch, kind)
    bound = h.bind()
    h.mismatch = "review"
    result = bound.apply(confirmation="APPLY")
    assert result.state == "conflict_requires_review"
    assert not any(s.startswith("apply:") for s in h.log)


def test_publication_drift_after_grade_blocks_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = Harness(monkeypatch, "create_and_link")
    bound = h.bind()
    h.mismatch = "publication"
    result = bound.apply(confirmation="APPLY")
    assert not result.ready
    assert "apply:grade_item_membership" not in h.log


def test_partial_grade_result_never_prepares_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = Harness(monkeypatch, "create_and_link")
    bound = h.bind()
    h.fail = "grade_item"
    result = bound.apply(confirmation="APPLY")
    assert result.state == "grade_item_incomplete"
    assert "preview_membership" not in h.log


def test_failed_membership_cannot_report_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    h = Harness(monkeypatch, "use_existing")
    bound = h.bind()
    h.fail = "grade_item_membership"
    result = bound.apply(confirmation="APPLY")
    assert result.state == "membership_incomplete"


def test_wrong_actor_rejected_before_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    h = Harness(monkeypatch, "use_existing")
    with pytest.raises(live.AssessmentSetupLiveError, match="actor"):
        live.bind_live_assessment_setup(
            h.root, h.preview, actor=None, dependencies=h.dependencies
        )


def test_exact_canonical_final_check_prevents_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = Harness(monkeypatch, "use_existing")
    bound = h.bind()
    h.mismatch = "publication"
    result = bound.apply(confirmation="APPLY")
    assert result.state in ("conflict_requires_review", "current_unverified")


def test_source_never_opens_producer_evidence_or_creates_own_receipt() -> None:
    path = Path(__file__).resolve().parents[1] / "meridian" / "assessment_setup_live.py"
    source = path.read_text(encoding="utf-8")
    for forbidden in (
        "verify_publication_manifest(",
        "write_publication_record(",
        "TeacherActionReceiptStore(",
        "commit_new_grade_item(",
        "commit_membership_link(",
    ):
        assert forbidden not in source
