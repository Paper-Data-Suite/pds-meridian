"""#124 E1: read-only recovery inventory and restart classification."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_recovery import (
    AssessmentSetupRecoveryReaders,
    inspect_assessment_setup_recovery,
)
from meridian.teacher_action_guided import _identity

WORK = ModuleWorkRef("scoreform", "english12", "scene")
YEAR = "2026-2027"


def proposed(kind: str = "create_and_link") -> AssessmentSetupPreview:
    return AssessmentSetupPreview(
        kind=cast(Any, kind),
        work=WORK,
        class_id="english12",
        school_year=YEAR,
        registration_revision=2,
        registration_lifecycle="active",
        assessment_title="Scene",
        producer_label="ScoreForm",
        publication_label="Published results",
        publication_id="pub_" + "a" * 32,
        grade_item_id="gi_scene",
        grade_item_title="Scene Grade",
        grade_item_purpose="standards_proficiency",
        selected_grade_item_revision=4 if kind != "create_and_link" else None,
        marking_period_id="mp1",
        marking_period_label="MP1",
        calendar_revision=3,
        actor_attribution="teacher" if kind != "already_ready" else None,
        rationale=None,
        operations=(),
        weighting_message="Not configured",
        review_sha256="f" * 64,
    )


def membership(
    *, selected: bool = True, decision: str = "included", period: str = "mp1"
) -> Any:
    return SimpleNamespace(
        work=WORK,
        selected_revision=1 if selected else None,
        decision=decision if selected else None,
        grade_item_basis_state="matches_current_grade_item",
        registration_revision=2,
        academic_period_school_year=YEAR,
        academic_period_id=period,
        academic_period_calendar_revision=3,
    )


def row(
    *,
    selected: int | None = 1,
    members: tuple[Any, ...] = (),
    purpose: str = "standards_proficiency",
    status: str = "active",
) -> Any:
    return SimpleNamespace(
        grade_item_id="gi_scene",
        selected_revision=selected,
        status=status if selected is not None else None,
        purpose=purpose if selected is not None else None,
        title="Scene Grade" if selected is not None else None,
        memberships=members,
    )


class Case:
    def __init__(self, tmp_path: Path, kind: str = "create_and_link") -> None:
        self.root = tmp_path
        self.preview = proposed(kind)
        self.rows: tuple[Any, ...] = ()
        self.receipts: tuple[Any, ...] = ()
        self.registration_revision = 2
        self.catalog_state = "needs_create"
        self.pub_id: str | None = self.preview.publication_id
        self.read_failure: str | None = None
        self.calls: list[str] = []

    def readers(self) -> AssessmentSetupRecoveryReaders:
        def named(*args: Any, **kwargs: Any) -> Any:
            self.calls.append("named")
            if self.read_failure == "named":
                raise OSError("read failed")
            assert args[0] == self.root
            assert kwargs == {
                "class_id": "english12",
                "school_year": YEAR,
                "period_id": "mp1",
            }
            c = SimpleNamespace(
                work=WORK,
                registration_revision=self.registration_revision,
                lifecycle="active",
                title="Scene",
                calendar_revision=3,
                period_id="mp1",
                publication_id=self.pub_id,
                setup_state=self.catalog_state,
                ready_grade_item_id="gi_scene"
                if self.catalog_state == "ready"
                else None,
            )
            return SimpleNamespace(
                class_id="english12",
                school_year=YEAR,
                period_id="mp1",
                items=(
                    SimpleNamespace(
                        candidate=c,
                        publication_state="current_results_verified",
                    ),
                ),
            )

        def grades(root: Path, class_id: str) -> Any:
            self.calls.append("grades")
            if self.read_failure == "grades":
                raise OSError("read failed")
            assert root == self.root and class_id == "english12"
            return SimpleNamespace(class_id=class_id, items=self.rows)

        def receipts(root: Path, class_id: str) -> Any:
            self.calls.append("receipts")
            if self.read_failure == "receipts":
                raise OSError("corrupt receipt")
            assert root == self.root and class_id == "english12"
            return self.receipts

        return AssessmentSetupRecoveryReaders(
            named=named, grades=grades, receipts=receipts
        )

    def inspect(self) -> Any:
        return inspect_assessment_setup_recovery(
            self.root, self.preview, readers=self.readers()
        )

    def receipt(self, kind: str, *, actor: str = "teacher", period: str = "mp1") -> Any:
        action_id = ("a" if kind == "grade_item" else "b") * 32
        return SimpleNamespace(
            preview=SimpleNamespace(
                kind=kind,
                action_id=action_id,
                actor=SimpleNamespace(actor_id=actor),
                target=SimpleNamespace(family=kind, revision=1),
                scope=SimpleNamespace(
                    class_id="english12",
                    grade_item_id="gi_scene",
                    workspace_sha256=_identity("workspace", str(self.root)),
                    school_year=YEAR if kind == "grade_item_membership" else None,
                    academic_period_id=period
                    if kind == "grade_item_membership"
                    else None,
                    work_identity_sha256=_identity(
                        "work", "english12", "scoreform", "scene"
                    )
                    if kind == "grade_item_membership"
                    else None,
                ),
            )
        )


def test_pristine_is_observation_not_permission(tmp_path: Path) -> None:
    c = Case(tmp_path)
    x = c.inspect()
    assert x.state == "pristine"
    assert not x.can_resume_without_review and not x.ready
    assert c.calls == ["named", "grades", "receipts"]
    assert list(tmp_path.iterdir()) == []


def test_grade_saved_without_selection_blocks_new_identity(tmp_path: Path) -> None:
    c = Case(tmp_path)
    c.rows = (row(selected=None),)
    assert c.inspect().state == "grade_item_written_not_selected"


def test_grade_current_without_membership_is_partial(tmp_path: Path) -> None:
    c = Case(tmp_path)
    c.rows = (row(),)
    assert c.inspect().state == "grade_item_selected_link_missing"


def test_unselected_membership_is_not_ready(tmp_path: Path) -> None:
    c = Case(tmp_path)
    c.rows = (row(members=(membership(selected=False),)),)
    assert c.inspect().state == "membership_written_not_selected"


def test_exact_canonical_ready_only_when_projection_agrees(tmp_path: Path) -> None:
    c = Case(tmp_path)
    c.rows = (row(members=(membership(),)),)
    c.catalog_state = "ready"
    x = c.inspect()
    assert x.state == "ready_verified" and x.ready
    assert not x.can_resume_without_review


def test_ready_membership_without_catalog_agreement_is_not_ready(
    tmp_path: Path,
) -> None:
    c = Case(tmp_path)
    c.rows = (row(members=(membership(),)),)
    assert c.inspect().reason == "readiness_projection_disagrees"


@pytest.mark.parametrize("problem", ["period", "exclusion", "archived", "purpose"])
def test_wrong_academic_meaning_needs_review(tmp_path: Path, problem: str) -> None:
    c = Case(tmp_path)
    c.rows = (
        row(
            members=(
                membership(
                    period="mp2" if problem == "period" else "mp1",
                    decision="excluded" if problem == "exclusion" else "included",
                ),
            ),
            status="archived" if problem == "archived" else "active",
            purpose="reporting_only"
            if problem == "purpose"
            else "standards_proficiency",
        ),
    )
    assert c.inspect().state == "relationship_needs_review"


@pytest.mark.parametrize("problem", ["registration", "publication"])
def test_source_drift_denies_recovery(tmp_path: Path, problem: str) -> None:
    c = Case(tmp_path)
    if problem == "registration":
        c.registration_revision = 3
    else:
        c.pub_id = None
    assert c.inspect().state == "source_changed"
    assert c.calls == ["named"]


def test_missing_grade_but_ready_catalog_is_not_pristine(tmp_path: Path) -> None:
    c = Case(tmp_path)
    c.catalog_state = "ready"
    assert c.inspect().reason == "catalog_grade_disagrees"


def test_prior_receipt_without_grade_blocks_new_create(tmp_path: Path) -> None:
    c = Case(tmp_path)
    c.receipts = (c.receipt("grade_item"),)
    x = c.inspect()
    assert x.state == "receipts_need_review"
    assert x.grade_action_ids == ("a" * 32,)


def test_receipt_scope_or_actor_change_is_conflict(tmp_path: Path) -> None:
    c = Case(tmp_path)
    c.rows = (row(),)
    c.receipts = (c.receipt("grade_item_membership", period="mp2"),)
    assert c.inspect().reason == "receipt_scope_conflict"
    c.receipts = (c.receipt("grade_item", actor="other"),)
    assert c.inspect().state == "receipts_need_review"


def test_multiple_attempts_never_choose_latest(tmp_path: Path) -> None:
    c = Case(tmp_path)
    second = c.receipt("grade_item")
    second.preview.action_id = "c" * 32
    c.receipts = (c.receipt("grade_item"), second)
    assert c.inspect().reason == "multiple_action_attempts"


@pytest.mark.parametrize("failed", ["named", "grades", "receipts"])
def test_unavailable_read_fails_closed(tmp_path: Path, failed: str) -> None:
    c = Case(tmp_path)
    c.read_failure = failed
    x = c.inspect()
    assert x.state == "inspection_unavailable"
    assert not x.ready


def test_existing_setup_without_grade_is_not_pristine(tmp_path: Path) -> None:
    c = Case(tmp_path, kind="use_existing")
    assert c.inspect().state == "receipts_need_review"


def test_readonly_source_has_no_authoring_or_selection_paths() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "meridian"
        / "assessment_setup_recovery.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "commit_grade_item",
        "commit_membership",
        "prepare_grade_item_action(",
        "prepare_membership_action(",
        "resume_restart_grade_item(",
        "verify_publication_manifest(",
        "input(",
    ):
        assert forbidden not in source
