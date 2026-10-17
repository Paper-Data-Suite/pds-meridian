"""Issue #121: opt-in teacher profile and safe classroom preference settings.

A local identity labels future records; it grants no evidence access. Saved
classroom hints are verified against Core before they enter transient navigation.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.school_years import SchoolYearStateError, get_active_school_year
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    clear_screen,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.teacher_preferences import (
    StoredTeacherNavigationPreferences,
    TeacherNavigationPreferences,
    TeacherNavigationPreferencesStore,
    TeacherPreferencesError,
    ValidatedResumeCandidate,
    _fingerprint,
    apply_verified_navigation,
    validate_resume_hint,
)
from meridian.teacher_profile import (
    StoredTeacherProfile,
    TeacherProfileError,
    TeacherProfileStore,
)
from meridian.teacher_session import TeacherSessionContext

WorkspaceResolver = Callable[[], Path]


def _message(
    output: TextIO,
    input_fn: InputFunction,
    clear_fn: ClearFunction,
    heading: str,
    *lines: str,
) -> None:
    clear_fn()
    print_menu_header(output, heading)
    write_lines(output, *lines)
    pause_for_user(input_fn)


def _confirmation(
    output: TextIO,
    input_fn: InputFunction,
    *lines: str,
    keyword: str,
) -> bool:
    write_lines(output, *lines, f"Type {keyword} to confirm; anything else cancels.")
    reply = read_choice(input_fn, "Confirmation: ")
    if reply != keyword:
        # Preserve standard Main/Quit navigation on cancellation.
        parse_navigation_choice(reply)
        write_lines(output, "Nothing was changed.")
        pause_for_user(input_fn)
        return False
    return True


def _profile_action(
    choice: str,
    store: TeacherProfileStore,
    current: StoredTeacherProfile | None,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    if choice == "1":
        if current is not None:
            _message(
                output,
                input_fn,
                clear_fn,
                "Saved Teacher Attribution",
                f"Name: {current.profile.display_name}",
                f"Actor ID (Advanced): {current.profile.actor_id}",
                "This is attribution only, not authentication or authorization.",
            )
            return
        clear_fn()
        print_menu_header(output, "Set Up Teacher Profile")
        name = read_choice(input_fn, "Name for future academic attribution: ")
        if not name:
            _message(output, input_fn, clear_fn, "Not Saved", "Name is required.")
            return
        if _confirmation(
            output,
            input_fn,
            f"Future attribution name: {name}",
            "A stable actor ID will be generated; no Grades will change.",
            keyword="SAVE",
        ):
            saved = store.create(name)
            _message(
                output,
                input_fn,
                clear_fn,
                "Teacher Profile Saved",
                f"Name: {saved.profile.display_name}",
                "Identity will be available on subsequent launches.",
            )
        return
    if current is None:
        _message(
            output,
            input_fn,
            clear_fn,
            "Set Up Profile First",
            "Choose option 1 to set up your teacher profile.",
        )
        return
    if choice == "2":
        clear_fn()
        print_menu_header(output, "Change Display Name (Advanced)")
        name = read_choice(input_fn, "New display name: ")
        if _confirmation(
            output,
            input_fn,
            f"Current: {current.profile.display_name}",
            f"New: {name}",
            "The stable actor ID and historical records stay unchanged.",
            keyword="SAVE",
        ):
            store.update_display_name(current, name)
            _message(
                output,
                input_fn,
                clear_fn,
                "Display Name Saved",
                "Future attribution will use the updated display name.",
            )
    elif choice == "3":
        clear_fn()
        print_menu_header(output, "Replace Attribution Identity (Advanced)")
        name = read_choice(input_fn, "Name for the new identity: ")
        if _confirmation(
            output,
            input_fn,
            f"Current: {current.profile.display_name}",
            f"New: {name}",
            "Creates a different actor ID for FUTURE decisions only.",
            "This will not modify or reattribute historical records.",
            keyword="CHANGE",
        ):
            store.replace_identity(current, display_name=name, confirmed=True)
            _message(
                output,
                input_fn,
                clear_fn,
                "Identity Replaced",
                "Future writes can use the new identity.",
            )
    elif choice == "4":
        clear_fn()
        print_menu_header(output, "Reset Saved Profile (Advanced)")
        if _confirmation(
            output,
            input_fn,
            f"Saved identity: {current.profile.display_name}",
            "Deletes only the local profile; no academic records are deleted.",
            keyword="RESET",
        ):
            store.reset(current, confirmed=True)
            _message(
                output,
                input_fn,
                clear_fn,
                "Profile Reset",
                "Set up a new profile before authoring future decisions.",
            )


def _resume_candidate(
    root: Path,
    preferences: StoredTeacherNavigationPreferences | None,
) -> ValidatedResumeCandidate:
    return validate_resume_hint(root, preferences)


def _save_navigation(
    session: TeacherSessionContext,
    store: TeacherNavigationPreferencesStore,
    root: Path,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    if session.active_class_id is None:
        _message(
            output,
            input_fn,
            clear_fn,
            "No Active Class",
            "Choose a class in Review New Evidence first.",
        )
        return
    school_year = get_active_school_year(root)
    if school_year is None:
        _message(
            output,
            input_fn,
            clear_fn,
            "No Active School Year",
            "Configure a current school year in PDS Core first.",
        )
        return
    candidate = TeacherNavigationPreferences(
        revision=1,
        workspace_fingerprint=_fingerprint(root),
        school_year=school_year,
        class_id=session.active_class_id,
        work=session.active_work,
    )
    staged = StoredTeacherNavigationPreferences(candidate, "")
    verified = _resume_candidate(root, staged)
    if (verified.school_year, verified.class_id, verified.work) != (
        school_year,
        session.active_class_id,
        session.active_work,
    ):
        _message(
            output,
            input_fn,
            clear_fn,
            "Classroom Context Is Stale",
            "The selected class/assessment did not pass Core validation.",
            "Reopen the class and try again.",
        )
        return
    prior = store.load()
    cross_workspace = (
        prior is not None
        and prior.preferences.workspace_fingerprint != candidate.workspace_fingerprint
    )
    clear_fn()
    print_menu_header(output, "Save Classroom Preference")
    keyword = "REPLACE" if cross_workspace else "SAVE"
    lines = [
        f"School year: {school_year}",
        f"Class: {session.active_class_id}",
        "Assessment: "
        + (session.active_work.work_id if session.active_work is not None else "None"),
        "The preference is a navigation hint, not academic authority.",
    ]
    if cross_workspace:
        lines.append(
            "Existing preference is for another workspace and will be replaced."
        )
    if not _confirmation(output, input_fn, *lines, keyword=keyword):
        return
    # Re-validate immediately before saving; never persist a stale selection.
    latest = _resume_candidate(root, staged)
    if (latest.school_year, latest.class_id, latest.work) != (
        school_year,
        session.active_class_id,
        session.active_work,
    ):
        _message(
            output,
            input_fn,
            clear_fn,
            "Context Changed",
            "Refresh your classroom selection before saving.",
        )
        return
    store.save_selection(
        root,
        school_year=school_year,
        class_id=session.active_class_id,
        work=session.active_work,
        expected=prior,
    )
    _message(
        output,
        input_fn,
        clear_fn,
        "Preference Saved",
        "You can resume this class on a later launch.",
    )


def _resume_navigation(
    session: TeacherSessionContext,
    store: TeacherNavigationPreferencesStore,
    root: Path,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    if session.active_class_id is not None:
        _message(
            output,
            input_fn,
            clear_fn,
            "Class Already Selected",
            "Your active session selection has not been replaced.",
            "You may change class in Review New Evidence.",
        )
        return
    current = store.for_workspace(root)
    candidate = _resume_candidate(root, current)
    if not candidate.resumable:
        _message(
            output,
            input_fn,
            clear_fn,
            "Cannot Resume Saved Class",
            candidate.reason,
            "Select a current class normally; nothing was opened.",
        )
        return
    clear_fn()
    print_menu_header(output, "Resume Classroom Navigation")
    if not _confirmation(
        output,
        input_fn,
        f"School year: {candidate.school_year}",
        f"Class: {candidate.class_id}",
        "Assessment: " + (candidate.work.work_id if candidate.work else "None"),
        "No student, publication, evidence, or Grade will be restored.",
        keyword="RESUME",
    ):
        return
    refreshed = store.for_workspace(root)
    # An edited preferences file invalidates the teacher's reviewed selection.
    if refreshed is None or current is None or refreshed.sha256 != current.sha256:
        _message(
            output,
            input_fn,
            clear_fn,
            "Preferences Changed",
            "Reload saved preferences before resuming.",
        )
        return
    confirmed = _resume_candidate(root, refreshed)
    if confirmed != candidate or not apply_verified_navigation(session, confirmed):
        _message(
            output,
            input_fn,
            clear_fn,
            "Cannot Resume",
            "Context changed or another class is selected; nothing resumed.",
        )
        return
    _message(
        output,
        input_fn,
        clear_fn,
        "Class Navigation Restored",
        f"Class: {session.active_class_id}",
        "Any future academic action must revalidate its own current sources.",
    )


def _clear_navigation(
    store: TeacherNavigationPreferencesStore,
    root: Path,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    current = store.load()
    if current is None:
        _message(
            output,
            input_fn,
            clear_fn,
            "No Saved Preferences",
            "No classroom preference has been saved.",
        )
        return
    clear_fn()
    print_menu_header(output, "Clear Classroom Preferences")
    if not _confirmation(
        output,
        input_fn,
        "Clear saved school year, class, and assessment navigation hints?",
        "This will not clear your profile or change canonical academic records.",
        keyword="CLEAR",
    ):
        return
    store.save_selection(
        root, school_year=None, class_id=None, work=None, expected=current
    )
    _message(
        output,
        input_fn,
        clear_fn,
        "Classroom Preference Cleared",
        "Your current in-process navigation is unchanged.",
    )


def run_teacher_settings_menu(
    *,
    session_context: TeacherSessionContext,
    profile_store: TeacherProfileStore | None = None,
    preferences_store: TeacherNavigationPreferencesStore | None = None,
    workspace_resolver: WorkspaceResolver = resolve_workspace_root,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    """Explicit settings actions, injectable for scripted teacher acceptance."""
    stream = sys.stdout if output is None else output
    profile = profile_store or TeacherProfileStore()
    preferences = preferences_store or TeacherNavigationPreferencesStore(profile)
    while True:
        try:
            current = profile.load()
        except TeacherProfileError:
            _message(
                stream,
                input_fn,
                clear_fn,
                "Teacher Profile Unavailable",
                "Saved profile could not be read safely.",
                "No profile or academic records were changed.",
                "Correct local profile storage before retrying.",
            )
            return
        clear_fn()
        print_menu_header(stream, "Teacher Settings")
        if current is None:
            write_lines(
                stream, "Identity: Not configured", "", "1. Set up teacher profile"
            )
        else:
            write_lines(
                stream,
                f"Identity: {current.profile.display_name}",
                "",
                "1. View teacher attribution (Advanced)",
            )
        write_lines(
            stream,
            "2. Change display name (Advanced)",
            "3. Replace teacher identity (Advanced)",
            "4. Reset saved profile (Advanced)",
            "5. Save current class / assessment preference",
            "6. Resume verified saved class",
            "7. Clear saved classroom preference",
            "",
            "A saved identity does not grant access to student evidence.",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or choice == "":
            return
        try:
            if choice in {"1", "2", "3", "4"}:
                _profile_action(
                    choice,
                    profile,
                    current,
                    input_fn=input_fn,
                    output=stream,
                    clear_fn=clear_fn,
                )
            elif choice in {"5", "6", "7"}:
                root = workspace_resolver()
                if choice == "5":
                    _save_navigation(
                        session_context,
                        preferences,
                        root,
                        input_fn=input_fn,
                        output=stream,
                        clear_fn=clear_fn,
                    )
                elif choice == "6":
                    _resume_navigation(
                        session_context,
                        preferences,
                        root,
                        input_fn=input_fn,
                        output=stream,
                        clear_fn=clear_fn,
                    )
                else:
                    _clear_navigation(
                        preferences,
                        root,
                        input_fn=input_fn,
                        output=stream,
                        clear_fn=clear_fn,
                    )
            else:
                _message(
                    stream,
                    input_fn,
                    clear_fn,
                    "Unknown Setting",
                    "Choose an option from 1-7, or B to return.",
                )
        except (
            TeacherProfileError,
            TeacherPreferencesError,
            WorkspaceRootError,
            SchoolYearStateError,
            OSError,
            ValueError,
        ) as error:
            _message(
                stream,
                input_fn,
                clear_fn,
                "Settings Action Not Completed",
                str(error),
                "No academic records or access grants were changed.",
                "Reload the current settings before retrying.",
            )


__all__ = ["run_teacher_settings_menu"]
