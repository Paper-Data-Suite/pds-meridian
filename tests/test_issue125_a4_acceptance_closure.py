"""#125-A4: exception-first closure at source and installed boundaries.

All classroom data are synthetic. Native tests run only in the explicitly
qualified five-wheel environment; a skipped native test is not acceptance.
"""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from test_issue125_sliceb_assessment_projection import (
    eligibility_row,
    project,
    roster,
    student,
)
from test_issue125_slicef1_assessment_menu import review as synthetic_review

import meridian.menu_teacher_assessment_eligibility as menu
from meridian.assessment_eligibility_review import (
    AssessmentEligibilityReviewScopeError,
)
from meridian.teacher_session import TeacherSessionContext

_NATIVE = os.environ.get("PDS_ISSUE125_A4_NATIVE_TEST") == "1"


class _Transcript:
    def __init__(self, *answers: str) -> None:
        self._answers = iter(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            return next(self._answers)
        except StopIteration as error:
            raise AssertionError(f"Unexpected teacher prompt: {prompt!r}") from error


def test_duplicate_exact_source_identity_stops_before_teacher_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = eligibility_row("student_01", 1, item_id="PRIVATE_DUPLICATE_ITEM")
    with pytest.raises(
        AssessmentEligibilityReviewScopeError, match="Duplicate exact item IDs"
    ):
        project((row, row), roster(student(1)))

    grade = SimpleNamespace(
        grade_item_id="grade_synthetic", display_label="Synthetic Grade Item"
    )
    work = SimpleNamespace(class_id="class_synthetic")
    prepared = SimpleNamespace(
        authorized=SimpleNamespace(
            current_context=SimpleNamespace(publication=SimpleNamespace(work=work))
        )
    )
    monkeypatch.setattr(
        menu, "discover_guided_eligibility_grade_items", lambda *_a, **_k: (grade,)
    )

    def fail_integrity(*_args: object, **_kwargs: object) -> object:
        raise AssessmentEligibilityReviewScopeError(
            "PRIVATE_DUPLICATE_ITEM appeared twice"
        )

    monkeypatch.setattr(menu, "project_assessment_eligibility_review", fail_integrity)
    transcript = _Transcript("1", "")
    output = StringIO()
    menu.run_assessment_eligibility_menu(
        workspace_root=Path("/synthetic-no-writes"),
        prepared=cast(object, prepared),
        class_label="Synthetic class",
        assessment_title="Synthetic assessment",
        session_context=TeacherSessionContext(active_class_id="class_synthetic"),
        dependencies=cast(object, SimpleNamespace()),
        diagnostics=cast(object, SimpleNamespace()),
        input_fn=transcript,
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Assessment source integrity could not be verified." in rendered
    assert "Review the source/publication and roster identities" in rendered
    assert "No evidence entered batch selection" in rendered
    assert "Choose Exact Batch Scope" not in rendered
    assert "PRIVATE_DUPLICATE_ITEM" not in rendered


def test_advanced_and_individual_recovery_routes_remain_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = synthetic_review(1, 1)
    data.shared_items = (data.students[0].items[0],)
    data.students[0].items = ()
    data.exceptions = (
        SimpleNamespace(
            code="non_student_evidence",
            route="review-individual",
            student_id=None,
            source=data.shared_items[0].source,
        ),
    )
    data.exception_count = 1
    data.status_counts = (("eligibility_no_decision", 1),)
    data.class_label = "Synthetic class"
    data.assessment_title = "Synthetic assessment"
    data.source_status = "current"
    data.membership_state = "included"
    queue_output = StringIO()
    assert menu._review_exception_queue(
        cast(object, data),
        input_fn=_Transcript("D"),
        output=queue_output,
        clear_fn=lambda: None,
        force=True,
    )
    assert "Review individual evidence" in queue_output.getvalue()

    monkeypatch.setattr(
        menu,
        "reconcile_sealed_eligibility_batch",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("synthetic conflict")),
    )
    recovery_output = StringIO()
    menu._show_recovery(
        Path("/synthetic-no-writes"),
        cast(object, SimpleNamespace()),
        diagnostics=cast(object, SimpleNamespace()),
        input_fn=_Transcript(""),
        output=recovery_output,
        clear_fn=lambda: None,
    )
    assert "Advanced individual-action recovery screen" in recovery_output.getvalue()


@pytest.mark.skipif(
    not _NATIVE, reason="Requires isolated official A4 five-wheel environment"
)
def test_installed_unreadable_scoreform_scan_fails_before_result_publication() -> None:
    from scoreform.attempt_assembly import (
        Pds2ScanDispatchResult,
        ScoreFormAttemptAssemblyBatch,
        ScoreFormRoutedScoringBatch,
    )
    from scoreform.cli_score import RoutedScoringOperationResult
    from scoreform.guided_scan_results import (
        build_guided_scan_summary,
        format_guided_scan_summary,
    )
    from scoreform.scan_review_models import ScoreFormFailurePersistenceBatch

    dispatch = Pds2ScanDispatchResult(
        retained_source=None,
        file_error=FileNotFoundError("synthetic unreadable scan"),
    )
    operation = RoutedScoringOperationResult(
        batch=ScoreFormRoutedScoringBatch(
            dispatch,
            ScoreFormAttemptAssemblyBatch(dispatch),
            export_result=None,
        ),
        review=ScoreFormFailurePersistenceBatch(),
    )
    summary = build_guided_scan_summary(operation, "synthetic_unreadable_scan.pdf")
    rendered = format_guided_scan_summary(summary)
    assert summary.outcome == "failed_safely"
    assert summary.targets == ()
    assert summary.completed_attempts == 0
    assert summary.attempts_appended == 0
    assert "Outcome: Failed safely" in rendered
    assert "Complete ScoreForm attempts: 0" in rendered
    assert "ScoreForm result targets:" not in rendered
    assert "synthetic unreadable scan" not in rendered


def _append_corrected_scoreform_attempt(root: Path, current_publication_id: str) -> str:
    from scoreform.academic_result_manifest_generation import (
        generate_academic_result_manifest,
    )
    from scoreform.academic_result_publication import (
        supersede_scoreform_academic_results,
    )
    from scoreform.page_scoring import ScoredAnswer
    from scoreform.results import ScoreFormRoutedResult, export_scoreform_result_models
    from test_issue124_slicee2g3k_composite_canonical import CLASS

    answers = tuple(ScoredAnswer(number, "A", True) for number in range(1, 7))
    corrected = ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id=CLASS,
        assignment_id="scene",
        student_id="student001",
        first_name="Synthetic",
        last_name="Learner",
        period="1",
        page_display="manual",
        score=6,
        total_points=6,
        answers=answers,
        source_file="plain_paper_manual_entry",
    )
    exported = export_scoreform_result_models((corrected,), workspace_root=root)
    assert exported.succeeded and len(exported.appended_attempts) == 1
    generated = generate_academic_result_manifest(root, CLASS, "scene")
    published = supersede_scoreform_academic_results(
        root,
        CLASS,
        "scene",
        manifest_revision=generated.revision,
        expected_current_publication_id=current_publication_id,
    )
    return published.publication.publication_id


@pytest.mark.skipif(
    not _NATIVE, reason="Requires isolated official A4 five-wheel environment"
)
def test_installed_scoreform_corrected_attempt_teacher_walkthrough_is_exception_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_issue124_slicee2g3k_composite_canonical import ACTOR, _all_bytes
    from test_issue124_slicee2g3o4_canonical_teacher_acceptance import _journey
    from test_issue124_slicee2g3o9_native_producer_acceptance import (
        _native_workspace,
        _scoreform_publication,
    )
    from test_issue125_sliceg1_native_source_acceptance import _native_roster

    from meridian.assessment_eligibility_review import (
        project_assessment_eligibility_review,
    )
    from meridian.diagnostics import default_diagnostics_dependencies
    from meridian.guided_eligibility import GuidedEligibilityDependencies
    from meridian.guided_projection import (
        default_guided_projection_dependencies,
        prepare_guided_evidence_projection,
    )
    from scripts.smoke_program_guided_evidence_issue110 import (
        AllowInstalledAcceptance,
    )

    root = _native_workspace(tmp_path)
    _native_roster(root, 29)
    work, initial_publication_id = _scoreform_publication(root)
    corrected_publication_id = _append_corrected_scoreform_attempt(
        root, initial_publication_id
    )
    setup = _journey(
        root,
        monkeypatch,
        (
            "1",
            "1",
            "S",
            "1",
            "A4 Corrected Attempt",
            "",
            ACTOR.actor_id,
            "APPLY",
            "",
        ),
    )
    assert setup.session.active_publication_id == corrected_publication_id
    grade_id = setup.session.active_grade_item_id
    assert grade_id is not None
    diagnostics = default_diagnostics_dependencies(
        authorizer=AllowInstalledAcceptance()
    )
    prepared = prepare_guided_evidence_projection(
        root,
        work,
        corrected_publication_id,
        dependencies=default_guided_projection_dependencies(diagnostics=diagnostics),
    )
    review = project_assessment_eligibility_review(
        root,
        grade_item_id=grade_id,
        prepared=prepared,
        class_label="Synthetic class",
        assessment_title="Synthetic six-question assessment",
    )
    competing = tuple(
        issue
        for issue in review.exceptions
        if issue.code == "multiple_items_same_native_target"
    )
    safe_ids = {row[0] for row in menu._enumerate_candidates(review)}
    unsafe_ids = {
        issue.source.item_id for issue in competing if issue.source is not None
    }
    assert competing
    assert safe_ids
    assert safe_ids.isdisjoint(unsafe_ids)

    before = _all_bytes(root)
    transcript = _Transcript("1", "B")
    output = StringIO()
    menu.run_assessment_eligibility_menu(
        workspace_root=root,
        prepared=prepared,
        class_label="Synthetic class",
        assessment_title="Synthetic six-question assessment",
        session_context=setup.session,
        dependencies=GuidedEligibilityDependencies(),
        diagnostics=diagnostics,
        input_fn=transcript,
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Assessment Exceptions" in rendered
    assert "multiple items same native target" in rendered
    assert "Review attempts (#126)" in rendered
    assert "Choose Exact Batch Scope" not in rendered
    assert corrected_publication_id not in rendered
    assert "plain_paper_manual_entry" not in rendered
    assert _all_bytes(root) == before
