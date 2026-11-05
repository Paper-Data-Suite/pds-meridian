"""#124 E2D: exact read-only durable composite restart reconciliation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_correlation import (
    AssessmentSetupCorrelation,
    bind_correlation_action,
    create_assessment_setup_correlation,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_recovery import AssessmentSetupRecoveryInspection
from meridian.assessment_setup_restart import (
    AssessmentSetupRestartReaders,
    inspect_stored_assessment_setup_restart,
)
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import PreparedGuidedAction, _identity
from meridian.teacher_action_receipts import TeacherActionReceipt

SHA = "a" * 64


def preview(kind: str = "create_and_link") -> AssessmentSetupPreview:
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


def actor(digest: str = SHA) -> TeacherActionActor:
    return TeacherActionActor("teacher", digest, "saved")


def action(root: Path, kind: str) -> PreparedGuidedAction:
    return PreparedGuidedAction(
        preview=cast(
            Any,
            SimpleNamespace(
                kind=kind,
                action_id=("b" if kind == "grade_item" else "c") * 32,
                target=SimpleNamespace(
                    family=kind, candidate_sha256="d" * 64, revision=1
                ),
                scope=SimpleNamespace(
                    class_id="english12",
                    workspace_sha256=_identity("workspace", str(root.resolve())),
                    grade_item_id="gi_scene",
                    school_year="2026-2027"
                    if kind == "grade_item_membership"
                    else None,
                    academic_period_id="mp1"
                    if kind == "grade_item_membership"
                    else None,
                    work_identity_sha256=(
                        _identity("work", "english12", "scoreform", "scene")
                        if kind == "grade_item_membership"
                        else None
                    ),
                ),
                actor=actor(),
            ),
        ),
        port=cast(Any, None),
        store=cast(Any, None),
    )


def receipt(one: PreparedGuidedAction) -> TeacherActionReceipt:
    obj = object.__new__(TeacherActionReceipt)
    object.__setattr__(obj, "preview", one.preview)
    return obj


def recovery(
    name: str,
    grades: tuple[str, ...] = (),
    members: tuple[str, ...] = (),
) -> AssessmentSetupRecoveryInspection:
    return AssessmentSetupRecoveryInspection(
        state=cast(Any, name),
        reason="test",
        review_sha256=SHA,
        grade_item_id="gi_scene",
        grade_action_ids=grades,
        membership_action_ids=members,
        grade_selected_revision=None,
        membership_selected_revision=None,
    )


def setup(
    root: Path,
    *,
    grade: bool = False,
    member: bool = False,
    kind: str = "create_and_link",
) -> tuple[AssessmentSetupCorrelation, tuple[TeacherActionReceipt, ...]]:
    value = create_assessment_setup_correlation(root, preview(kind), actor())
    rs = []
    if grade:
        a = action(root, "grade_item")
        value = bind_correlation_action(value, a, family="grade_item")
        rs.append(receipt(a))
    if member:
        a = action(root, "grade_item_membership")
        value = bind_correlation_action(value, a, family="grade_item_membership")
        rs.append(receipt(a))
    return value, tuple(rs)


def ports(
    records: tuple[AssessmentSetupCorrelation, ...],
    receipts: tuple[TeacherActionReceipt, ...],
    canonical: AssessmentSetupRecoveryInspection,
) -> AssessmentSetupRestartReaders:
    return AssessmentSetupRestartReaders(
        correlations=lambda *_: records,
        receipts=lambda *_: receipts,
        canonical=lambda *args: canonical,
    )


@pytest.mark.parametrize(
    ("stage", "state", "expected"),
    [
        ("reviewed", "pristine", "reviewed_not_started"),
        ("grade", "grade_item_written_not_selected", "original_grade_action_pending"),
        (
            "grade",
            "grade_item_selected_link_missing",
            "original_membership_action_pending",
        ),
        (
            "both",
            "membership_written_not_selected",
            "original_membership_action_pending",
        ),
        ("both", "ready_verified", "ready_verified"),
    ],
)
def test_exact_original_action_advice_is_readonly(
    tmp_path: Path, stage: str, state: str, expected: str
) -> None:
    value, recs = setup(tmp_path, grade=stage != "reviewed", member=stage == "both")
    result = inspect_stored_assessment_setup_restart(
        tmp_path,
        preview(),
        actor(),
        readers=ports(
            (value,),
            recs,
            recovery(
                state,
                ("b" * 32,) if stage != "reviewed" else (),
                ("c" * 32,) if stage == "both" else (),
            ),
        ),
    )
    assert result.disposition == expected
    assert result.intent_sha256 == value.intent_sha256
    assert not result.may_resume_automatically
    assert not result.may_create_new_action
    assert not result.may_select_academic_record


def test_use_existing_requires_only_original_membership(tmp_path: Path) -> None:
    value, recs = setup(tmp_path, kind="use_existing", member=True)
    result = inspect_stored_assessment_setup_restart(
        tmp_path,
        preview("use_existing"),
        actor(),
        readers=ports(
            (value,),
            recs,
            recovery("membership_written_not_selected", (), ("c" * 32,)),
        ),
    )
    assert result.disposition == "original_membership_action_pending"
    assert result.grade_action_id is None


@pytest.mark.parametrize(
    "failure",
    [
        "missing_receipt",
        "wrong_action",
        "source_drift",
        "unknown_grade",
        "wrong_review",
        "not_ready",
        "competing",
        "absent",
        "actor_drift",
        "duplicate",
        "untyped",
        "invalid_canonical",
        "read_failed",
        "inventory_race",
    ],
)
def test_conflicts_and_absence_fail_closed(tmp_path: Path, failure: str) -> None:
    value, recs = setup(tmp_path, grade=True, member=True)
    canonical = recovery("ready_verified", ("b" * 32,), ("c" * 32,))
    records = (value,)
    current = recs
    if failure == "missing_receipt":
        current = recs[:1]
    elif failure == "wrong_action":
        canonical = recovery("ready_verified", ("b" * 32,), ("e" * 32,))
    elif failure == "source_drift":
        canonical = recovery("source_changed")
    elif failure == "unknown_grade":
        canonical = recovery("ready_verified", ("f" * 32,), ("c" * 32,))
    elif failure == "wrong_review":
        canonical = replace(canonical, review_sha256="f" * 64)
    elif failure == "not_ready":
        canonical = recovery("relationship_needs_review")
    elif failure == "competing":
        records = (value, replace(value, review_sha256="f" * 64))
    elif failure == "absent":
        records = ()
    elif failure == "actor_drift":
        pass
    elif failure == "duplicate":
        records = (value, value)
    elif failure == "untyped":
        records = cast(Any, ("unexpected",))
    elif failure == "invalid_canonical":
        canonical = cast(Any, None)
    elif failure == "read_failed":
        records = ()
    elif failure == "inventory_race":
        pass

    reader = ports(records, current, canonical)
    if failure == "read_failed":

        def broken(*args: object) -> tuple[AssessmentSetupCorrelation, ...]:
            raise OSError("offline")

        reader = replace(reader, correlations=broken)
    if failure == "inventory_race":
        seen = [0]

        def shifting(*args: object) -> tuple[AssessmentSetupCorrelation, ...]:
            seen[0] += 1
            return (value,) if seen[0] == 1 else ()

        reader = replace(reader, correlations=shifting)
    result = inspect_stored_assessment_setup_restart(
        tmp_path,
        preview(),
        actor("f" * 64) if failure == "actor_drift" else actor(),
        readers=reader,
    )
    assert result.disposition == "requires_review"
    assert not result.may_resume_automatically
    assert not result.may_select_academic_record


def test_malformed_context_is_refused(tmp_path: Path) -> None:
    result = inspect_stored_assessment_setup_restart(
        Path("relative"),
        preview(),
        actor(),
        readers=ports((), (), recovery("pristine")),
    )
    assert result.reason == "invalid_restart_context"


def test_real_readers_never_create_missing_store_or_receipt_files(
    tmp_path: Path,
) -> None:
    from meridian.assessment_setup_restart import AssessmentSetupRestartReaders

    (tmp_path / "classes" / "english12").mkdir(parents=True)
    root_before = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")}
    result = inspect_stored_assessment_setup_restart(
        tmp_path, preview(), actor(), readers=AssessmentSetupRestartReaders()
    )
    root_after = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")}
    assert root_before == root_after
    assert result.disposition == "requires_review"


def test_source_has_no_academic_executor() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "meridian" / "assessment_setup_restart.py"
    ).read_text(encoding="utf-8")
    for fragment in (
        ".apply(",
        ".resume(",
        ".advance_exact(",
        ".create_reviewed(",
        "commit_grade_item(",
        "commit_membership(",
        "select_exact(",
        "input(",
        "open(",
    ):
        assert fragment not in source
