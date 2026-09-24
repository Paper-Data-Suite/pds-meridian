from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from meridian.menu_evidence import (
    AuthorizedEvidenceContext,
    EvidenceMenuDependencies,
    StandardsActionDependencies,
    run_new_evidence_menu,
)
from meridian.new_evidence_workflow import NewEvidenceReview
from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.standards_review_workflow import StandardsReviewProjection


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _context() -> AuthorizedEvidenceContext:
    work = SimpleNamespace(class_id="class_1")
    publication = SimpleNamespace(work=work)
    authorized = cast(
        AuthorizedProjectionSnapshot,
        SimpleNamespace(
            stored=SimpleNamespace(
                snapshot=SimpleNamespace(
                    source=SimpleNamespace(publication=publication)
                )
            )
        ),
    )
    review = cast(
        NewEvidenceReview,
        SimpleNamespace(grade_item_id="grade_item_1"),
    )
    return AuthorizedEvidenceContext(review=review, authorized=authorized)


def _projection() -> StandardsReviewProjection:
    return cast(
        StandardsReviewProjection,
        SimpleNamespace(
            item_id="item_1",
            student_id="student_1",
            standard_id="NJSLSA.R1",
            producer_declared_standard_ids=("NJSLSA.R1",),
            producer_declares_standard=True,
            standard_resolution=SimpleNamespace(resolved=True),
            association_revision=1,
            association_disposition="associated",
            association_basis="explicit",
            eligibility_state="included",
            attempt_state="not_applicable",
            reassessment_state="not_applicable",
            aggregation_status="performance",
            target_scale=SimpleNamespace(
                scale_id="four_level",
                scale_revision=2,
            ),
        ),
    )


def _menu_deps() -> EvidenceMenuDependencies:
    return EvidenceMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        diagnostics=cast(object, object()),  # type: ignore[arg-type]
        review_loader=lambda *_args: cast(NewEvidenceReview, object()),
    )


def _standards(
    log: list[str],
    *,
    author_preview: object | None = None,
    selection_preview: object | None = None,
) -> StandardsActionDependencies:
    return StandardsActionDependencies(
        clock=lambda: datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
        context_loader=lambda *_args: _context(),
        projection_builder=lambda *_args: _projection(),
        authoring_previewer=lambda *_args: author_preview,
        authoring_committer=lambda *_args: (
            log.append("write")
            or SimpleNamespace(
                write_result=SimpleNamespace(disposition="created"),
                written_revision=2,
                written_disposition="not_associated",
            )
        ),
        selection_previewer=lambda *_args: selection_preview,
        selection_committer=lambda *_args: (
            log.append("select")
            or SimpleNamespace(
                selection_disposition="updated",
                selected_revision=2,
                selected_disposition="not_associated",
                selected_basis="explicit",
            )
        ),
    )  # type: ignore[arg-type]


def test_new_evidence_menu_exposes_standards_follow_up() -> None:
    output = StringIO()
    run_new_evidence_menu(
        dependencies=_menu_deps(),
        action_dependencies=cast(object, object()),  # type: ignore[arg-type]
        attempt_dependencies=cast(object, object()),  # type: ignore[arg-type]
        standards_dependencies=_standards([]),
        input_fn=ScriptedInput("b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Author evidence / Standard association" in rendered
    assert "Select evidence / Standard association" in rendered
    assert "Grade Item authoring remains in Manage Grade Items." in rendered


def test_standards_write_cancel_does_not_commit() -> None:
    log: list[str] = []
    candidate = SimpleNamespace(
        disposition="not_associated",
        basis="explicit",
        association_revision=2,
        actor=SimpleNamespace(actor_id="teacher_1"),
    )
    preview = SimpleNamespace(
        candidate=candidate,
        projection=_projection(),
        expected_current_association_revision=1,
    )
    output = StringIO()
    run_new_evidence_menu(
        dependencies=_menu_deps(),
        action_dependencies=cast(object, object()),  # type: ignore[arg-type]
        attempt_dependencies=cast(object, object()),  # type: ignore[arg-type]
        standards_dependencies=_standards(log, author_preview=preview),
        input_fn=ScriptedInput(
            "6",
            "pub_00000000000000000000000000000000",
            "a" * 64,
            "grade_item_1",
            "teacher_review",
            "student_1",
            "item_1",
            "NJSLSA.R1",
            "four_level",
            "2",
            "b" * 64,
            "2",
            "2",
            "2",
            "teacher_1",
            "",
            "no",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == []
    rendered = output.getvalue()
    assert "Writing this revision will NOT select it." in rendered
    assert "No standards-association revision was written." in rendered


def test_standards_selection_requires_select_confirmation() -> None:
    log: list[str] = []
    preview = SimpleNamespace(
        projection=_projection(),
        target_revision=2,
        target_disposition="not_associated",
        target_basis="explicit",
        target_sha256="c" * 64,
        expected_current_association_revision=1,
    )
    run_new_evidence_menu(
        dependencies=_menu_deps(),
        action_dependencies=cast(object, object()),  # type: ignore[arg-type]
        attempt_dependencies=cast(object, object()),  # type: ignore[arg-type]
        standards_dependencies=_standards(log, selection_preview=preview),
        input_fn=ScriptedInput(
            "7",
            "pub_00000000000000000000000000000000",
            "a" * 64,
            "grade_item_1",
            "teacher_review",
            "student_1",
            "item_1",
            "NJSLSA.R1",
            "four_level",
            "2",
            "b" * 64,
            "2",
            "SELECT",
            "",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == ["select"]
