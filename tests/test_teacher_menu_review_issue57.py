from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef

from meridian.diagnostics import DiagnosticsAuthorizationProviderRequiredError
from meridian.grade_items_workflow import GradeItemsReview
from meridian.menu_evidence import (
    EvidenceMenuDependencies,
    run_new_evidence_menu,
)
from meridian.menu_grade_items import (
    GradeItemsMenuDependencies,
    run_grade_items_menu,
)
from meridian.new_evidence_workflow import NewEvidenceReview


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _empty_grade_review(class_id: str = "class_1") -> GradeItemsReview:
    return GradeItemsReview(
        schema_version=1,
        class_id=class_id,
        items=(),
        active_count=0,
        archived_count=0,
        unselected_count=0,
        membership_relationship_count=0,
        membership_included_count=0,
        membership_excluded_count=0,
        membership_unselected_count=0,
    )


def _empty_evidence_review() -> NewEvidenceReview:
    return NewEvidenceReview(
        class_id="class_1",
        grade_item_id="grade_item_1",
        work=ModuleWorkRef(
            module_id="scoreform",
            class_id="class_1",
            work_id="assessment_1",
        ),
        publication_id="publication_1",
        cache_key="cache_1",
        snapshot_digest="a" * 64,
        projection_source_status="current",
        membership_state="no_decision",
        membership_revision=None,
        academic_period_id=None,
        academic_period_calendar_revision=None,
        rows=(),
        status_summary=(),
        attention_count=0,
    )


def test_grade_items_review_is_read_only_low_density() -> None:
    output = StringIO()
    observed: list[tuple[Path, str]] = []
    root = Path("synthetic-workspace")

    def load_review(workspace: Path, class_id: str) -> GradeItemsReview:
        observed.append((workspace, class_id))
        return _empty_grade_review(class_id)

    dependencies = GradeItemsMenuDependencies(
        workspace_resolver=lambda: root,
        review_loader=load_review,
    )

    run_grade_items_menu(
        dependencies=dependencies,
        input_fn=ScriptedInput("1", "class_1", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    assert observed == [(root, "class_1")]
    assert "Grade Items: 0" in rendered
    assert "Nothing was inferred from publications, dates, or evidence." in rendered
    assert "SHA-256" not in rendered
    assert "current.json" not in rendered


def test_grade_items_technical_details_reuse_same_review() -> None:
    output = StringIO()
    loads = 0

    def load_review(workspace: Path, class_id: str) -> GradeItemsReview:
        nonlocal loads
        _ = workspace
        loads += 1
        return _empty_grade_review(class_id)

    run_grade_items_menu(
        dependencies=GradeItemsMenuDependencies(
            workspace_resolver=lambda: Path("workspace"),
            review_loader=load_review,
        ),
        input_fn=ScriptedInput("1", "class_1", "t", "", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )

    assert loads == 1
    assert "Technical details / provenance" in output.getvalue()
    assert "class_id: class_1" in output.getvalue()


@pytest.mark.parametrize(("choice", "error"), [("m", ReturnToMainMenu), ("q", QuitPDS)])
def test_grade_items_menu_preserves_core_navigation(
    choice: str,
    error: type[BaseException],
) -> None:
    with pytest.raises(error):
        run_grade_items_menu(
            dependencies=GradeItemsMenuDependencies(
                workspace_resolver=lambda: Path("workspace"),
                review_loader=lambda _root, class_id: _empty_grade_review(class_id),
            ),
            input_fn=ScriptedInput(choice),
            output=StringIO(),
            clear_fn=lambda: None,
        )


def test_new_evidence_review_uses_exact_authorized_request() -> None:
    output = StringIO()
    observed: list[tuple[object, ...]] = []
    root = Path("workspace")

    def load_review(
        workspace: Path,
        publication_id: str,
        cache_key: str,
        grade_item_id: str,
        purpose_id: str,
        student_ids: tuple[str, ...],
    ) -> NewEvidenceReview:
        observed.append(
            (
                workspace,
                publication_id,
                cache_key,
                grade_item_id,
                purpose_id,
                student_ids,
            )
        )
        return _empty_evidence_review()

    run_new_evidence_menu(
        dependencies=EvidenceMenuDependencies(
            workspace_resolver=lambda: root,
            diagnostics=object(),  # type: ignore[arg-type]
            review_loader=load_review,
        ),
        input_fn=ScriptedInput(
            "1",
            "publication_1",
            "cache_1",
            "grade_item_1",
            "teacher_review",
            "student_1, student_2",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )

    assert observed == [
        (
            root,
            "publication_1",
            "cache_1",
            "grade_item_1",
            "teacher_review",
            ("student_1", "student_2"),
        )
    ]
    rendered = output.getvalue()
    assert "Evidence rows: 0" in rendered
    assert "snapshot_sha256" not in rendered


def test_new_evidence_technical_details_reuse_authorized_review() -> None:
    output = StringIO()
    loads = 0

    def load_review(
        _root: Path,
        _publication_id: str,
        _cache_key: str,
        _grade_item_id: str,
        _purpose_id: str,
        _student_ids: tuple[str, ...],
    ) -> NewEvidenceReview:
        nonlocal loads
        loads += 1
        return _empty_evidence_review()

    run_new_evidence_menu(
        dependencies=EvidenceMenuDependencies(
            workspace_resolver=lambda: Path("workspace"),
            diagnostics=object(),  # type: ignore[arg-type]
            review_loader=load_review,
        ),
        input_fn=ScriptedInput(
            "1",
            "publication_1",
            "cache_1",
            "grade_item_1",
            "teacher_review",
            "",
            "t",
            "",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )

    assert loads == 1
    rendered = output.getvalue()
    assert "Technical details / provenance" in rendered
    assert "publication_id: publication_1" in rendered
    assert f"snapshot_sha256: {'a' * 64}" in rendered


def test_new_evidence_fails_closed_without_authorizer() -> None:
    output = StringIO()
    opened = False

    def unavailable(
        _root: Path,
        _publication_id: str,
        _cache_key: str,
        _grade_item_id: str,
        _purpose_id: str,
        _student_ids: tuple[str, ...],
    ) -> NewEvidenceReview:
        nonlocal opened
        opened = True
        raise DiagnosticsAuthorizationProviderRequiredError("authorizer required")

    run_new_evidence_menu(
        dependencies=EvidenceMenuDependencies(
            workspace_resolver=lambda: Path("workspace"),
            diagnostics=object(),  # type: ignore[arg-type]
            review_loader=unavailable,
        ),
        input_fn=ScriptedInput(
            "1",
            "publication_1",
            "cache_1",
            "grade_item_1",
            "teacher_review",
            "",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )

    assert opened is True
    rendered = output.getvalue()
    assert "Protected evidence review is unavailable" in rendered
    assert "No evidence was opened." in rendered
    assert "deployment-provided authorization capability is required" in rendered


def test_new_evidence_back_does_not_open_evidence() -> None:
    called = False

    def load_review(
        _root: Path,
        _publication_id: str,
        _cache_key: str,
        _grade_item_id: str,
        _purpose_id: str,
        _student_ids: tuple[str, ...],
    ) -> NewEvidenceReview:
        nonlocal called
        called = True
        return _empty_evidence_review()

    run_new_evidence_menu(
        dependencies=EvidenceMenuDependencies(
            workspace_resolver=lambda: Path("workspace"),
            diagnostics=object(),  # type: ignore[arg-type]
            review_loader=load_review,
        ),
        input_fn=ScriptedInput("b"),
        output=StringIO(),
        clear_fn=lambda: None,
    )

    assert called is False
