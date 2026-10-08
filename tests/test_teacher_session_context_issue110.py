from __future__ import annotations

from collections.abc import Callable
from io import StringIO

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef

from meridian.menu import TeacherMenuDependencies, run_menu
from meridian.teacher_session import TeacherSessionContext, TeacherSessionContextError


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _work(class_id: str = "class_1", work_id: str = "work_1") -> ModuleWorkRef:
    return ModuleWorkRef(
        module_id="scoreform",
        class_id=class_id,
        work_id=work_id,
    )


def _dependencies(
    session: TeacherSessionContext,
    *,
    review_new_evidence: Callable[[], None] = lambda: None,
    manage_grade_items: Callable[[], None] = lambda: None,
) -> TeacherMenuDependencies:
    return TeacherMenuDependencies(
        review_new_evidence=review_new_evidence,
        manage_grade_items=manage_grade_items,
        review_proficiency=lambda: None,
        preview_grades=lambda: None,
        overrides=lambda: None,
        snapshots=lambda: None,
        export=lambda: None,
        explain=lambda: None,
        session_context=session,
    )


def _populate(session: TeacherSessionContext) -> None:
    session.select_work(_work())
    session.select_publication("pub_1")
    session.select_grade_item("grade_item_1")
    session.select_student("student_1")


def test_teacher_session_context_starts_empty_and_has_no_storage_surface() -> None:
    session = TeacherSessionContext()

    assert session.active_class_id is None
    assert session.active_work is None
    assert session.active_publication_id is None
    assert session.active_grade_item_id is None
    assert session.active_student_id is None
    assert not hasattr(session, "save")
    assert not hasattr(session, "load")
    assert not hasattr(session, "workspace_root")


def test_teacher_session_context_carries_exact_selected_identity() -> None:
    session = TeacherSessionContext()
    _populate(session)

    assert session.active_class_id == "class_1"
    assert session.active_work == _work()
    assert session.active_publication_id == "pub_1"
    assert session.active_grade_item_id == "grade_item_1"
    assert session.active_student_id == "student_1"


def test_switching_class_clears_every_dependent_selection() -> None:
    session = TeacherSessionContext()
    _populate(session)

    session.select_class("class_2")

    assert session.active_class_id == "class_2"
    assert session.active_work is None
    assert session.active_publication_id is None
    assert session.active_grade_item_id is None
    assert session.active_student_id is None


def test_switching_work_clears_stale_downstream_context() -> None:
    session = TeacherSessionContext()
    _populate(session)

    session.select_work(_work(work_id="work_2"))

    assert session.active_class_id == "class_1"
    assert session.active_work == _work(work_id="work_2")
    assert session.active_publication_id is None
    assert session.active_grade_item_id is None
    assert session.active_student_id is None


def test_switching_publication_clears_downstream_context() -> None:
    session = TeacherSessionContext()
    _populate(session)

    session.select_publication("pub_2")

    assert session.active_work == _work()
    assert session.active_publication_id == "pub_2"
    assert session.active_grade_item_id is None
    assert session.active_student_id is None


def test_reselecting_same_scope_preserves_valid_downstream_context() -> None:
    session = TeacherSessionContext()
    _populate(session)

    session.select_class("class_1")
    session.select_work(_work())
    session.select_publication("pub_1")
    session.select_grade_item("grade_item_1")

    assert session.active_publication_id == "pub_1"
    assert session.active_grade_item_id == "grade_item_1"
    assert session.active_student_id == "student_1"


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (
            lambda session: session.select_publication("pub_1"),
            "publication selection requires active work context",
        ),
        (
            lambda session: session.select_grade_item("grade_item_1"),
            "Grade Item selection requires active class context",
        ),
        (
            lambda session: session.select_student("student_1"),
            "student selection requires active class context",
        ),
    ],
)
def test_dependent_selection_never_guesses_missing_parent_context(
    operation: Callable[[TeacherSessionContext], None],
    message: str,
) -> None:
    session = TeacherSessionContext()

    with pytest.raises(TeacherSessionContextError, match=message):
        operation(session)


@pytest.mark.parametrize("value", ["", " class_1", "class_1 ", "class\n1"])
def test_session_identifiers_are_not_normalized(value: str) -> None:
    session = TeacherSessionContext()

    with pytest.raises(TeacherSessionContextError):
        session.select_class(value)


def test_normal_child_return_preserves_context_until_terminal_exit() -> None:
    session = TeacherSessionContext()
    observed: list[ModuleWorkRef | None] = []

    def review() -> None:
        session.select_work(_work())

    def grade_items() -> None:
        observed.append(session.active_work)

    assert run_menu(
        dependencies=_dependencies(
            session,
            review_new_evidence=review,
            manage_grade_items=grade_items,
        ),
        input_fn=ScriptedInput("1", "2", "q"),
        output=StringIO(),
        clear_fn=lambda: None,
    ) == 0

    assert observed == [_work()]
    assert session.active_class_id is None
    assert session.active_work is None


def test_return_to_main_menu_preserves_context_until_terminal_exit() -> None:
    session = TeacherSessionContext()
    observed: list[ModuleWorkRef | None] = []

    def review() -> None:
        session.select_work(_work())
        raise ReturnToMainMenu()

    def grade_items() -> None:
        observed.append(session.active_work)

    assert run_menu(
        dependencies=_dependencies(
            session,
            review_new_evidence=review,
            manage_grade_items=grade_items,
        ),
        input_fn=ScriptedInput("1", "2", "q"),
        output=StringIO(),
        clear_fn=lambda: None,
    ) == 0

    assert observed == [_work()]
    assert session.active_class_id is None
    assert session.active_work is None


def test_quit_from_child_discards_process_local_context() -> None:
    session = TeacherSessionContext()

    def review() -> None:
        _populate(session)
        raise QuitPDS()

    assert run_menu(
        dependencies=_dependencies(session, review_new_evidence=review),
        input_fn=ScriptedInput("1"),
        output=StringIO(),
        clear_fn=lambda: None,
    ) == 0

    assert session.active_class_id is None
    assert session.active_work is None
    assert session.active_publication_id is None
    assert session.active_grade_item_id is None
    assert session.active_student_id is None


@pytest.mark.parametrize("error", [EOFError(), KeyboardInterrupt()])
def test_terminal_exit_discards_existing_context(error: BaseException) -> None:
    session = TeacherSessionContext()
    _populate(session)

    def input_fn(prompt: str) -> str:
        _ = prompt
        raise error

    assert run_menu(
        dependencies=_dependencies(session),
        input_fn=input_fn,
        output=StringIO(),
        clear_fn=lambda: None,
    ) == 0

    assert session.active_class_id is None
    assert session.active_work is None
    assert session.active_publication_id is None
    assert session.active_grade_item_id is None
    assert session.active_student_id is None
