"""#124 D1: single-confirmation coordinator, injected #122 boundaries only."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import pytest

from meridian.assessment_setup_composite import PreparedAssessmentSetupComposite
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.teacher_action_contract import TeacherActionResult
from meridian.teacher_action_guided import PreparedGuidedAction


@dataclass
class Harness:
    kind: str = "create_and_link"
    grade_status: str = "applied"
    membership_status: str = "applied"
    fresh: bool = True
    interim: bool = True
    final: bool = True
    fail: str | None = None
    bad_scope: bool = False
    logs: list[str] | None = None

    def __post_init__(self) -> None:
        self.logs = []

    def build(self) -> PreparedAssessmentSetupComposite:
        logs = self.logs
        assert logs is not None
        preview = cast(
            AssessmentSetupPreview,
            SimpleNamespace(
                kind=self.kind,
                class_id="english12",
                school_year="2026-2027",
                grade_item_id="gi_scene",
                marking_period_id="mp1",
                actor_attribution=None if self.kind == "already_ready" else "teacher",
                needs_confirmation=self.kind != "already_ready",
                review_sha256="a" * 64,
            ),
        )

        def fresh() -> AssessmentSetupPreview:
            logs.append("fresh")
            if self.fail == "fresh":
                raise RuntimeError("no canonical read")
            if not self.fresh:
                return cast(
                    AssessmentSetupPreview,
                    SimpleNamespace(review_sha256="f" * 64),
                )
            return preview

        def interim() -> bool:
            logs.append("interim")
            if self.fail == "interim":
                raise RuntimeError("interim canonical failure")
            return self.interim

        def final() -> bool:
            logs.append("final")
            if self.fail == "final":
                raise RuntimeError("final canonical failure")
            return self.final

        def action(kind: str, status: str) -> PreparedGuidedAction:
            scope = SimpleNamespace(
                class_id="other" if self.bad_scope else "english12",
                grade_item_id="gi_scene",
                school_year="2026-2027",
                academic_period_id="mp1",
            )
            p = SimpleNamespace(
                kind=kind,
                target=SimpleNamespace(family=kind),
                scope=scope,
                actor=SimpleNamespace(actor_id="teacher"),
            )

            def apply(*, confirmed: bool) -> TeacherActionResult:
                assert confirmed
                logs.append("apply:" + kind)
                if self.fail == kind:
                    raise RuntimeError("unknown after possible write")
                return cast(
                    TeacherActionResult,
                    SimpleNamespace(
                        status=status,
                        action_id=("b" if kind == "grade_item" else "c") * 32,
                    ),
                )

            return cast(PreparedGuidedAction, SimpleNamespace(preview=p, apply=apply))

        def membership() -> PreparedGuidedAction:
            logs.append("prepare:membership")
            if self.fail == "prepare":
                raise RuntimeError("cannot make fresh preview")
            return action("grade_item_membership", self.membership_status)

        return PreparedAssessmentSetupComposite(
            preview=preview,
            fresh_review=fresh,
            after_grade_read=interim,
            verify_ready=final,
            grade_item_action=(
                action("grade_item", self.grade_status)
                if self.kind == "create_and_link"
                else None
            ),
            membership_factory=membership if self.kind != "already_ready" else None,
        )


def test_cancel_is_zero_callbacks_and_does_not_consume_preview() -> None:
    h = Harness()
    runner = h.build()
    assert runner.apply(confirmation="CANCEL").state == "cancelled"
    assert h.logs == []
    assert runner.apply(confirmation="APPLY").state == "ready"


def test_new_grade_item_one_apply_two_domain_actions_and_final_read() -> None:
    h = Harness()
    result = h.build().apply(confirmation="APPLY")
    assert result.ready and result.state == "ready"
    assert result.action_ids == ("b" * 32, "c" * 32)
    assert h.logs == [
        "fresh",
        "apply:grade_item",
        "interim",
        "prepare:membership",
        "apply:grade_item_membership",
        "final",
    ]


def test_existing_grade_item_requires_only_membership_action() -> None:
    h = Harness(kind="use_existing")
    result = h.build().apply(confirmation="APPLY")
    assert result.ready
    assert result.grade_item_result is None
    assert result.action_ids == ("c" * 32,)
    assert "apply:grade_item" not in (h.logs or [])


def test_already_ready_never_opens_write_actions() -> None:
    h = Harness(kind="already_ready")
    result = h.build().apply(confirmation="APPLY")
    assert result.state == "already_ready"
    assert h.logs == ["fresh", "final"]


def test_already_ready_requires_canonical_verification() -> None:
    h = Harness(kind="already_ready", final=False)
    assert h.build().apply(confirmation="APPLY").state == "current_unverified"


def test_changed_review_fences_off_all_actions() -> None:
    h = Harness(fresh=False)
    assert h.build().apply(confirmation="APPLY").reason == "review_changed"
    assert h.logs == ["fresh"]


def test_unavailable_source_read_blocks_before_write() -> None:
    h = Harness(fail="fresh")
    assert h.build().apply(confirmation="APPLY").state == "blocked_before_write"
    assert h.logs == ["fresh"]


@pytest.mark.parametrize(
    "status", ["written_not_current", "conflict_requires_review", "recovery_required"]
)
def test_incomplete_grade_action_never_starts_membership(status: str) -> None:
    h = Harness(grade_status=status)
    result = h.build().apply(confirmation="APPLY")
    assert result.state == "grade_item_incomplete"
    assert result.membership_result is None
    assert h.logs == ["fresh", "apply:grade_item"]


def test_exception_during_grade_action_does_not_attempt_replay() -> None:
    h = Harness(fail="grade_item")
    result = h.build().apply(confirmation="APPLY")
    assert result.reason == "grade_action_unknown"
    assert result.membership_result is None


@pytest.mark.parametrize("fault", ["interim", "prepare"])
def test_intermediate_failure_never_applies_membership(fault: str) -> None:
    h = Harness(fail=fault)
    result = h.build().apply(confirmation="APPLY")
    assert not result.ready
    assert "apply:grade_item_membership" not in (h.logs or [])


def test_intermediate_stale_basis_fails_closed() -> None:
    h = Harness(interim=False)
    result = h.build().apply(confirmation="APPLY")
    assert result.state == "conflict_requires_review"
    assert result.grade_item_result is not None


def test_wrong_grade_or_membership_scope_cannot_write() -> None:
    h = Harness(bad_scope=True)
    assert h.build().apply(confirmation="APPLY").reason == "grade_action_mismatch"
    h2 = Harness(kind="use_existing", bad_scope=True)
    result = h2.build().apply(confirmation="APPLY")
    assert result.reason == "membership_action_mismatch"
    assert "apply:grade_item_membership" not in (h2.logs or [])


@pytest.mark.parametrize("status", ["written_not_current", "recovery_required"])
def test_incomplete_membership_action_preserves_first_stage_receipt(
    status: str,
) -> None:
    h = Harness(membership_status=status)
    result = h.build().apply(confirmation="APPLY")
    assert result.state == "membership_incomplete"
    assert result.grade_item_result is not None
    assert result.membership_result is not None
    assert result.action_ids == ("b" * 32, "c" * 32)


def test_unknown_membership_exception_is_not_reported_ready() -> None:
    h = Harness(fail="grade_item_membership")
    result = h.build().apply(confirmation="APPLY")
    assert result.state == "membership_incomplete"
    assert result.reason == "membership_action_unknown"


@pytest.mark.parametrize("final,fail", [(False, None), (True, "final")])
def test_canonical_final_failure_never_claims_ready(
    final: bool, fail: str | None
) -> None:
    h = Harness(final=final, fail=fail)
    result = h.build().apply(confirmation="APPLY")
    assert result.state == "current_unverified"
    assert result.membership_result is not None


def test_one_shot_prevents_in_process_duplicate_execution() -> None:
    h = Harness()
    runner = h.build()
    assert runner.apply(confirmation="APPLY").ready
    before = list(h.logs or [])
    assert runner.apply(confirmation="APPLY").reason == "same_preview_already_attempted"
    assert h.logs == before


def test_no_new_authoring_or_receipt_writer_in_module() -> None:
    from pathlib import Path

    s = (
        Path(__file__).resolve().parents[1]
        / "meridian"
        / "assessment_setup_composite.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "commit_grade_item",
        "commit_membership",
        "write_grade_item_revision",
        "write_grade_item_membership",
        "TeacherActionReceiptStore(",
        "input(",
        "verify_publication_manifest(",
    ):
        assert forbidden not in s
