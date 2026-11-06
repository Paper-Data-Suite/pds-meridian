"""#125-G1: native source cardinality and bounded batch eligibility boundaries.

Source-only tests use synthetic rows. Installed tests use real producer builders
from the qualified #124 acceptance suite, never fabricated native manifests.
Every workspace, roster, and teacher attribution in this file is synthetic.
"""

from __future__ import annotations

import os
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from pds_core.classes import write_class_roster
from pds_core.rosters import create_roster
from test_issue125_sliceb_assessment_projection import (
    eligibility_row,
    project,
    roster,
    student,
)

from meridian import menu_teacher_assessment_eligibility as menu


def test_distinct_result_kinds_on_same_question_are_not_competing_attempts() -> None:
    response = eligibility_row("student_01", 1, item_id="response_q1")
    correctness = replace(
        eligibility_row("student_01", 1, item_id="correctness_q1"),
        result_kind="question_correctness",
    )
    summary = project((response, correctness), roster(student(1)))
    assert summary.candidate_item_count == 2
    assert summary.exception_count == 0
    labels = tuple(item.evidence_label for item in summary.students[0].items)
    assert len(set(labels)) == 2
    assert all(label.startswith("Question 1") for label in labels)
    assert all(item.candidate_for_explicit_review for item in summary.students[0].items)


def test_repeated_result_kind_on_same_target_blocks_every_competing_item() -> None:
    rows = tuple(
        replace(
            eligibility_row("student_01", 1, item_id=f"attempt_{attempt}_{kind}"),
            result_kind=kind,
        )
        for attempt in (1, 2)
        for kind in ("selected_response", "question_correctness")
    )
    summary = project(rows, roster(student(1)))
    assert summary.candidate_item_count == 0
    assert len(summary.exceptions) == 4
    assert {issue.code for issue in summary.exceptions} == {
        "multiple_items_same_native_target"
    }
    assert all(issue.route == "review-attempts" for issue in summary.exceptions)


def test_separate_standard_observations_do_not_create_false_duplicates() -> None:
    first = replace(
        eligibility_row("student_01", 1, item_id="observation_standard_a"),
        result_kind="standard_observation_rating",
        standard_ids=("synthetic:W.A",),
    )
    second = replace(
        eligibility_row("student_01", 1, item_id="observation_standard_b"),
        result_kind="standard_observation_rating",
        standard_ids=("synthetic:W.B",),
    )
    summary = project((first, second), roster(student(1)))
    assert summary.candidate_item_count == 2
    assert not summary.exceptions


def test_29_by_6_source_cardinality_is_not_only_174_evidence_items() -> None:
    rows = []
    for number in range(1, 30):
        student_id = f"student_{number:02d}"
        for question in range(1, 7):
            for kind in ("selected_response", "question_correctness"):
                item_id = f"{student_id}_question_{question}_{kind}"
                rows.append(
                    replace(
                        eligibility_row(student_id, question, item_id=item_id),
                        result_kind=kind,
                    )
                )
    summary = project(tuple(rows), roster(*(student(i) for i in range(1, 30))))
    assert summary.projected_item_count == 29 * 6 * 2
    assert summary.candidate_item_count == 29 * 6 * 2
    assert summary.no_result_student_count == 0
    assert summary.exception_count == 0
    assert len(menu._enumerate_candidates(summary)) == 348
    assert len({item.source for s in summary.students for item in s.items}) == 348
    prompts = []

    def choose(prompt: str) -> str:
        prompts.append(prompt)
        return "A"

    selected = menu._choose_source_ids(
        summary, input_fn=choose, output=StringIO(), clear_fn=lambda: None
    )
    assert selected is not None and len(selected) == 348
    assert len(prompts) == 1
    assert prompts[0] == "Choice: "


def test_repeated_exact_kind_same_target_still_refused_with_other_sibling() -> None:
    rows = (
        eligibility_row("student_01", 1, item_id="attempt1_response"),
        replace(
            eligibility_row("student_01", 1, item_id="attempt1_correct"),
            result_kind="question_correctness",
        ),
        eligibility_row("student_01", 1, item_id="attempt2_response"),
    )
    summary = project(rows, roster(student(1)))
    assert summary.candidate_item_count == 0
    assert len(summary.exceptions) == 3


# The following tests MUST run with PDS_ISSUE125_NATIVE_TEST=1 against actual
# compatible ScoreForm, Quillan, and Concord distributions. Ordinary source
# pytest collection skips them; skipped results are NOT installed acceptance.
_NATIVE = os.environ.get("PDS_ISSUE125_NATIVE_TEST") == "1"


def _native_roster(root: Path, count: int) -> None:
    from test_issue124_slicee2g3k_composite_canonical import CLASS

    write_class_roster(
        root,
        create_roster(
            CLASS,
            tuple(
                {
                    "student_id": f"student{number:03d}",
                    "first_name": "Synthetic",
                    "last_name": f"Learner{number:03d}",
                    "period": "1",
                }
                for number in range(1, count + 1)
            ),
        ),
    )


def _project_native(root: Path, work: object, publication_id: str, grade_id: str):
    from meridian.assessment_eligibility_review import (
        project_assessment_eligibility_review,
    )
    from meridian.diagnostics import default_diagnostics_dependencies
    from meridian.guided_projection import (
        default_guided_projection_dependencies,
        prepare_guided_evidence_projection,
    )
    from scripts.smoke_program_guided_evidence_issue110 import AllowInstalledAcceptance

    diagnostics = default_diagnostics_dependencies(
        authorizer=AllowInstalledAcceptance()
    )
    prepared = prepare_guided_evidence_projection(
        root,
        work,  # type: ignore[arg-type]
        publication_id,
        dependencies=default_guided_projection_dependencies(diagnostics=diagnostics),
    )
    return project_assessment_eligibility_review(
        root, grade_item_id=grade_id, prepared=prepared
    )


@pytest.mark.skipif(not _NATIVE, reason="Needs installed native producer matrix")
def test_installed_scoreform_29_by_6_native_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_issue124_slicee2g3k_composite_canonical import ACTOR, CLASS, _all_bytes
    from test_issue124_slicee2g3o4_canonical_teacher_acceptance import _journey
    from test_issue124_slicee2g3o9_native_producer_acceptance import (
        _native_workspace,
        _scoreform_publication,
    )

    root = _native_workspace(tmp_path)
    _native_roster(root, 29)
    work, publication_id = _scoreform_publication(root)
    journey = _journey(
        root,
        monkeypatch,
        ("1", "1", "S", "1", "Native ScoreForm", "", ACTOR.actor_id, "APPLY", ""),
    )
    grade_id = journey.session.active_grade_item_id
    assert journey.session.active_publication_id == publication_id
    assert grade_id is not None
    # Reuse the exact authorized cache; only the roster/eligibility read must be pure.
    from meridian.assessment_eligibility_review import (
        project_assessment_eligibility_review,
    )
    from meridian.diagnostics import default_diagnostics_dependencies
    from meridian.guided_projection import (
        default_guided_projection_dependencies,
        prepare_guided_evidence_projection,
    )
    from scripts.smoke_program_guided_evidence_issue110 import AllowInstalledAcceptance

    deps = default_guided_projection_dependencies(
        diagnostics=default_diagnostics_dependencies(
            authorizer=AllowInstalledAcceptance()
        )
    )
    prepared = prepare_guided_evidence_projection(
        root, work, publication_id, dependencies=deps
    )
    before_review = _all_bytes(root)
    summary = project_assessment_eligibility_review(
        root, grade_item_id=grade_id, prepared=prepared
    )
    assert _all_bytes(root) == before_review
    assert summary.class_id == CLASS
    assert len(summary.students) == 29
    assert summary.projected_item_count == 406
    assert summary.candidate_item_count == 406
    assert (
        sum(
            item.target_kind == "question"
            for record in summary.students
            for item in record.items
        )
        == 348
    )
    assert summary.exception_count == 0
    assert len({item.source for s in summary.students for item in s.items}) == 406


@pytest.mark.skipif(not _NATIVE, reason="Needs installed native producer matrix")
def test_installed_quillan_review_does_not_invent_missing_result_zeros(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_issue124_slicee2g3k_composite_canonical import ACTOR
    from test_issue124_slicee2g3o4_canonical_teacher_acceptance import _journey
    from test_issue124_slicee2g3o9_native_producer_acceptance import (
        _native_workspace,
        _quillan_publication,
    )

    root = _native_workspace(tmp_path)
    _native_roster(root, 29)
    work, publication_id = _quillan_publication(root)
    journey = _journey(
        root,
        monkeypatch,
        ("1", "1", "S", "1", "Native Quillan", "", ACTOR.actor_id, "APPLY", ""),
    )
    grade_id = journey.session.active_grade_item_id
    assert grade_id is not None
    summary = _project_native(root, work, publication_id, grade_id)
    assert len(summary.students) == 29
    assert summary.no_result_student_count == 28
    assert sum(not s.no_result for s in summary.students) == 1
    assert all(s.no_result for s in summary.students[1:])
    assert not summary.shared_items
    assert not summary.unmatched_items


@pytest.mark.skipif(not _NATIVE, reason="Needs installed native producer matrix")
@pytest.mark.parametrize("group", (False, True), ids=("student", "group"))
def test_installed_concord_group_is_not_student_attributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, group: bool
) -> None:
    from test_issue124_slicee2g3k_composite_canonical import ACTOR
    from test_issue124_slicee2g3o4_canonical_teacher_acceptance import _journey
    from test_issue124_slicee2g3o10_native_concord_acceptance import (
        _native_scored_publication,
        _native_workspace,
    )

    root = _native_workspace(tmp_path)
    publication = _native_scored_publication(root, group=group)
    journey = _journey(
        root,
        monkeypatch,
        ("1", "1", "S", "1", "Native Concord", "", ACTOR.actor_id, "APPLY", ""),
    )
    grade_id = journey.session.active_grade_item_id
    assert grade_id is not None
    summary = _project_native(
        root, publication.work, publication.publication_id, grade_id
    )
    if group:
        assert summary.candidate_item_count == 0
        assert len(summary.shared_items) == 1
        assert not summary.students[0].items
        assert not summary.shared_items[0].candidate_for_explicit_review
    else:
        assert not summary.shared_items
        assert summary.candidate_item_count == 1
        assert len(summary.students[0].items) == 1


@pytest.mark.skipif(not _NATIVE, reason="Needs installed native producer matrix")
def test_installed_concord_evidence_only_cannot_fabricate_result_publication(
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
    from pds_core.publication_storage import get_current_publication_record
    from pds_core.routing_models import ModuleWorkRef
    from test_issue124_slicee2g3k_composite_canonical import CLASS
    from test_issue124_slicee2g3o10_native_concord_acceptance import (
        _activity,
        _actor,
        _clock,
        _native_workspace,
    )

    root = _native_workspace(tmp_path)
    activity = _activity(root, orientation="evidence_only")
    register_concord_academic_work(
        root,
        CLASS,
        "activity_native",
        academic_intent="reporting_only",
        lifecycle="active",
    )
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


@pytest.mark.skipif(not _NATIVE, reason="Needs installed native producer matrix")
def test_installed_source_without_authorizer_fails_closed_before_cache_write(
    tmp_path: Path,
) -> None:
    from test_issue124_slicee2g3k_composite_canonical import _all_bytes
    from test_issue124_slicee2g3o9_native_producer_acceptance import (
        _native_workspace,
        _scoreform_publication,
    )

    from meridian.diagnostics import default_diagnostics_dependencies
    from meridian.guided_projection import (
        GuidedProjectionAuthorizationUnavailableError,
        default_guided_projection_dependencies,
        prepare_guided_evidence_projection,
    )

    root = _native_workspace(tmp_path)
    _native_roster(root, 1)
    work, publication_id = _scoreform_publication(root)
    before = _all_bytes(root)
    with pytest.raises(GuidedProjectionAuthorizationUnavailableError):
        prepare_guided_evidence_projection(
            root,
            work,
            publication_id,
            dependencies=default_guided_projection_dependencies(
                diagnostics=default_diagnostics_dependencies(authorizer=None)
            ),
        )
    assert _all_bytes(root) == before
