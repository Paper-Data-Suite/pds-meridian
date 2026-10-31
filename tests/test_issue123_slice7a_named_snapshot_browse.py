"""#123 Slice 7A: named frozen-snapshot discovery without academic mutations."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_snapshots as named

CLASS = "class-canonical"
SNAPSHOT = "opaque-snapshot-id"
DIGEST = "a" * 64


def answers(*values: str):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def source():
    item = SimpleNamespace(
        snapshot_id=SNAPSHOT,
        definition_id="private-definition",
        definition_revision=2,
        school_year="2026-2027",
        period_id="mp1",
        calendar_revision=4,
        row_count=8,
        created_at="2026-10-20T14:33:00+00:00",
        snapshot_sha256=DIGEST,
    )
    return item


def setup(tmp_path, monkeypatch, *, chosen=True):
    item = source()
    navigation = MagicMock()
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    lister = MagicMock(return_value=(item,))
    inspector = MagicMock(
        return_value=SimpleNamespace(item=item, current_for_scope=True)
    )
    title = MagicMock(return_value="Marking Period Report")
    classes = MagicMock()
    catalog = named.FrozenSnapshotChoiceCatalog(navigation, lister, title)
    choice = catalog.options(scope="frozen_snapshot", selected={"class": CLASS})[0]
    lister.reset_mock()
    title.reset_mock()
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named,
        "select_teacher_choice",
        lambda **_kw: choice if chosen else None,
    )
    monkeypatch.setattr(
        named,
        "load_teacher_choices",
        lambda _catalog, *, scope, selected, **_kw: (choice,),
    )
    output = StringIO()
    return navigation, lister, inspector, title, classes, catalog, choice, output


def run(tmp_path, monkeypatch, *, chosen=True):
    nav, lst, insp, title, classes, catalog, choice, output = setup(
        tmp_path, monkeypatch, chosen=chosen
    )
    named.run_named_snapshot_browse(
        navigation=nav,
        lister=lst,
        inspector=insp,
        input_fn=answers(""),
        output=output,
        clear_fn=lambda: None,
        title_loader=title,
        class_catalog=classes,
        snapshot_catalog=catalog,
    )
    return output.getvalue(), nav, lst, insp, title, choice


def test_catalog_shows_real_definition_title_without_opaque_ids(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    lister = MagicMock(return_value=(source(),))
    title = MagicMock(return_value="Reading Progress Report")
    catalog = named.FrozenSnapshotChoiceCatalog(nav, lister, title)
    choices = catalog.options(scope="frozen_snapshot", selected={"class": CLASS})
    assert len(choices) == 1
    assert choices[0].label == "Reading Progress Report"
    assert SNAPSHOT not in choices[0].display
    assert "private-definition" not in choices[0].display
    assert DIGEST not in choices[0].display
    assert "8 rows" in choices[0].display
    assert choices[0].identity == (SNAPSHOT,)
    assert DIGEST in choices[0].witness
    title.assert_called_once_with(tmp_path, CLASS, "private-definition", 2)


def test_named_review_honors_actual_current_selection(tmp_path, monkeypatch):
    output, nav, lst, insp, _, _ = run(tmp_path, monkeypatch)
    assert "Marking Period Report" in output
    assert "Current for this reporting scope: yes" in output
    assert "Report rows: 8" in output
    assert SNAPSHOT not in output and DIGEST not in output
    assert "No snapshot was frozen or selected" in output
    assert insp.call_count == 2
    insp.assert_called_with(tmp_path, CLASS, SNAPSHOT)
    nav.session.select_student.assert_not_called()


def test_current_false_does_not_get_promoted_to_current(tmp_path, monkeypatch):
    nav, lst, insp, title, classes, catalog, choice, out = setup(tmp_path, monkeypatch)
    insp.return_value = SimpleNamespace(item=source(), current_for_scope=False)
    named.run_named_snapshot_browse(
        navigation=nav,
        lister=lst,
        inspector=insp,
        input_fn=answers(""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=classes,
        snapshot_catalog=catalog,
    )
    assert "Current for this reporting scope: no" in out.getvalue()


def test_cancel_performs_no_inspection(tmp_path, monkeypatch):
    text, _, _, inspector, _, _ = run(tmp_path, monkeypatch, chosen=False)
    assert text == ""
    inspector.assert_not_called()


def test_wrong_current_class_stops_before_inspector(tmp_path, monkeypatch):
    nav, lst, insp, title, classes, catalog, choice, out = setup(tmp_path, monkeypatch)
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id="another-class", school_year="2026-2027"
    )
    named.run_named_snapshot_browse(
        navigation=nav,
        lister=lst,
        inspector=insp,
        input_fn=answers(""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=classes,
        snapshot_catalog=catalog,
    )
    assert "changed" in out.getvalue().lower()
    insp.assert_not_called()


def test_bad_snapshot_id_stops_instead_of_guessing(tmp_path, monkeypatch):
    nav, lst, insp, title, classes, catalog, choice, out = setup(tmp_path, monkeypatch)
    lst.return_value = (replace_for(source(), snapshot_id="other"),)
    named.run_named_snapshot_browse(
        navigation=nav,
        lister=lst,
        inspector=insp,
        input_fn=answers(""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=classes,
        snapshot_catalog=catalog,
    )
    assert "changed" in out.getvalue().lower()
    insp.assert_not_called()


def replace_for(item, **kwargs):
    return SimpleNamespace(**{**vars(item), **kwargs})


def test_changed_snapshot_digest_is_blocked(tmp_path, monkeypatch):
    nav, lst, insp, title, classes, catalog, choice, out = setup(tmp_path, monkeypatch)
    insp.return_value = SimpleNamespace(
        item=replace_for(source(), snapshot_sha256="b" * 64),
        current_for_scope=True,
    )
    named.run_named_snapshot_browse(
        navigation=nav,
        lister=lst,
        inspector=insp,
        input_fn=answers(""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=classes,
        snapshot_catalog=catalog,
    )
    assert "changed" in out.getvalue().lower()
    assert insp.call_count == 1


def test_current_selector_change_between_reads_blocks_display(tmp_path, monkeypatch):
    nav, lst, insp, title, classes, catalog, choice, out = setup(tmp_path, monkeypatch)
    insp.side_effect = [
        SimpleNamespace(item=source(), current_for_scope=True),
        SimpleNamespace(item=source(), current_for_scope=False),
    ]
    named.run_named_snapshot_browse(
        navigation=nav,
        lister=lst,
        inspector=insp,
        input_fn=answers(""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=classes,
        snapshot_catalog=catalog,
    )
    assert "changed" in out.getvalue().lower()
    assert "Report rows:" not in out.getvalue()


def test_selection_disappears_after_inspection(tmp_path, monkeypatch):
    nav, lst, insp, title, classes, catalog, choice, out = setup(tmp_path, monkeypatch)
    count = 0

    def check(*_a, **_kw):
        nonlocal count
        count += 1
        return (choice,) if count < 3 else ()

    monkeypatch.setattr(named, "load_teacher_choices", check)
    named.run_named_snapshot_browse(
        navigation=nav,
        lister=lst,
        inspector=insp,
        input_fn=answers(""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=classes,
        snapshot_catalog=catalog,
    )
    assert "changed" in out.getvalue().lower()
    assert "Report rows:" not in out.getvalue()


def test_internal_exception_is_redacted(tmp_path, monkeypatch):
    nav, lst, insp, title, classes, catalog, choice, out = setup(tmp_path, monkeypatch)
    insp.side_effect = RuntimeError("sensitive /private/student/source")
    named.run_named_snapshot_browse(
        navigation=nav,
        lister=lst,
        inspector=insp,
        input_fn=answers(""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=classes,
        snapshot_catalog=catalog,
    )
    assert "/private/" not in out.getvalue()
    assert "could not be verified" in out.getvalue()


def test_catalog_blocks_unselected_class(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    lst = MagicMock(return_value=(source(),))
    cat = named.FrozenSnapshotChoiceCatalog(nav, lst, MagicMock(return_value="Report"))
    with pytest.raises(named.TeacherChoiceUnavailable):
        cat.options(scope="frozen_snapshot", selected={"class": "other"})
    lst.assert_not_called()


def test_catalog_blocks_unbounded_inventory_before_definition_reads(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    lst = MagicMock(return_value=(source(),) * 201)
    title = MagicMock(return_value="Report")
    cat = named.FrozenSnapshotChoiceCatalog(nav, lst, title)
    with pytest.raises(named.TeacherChoiceUnavailable):
        cat.options(scope="frozen_snapshot", selected={"class": CLASS})
    title.assert_not_called()


def test_cancel_main_and_quit_propagate(tmp_path, monkeypatch):
    for err in (ReturnToMainMenu, QuitPDS):
        nav, lst, insp, title, classes, catalog, choice, out = setup(
            tmp_path, monkeypatch
        )
        monkeypatch.setattr(named, "_class", MagicMock(side_effect=err))
        with pytest.raises(err):
            named.run_named_snapshot_browse(
                navigation=nav,
                lister=lst,
                inspector=insp,
                input_fn=answers(""),
                output=out,
                clear_fn=lambda: None,
                class_catalog=classes,
                snapshot_catalog=catalog,
            )
        insp.assert_not_called()


def test_menu_declares_named_route_and_retains_advanced_controls():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_snapshots.py"
    ).read_text(encoding="utf-8")
    assert "run_named_snapshot_browse(" in source
    assert "7. Browse frozen reporting checkpoints by name" in source
    assert 'if choice == "7" and navigation_context is not None:' in source
    for old in (
        "_list(",
        "_inspect(",
        "_show_current(",
        "_select(",
        "_freeze_snapshot(",
        "_author_definition(",
    ):
        assert old in source
