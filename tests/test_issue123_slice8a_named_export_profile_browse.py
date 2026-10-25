"""#123 Slice 8A: class-scoped named Export Profile inspection, no mutations."""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_export_profiles as named
from meridian.teacher_navigation_choices import (
    TeacherChoiceUnavailable,
    load_teacher_choices,
)

CLASS = "class-opaque"
PROFILE = "opaque-export-profile"


def row(**changes):
    value = dict(
        profile_id=PROFILE,
        title="Local Gradebook Copy",
        latest_revision=4,
        current_revision=3,
    )
    value.update(changes)
    return SimpleNamespace(**value)


def current(**changes):
    value = dict(
        class_id=CLASS,
        profile_id=PROFILE,
        title="Local Gradebook Copy",
        purpose="Review local Grades",
        revision=3,
        profile_sha256="a" * 64,
        columns=(("student_name", "Student"), ("grade", "Current Grade")),
        format="csv",
        include_header=True,
        line_ending="lf",
        utf8_bom=False,
    )
    value.update(changes)
    return SimpleNamespace(**value)


def prepare(tmp_path, monkeypatch, *, chosen=True):
    navigation = MagicMock()
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    lister = MagicMock(return_value=(row(),))
    loader = MagicMock(return_value=current())
    catalog = named.NamedExportProfileCatalog(navigation, lister)
    choice = load_teacher_choices(
        catalog, scope="export_profile", selected={"class": CLASS}
    )[0]
    lister.reset_mock()
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named,
        "select_teacher_choice",
        lambda **_kwargs: choice if chosen else None,
    )
    output = StringIO()
    args = dict(
        navigation=navigation,
        profile_lister=lister,
        profile_loader=loader,
        input_fn=lambda _prompt: "",
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        profile_catalog=catalog,
    )
    return args, navigation, lister, loader, catalog, choice, output


def test_choice_displays_real_name_and_selected_status_without_id(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    options = load_teacher_choices(
        named.NamedExportProfileCatalog(nav, lambda *_args: (row(),)),
        scope="export_profile",
        selected={"class": CLASS},
    )
    assert len(options) == 1
    assert "Local Gradebook Copy" in options[0].display
    assert "Latest authored version 4" in options[0].display
    assert "Selected version 3" in options[0].display
    assert PROFILE not in options[0].display
    assert options[0].identity == (PROFILE,)


def test_successful_review_is_read_only(tmp_path, monkeypatch):
    args, nav, lister, loader, _, _, output = prepare(tmp_path, monkeypatch)
    named.run_named_export_profile_browse(**args)
    text = output.getvalue()
    assert "Local Gradebook Copy" in text
    assert "Review local Grades" in text
    assert "CSV" in text
    assert "Student, Current Grade" in text
    assert "newer version is available" in text
    assert "No report, file, receipt, or district/SIS record was written" in text
    assert PROFILE not in text
    assert loader.call_count == 2
    nav.session.select_student.assert_not_called()


def test_latest_selected_is_distinguished(tmp_path, monkeypatch):
    args, _, lister, loader, _, _, output = prepare(tmp_path, monkeypatch)
    lister.return_value = (row(latest_revision=3),)
    choice = load_teacher_choices(
        args["profile_catalog"], scope="export_profile", selected={"class": CLASS}
    )[0]
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_k: choice)
    named.run_named_export_profile_browse(**args)
    assert "latest authored version is selected" in output.getvalue()
    assert loader.call_count == 2


def test_older_selected_title_does_not_impersonate_latest(tmp_path, monkeypatch):
    args, _, _, loader, _, _, output = prepare(tmp_path, monkeypatch)
    loader.return_value = current(title="Earlier Profile Title")
    named.run_named_export_profile_browse(**args)
    text = output.getvalue()
    assert "Profile: Local Gradebook Copy" in text
    assert "Selected version title: Earlier Profile Title" in text
    assert "newer version is available" in text


def test_unselected_profile_displays_blocker(tmp_path, monkeypatch):
    args, _, lister, loader, _, _, output = prepare(tmp_path, monkeypatch)
    lister.return_value = (row(current_revision=None),)
    # Reconstruct the choice to reflect the unselected state.
    choice = load_teacher_choices(
        args["profile_catalog"], scope="export_profile", selected={"class": CLASS}
    )[0]
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_k: choice)
    loader.return_value = None
    named.run_named_export_profile_browse(**args)
    assert "No version is selected" in output.getvalue()
    assert "no profile was selected" in output.getvalue()


def test_cancel_never_reads_selected_record(tmp_path, monkeypatch):
    args, _, _, loader, _, _, out = prepare(tmp_path, monkeypatch, chosen=False)
    named.run_named_export_profile_browse(**args)
    assert out.getvalue() == ""
    loader.assert_not_called()


def test_no_active_class_stops_before_loader(tmp_path, monkeypatch):
    args, nav, _, loader, _, _, out = prepare(tmp_path, monkeypatch)
    nav.current_class.return_value = None
    named.run_named_export_profile_browse(**args)
    assert "changed" in out.getvalue()
    loader.assert_not_called()


def test_other_class_is_rejected_in_catalog(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    lister = MagicMock(return_value=(row(),))
    catalog = named.NamedExportProfileCatalog(nav, lister)
    with pytest.raises(TeacherChoiceUnavailable):
        catalog.options(scope="export_profile", selected={"class": "other"})
    lister.assert_not_called()


def test_unknown_scope_is_rejected(tmp_path):
    cat = named.NamedExportProfileCatalog(MagicMock(), MagicMock())
    with pytest.raises(TeacherChoiceUnavailable):
        cat.options(scope="receipt", selected={"class": CLASS})


def test_bounded_inventory_rejects_unverified_count(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    cat = named.NamedExportProfileCatalog(
        nav, lambda *_args: tuple(row(profile_id=str(i)) for i in range(201))
    )
    with pytest.raises(TeacherChoiceUnavailable):
        load_teacher_choices(cat, scope="export_profile", selected={"class": CLASS})


def test_duplicate_indistinguishable_names_cannot_be_guessed(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    cat = named.NamedExportProfileCatalog(
        nav, lambda *_args: (row(), row(profile_id="another-opaque-profile"))
    )
    with pytest.raises(TeacherChoiceUnavailable):
        load_teacher_choices(cat, scope="export_profile", selected={"class": CLASS})


@pytest.mark.parametrize(
    "changed",
    [
        dict(profile_id="different"),
        dict(title="Changed title"),
        dict(latest_revision=5),
        dict(current_revision=None),
    ],
)
def test_stale_named_choice_blocks_inspection(tmp_path, monkeypatch, changed):
    args, _, lister, loader, _, _, output = prepare(tmp_path, monkeypatch)
    lister.return_value = (row(**changed),)
    named.run_named_export_profile_browse(**args)
    assert "changed" in output.getvalue().lower()
    loader.assert_not_called()


@pytest.mark.parametrize(
    "changed", [dict(class_id="other"), dict(profile_id="changed"), dict(revision=4)]
)
def test_wrong_selected_profile_blocks_display(tmp_path, monkeypatch, changed):
    args, _, _, loader, _, _, output = prepare(tmp_path, monkeypatch)
    loader.return_value = current(**changed)
    named.run_named_export_profile_browse(**args)
    assert "changed" in output.getvalue().lower()
    assert "Column headings" not in output.getvalue()


def test_selector_changed_between_two_loads_is_blocked(tmp_path, monkeypatch):
    args, _, _, loader, _, _, output = prepare(tmp_path, monkeypatch)
    loader.side_effect = [current(), current(profile_sha256="b" * 64)]
    named.run_named_export_profile_browse(**args)
    assert "changed" in output.getvalue().lower()
    assert "Column headings" not in output.getvalue()


def test_current_selector_on_previously_unselected_profile_fails_closed(
    tmp_path, monkeypatch
):
    args, _, lister, loader, _, _, output = prepare(tmp_path, monkeypatch)
    lister.return_value = (row(current_revision=None),)
    choice = load_teacher_choices(
        args["profile_catalog"], scope="export_profile", selected={"class": CLASS}
    )[0]
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_k: choice)
    named.run_named_export_profile_browse(**args)
    assert "changed" in output.getvalue().lower()


def test_internal_errors_are_redacted(tmp_path, monkeypatch):
    args, _, _, loader, _, _, output = prepare(tmp_path, monkeypatch)
    loader.side_effect = RuntimeError("private /students/medical-path")
    named.run_named_export_profile_browse(**args)
    assert "/students/" not in output.getvalue()
    assert "could not be verified safely" in output.getvalue()


@pytest.mark.parametrize("signal", [ReturnToMainMenu, QuitPDS])
def test_core_navigation_exceptions_propagate(tmp_path, monkeypatch, signal):
    args, _, _, _, _, _, _ = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(named, "_class", MagicMock(side_effect=signal))
    with pytest.raises(signal):
        named.run_named_export_profile_browse(**args)


def test_no_new_raw_identifier_prompts_or_export_writes():
    code = Path(named.__file__).read_text(encoding="utf-8")
    assert "read_choice(" not in code
    assert "commit_report_export(" not in code
    assert "select_export_profile(" not in code
    assert "write_export_profile_revision(" not in code


def test_previous_export_routes_and_new_named_route_are_present():
    code = (Path(__file__).resolve().parents[1] / "meridian/menu_export.py").read_text(
        encoding="utf-8"
    )
    assert "7. Browse Export Profiles by name" in code
    assert "run_named_export_profile_browse(" in code
    assert "5. Preview and export a ReportingSnapshot" in code
    assert '"1": _profiles' in code
    bounds = re.findall(r"Please choose 1-(\d+), B, M, or Q\.", code)
    assert any(int(bound) >= 7 for bound in bounds)
    assert "Please choose 1-6, B, M, or Q." in code
