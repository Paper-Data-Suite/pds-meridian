"""#124 E2G3O10: installed native scored Concord -> Meridian acceptance.

Concord owns all Activity, Score, manifest, and publication writes. Only the
existing Meridian synthetic saved-actor witness is substituted. Group scores
remain group scores, never inferred as individual student evidence.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pds_core.classes import write_class_roster
from pds_core.publication_storage import get_current_publication_record
from pds_core.rosters import create_roster
from test_issue124_slicee2g3k_composite_canonical import ACTOR, CLASS, _all_bytes
from test_issue124_slicee2g3o4_canonical_teacher_acceptance import _journey
from test_issue124_slicee2g3o9_native_producer_acceptance import _native_workspace

from meridian.assessment_setup_choices import load_named_assessment_choices
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
)
from meridian.grade_item_storage import get_current_grade_item_revision
from meridian.teacher_action_receipts import TeacherActionReceiptStore

pytestmark = pytest.mark.skipif(
    os.environ.get("PDS_ISSUE124_CONCORD_NATIVE_TEST") != "1",
    reason="Requires pinned installed five-wheel Concord acceptance environment",
)


def _clock(hour: int) -> datetime:
    return datetime(2026, 8, 14, hour, 0, tzinfo=timezone.utc)


def _actor():
    from concord.workflows import WorkflowActor

    return WorkflowActor(
        actor_id="teacher-1", display_label="Synthetic Teacher", role_label="teacher"
    )


def _activity(root: Path, *, orientation: str = "local_criteria_only"):
    from concord.models import PrivacyPolicy
    from concord.workflows import CreateActivityContextRequest, create_activity_context

    write_class_roster(
        root,
        create_roster(
            CLASS,
            (
                {
                    "student_id": "student-1",
                    "last_name": "Synthetic",
                    "first_name": "Learner",
                    "period": "1",
                },
            ),
        ),
    )
    return create_activity_context(
        CreateActivityContextRequest(
            class_id=CLASS,
            activity_id="activity_native",
            title="Synthetic Concord Scored Activity",
            activity_type="project",
            scoring_orientation=orientation,
            session_id="session-1",
            actor=_actor(),
            activity_status="active",
            session_status="active",
            privacy_policy=PrivacyPolicy(classification="teacher_restricted"),
        ),
        workspace_root=root,
        clock=lambda: _clock(9),
    )


def _native_scored_publication(root: Path, *, group: bool):
    from concord.academic_result_manifest import academic_result_manifest_from_bytes
    from concord.academic_result_manifest_generation import (
        GenerateAcademicResultManifestRequest,
    )
    from concord.academic_result_publication import publish_concord_academic_results
    from concord.academic_work_registration import register_concord_academic_work
    from concord.models import (
        PrivacyPolicy,
        ScoreTargetReference,
        ScoringScaleLevel,
        SubjectReference,
    )
    from concord.workflows import (
        AddScoreRequest,
        CreateCriterionSetRequest,
        CreateGroupRequest,
        CreateScoringScaleRequest,
        CriterionSpec,
        SelectActivityCriterionSetsRequest,
        add_score,
        create_criterion_set,
        create_group,
        create_scoring_scale,
        select_activity_criterion_sets,
    )

    activity = _activity(root)
    scale = create_scoring_scale(
        CreateScoringScaleRequest(
            class_id=CLASS,
            activity_id="activity_native",
            scoring_scale_id="scale-1",
            lineage_id="scale-lineage",
            name="Local scale",
            revision=1,
            scale_type="teacher_defined",
            levels=(
                ScoringScaleLevel(value=1, label="One", meaning="First exact level."),
                ScoringScaleLevel(value=2, label="Two", meaning="Second exact level."),
            ),
            status="active",
            expected_snapshot_revision=activity.commit.snapshot_revision,
            actor=_actor(),
        ),
        workspace_root=root,
        clock=lambda: _clock(10),
    )
    criterion_set = create_criterion_set(
        CreateCriterionSetRequest(
            class_id=CLASS,
            activity_id="activity_native",
            criterion_set_id="set-1",
            lineage_id="set-lineage",
            name="Local criteria",
            purpose="Synthetic publication validation.",
            revision=1,
            scope="activity_specific",
            criterion_set_kind="local",
            criteria=(
                CriterionSpec(
                    criterion_id="criterion-1",
                    key="collaboration",
                    label="Collaboration",
                    definition="Demonstrates collaborative practice.",
                    criterion_kind="local",
                    supported_target_kinds=("core_student", "concord_group"),
                    default_scoring_scale_id="scale-1",
                ),
            ),
            status="active",
            expected_snapshot_revision=scale.commit.snapshot_revision,
            actor=_actor(),
        ),
        workspace_root=root,
        clock=lambda: _clock(11),
    )
    selected = select_activity_criterion_sets(
        SelectActivityCriterionSetsRequest(
            class_id=CLASS,
            activity_id="activity_native",
            criterion_set_ids=("set-1",),
            expected_snapshot_revision=criterion_set.commit.snapshot_revision,
            actor=_actor(),
        ),
        workspace_root=root,
        clock=lambda: _clock(12),
    )
    previous_revision = selected.commit.snapshot_revision
    if group:
        created_group = create_group(
            CreateGroupRequest(
                class_id=CLASS,
                activity_id="activity_native",
                group_id="group-1",
                label="Group One",
                status="active",
                expected_snapshot_revision=previous_revision,
                actor=_actor(),
            ),
            workspace_root=root,
            clock=lambda: _clock(13),
        )
        previous_revision = created_group.commit.snapshot_revision
        target = ScoreTargetReference(
            target_kind="concord_group", target_id="group-1", owning_system="concord"
        )
        privacy = PrivacyPolicy(
            classification="group_and_teacher",
            audience_references=(
                SubjectReference(
                    subject_kind="concord_group",
                    subject_id="group-1",
                    owning_system="concord",
                ),
            ),
        )
    else:
        target = ScoreTargetReference(
            target_kind="core_student", target_id="student-1", owning_system="core"
        )
        privacy = PrivacyPolicy(classification="teacher_restricted")

    scored = add_score(
        AddScoreRequest(
            class_id=CLASS,
            activity_id="activity_native",
            score_record_id="score-1",
            target_reference=target,
            criterion_id="criterion-1",
            scoring_scale_id="scale-1",
            disposition="scored",
            value=1,
            basis="professional_judgment",
            rationale="Private reason never to publish.",
            privacy_policy=privacy,
            expected_snapshot_revision=previous_revision,
            actor=_actor(),
            session_id="session-1",
        ),
        workspace_root=root,
        clock=lambda: _clock(14),
    )
    registered = register_concord_academic_work(
        root,
        CLASS,
        "activity_native",
        academic_intent="summative",
        lifecycle="active",
    )
    assert registered.registration.registration_revision == 1
    publication = publish_concord_academic_results(
        GenerateAcademicResultManifestRequest(
            class_id=CLASS,
            activity_id="activity_native",
            expected_snapshot_revision=scored.commit.snapshot_revision,
            actor=_actor(),
            revision_reason="initial",
        ),
        workspace_root=root,
        clock=lambda: _clock(15),
    )
    record = publication.publication
    raw = (root / record.manifest_path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == record.manifest_digest
    manifest = academic_result_manifest_from_bytes(raw)
    assert manifest.record_set.record_set_id == "academic_results"
    assert manifest.work == record.work
    assert record.capabilities == ("criterion_scores",)
    assert record.source_record is not None
    assert record.source_record.record_kind == "activity"
    assert len(manifest.scores) == 1
    assert manifest.scores[0].target_reference.target_kind == (
        "concord_group" if group else "core_student"
    )
    assert manifest.scores[0].target_reference.target_id == (
        "group-1" if group else "student-1"
    )
    assert b"Private reason never to publish." not in raw
    assert publication.compatibility.compatible
    return record


@pytest.mark.parametrize("group", (False, True), ids=("student-score", "group-score"))
def test_native_concord_scored_publication_to_meridian_one_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, group: bool
) -> None:
    root = _native_workspace(tmp_path)
    publication = _native_scored_publication(root, group=group)
    work = publication.work
    named = load_named_assessment_choices(
        root, class_id=CLASS, school_year="2026-2027", period_id="mp1"
    )
    assert len(named.items) == 1
    assert named.items[0].candidate.work == work
    assert named.items[0].candidate.publication_id == publication.publication_id
    assert named.items[0].publication_state == "current_results_verified"

    journey = _journey(
        root,
        monkeypatch,
        ("1", "1", "S", "1", "Concord Activity", "", ACTOR.actor_id, "APPLY", ""),
    )
    assert "Assessment relationship verified current." in journey.output
    assert journey.prompts.count("Confirmation: ") == 1
    assert journey.session.active_work == work
    assert journey.session.active_publication_id == publication.publication_id
    grade_id = journey.session.active_grade_item_id
    assert grade_id is not None
    assert get_current_grade_item_revision(root, CLASS, grade_id) == 1
    selected = load_current_grade_item_membership_decision(root, CLASS, grade_id, work)
    assert selected is not None
    assert selected.decision.decision == "included"
    assert selected.decision.academic_period is not None
    assert selected.decision.academic_period.period.period_id == "mp1"
    assert (
        get_current_publication_record(
            root, work, "academic_result_set", "academic_results"
        )
        == publication
    )
    assert len(AssessmentSetupCorrelationStore(root, CLASS).list_records()) == 1
    assert len(TeacherActionReceiptStore(root, CLASS).list_receipts()) == 2
    before = _all_bytes(root)
    reopened = _journey(root, monkeypatch, ("1", "1", "S", ""))
    assert reopened.prompts.count("Confirmation: ") == 0
    assert reopened.session.active_publication_id == publication.publication_id
    assert _all_bytes(root) == before


def test_native_concord_evidence_only_cannot_publish_academic_result(
    tmp_path: Path,
) -> None:
    from concord.academic_result_manifest_generation import (
        GenerateAcademicResultManifestRequest,
    )
    from concord.academic_result_publication import (
        ConcordAcademicResultPublicationError,
        publish_concord_academic_results,
    )
    from concord.academic_work_registration import register_concord_academic_work
    from pds_core.routing_models import ModuleWorkRef

    root = _native_workspace(tmp_path)
    activity = _activity(root, orientation="evidence_only")
    registered = register_concord_academic_work(
        root,
        CLASS,
        "activity_native",
        academic_intent="reporting_only",
        lifecycle="active",
    )
    assert registered.registration.registration_revision == 1
    work = ModuleWorkRef("concord", CLASS, "activity_native")
    assert (
        get_current_publication_record(
            root, work, "academic_result_set", "academic_results"
        )
        is None
    )
    with pytest.raises(ConcordAcademicResultPublicationError):
        publish_concord_academic_results(
            GenerateAcademicResultManifestRequest(
                class_id=CLASS,
                activity_id="activity_native",
                expected_snapshot_revision=activity.commit.snapshot_revision,
                actor=_actor(),
                revision_reason="initial",
            ),
            workspace_root=root,
            clock=lambda: _clock(15),
        )
    assert (
        get_current_publication_record(
            root, work, "academic_result_set", "academic_results"
        )
        is None
    )
    assert AssessmentSetupCorrelationStore(root, CLASS).list_records() == ()
    assert TeacherActionReceiptStore(root, CLASS).list_receipts() == ()
