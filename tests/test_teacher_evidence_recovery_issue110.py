from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from meridian.diagnostics import DiagnosticsDependencies
from meridian.ingestion import CatalogMissingError
from meridian.menu_teacher_evidence import (
    TeacherEvidenceInboxMenuDependencies,
    _show_review_item,
    run_teacher_evidence_inbox_menu,
)
from meridian.teacher_evidence_continuation import TeacherEvidenceContinuation
from meridian.teacher_evidence_inbox import TeacherEvidenceInbox
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem
from meridian.teacher_session import TeacherSessionContext


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _dependencies(
    inbox_loader,
    *,
    continuation_resolver=None,
    catalog_rebuilder=lambda _root: object(),
) -> TeacherEvidenceInboxMenuDependencies:
    return TeacherEvidenceInboxMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        diagnostics=cast(DiagnosticsDependencies, object()),
        inbox_loader=inbox_loader,
        projection_preparer=lambda *_args: cast(object, SimpleNamespace()),
        review_loader=lambda *_args: cast(object, SimpleNamespace()),
        eligibility_handler=lambda *_args: None,
        attempt_handler=lambda *_args: None,
        standards_handler=lambda *_args: None,
        continuation_resolver=continuation_resolver,
        catalog_rebuilder=catalog_rebuilder,
    )


def test_missing_catalog_offers_bounded_rebuild_then_retries() -> None:
    loads = 0
    rebuilds = 0

    def load(_root, _diagnostics):
        nonlocal loads
        loads += 1
        if loads == 1:
            raise CatalogMissingError("missing derived catalog")
        return TeacherEvidenceInbox(groups=())

    def rebuild(_root):
        nonlocal rebuilds
        rebuilds += 1
        return object()

    output = StringIO()
    run_teacher_evidence_inbox_menu(
        dependencies=_dependencies(load, catalog_rebuilder=rebuild),
        session_context=TeacherSessionContext(),
        input_fn=ScriptedInput("1", "", "b"),
        output=output,
        clear_fn=lambda: None,
    )

    assert loads == 2
    assert rebuilds == 1
    rendered = output.getvalue()
    assert "available-work index" in rendered
    assert "Rebuild the derived publication index" in rendered
    assert "No current academic evidence publications were found." in rendered


def test_empty_inbox_can_refresh_without_mutating_authority() -> None:
    loads = 0

    def load(_root, _diagnostics):
        nonlocal loads
        loads += 1
        return TeacherEvidenceInbox(groups=())

    output = StringIO()
    run_teacher_evidence_inbox_menu(
        dependencies=_dependencies(load),
        session_context=TeacherSessionContext(),
        input_fn=ScriptedInput("r", "b"),
        output=output,
        clear_fn=lambda: None,
    )

    assert loads == 2
    assert "R. Refresh evidence list" in output.getvalue()


def test_evidence_detail_recomputes_continue_after_child_return() -> None:
    state = {"action": "eligibility"}
    calls: list[str] = []

    def resolve(*_args):
        action = state["action"]
        label = {
            "eligibility": "Review eligibility",
            "attempts": "Review attempts / reassessment",
            "standards": "Review Standard association",
        }[action]
        return TeacherEvidenceContinuation(action, label, "Current state reloaded.")

    def eligibility(*_args):
        calls.append("eligibility")
        state["action"] = "attempts"

    def attempts(*_args):
        calls.append("attempts")
        state["action"] = "standards"

    deps = _dependencies(
        lambda *_args: TeacherEvidenceInbox(groups=()),
        continuation_resolver=resolve,
    )
    deps = TeacherEvidenceInboxMenuDependencies(
        workspace_resolver=deps.workspace_resolver,
        diagnostics=deps.diagnostics,
        inbox_loader=deps.inbox_loader,
        projection_preparer=deps.projection_preparer,
        review_loader=deps.review_loader,
        eligibility_handler=eligibility,
        attempt_handler=attempts,
        standards_handler=deps.standards_handler,
        continuation_resolver=resolve,
        catalog_rebuilder=deps.catalog_rebuilder,
    )

    output = StringIO()
    _show_review_item(
        root=Path("workspace"),
        prepared=cast(object, SimpleNamespace()),
        item=TeacherEvidenceReviewItem(
            item_id="hidden_item",
            student_id="00001",
            evidence_label="Attempt 1",
            value_label="8 / 10",
            result_kind_label="Submitted result",
            standard_ids=("RL.TS.11-12.4",),
        ),
        subject_label="Jane Smith",
        dependencies=deps,
        session_context=TeacherSessionContext(
            active_class_id="english_12_pd2"
        ),
        input_fn=ScriptedInput("c", "c", "b"),
        output=output,
        clear_fn=lambda: None,
    )

    assert calls == ["eligibility", "attempts"]
    rendered = output.getvalue()
    assert "C. Review eligibility" in rendered
    assert "C. Review attempts / reassessment" in rendered
    assert "C. Review Standard association" in rendered
    assert "hidden_item" not in rendered
    assert "00001" not in rendered
