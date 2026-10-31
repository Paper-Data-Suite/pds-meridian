"""Meridian #123 Slice 4D2: named membership history and guarded Use."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_item_membership_selection_workflow import (
    GradeItemMembershipSelectionStaleError,
)
from meridian.menu_teacher_named_membership_selection import (
    run_named_membership_revision_selection,
)
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
    load_teacher_choices,
)
from meridian.teacher_navigation_membership_revisions import (
    TeacherMembershipRevisionCatalog,
)
from meridian.teacher_session import TeacherSessionContext

CLASS = "english-12"
YEAR = "2026-2027"
ITEM = "opaque-grade-item"
WORK = ModuleWorkRef("quillan", CLASS, "opaque-work")
DIGEST = "a" * 64
REG = 3


def setup(tmp_path: Path):
    session = TeacherSessionContext()
    session.select_class(CLASS)
    nav = MagicMock()
    nav.session = session
    verified = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    nav.verify_class.return_value = verified
    nav.current_class.return_value = verified
    nav.verify_period.return_value = SimpleNamespace(
        label="Marking Period 1", calendar_revision=2
    )
    registration = SimpleNamespace(
        work=WORK,
        school_year=YEAR,
        lifecycle="active",
        is_current_registration=True,
        registration_revision=REG,
    )
    registration_lister = MagicMock(return_value=(registration,))
    membership = SimpleNamespace(
        work=WORK,
        latest_persisted_revision=2,
        selected_revision=1,
        selected_revision_sha256="1" * 64,
    )
    grade_item = SimpleNamespace(
        grade_item_id=ITEM,
        title="Guava Memoir",
        status="active",
        selected_revision=2,
        selected_revision_sha256=DIGEST,
        memberships=(membership,),
    )
    review = MagicMock(
        return_value=SimpleNamespace(class_id=CLASS, items=(grade_item,))
    )
    history = MagicMock(return_value=(1, 2))
    current = MagicMock(return_value=1)
    decisions = {}
    for number, disposition in ((1, "excluded"), (2, "included")):
        decisions[number] = SimpleNamespace(
            decision=SimpleNamespace(
                class_id=CLASS,
                grade_item_id=ITEM,
                work_reference=SimpleNamespace(
                    work=WORK,
                    registration_revision=REG,
                ),
                membership_revision=number,
                decision=disposition,
                grade_item_revision=2,
                grade_item_revision_sha256=DIGEST,
                academic_period=(
                    None
                    if disposition == "excluded"
                    else SimpleNamespace(
                        period=SimpleNamespace(school_year=YEAR, period_id="mp1"),
                        calendar_revision=2,
                    )
                ),
                decided_at=datetime(2026, 10, 20, tzinfo=UTC),
            ),
            decision_sha256=str(number) * 64,
        )
    loader = MagicMock(side_effect=lambda _r, _c, _i, _w, n: decisions[n])
    catalog = TeacherMembershipRevisionCatalog(
        navigation=nav,
        review_loader=review,
        registration_lister=registration_lister,
        history_reader=history,
        revision_reader=loader,
        current_reader=current,
    )
    return (
        nav,
        catalog,
        grade_item,
        membership,
        registration,
        decisions,
        history,
        current,
    )


def context():
    return {
        "class": CLASS,
        "grade_item": ITEM,
        "module": WORK.module_id,
        "work": WORK.work_id,
    }


def choices(catalog):
    return load_teacher_choices(
        catalog, scope="membership_revision", selected=context()
    )


def entries(*values: str):
    seq = iter(values)
    return lambda _prompt: next(seq)


def test_versions_explain_status_period_and_hide_opaque_tokens(tmp_path):
    _, catalog, *_ = setup(tmp_path)
    found = choices(catalog)
    assert {x.identity for x in found} == {("1",), ("2",)}
    assert "Excluded relationship" in found[0].display
    assert "Included relationship" in found[1].display
    assert "Marking Period 1" in found[1].display
    assert "Available to use" in found[1].display
    assert DIGEST not in found[1].display
    assert WORK.work_id not in found[1].display


def test_missing_or_unbounded_history_fail_closed(tmp_path):
    _, catalog, _, _, _, _, history, _ = setup(tmp_path)
    for invalid in ((), tuple(range(1, 102)), (1, 3)):
        history.return_value = invalid
        with pytest.raises(TeacherChoiceUnavailable, match="missing or unbounded"):
            catalog.options(scope="membership_revision", selected=context())


def test_missing_or_ambiguous_membership_fails_closed(tmp_path):
    _, catalog, grade_item, membership, *_ = setup(tmp_path)
    grade_item.memberships = ()
    with pytest.raises(TeacherChoiceUnavailable, match="No unique"):
        catalog.options(scope="membership_revision", selected=context())
    grade_item.memberships = (membership, membership)
    with pytest.raises(TeacherChoiceUnavailable, match="No unique"):
        catalog.options(scope="membership_revision", selected=context())


def test_changed_registration_or_current_pointer_rejects_old_witness(tmp_path):
    (_, catalog, _item, _member, registration, _decisions, _history, current) = setup(
        tmp_path
    )
    original = choices(catalog)[1]
    registration.registration_revision += 1
    changed = choices(catalog)[1]
    assert changed != original
    assert changed.status == "Historical basis · Advanced only"
    registration.registration_revision -= 1
    current.return_value = 2
    with pytest.raises(TeacherChoiceUnavailable, match="changed"):
        catalog.options(scope="membership_revision", selected=context())


def test_stale_grade_item_basis_and_calendar_are_advanced_only(tmp_path):
    nav, catalog, item, _member, _registration, decisions, *_ = setup(tmp_path)
    item.selected_revision = 3
    assert all(x.status == "Historical basis · Advanced only" for x in choices(catalog))
    item.selected_revision = 2
    nav.verify_period.return_value.calendar_revision = 4
    found = choices(catalog)
    assert found[1].status == "Historical basis · Advanced only"
    assert found[0].status == "Available to use"
    decisions[2].decision.grade_item_revision = 1
    assert choices(catalog)[1].status == "Historical basis · Advanced only"


def test_wrong_identity_duplicate_registration_and_scope_block(tmp_path):
    _, catalog, _item, _member, registration, decisions, *_ = setup(tmp_path)
    with pytest.raises(TeacherChoiceUnavailable):
        catalog.options(scope="other", selected=context())
    with pytest.raises(TeacherChoiceUnavailable):
        catalog.options(scope="membership_revision", selected={"class": CLASS})
    catalog.registration_lister.return_value = (registration, registration)
    with pytest.raises(TeacherChoiceUnavailable, match="ambiguous"):
        catalog.options(scope="membership_revision", selected=context())
    catalog.registration_lister.return_value = (registration,)
    decisions[2].decision.class_id = "different-class"
    with pytest.raises(TeacherChoiceUnavailable, match="identity"):
        catalog.options(scope="membership_revision", selected=context())


def run(tmp_path, monkeypatch, values, *, target=2, mutate=None, fail=None):
    import meridian.menu_teacher_named_membership_selection as screen
    import meridian.menu_teacher_named_review as named

    (nav, catalog, _item, _membership, _registration, decisions, _hist, _current) = (
        setup(tmp_path)
    )
    item_choice = TeacherChoice(identity=(ITEM,), label="Guava Memoir")
    work_choice = TeacherChoice(
        identity=(WORK.module_id, WORK.work_id), label="Memoir Revision"
    )
    revision_choice = next(x for x in choices(catalog) if x.identity == (str(target),))
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: item_choice)
    monkeypatch.setattr(
        screen,
        "select_teacher_choice",
        lambda **kw: (
            work_choice if kw["scope"] == "registered_work" else revision_choice
        ),
    )

    class Catalog:
        def __init__(self, choice, expected_scope):
            self.choice = choice
            self.expected_scope = expected_scope

        def options(self, *, scope, selected):
            assert scope == self.expected_scope
            return (self.choice,)

    grades = Catalog(item_choice, "grade_item")
    works = Catalog(work_choice, "registered_work")
    preview = SimpleNamespace(
        class_id=CLASS,
        grade_item_id=ITEM,
        work=WORK,
        target_revision=target,
        target_decision=decisions[target].decision.decision,
        target=decisions[target],
        expected_current_membership_revision=1,
    )
    previewer = MagicMock(return_value=preview)
    committer = MagicMock(
        return_value=SimpleNamespace(
            selected_decision=decisions[target].decision.decision,
            selected_revision=target,
            selection_disposition="updated",
        )
    )
    if mutate:
        mutate(catalog, nav, decisions, previewer)
    if fail:
        committer.side_effect = fail
    output = StringIO()
    run_named_membership_revision_selection(
        navigation=nav,
        review_loader=catalog.review_loader,
        previewer=previewer,
        committer=committer,
        input_fn=entries(*values),
        output=output,
        clear_fn=lambda: None,
        grade_catalog=grades,
        work_catalog=works,
        revision_catalog=catalog,
    )
    return output.getvalue(), previewer, committer


def test_use_commits_exact_existing_decision(tmp_path, monkeypatch):
    output, previewer, committer = run(tmp_path, monkeypatch, ("USE", ""))
    assert "Current work relationship: included" in output
    previewer.assert_called_once()
    committer.assert_called_once()
    assert committer.call_args.args[1].target_revision == 2


def test_cancellation_never_commits(tmp_path, monkeypatch):
    output, _previewer, committer = run(tmp_path, monkeypatch, ("", ""))
    assert "Canceled" in output
    committer.assert_not_called()


def test_already_current_never_commits(tmp_path, monkeypatch):
    output, _previewer, committer = run(tmp_path, monkeypatch, ("",), target=1)
    assert "already current" in output
    committer.assert_not_called()


def test_changed_preview_digest_never_commits(tmp_path, monkeypatch):
    def change(_catalog, _nav, decisions, _previewer):
        decisions[2].decision_sha256 = "b" * 64

    output, _previewer, committer = run(tmp_path, monkeypatch, ("",), mutate=change)
    assert "changed" in output or "could not" in output
    committer.assert_not_called()


def test_historical_basis_is_advanced_only(tmp_path, monkeypatch):
    def change(catalog, _nav, _decisions, _previewer):
        registration = catalog.registration_lister.return_value[0]
        registration.registration_revision = 4

    output, previewer, committer = run(tmp_path, monkeypatch, ("",), mutate=change)
    assert "changed" in output or "could not" in output
    previewer.assert_not_called()
    committer.assert_not_called()


def test_stale_cas_failure_does_not_report_success(tmp_path, monkeypatch):
    output, _previewer, committer = run(
        tmp_path,
        monkeypatch,
        ("USE", ""),
        fail=GradeItemMembershipSelectionStaleError("stale"),
    )
    assert "changed" in output
    assert "now current" not in output
    committer.assert_called_once()


def test_main_and_quit_unwind_unchanged(tmp_path, monkeypatch):
    import meridian.menu_teacher_named_review as named

    nav, catalog, *_ = setup(tmp_path)
    for error in (ReturnToMainMenu, QuitPDS):
        monkeypatch.setattr(
            named, "select_teacher_choice", MagicMock(side_effect=error)
        )
        with pytest.raises(error):
            run_named_membership_revision_selection(
                navigation=nav,
                review_loader=catalog.review_loader,
                previewer=MagicMock(),
                committer=MagicMock(),
                input_fn=entries(),
                output=StringIO(),
                clear_fn=lambda: None,
            )


def test_menu_entry_is_teacher_first_only_and_advanced_remains():
    root = Path(__file__).resolve().parents[1]
    text = (root / "meridian/menu_grade_items.py").read_text(encoding="utf-8")
    assert "9. Use an existing work membership decision" in text
    assert 'if choice == "9" and navigation_context is not None:' in text
    assert "Advanced: Select work membership revision" in text
    assert "_select_membership(" in text
