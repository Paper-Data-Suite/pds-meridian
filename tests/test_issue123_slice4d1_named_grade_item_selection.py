"""#123 Slice 4D1: named immutable Grade Item revision and guarded adoption."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.grade_item_selection_workflow import GradeItemSelectionStaleError
from meridian.menu_teacher_named_revision import run_named_grade_item_revision_selection
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
    load_teacher_choices,
)
from meridian.teacher_navigation_revisions import TeacherGradeItemRevisionCatalog
from meridian.teacher_session import TeacherSessionContext

CLASS = "english-12"
YEAR = "2026-2027"
ITEM = "grade-item-opaque"
DIGEST1 = "a" * 64
DIGEST2 = "b" * 64


def setup(tmp_path: Path):
    session = TeacherSessionContext()
    session.select_class(CLASS)
    nav = MagicMock()
    nav.session = session
    verified = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    nav.verify_class.return_value = verified
    nav.current_class.return_value = verified
    history = MagicMock(return_value=(1, 2))
    pointer = MagicMock(return_value=1)
    review = MagicMock(
        return_value=SimpleNamespace(
            class_id=CLASS,
            items=(
                SimpleNamespace(
                    grade_item_id=ITEM, latest_persisted_revision=2, selected_revision=1
                ),
            ),
        )
    )
    revisions = {
        1: SimpleNamespace(
            revision=SimpleNamespace(
                class_id=CLASS,
                grade_item_id=ITEM,
                grade_item_revision=1,
                title="Reflective Essay",
                status="active",
                revised_at=SimpleNamespace(
                    date=lambda: SimpleNamespace(isoformat=lambda: "2026-09-01")
                ),
            ),
            revision_sha256=DIGEST1,
        ),
        2: SimpleNamespace(
            revision=SimpleNamespace(
                class_id=CLASS,
                grade_item_id=ITEM,
                grade_item_revision=2,
                title="Reflective Essay (revised)",
                status="active",
                revised_at=SimpleNamespace(
                    date=lambda: SimpleNamespace(isoformat=lambda: "2026-09-16")
                ),
            ),
            revision_sha256=DIGEST2,
        ),
    }
    loader = MagicMock(
        side_effect=lambda _root, _class, _item, number: revisions[number]
    )
    catalog = TeacherGradeItemRevisionCatalog(
        nav,
        review_loader=review,
        history_reader=history,
        revision_reader=loader,
        current_reader=pointer,
    )
    item_choice = TeacherChoice(identity=(ITEM,), label="Reflective Essay (revised)")

    class GradeCatalog:
        def options(self, *, scope, selected):
            assert scope == "grade_item"
            assert selected["class"] == CLASS
            return (item_choice,)

    grade_catalog = GradeCatalog()
    return nav, catalog, grade_catalog, item_choice, revisions, history, pointer, review


def choices(catalog):
    return load_teacher_choices(
        catalog,
        scope="grade_item_revision",
        selected={"class": CLASS, "grade_item": ITEM},
    )


def entries(*values: str):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def run(
    tmp_path,
    monkeypatch,
    values,
    *,
    target=2,
    mutator=None,
    fail_commit=None,
):
    import meridian.menu_teacher_named_review as named
    import meridian.menu_teacher_named_revision as screen

    nav, catalog, grades, item_choice, revisions, _hist, _pointer, review = setup(
        tmp_path
    )
    chosen = next(
        choice for choice in choices(catalog) if choice.identity == (str(target),)
    )
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: item_choice)
    monkeypatch.setattr(screen, "select_teacher_choice", lambda **_kw: chosen)
    preview = SimpleNamespace(
        class_id=CLASS,
        grade_item_id=ITEM,
        target_revision=target,
        target=revisions[target],
        expected_current_revision=1,
        target_status="active",
    )
    previewer = MagicMock(return_value=preview)
    committer = MagicMock(
        return_value=SimpleNamespace(
            selected_revision=target, selection_disposition="updated"
        )
    )
    if fail_commit is not None:
        committer.side_effect = fail_commit
    if mutator is not None:
        mutator(catalog, nav, revisions, previewer)
    screen_output = StringIO()
    run_named_grade_item_revision_selection(
        navigation=nav,
        review_loader=review,
        previewer=previewer,
        committer=committer,
        input_fn=entries(*values),
        output=screen_output,
        clear_fn=lambda: None,
        revision_catalog=catalog,
        grade_catalog=grades,
    )
    return screen_output.getvalue(), nav, previewer, committer


def test_labeled_history_has_opaque_exact_revision_but_no_digest(tmp_path):
    _nav, catalog, *_rest = setup(tmp_path)
    found = choices(catalog)
    assert len(found) == 2
    assert {c.identity for c in found} == {("1",), ("2",)}
    current = next(c for c in found if c.identity == ("1",))
    historical = next(c for c in found if c.identity == ("2",))
    assert "Reflective Essay (revised)" in historical.display
    assert "Version 2" in historical.display
    assert "Currently in use" in current.display
    assert "Not current" in historical.display
    assert DIGEST2 not in historical.display
    assert ITEM not in historical.display


def test_missing_history_fails_closed(tmp_path):
    _nav, catalog, _grades, _item, _revisions, history, *_ = setup(tmp_path)
    history.return_value = ()
    with pytest.raises(TeacherChoiceUnavailable, match="missing or unbounded"):
        catalog.options(
            scope="grade_item_revision", selected={"class": CLASS, "grade_item": ITEM}
        )


def test_overlarge_history_rejected_before_loading(tmp_path):
    _nav, catalog, _grades, _item, _revisions, history, *_ = setup(tmp_path)
    history.return_value = tuple(range(1, 102))
    with pytest.raises(TeacherChoiceUnavailable, match="unbounded"):
        catalog.options(
            scope="grade_item_revision", selected={"class": CLASS, "grade_item": ITEM}
        )
    catalog.revision_reader.assert_not_called()


def test_stale_current_pointer_blocks_catalog(tmp_path):
    _nav, catalog, _grades, _item, _revisions, _hist, pointer, *_ = setup(tmp_path)
    pointer.return_value = 999
    with pytest.raises(TeacherChoiceUnavailable, match="outside history"):
        catalog.options(
            scope="grade_item_revision", selected={"class": CLASS, "grade_item": ITEM}
        )


def test_stale_grade_item_review_blocks_catalog(tmp_path):
    _nav, catalog, _grades, _item, _revisions, _hist, pointer, review = setup(tmp_path)
    pointer.return_value = 2
    with pytest.raises(TeacherChoiceUnavailable, match="changed"):
        catalog.options(
            scope="grade_item_revision", selected={"class": CLASS, "grade_item": ITEM}
        )
    review.return_value.items[0].selected_revision = 2
    assert len(choices(catalog)) == 2


def test_wrong_class_or_revision_identity_blocks_catalog(tmp_path):
    _nav, catalog, _grades, _item, revisions, *_ = setup(tmp_path)
    revisions[2].revision.class_id = "different-class"
    with pytest.raises(TeacherChoiceUnavailable, match="identity"):
        catalog.options(
            scope="grade_item_revision", selected={"class": CLASS, "grade_item": ITEM}
        )


def test_invalid_scope_and_missing_parent_block_catalog(tmp_path):
    _nav, catalog, *_rest = setup(tmp_path)
    with pytest.raises(TeacherChoiceUnavailable):
        catalog.options(
            scope="something_else", selected={"class": CLASS, "grade_item": ITEM}
        )
    with pytest.raises(TeacherChoiceUnavailable):
        catalog.options(scope="grade_item_revision", selected={"class": CLASS})


def test_explicit_use_commits_once(tmp_path, monkeypatch):
    output, nav, previewer, committer = run(tmp_path, monkeypatch, ("USE", ""))
    assert "Grade Item version 2 is now current" in output
    assert (
        "does not create a new revision" in output
        or "no new revision was authored" in output
    )
    previewer.assert_called_once()
    committer.assert_called_once()
    assert nav.session.active_grade_item_id == ITEM


def test_cancel_after_review_never_commits(tmp_path, monkeypatch):
    output, nav, previewer, committer = run(tmp_path, monkeypatch, ("", ""))
    assert "Canceled" in output
    previewer.assert_called_once()
    committer.assert_not_called()
    assert nav.session.active_grade_item_id is None


def test_target_already_current_does_not_commit(tmp_path, monkeypatch):
    output, _nav, previewer, committer = run(tmp_path, monkeypatch, ("",), target=1)
    assert "already current" in output
    previewer.assert_called_once()
    committer.assert_not_called()


def test_stale_preview_target_blocks_without_commit(tmp_path, monkeypatch):
    def mutate(_catalog, _nav, revisions, _previewer):
        revisions[2].revision.title = "New name"

    output, _nav, _previewer, committer = run(
        tmp_path, monkeypatch, ("",), mutator=mutate
    )
    assert "could not be safely used" in output or "changed during review" in output
    committer.assert_not_called()


def test_stale_state_between_confirm_and_commit_blocks(tmp_path, monkeypatch):
    def mutate(catalog, _nav, _revisions, _previewer):
        original = catalog.current_reader
        count = 0

        def changed(*args):
            nonlocal count
            count += 1
            if count >= 2:
                return 2
            return original(*args)

        catalog.current_reader = changed

    output, _nav, _previewer, committer = run(
        tmp_path, monkeypatch, ("USE", ""), mutator=mutate
    )
    assert "changed during review" in output or "could not be safely used" in output
    committer.assert_not_called()


def test_domain_commit_conflict_remains_reported_as_blocker(tmp_path, monkeypatch):
    output, _nav, _previewer, committer = run(
        tmp_path,
        monkeypatch,
        ("USE", ""),
        fail_commit=GradeItemSelectionStaleError("pointer changed"),
    )
    assert "Refresh and review again" in output
    committer.assert_called_once()


def test_navigation_m_and_q_propagate(tmp_path, monkeypatch):
    import meridian.menu_teacher_named_review as named

    nav, catalog, grades, _item, _revs, _h, _p, review = setup(tmp_path)
    for exc in (ReturnToMainMenu, QuitPDS):
        monkeypatch.setattr(named, "select_teacher_choice", MagicMock(side_effect=exc))
        with pytest.raises(exc):
            run_named_grade_item_revision_selection(
                navigation=nav,
                review_loader=review,
                previewer=MagicMock(),
                committer=MagicMock(),
                input_fn=entries(),
                output=StringIO(),
                clear_fn=lambda: None,
                revision_catalog=catalog,
                grade_catalog=grades,
            )


def test_menu_has_guided_option_without_changing_direct_advanced_paths():
    root = Path(__file__).resolve().parents[1]
    source = (root / "meridian/menu_grade_items.py").read_text(encoding="utf-8")
    assert 'if choice == "8" and navigation_context is not None:' in source
    assert "run_named_grade_item_revision_selection(" in source
    assert 'if choice == "4":' in source
    assert "Advanced: Select Grade Item revision" in source
    assert "run_named_grade_item_revision_selection" in source
    assert ":notes" not in (root / "meridian/menu_teacher_named_revision.py").read_text(
        encoding="utf-8"
    )
