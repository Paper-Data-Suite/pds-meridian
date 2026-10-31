"""#123 Slice 7C: independently discover existing reporting definitions by name."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_definitions as named
from meridian.teacher_navigation_choices import load_teacher_choices

CLASS = "class-canonical"
DEFINITION = "opaque-definition-id"
SHA = "a" * 64


def item(**changes):
    data = dict(
        definition_id=DEFINITION,
        revision=3,
        sha256=SHA,
        title="Semester Progress Report",
        purpose="Review learning progress",
        school_year="2026-2027",
        period_id="mp1",
        revised_at="2026-10-23T18:00:00+00:00",
    )
    data.update(changes)
    return named.NamedDefinitionItem(**data)


def setup(tmp_path, monkeypatch, *, chosen=True):
    navigation = MagicMock()
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    lister = MagicMock(return_value=(item(),))
    catalog = named.NamedDefinitionCatalog(navigation, lister)
    choice = load_teacher_choices(
        catalog, scope="report_definition", selected={"class": CLASS}
    )[0]
    lister.reset_mock()
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(
        named,
        "select_teacher_choice",
        lambda **_kw: choice if chosen else None,
    )
    out = StringIO()
    return navigation, lister, catalog, choice, out


def run(tmp_path, monkeypatch, *, chosen=True):
    navigation, lister, catalog, choice, out = setup(
        tmp_path, monkeypatch, chosen=chosen
    )
    named.run_named_definition_browse(
        navigation=navigation,
        input_fn=lambda _prompt: "",
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        definition_catalog=catalog,
    )
    return out.getvalue(), navigation, lister


def test_canonical_definition_discovery_does_not_require_snapshots(
    tmp_path, monkeypatch
):
    definitions = ("family-1", "family-2")
    monkeypatch.setattr(
        named, "list_reporting_definition_ids", lambda *_args: definitions
    )
    revisions = MagicMock(return_value=(1, 2, 3))
    loader = MagicMock(
        side_effect=lambda root, cid, did, rev: SimpleNamespace(
            definition=SimpleNamespace(
                class_id=cid,
                definition_id=did,
                definition_revision=rev,
                title="Student Progress" if did == "family-1" else "Grade Report",
                purpose="Instructional review",
                target_period=SimpleNamespace(school_year="2026-2027", period_id="mp1"),
                revised_at=datetime(2026, 10, 23, tzinfo=UTC),
            ),
            definition_sha256="b" * 64,
        )
    )
    monkeypatch.setattr(named, "list_reporting_definition_revisions", revisions)
    monkeypatch.setattr(named, "load_reporting_definition_revision", loader)
    result = named._list_definitions(tmp_path, CLASS)
    assert len(result) == 2
    assert result[0].title == "Student Progress"
    assert result[0].revision == 3
    assert loader.call_count == 2
    assert revisions.call_count == 2


def test_catalog_shows_title_purpose_period_and_no_technical_id(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    catalog = named.NamedDefinitionCatalog(nav, lambda *_args: (item(),))
    choice = load_teacher_choices(
        catalog, scope="report_definition", selected={"class": CLASS}
    )[0]
    assert "Semester Progress Report" in choice.display
    assert "Review learning progress" in choice.display
    assert "mp1" in choice.display
    assert DEFINITION not in choice.display
    assert SHA not in choice.display
    assert choice.identity == (DEFINITION,)
    assert SHA in choice.witness


def test_browse_presents_latest_definition_but_no_snapshot(tmp_path, monkeypatch):
    output, navigation, lister = run(tmp_path, monkeypatch)
    assert "Semester Progress Report" in output
    assert "Latest authored revision: 3" in output
    assert "not a frozen checkpoint" in output
    assert "No ReportingSnapshot was frozen or selected" in output
    assert DEFINITION not in output and SHA not in output
    assert lister.call_count >= 2
    navigation.session.select_student.assert_not_called()


def test_empty_catalog_is_valid(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    choices = load_teacher_choices(
        named.NamedDefinitionCatalog(nav, lambda *_args: ()),
        scope="report_definition",
        selected={"class": CLASS},
    )
    assert choices == ()


def test_cancel_does_not_inspect_or_write(tmp_path, monkeypatch):
    text, _, lister = run(tmp_path, monkeypatch, chosen=False)
    assert text == ""
    lister.assert_not_called()


def test_scope_change_blocks_display(tmp_path, monkeypatch):
    nav, lister, cat, choice, out = setup(tmp_path, monkeypatch)
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id="another", school_year="2026-2027"
    )
    named.run_named_definition_browse(
        navigation=nav,
        input_fn=lambda _prompt: "",
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        definition_catalog=cat,
    )
    assert "changed" in out.getvalue().lower()
    assert "Report: Semester" not in out.getvalue()


@pytest.mark.parametrize(
    "changed",
    [
        dict(sha256="b" * 64),
        dict(revision=4),
        dict(title="Different Report"),
        dict(purpose="Different meaning"),
    ],
)
def test_change_in_latest_definition_blocks_review(tmp_path, monkeypatch, changed):
    nav, lister, cat, choice, out = setup(tmp_path, monkeypatch)
    lister.return_value = (item(**changed),)
    named.run_named_definition_browse(
        navigation=nav,
        input_fn=lambda _prompt: "",
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        definition_catalog=cat,
    )
    assert "changed" in out.getvalue().lower()
    assert "Latest authored revision: " not in out.getvalue()


def test_duplicate_names_are_rejected_instead_of_picked(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    cat = named.NamedDefinitionCatalog(
        nav,
        lambda *_args: (item(), item(definition_id="another-family")),
    )
    with pytest.raises(named.TeacherChoiceUnavailable):
        load_teacher_choices(cat, scope="report_definition", selected={"class": CLASS})


def test_wrong_class_and_scope_are_blocked(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    catalog = named.NamedDefinitionCatalog(nav, MagicMock(return_value=(item(),)))
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="something_else", selected={"class": CLASS})
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="report_definition", selected={"class": "wrong"})
    catalog.lister.assert_not_called()


def test_large_definition_inventory_blocks_before_reading_histories(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        named,
        "list_reporting_definition_ids",
        lambda *_args: tuple(f"id-{n}" for n in range(201)),
    )
    revisions = MagicMock()
    monkeypatch.setattr(named, "list_reporting_definition_revisions", revisions)
    with pytest.raises(named.TeacherChoiceUnavailable):
        named._list_definitions(tmp_path, CLASS)
    revisions.assert_not_called()


def test_empty_or_excessive_history_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(
        named, "list_reporting_definition_ids", lambda *_args: (DEFINITION,)
    )
    for history in ((), tuple(range(1, 502))):
        monkeypatch.setattr(
            named, "list_reporting_definition_revisions", lambda *_args: history
        )
        with pytest.raises(named.TeacherChoiceUnavailable):
            named._list_definitions(tmp_path, CLASS)


def test_corrupt_canonical_id_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(
        named, "list_reporting_definition_ids", lambda *_args: (DEFINITION,)
    )
    monkeypatch.setattr(
        named, "list_reporting_definition_revisions", lambda *_args: (1,)
    )
    monkeypatch.setattr(
        named,
        "load_reporting_definition_revision",
        lambda *_args: SimpleNamespace(
            definition=SimpleNamespace(
                class_id="wrong",
                definition_id=DEFINITION,
                definition_revision=1,
            )
        ),
    )
    with pytest.raises(named.TeacherChoiceUnavailable):
        named._list_definitions(tmp_path, CLASS)


def test_sensitive_error_is_redacted(tmp_path, monkeypatch):
    nav, lister, cat, choice, out = setup(tmp_path, monkeypatch)
    lister.side_effect = RuntimeError("sensitive /students/private/path")
    named.run_named_definition_browse(
        navigation=nav,
        input_fn=lambda _prompt: "",
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        definition_catalog=cat,
    )
    assert "/students/" not in out.getvalue()
    assert "could not be verified" in out.getvalue()


def test_core_navigation_exceptions_propagate(tmp_path, monkeypatch):
    nav, lister, cat, choice, out = setup(tmp_path, monkeypatch)
    for raised in (ReturnToMainMenu, QuitPDS):
        monkeypatch.setattr(named, "_class", MagicMock(side_effect=raised))
        with pytest.raises(raised):
            named.run_named_definition_browse(
                navigation=nav,
                input_fn=lambda _prompt: "",
                output=out,
                clear_fn=lambda: None,
                class_catalog=MagicMock(),
                definition_catalog=cat,
            )


def test_no_new_raw_id_prompt_sites():
    source = Path(named.__file__).read_text(encoding="utf-8")
    assert "read_choice(" not in source
    assert "Teacher actor ID: " not in source
    assert "select_reporting_snapshot(" not in source
    assert "write_reporting_definition_revision(" not in source
