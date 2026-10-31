"""#123 Slice 8B: named Export Profile selection, exact CAS and no export."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_export_profile_selection as named
from meridian.teacher_navigation_choices import load_teacher_choices

CLASS = "verified-class"
PROFILE = "opaque-export-profile"
OLD_SHA = "a" * 64
NEW_SHA = "b" * 64
NOW = datetime(2026, 10, 25, 18, tzinfo=UTC)


def row(*, selected=3, latest=4, title="Local Gradebook Format"):
    return SimpleNamespace(
        profile_id=PROFILE,
        title=title,
        latest_revision=latest,
        current_revision=selected,
    )


def selected(*, revision=3, digest=OLD_SHA, title="Earlier Format"):
    return SimpleNamespace(
        class_id=CLASS,
        profile_id=PROFILE,
        title=title,
        purpose="For a local file",
        revision=revision,
        profile_sha256=digest,
        columns=(("row.status", "Status"),),
        format="csv",
        include_header=True,
        line_ending="lf",
        utf8_bom=False,
    )


def preview(
    *, latest=4, target_sha=NEW_SHA, current=True, title="Local Gradebook Format"
):
    reference = SimpleNamespace(
        class_id=CLASS,
        profile_id=PROFILE,
        profile_revision=latest,
        profile_sha256=target_sha,
    )
    witness = (
        SimpleNamespace(
            class_id=CLASS,
            profile_id=PROFILE,
            selection_revision=7,
            selection_sha256="c" * 64,
        )
        if current
        else None
    )
    return SimpleNamespace(target=reference, title=title, expected_current=witness)


def fixture(
    tmp_path, monkeypatch, *, answers=("teacher", "reviewed", "USE", ""), choice=True
):
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year="2026-2027")
    nav = MagicMock()
    nav.current_class.return_value = scope
    state = {
        "current": 3,
        "latest": 4,
        "title": "Local Gradebook Format",
        "sha": OLD_SHA,
    }
    lister = MagicMock(
        side_effect=lambda *_a: (
            row(
                selected=state["current"], latest=state["latest"], title=state["title"]
            ),
        )
    )
    loader = MagicMock(
        side_effect=lambda *_a: (
            None
            if state["current"] is None
            else selected(
                revision=state["current"],
                digest=state["sha"],
                title=state["title"] if state["current"] == 4 else "Earlier Format",
            )
        )
    )
    plan = preview()
    previewer = MagicMock(return_value=plan)

    def write(*_args):
        state["current"] = 4
        state["sha"] = NEW_SHA
        return "updated"

    committer = MagicMock(side_effect=write)
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    catalog = named.NamedExportProfileCatalog(nav, lister)
    selected_choice = load_teacher_choices(
        catalog, scope="export_profile", selected={"class": CLASS}
    )[0]
    lister.reset_mock()
    monkeypatch.setattr(
        named, "select_teacher_choice", lambda **_k: selected_choice if choice else None
    )
    values = iter(answers)
    output = StringIO()
    args = dict(
        navigation=nav,
        profile_lister=lister,
        profile_loader=loader,
        selection_previewer=previewer,
        selection_committer=committer,
        clock=lambda: NOW,
        input_fn=lambda _prompt: next(values),
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        profile_catalog=catalog,
    )
    return (
        args,
        state,
        nav,
        lister,
        loader,
        previewer,
        committer,
        output,
        selected_choice,
    )


def test_successfully_selects_latest_with_verified_readback(tmp_path, monkeypatch):
    args, state, _, lister, loader, previewer, committer, out, _ = fixture(
        tmp_path, monkeypatch
    )
    named.run_named_export_profile_selection(**args)
    assert state["current"] == 4
    assert state["sha"] == NEW_SHA
    committer.assert_called_once_with(tmp_path, preview(), "teacher", "reviewed", NOW)
    assert previewer.call_count == 2
    assert loader.call_count >= 3
    assert lister.call_count >= 3
    assert "selected for local use" in out.getvalue()
    assert "district/SIS" in out.getvalue()
    assert PROFILE not in out.getvalue()


def test_previewer_targets_exact_latest_revision_and_digest(tmp_path, monkeypatch):
    args, _, _, _, _, previewer, _, _, _ = fixture(tmp_path, monkeypatch)
    named.run_named_export_profile_selection(**args)
    previewer.assert_called_with(tmp_path, CLASS, PROFILE)


def test_catalog_keeps_names_and_technical_authority_separate(tmp_path, monkeypatch):
    args, _, _, _, _, _, _, _, choice = fixture(tmp_path, monkeypatch)
    assert choice.identity == (PROFILE,)
    assert PROFILE not in choice.display
    assert "Latest authored version 4" in choice.display
    assert choice.witness == "4:3"


def test_cancellation_does_not_commit(tmp_path, monkeypatch):
    args, _, _, _, _, _, committer, out, _ = fixture(
        tmp_path, monkeypatch, answers=("teacher", "reviewed", "", "")
    )
    named.run_named_export_profile_selection(**args)
    committer.assert_not_called()
    assert "Canceled" in out.getvalue()


def test_empty_teacher_attribution_stops_before_preview(tmp_path, monkeypatch):
    args, _, _, _, _, previewer, committer, out, _ = fixture(
        tmp_path, monkeypatch, answers=("", "")
    )
    named.run_named_export_profile_selection(**args)
    previewer.assert_not_called()
    committer.assert_not_called()
    assert "unavailable" in out.getvalue()


def test_cancel_chooser_stops_before_selected_read(tmp_path, monkeypatch):
    args, _, _, _, loader, previewer, committer, out, _ = fixture(
        tmp_path, monkeypatch, choice=False
    )
    named.run_named_export_profile_selection(**args)
    loader.assert_not_called()
    previewer.assert_not_called()
    committer.assert_not_called()
    assert out.getvalue() == ""


def test_already_current_no_write_or_attribution(tmp_path, monkeypatch):
    args, state, _, lister, loader, previewer, committer, out, _ = fixture(
        tmp_path, monkeypatch
    )
    state.update(current=4, sha=NEW_SHA)
    options = load_teacher_choices(
        args["profile_catalog"], scope="export_profile", selected={"class": CLASS}
    )
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_k: options[0])
    named.run_named_export_profile_selection(**args)
    assert "already selected" in out.getvalue()
    assert "No selection was changed" in out.getvalue()
    committer.assert_not_called()
    previewer.assert_not_called()


@pytest.mark.parametrize(
    "invalid",
    ["class", "family", "version", "title", "current_missing", "current_extra"],
)
def test_invalid_preview_fails_closed(tmp_path, monkeypatch, invalid):
    args, state, _, _, _, previewer, committer, out, _ = fixture(tmp_path, monkeypatch)
    if invalid == "class":
        previewer.return_value.target.class_id = "other"
    elif invalid == "family":
        previewer.return_value.target.profile_id = "other"
    elif invalid == "version":
        previewer.return_value.target.profile_revision = 3
    elif invalid == "title":
        previewer.return_value.title = "Different title"
    elif invalid == "current_missing":
        previewer.return_value.expected_current = None
    else:
        state["current"] = None
        choice = load_teacher_choices(
            args["profile_catalog"], scope="export_profile", selected={"class": CLASS}
        )[0]
        monkeypatch.setattr(named, "select_teacher_choice", lambda **_k: choice)
        previewer.return_value.expected_current = preview().expected_current
    named.run_named_export_profile_selection(**args)
    assert "No selection was attempted" in out.getvalue()
    committer.assert_not_called()


def test_changed_profile_in_lister_blocks_before_commit(tmp_path, monkeypatch):
    args, state, _, _, _, _, committer, out, _ = fixture(tmp_path, monkeypatch)
    state["title"] = "Replaced Name"
    named.run_named_export_profile_selection(**args)
    assert "changed" in out.getvalue()
    committer.assert_not_called()


def test_selected_revision_changes_before_commit(tmp_path, monkeypatch):
    args, state, _, _, loader, _, committer, out, _ = fixture(tmp_path, monkeypatch)
    original = loader.side_effect
    count = 0

    def changed(*a):
        nonlocal count
        count += 1
        result = original(*a)
        if count >= 3 and result is not None:
            return selected(revision=2)
        return result

    loader.side_effect = changed
    named.run_named_export_profile_selection(**args)
    assert "No selection was attempted" in out.getvalue()
    committer.assert_not_called()


def test_preview_cas_changes_between_confirmation_and_write(tmp_path, monkeypatch):
    args, _, _, _, _, previewer, committer, out, _ = fixture(tmp_path, monkeypatch)
    newer = preview()
    newer.expected_current.selection_sha256 = "d" * 64
    previewer.side_effect = [preview(), newer]
    named.run_named_export_profile_selection(**args)
    assert "No selection was attempted" in out.getvalue()
    committer.assert_not_called()


def test_commit_conflict_reports_uncertain_no_success(tmp_path, monkeypatch):
    args, _, _, _, _, _, committer, out, _ = fixture(tmp_path, monkeypatch)
    committer.side_effect = RuntimeError("sensitive private /student/grade")
    named.run_named_export_profile_selection(**args)
    assert "outcome could not be verified" in out.getvalue()
    assert "/student/grade" not in out.getvalue()
    assert "selected for local use" not in out.getvalue()


def test_post_commit_digest_mismatch_uncertain(tmp_path, monkeypatch):
    args, state, _, _, loader, _, committer, out, _ = fixture(tmp_path, monkeypatch)

    def write(*_a):
        state["current"] = 4
        state["sha"] = "z" * 64
        return "updated"

    committer.side_effect = write
    named.run_named_export_profile_selection(**args)
    assert "outcome is uncertain" in out.getvalue()
    assert "selected for local use" not in out.getvalue()


def test_post_commit_lister_missing_current_uncertain(tmp_path, monkeypatch):
    args, state, _, lister, _, _, committer, out, _ = fixture(tmp_path, monkeypatch)

    def write(*_a):
        state["sha"] = NEW_SHA
        return "created"

    committer.side_effect = write
    named.run_named_export_profile_selection(**args)
    assert "outcome is uncertain" in out.getvalue()
    assert "selected for local use" not in out.getvalue()


def test_unrecognized_disposition_uncertain(tmp_path, monkeypatch):
    args, _, _, _, _, _, committer, out, _ = fixture(tmp_path, monkeypatch)
    committer.side_effect = lambda *_a: "unrecognized"
    named.run_named_export_profile_selection(**args)
    assert "outcome is uncertain" in out.getvalue()


def test_unavailable_scope_redacts_errors(tmp_path, monkeypatch):
    args, _, nav, _, _, _, committer, out, _ = fixture(tmp_path, monkeypatch)
    nav.current_class.side_effect = RuntimeError("private roster /secret")
    named.run_named_export_profile_selection(**args)
    assert "/secret" not in out.getvalue()
    committer.assert_not_called()


@pytest.mark.parametrize("raised", [ReturnToMainMenu, QuitPDS])
def test_global_core_navigation_propagates(tmp_path, monkeypatch, raised):
    args, _, _, _, _, _, committer, out, _ = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(named, "_class", MagicMock(side_effect=raised))
    with pytest.raises(raised):
        named.run_named_export_profile_selection(**args)
    committer.assert_not_called()


def test_no_new_literal_raw_ids_or_file_export():
    source = Path(named.__file__).read_text(encoding="utf-8")
    assert 'read_choice(input_fn, "Export Profile ID' not in source
    assert 'read_choice(input_fn, "Class ID' not in source
    assert "commit_report_export(" not in source
    assert "select_export_profile(" not in source


def test_previous_export_routes_remain_when_new_choice_appears():
    menu = (Path(__file__).resolve().parents[1] / "meridian/menu_export.py").read_text(
        encoding="utf-8"
    )
    assert "7. Browse Export Profiles by name" in menu
    assert "8. Use latest Export Profile version by name" in menu
    assert "run_named_export_profile_selection(" in menu
    assert "Advanced: Preview and export a ReportingSnapshot" in menu
    bounds = re.findall(r"Please choose 1-(\d+), B, M, or Q\.", menu)
    assert any(int(bound) >= 8 for bound in bounds)
    assert "Please choose 1-6, B, M, or Q." in menu
