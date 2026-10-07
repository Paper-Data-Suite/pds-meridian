from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef

from meridian.diagnostics import DiagnosticsDependencies
from meridian.guided_projection import (
    GuidedProjectionAuthorizationUnavailableError,
    GuidedProjectionResult,
)
from meridian.menu_teacher_evidence import (
    TeacherEvidenceInboxMenuDependencies,
    run_teacher_evidence_inbox_menu,
)
from meridian.teacher_evidence_inbox import (
    TeacherEvidenceClassGroup,
    TeacherEvidenceInbox,
    TeacherEvidenceInboxItem,
)
from meridian.teacher_session import TeacherSessionContext


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self._responses)


def _item(
    *,
    publication_id: str,
    class_id: str = "english_12_pd2",
    module_id: str = "scoreform",
    work_id: str = "memory_snapshot",
    work_title: str = "Memory Snapshot",
    producer_label: str = "ScoreForm",
    actionability: str = "ready",
    status_code: str = "ready_to_review",
) -> TeacherEvidenceInboxItem:
    return TeacherEvidenceInboxItem(
        publication_id=publication_id,
        work=ModuleWorkRef(module_id, class_id, work_id),
        school_year="2026-2027",
        class_label=class_id,
        work_title=work_title,
        producer_label=producer_label,
        actionability=actionability,  # type: ignore[arg-type]
        status_code=status_code,  # type: ignore[arg-type]
        canonical_state="current_selectable",
        canonical_error_code=None,
        drift_fields=(),
        support_reason_codes=(),
    )


def _group(
    class_id: str,
    *items: TeacherEvidenceInboxItem,
) -> TeacherEvidenceClassGroup:
    return TeacherEvidenceClassGroup(
        class_id=class_id,
        school_year="2026-2027",
        class_label=class_id,
        items=items,
    )


def _inbox(
    *groups: TeacherEvidenceClassGroup,
) -> TeacherEvidenceInbox:
    return TeacherEvidenceInbox(groups=groups)


def _prepared_result() -> GuidedProjectionResult:
    authorized = cast(
        object,
        SimpleNamespace(
            stored=SimpleNamespace(
                snapshot=SimpleNamespace(
                    inventory=SimpleNamespace(items=("one", "two")),
                )
            )
        ),
    )
    return GuidedProjectionResult(
        purpose_id="review_evidence",
        requested_student_ids=(),
        cache_disposition="created",
        authorized=authorized,  # type: ignore[arg-type]
    )


def _dependencies(
    inbox: TeacherEvidenceInbox,
    *,
    projection_preparer=None,
) -> TeacherEvidenceInboxMenuDependencies:
    diagnostics = cast(DiagnosticsDependencies, object())
    prepare = (
        projection_preparer
        if projection_preparer is not None
        else lambda _root, _work, _publication_id: _prepared_result()
    )
    return TeacherEvidenceInboxMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        diagnostics=diagnostics,
        inbox_loader=lambda _root, _diagnostics: inbox,
        projection_preparer=prepare,
    )


def _two_class_inbox() -> TeacherEvidenceInbox:
    english_12 = _group(
        "english_12_pd2",
        _item(
            publication_id="pub_11111111111111111111111111111111",
        ),
        _item(
            publication_id="pub_22222222222222222222222222222222",
            work_id="locke_identity",
            work_title="Locke Personal Identity",
            module_id="quillan",
            producer_label="Quillan",
        ),
    )
    english_10 = _group(
        "english_10_pd4",
        _item(
            publication_id="pub_33333333333333333333333333333333",
            class_id="english_10_pd4",
            module_id="quillan",
            work_id="desirees_baby",
            work_title="Désirée's Baby Analysis",
            producer_label="Quillan",
            actionability="blocked",
            status_code="reader_not_compatible",
        ),
    )
    return _inbox(english_12, english_10)


def test_first_screen_is_class_selection_not_workspace_wide_evidence_dump() -> None:
    output = StringIO()
    scripted = ScriptedInput("b")

    run_teacher_evidence_inbox_menu(
        dependencies=_dependencies(_two_class_inbox()),
        session_context=TeacherSessionContext(),
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    assert "Choose a class." in rendered
    assert "1. english_12_pd2" in rendered
    assert "2 evidence sets · 2 ready" in rendered
    assert "2. english_10_pd4" in rendered
    assert "1 evidence set · 0 ready · 1 needs attention" in rendered

    assert "Memory Snapshot" not in rendered
    assert "Locke Personal Identity" not in rendered
    assert "Désirée's Baby Analysis" not in rendered


def test_class_selection_then_shows_only_that_class_evidence() -> None:
    output = StringIO()

    run_teacher_evidence_inbox_menu(
        dependencies=_dependencies(_two_class_inbox()),
        session_context=TeacherSessionContext(),
        input_fn=ScriptedInput("1", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    assert "Class: english_12_pd2" in rendered
    assert "Memory Snapshot" in rendered
    assert "Locke Personal Identity" in rendered
    assert "Désirée's Baby Analysis" not in rendered


def test_selecting_class_updates_parent_session_scope() -> None:
    session = TeacherSessionContext()
    stale_work = ModuleWorkRef("quillan", "english_10_pd4", "old_work")
    session.select_work(stale_work)
    session.select_publication("pub_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    run_teacher_evidence_inbox_menu(
        dependencies=_dependencies(_two_class_inbox()),
        session_context=session,
        input_fn=ScriptedInput("1", "b", "b"),
        output=StringIO(),
        clear_fn=lambda: None,
    )

    assert session.active_class_id == "english_12_pd2"
    assert session.active_work is None
    assert session.active_publication_id is None


def test_ready_evidence_selection_carries_hidden_identity_into_session() -> None:
    inbox = _two_class_inbox()
    selected = inbox.groups[0].items[1]
    session = TeacherSessionContext()
    output = StringIO()

    run_teacher_evidence_inbox_menu(
        dependencies=_dependencies(inbox),
        session_context=session,
        input_fn=ScriptedInput("1", "2", "", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )

    assert session.active_class_id == "english_12_pd2"
    assert session.active_work == selected.work
    assert session.active_publication_id == selected.publication_id
    assert session.active_grade_item_id is None
    assert session.active_student_id is None

    rendered = output.getvalue()
    assert "Evidence Ready" in rendered
    assert "Evidence rows available: 2" in rendered
    assert "Authorized evidence is prepared for review." in rendered
    assert selected.publication_id not in rendered
    assert "Selected for this session" in rendered


def test_blocked_evidence_explains_reason_without_replacing_work_selection() -> None:
    blocked_group = _two_class_inbox().groups[1]
    blocked = blocked_group.items[0]
    session = TeacherSessionContext()
    existing = ModuleWorkRef("quillan", "english_10_pd4", "existing_work")
    session.select_work(existing)
    session.select_publication("pub_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    output = StringIO()

    run_teacher_evidence_inbox_menu(
        dependencies=_dependencies(_inbox(blocked_group)),
        session_context=session,
        input_fn=ScriptedInput("1", "1", "", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )

    assert session.active_class_id == "english_10_pd4"
    assert session.active_work == existing
    assert (
        session.active_publication_id
        == "pub_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    )

    rendered = output.getvalue()
    assert "Evidence Not Ready" in rendered
    assert "Reader not compatible" in rendered
    assert "installed reader is not compatible" in rendered
    assert blocked.publication_id not in rendered


def test_projection_auth_unavailable_is_teacher_facing_and_fail_closed() -> None:
    inbox = _two_class_inbox()
    selected = inbox.groups[0].items[0]
    session = TeacherSessionContext()
    output = StringIO()

    def unavailable(_root, _work, _publication_id):
        raise GuidedProjectionAuthorizationUnavailableError("not configured")

    run_teacher_evidence_inbox_menu(
        dependencies=_dependencies(
            inbox,
            projection_preparer=unavailable,
        ),
        session_context=session,
        input_fn=ScriptedInput("1", "1", "", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )

    assert session.active_class_id == "english_12_pd2"
    assert session.active_work is None
    assert session.active_publication_id is None

    rendered = output.getvalue()
    assert "Evidence access is not configured" in rendered
    assert "No protected evidence was opened." in rendered
    assert selected.publication_id not in rendered


def test_guided_route_never_prompts_for_infrastructure_identity() -> None:
    output = StringIO()
    scripted = ScriptedInput("1", "1", "", "b", "b")

    run_teacher_evidence_inbox_menu(
        dependencies=_dependencies(_two_class_inbox()),
        session_context=TeacherSessionContext(),
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    for forbidden in (
        "pub_11111111111111111111111111111111",
        "Publication ID",
        "cache key",
        "sha256",
        "Student ID",
        "policy ID",
        "revision",
    ):
        assert forbidden not in rendered
        assert all(forbidden not in prompt for prompt in scripted.prompts)


def test_back_from_evidence_returns_to_class_list() -> None:
    output = StringIO()

    run_teacher_evidence_inbox_menu(
        dependencies=_dependencies(_two_class_inbox()),
        session_context=TeacherSessionContext(),
        input_fn=ScriptedInput("1", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )

    assert output.getvalue().count("Choose a class.") == 2


def test_empty_inbox_is_a_bounded_teacher_facing_state() -> None:
    output = StringIO()

    run_teacher_evidence_inbox_menu(
        dependencies=_dependencies(TeacherEvidenceInbox(groups=())),
        session_context=TeacherSessionContext(),
        input_fn=ScriptedInput("b"),
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    assert "No current academic evidence publications were found." in rendered
    assert "Publication ID" not in rendered


@pytest.mark.parametrize(("choice", "error"), [("m", ReturnToMainMenu), ("q", QuitPDS)])
def test_class_list_preserves_core_navigation(
    choice: str,
    error: type[BaseException],
) -> None:
    with pytest.raises(error):
        run_teacher_evidence_inbox_menu(
            dependencies=_dependencies(_two_class_inbox()),
            session_context=TeacherSessionContext(),
            input_fn=ScriptedInput(choice),
            output=StringIO(),
            clear_fn=lambda: None,
        )


@pytest.mark.parametrize(("choice", "error"), [("m", ReturnToMainMenu), ("q", QuitPDS)])
def test_evidence_list_preserves_core_navigation(
    choice: str,
    error: type[BaseException],
) -> None:
    with pytest.raises(error):
        run_teacher_evidence_inbox_menu(
            dependencies=_dependencies(_two_class_inbox()),
            session_context=TeacherSessionContext(),
            input_fn=ScriptedInput("1", choice),
            output=StringIO(),
            clear_fn=lambda: None,
        )
