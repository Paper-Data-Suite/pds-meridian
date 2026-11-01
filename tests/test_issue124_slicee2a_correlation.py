"""#124 E2A: cross-action correlation is exact and never resume authority."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_correlation import (
    AssessmentSetupCorrelation,
    AssessmentSetupCorrelationError,
    bind_correlation_action,
    create_assessment_setup_correlation,
    inspect_assessment_setup_correlation,
    verify_correlation_context,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_recovery import AssessmentSetupRecoveryInspection
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import PreparedGuidedAction, _identity
from meridian.teacher_action_receipts import TeacherActionReceipt

SHA = "a" * 64
ROOT = Path(__file__).resolve().parents[1]
WORK = ModuleWorkRef("scoreform", "english12", "scene")


def preview(kind: str = "create_and_link") -> AssessmentSetupPreview:
    return AssessmentSetupPreview(
        kind=cast(Any, kind),
        review_sha256=SHA,
        work=WORK,
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


def actor(profile: str = SHA) -> TeacherActionActor:
    return TeacherActionActor("teacher", profile, "saved")


def action(kind: str, action_id: str | None = None) -> PreparedGuidedAction:
    return PreparedGuidedAction(
        preview=cast(
            Any,
            SimpleNamespace(
                kind=kind,
                action_id=action_id or ("b" if kind == "grade_item" else "c") * 32,
                target=SimpleNamespace(
                    family=kind, candidate_sha256="d" * 64, revision=1
                ),
                scope=SimpleNamespace(
                    class_id="english12",
                    workspace_sha256=_identity("workspace", str(ROOT)),
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


def state(
    name: str,
    *,
    grades: tuple[str, ...] = (),
    members: tuple[str, ...] = (),
    review_sha256: str = SHA,
) -> AssessmentSetupRecoveryInspection:
    return AssessmentSetupRecoveryInspection(
        state=cast(Any, name),
        reason="test",
        review_sha256=review_sha256,
        grade_item_id="gi_scene",
        grade_action_ids=grades,
        membership_action_ids=members,
        grade_selected_revision=None,
        membership_selected_revision=None,
    )


def correlated() -> tuple[
    AssessmentSetupCorrelation, PreparedGuidedAction, PreparedGuidedAction
]:
    grade = action("grade_item")
    member = action("grade_item_membership")
    base = create_assessment_setup_correlation(ROOT, preview(), actor())
    return (
        bind_correlation_action(
            bind_correlation_action(base, grade, family="grade_item"),
            member,
            family="grade_item_membership",
        ),
        grade,
        member,
    )


def test_start_is_exact_and_not_a_write_or_automatic_resume() -> None:
    result = create_assessment_setup_correlation(ROOT, preview(), actor())
    assert result.stage == "reviewed"
    assert result.grade_action_id is None
    assert result.membership_action_id is None
    advice = inspect_assessment_setup_correlation(result, state("pristine"), ())
    assert advice.advice == "not_started"
    assert not advice.may_resume_automatically


def test_roundtrip_is_canonical_checksum_protected_and_bounded() -> None:
    result, _, _ = correlated()
    content = result.to_json_bytes()
    assert AssessmentSetupCorrelation.from_json_bytes(content) == result
    assert (
        content == AssessmentSetupCorrelation.from_json_bytes(content).to_json_bytes()
    )
    assert (
        result.intent_sha256
        == create_assessment_setup_correlation(ROOT, preview(), actor()).intent_sha256
    )


@pytest.mark.parametrize(
    "failure", ["tamper", "additional", "duplicate", "spaces", "oversize", "unknown"]
)
def test_invalid_serialization_fails_closed(failure: str) -> None:
    content = correlated()[0].to_json_bytes()
    if failure == "tamper":
        content = content.replace(b"english12", b"english11")
    elif failure == "additional":
        content += b"\n"
    elif failure == "duplicate":
        content = content.replace(b'"payload":', b'"payload":null,"payload":')
    elif failure == "spaces":
        content = json.dumps(json.loads(content), indent=2).encode()
    elif failure == "oversize":
        content = b"a" * 9000
    else:
        content = content.replace(b'"schema_version":1', b'"schema_version":2')
    with pytest.raises(AssessmentSetupCorrelationError):
        AssessmentSetupCorrelation.from_json_bytes(content)


def test_review_actor_and_profile_drift_fails() -> None:
    result, _, _ = correlated()
    verify_correlation_context(ROOT, result, preview(), actor())
    with pytest.raises(AssessmentSetupCorrelationError, match="changed"):
        verify_correlation_context(ROOT, result, preview(), actor("f" * 64))
    with pytest.raises(AssessmentSetupCorrelationError, match="changed"):
        verify_correlation_context(ROOT, result, replace_preview_period("mp2"), actor())


def replace_preview_period(period: str) -> AssessmentSetupPreview:
    return replace(preview(), marking_period_id=period)


def test_temporary_attribution_and_ready_plan_cannot_be_correlated() -> None:
    with pytest.raises(AssessmentSetupCorrelationError, match="saved"):
        create_assessment_setup_correlation(
            ROOT, preview(), TeacherActionActor("teacher", SHA, "temporary")
        )
    with pytest.raises(AssessmentSetupCorrelationError, match="Already-ready"):
        create_assessment_setup_correlation(ROOT, preview("already_ready"), actor())


def test_stage_order_is_fixed_and_action_ids_never_rebound() -> None:
    base = create_assessment_setup_correlation(ROOT, preview(), actor())
    with pytest.raises(AssessmentSetupCorrelationError, match="not available"):
        bind_correlation_action(
            base, action("grade_item_membership"), family="grade_item_membership"
        )
    grade = bind_correlation_action(base, action("grade_item"), family="grade_item")
    assert grade.stage == "grade_bound"
    with pytest.raises(AssessmentSetupCorrelationError, match="already bound"):
        bind_correlation_action(grade, action("grade_item"), family="grade_item")
    with pytest.raises(AssessmentSetupCorrelationError, match="scope/actor"):
        bind_correlation_action(
            grade, action("grade_item"), family="grade_item_membership"
        )
    full = bind_correlation_action(
        grade, action("grade_item_membership"), family="grade_item_membership"
    )
    assert full.stage == "membership_bound"
    with pytest.raises(AssessmentSetupCorrelationError, match="not available"):
        bind_correlation_action(
            full, action("grade_item_membership"), family="grade_item_membership"
        )


def test_existing_item_has_only_membership_action() -> None:
    base = create_assessment_setup_correlation(ROOT, preview("use_existing"), actor())
    with pytest.raises(AssessmentSetupCorrelationError, match="invalid"):
        bind_correlation_action(base, action("grade_item"), family="grade_item")
    bound = bind_correlation_action(
        base, action("grade_item_membership"), family="grade_item_membership"
    )
    assert bound.grade_action_id is None and bound.stage == "membership_bound"


def test_canonical_partial_status_never_authorizes_replay() -> None:
    corr, grade, member = correlated()
    both = (receipt(grade), receipt(member))
    for name, expected in (
        ("grade_item_written_not_selected", "original_grade_action_pending"),
        ("membership_written_not_selected", "original_membership_action_pending"),
        ("ready_verified", "ready_verified"),
    ):
        advice = inspect_assessment_setup_correlation(
            corr,
            state(
                name,
                grades=(grade.preview.action_id,),
                members=(member.preview.action_id,),
            ),
            both,
        )
        assert advice.advice == expected
        assert not advice.may_resume_automatically


def test_grade_selected_requires_membership_preparation_not_new_grade() -> None:
    corr = bind_correlation_action(
        create_assessment_setup_correlation(ROOT, preview(), actor()),
        action("grade_item"),
        family="grade_item",
    )
    grade = action("grade_item")
    advice = inspect_assessment_setup_correlation(
        corr,
        state("grade_item_selected_link_missing", grades=(grade.preview.action_id,)),
        (receipt(grade),),
    )
    assert advice.advice == "original_membership_action_pending"
    assert not advice.may_resume_automatically


@pytest.mark.parametrize(
    "failure",
    [
        "receipt_missing",
        "receipt_scope",
        "other_action",
        "source_changed",
        "wrong_review",
    ],
)
def test_correlation_conflicts_refuse_advice(failure: str) -> None:
    corr, grade, member = correlated()
    receipts = (receipt(grade), receipt(member))
    recovery = state(
        "membership_written_not_selected",
        grades=(grade.preview.action_id,),
        members=(member.preview.action_id,),
    )
    if failure == "receipt_missing":
        receipts = (receipt(grade),)
    elif failure == "receipt_scope":
        member.preview.scope.grade_item_id = "different"
    elif failure == "other_action":
        recovery = replace(recovery, membership_action_ids=("e" * 32,))
    elif failure == "source_changed":
        recovery = replace(recovery, state="source_changed")
    else:
        recovery = replace(recovery, review_sha256="f" * 64)
    advice = inspect_assessment_setup_correlation(corr, recovery, receipts)
    assert advice.advice == "requires_review"


def test_no_mutation_or_executor_in_correlation_module() -> None:
    content = (
        Path(__file__).resolve().parents[1]
        / "meridian"
        / "assessment_setup_correlation.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "commit_grade_item(",
        "commit_membership(",
        "write_grade_item",
        "resume_restart_grade_item(",
        "TeacherActionReceiptStore(",
        "open(",
        "input(",
    ):
        assert forbidden not in content
