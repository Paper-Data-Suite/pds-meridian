"""#124 E2G3O3: named assessment discovery and guarded setup entry.

Core catalog choices are hints, not authorization. A fresh canonical
review may enter the correlated one-confirmation #122 workflow.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TextIO, cast

from pds_core.academic_period_storage import load_current_academic_period_calendar
from pds_core.class_metadata import load_class_metadata
from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)
from pds_core.routes import class_metadata_path
from pds_core.routing_models import ModuleWorkRef
from pds_core.workspace import resolve_workspace_root

from meridian.assessment_setup_choices import load_named_assessment_choices
from meridian.assessment_setup_preview import load_assessment_setup_preview
from meridian.grade_items import GradeItemPurpose
from meridian.guided_grade_items import (
    GuidedGradeItemBridgeDependencies,
    load_guided_grade_item_bridge_context,
)
from meridian.menu_teacher_assessment_setup_review import (
    TeacherAssessmentReviewOutcome,
    review_correlated_assessment_setup_once,
)
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
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import resolve_menu_actor
from meridian.teacher_navigation_choices import page_teacher_choices
from meridian.teacher_session import TeacherSessionContext

WorkspaceResolver = Callable[[], Path]


_PURPOSE_CHOICES: tuple[tuple[str, GradeItemPurpose], ...] = (
    ("Standards proficiency", "standards_proficiency"),
    ("Conventional grade", "conventional_grade"),
    ("Standards + conventional", "standards_and_conventional"),
    ("Reporting only", "reporting_only"),
)


def _offer_selected_assessment_setup(
    root: Path,
    session: TeacherSessionContext,
    work: ModuleWorkRef,
    *,
    year: str,
    period_id: str,
    registration_revision: int,
    setup_state: str,
    active_unlinked_ids: tuple[str, ...],
    dependencies: GuidedGradeItemBridgeDependencies,
    input_fn: InputFunction,
    output: TextIO,
) -> TeacherAssessmentReviewOutcome | None:
    """Only explicit teacher choices can reach the correlated #122 binder.

    The cached catalog row identifies a requested work, not an authorization.
    A new C1 preview rechecks all Core and Meridian sources before binding.
    Cancel returns None without requesting a write. Every uncertain result
    unwinds discovery instead of reoffering an unreviewed second APPLY.
    """

    def refuse(reason: str) -> TeacherAssessmentReviewOutcome:
        write_lines(
            output,
            "Assessment setup could not be verified safely.",
            "Use Review Interrupted Saves after any uncertain action.",
            "No additional setup attempt is authorized here.",
        )
        return TeacherAssessmentReviewOutcome("requires_review", reason)

    if (
        session.active_class_id != work.class_id
        or (session.active_work is not None and session.active_work != work)
        or setup_state not in ("ready", "needs_create", "choose_existing")
    ):
        return refuse("discovery_scope_or_relationship_requires_review")

    purpose: GradeItemPurpose | None = None
    existing_id: str | None = None
    title: str | None = None
    rationale: str | None = None
    actor: TeacherActionActor | None = None

    try:
        if setup_state != "ready":
            bridge = load_guided_grade_item_bridge_context(
                root, work, dependencies=dependencies
            )
            if (
                bridge.work != work
                or bridge.registration_revision != registration_revision
            ):
                return refuse("registration_changed_before_review")
            if setup_state == "choose_existing":
                available = tuple(
                    choice
                    for choice in bridge.existing_grade_items
                    if choice.grade_item_id in active_unlinked_ids
                )
                if not available:
                    return refuse("existing_grade_item_not_available")
                print_menu_header(output, "Choose Existing Grade Item")
                for index, item in enumerate(available, start=1):
                    print(
                        f"{index}. {item.display_label} "
                        f"({item.purpose.replace('_', ' ')})",
                        file=output,
                    )
                print_standard_navigation(output)
                raw = read_choice(input_fn)
                navigation = parse_navigation_choice(raw)
                if navigation is NavigationChoice.BACK or raw == "":
                    return None
                if not raw.isascii() or not raw.isdigit():
                    return refuse("existing_grade_item_choice_invalid")
                choice_index = int(raw)
                if not 1 <= choice_index <= len(available):
                    return refuse("existing_grade_item_choice_out_of_range")
                selected = available[choice_index - 1]
                existing_id = selected.grade_item_id
                purpose = cast(GradeItemPurpose, selected.purpose)
            else:
                print_menu_header(output, "Choose Grade Item Purpose")
                for index, (label, _) in enumerate(_PURPOSE_CHOICES, start=1):
                    print(f"{index}. {label}", file=output)
                print_standard_navigation(output)
                raw = read_choice(input_fn)
                navigation = parse_navigation_choice(raw)
                if navigation is NavigationChoice.BACK or raw == "":
                    return None
                if not raw.isascii() or not raw.isdigit():
                    return refuse("grade_item_purpose_invalid")
                choice_index = int(raw)
                if not 1 <= choice_index <= len(_PURPOSE_CHOICES):
                    return refuse("grade_item_purpose_out_of_range")
                purpose = _PURPOSE_CHOICES[choice_index - 1][1]
                title = read_choice(input_fn, "New Grade Item title: ")
                navigation = parse_navigation_choice(title)
                if navigation is NavigationChoice.BACK or title == "":
                    return None
            rationale_raw = read_choice(input_fn, "Rationale (blank if none): ")
            navigation = parse_navigation_choice(rationale_raw)
            if navigation is NavigationChoice.BACK:
                return None
            rationale = rationale_raw or None
            actor_id = read_choice(input_fn, "Saved teacher attribution ID: ")
            navigation = parse_navigation_choice(actor_id)
            if navigation is NavigationChoice.BACK or actor_id == "":
                return None
            actor = resolve_menu_actor(actor_id, input_fn)
            if actor.source != "saved" or actor.actor_id != actor_id:
                return refuse("saved_actor_not_verified")

        reviewed = load_assessment_setup_preview(
            root,
            class_id=work.class_id,
            school_year=year,
            period_id=period_id,
            work=work,
            dependencies=dependencies,
            purpose=purpose,
            existing_grade_item_id=existing_id,
            new_title=title,
            actor_attribution=None if actor is None else actor.actor_id,
            rationale=rationale,
        )
        if (
            reviewed.work != work
            or reviewed.school_year != year
            or reviewed.marking_period_id != period_id
            or reviewed.registration_revision != registration_revision
            or (reviewed.kind == "already_ready") != (setup_state == "ready")
        ):
            return refuse("fresh_assessment_review_changed")
        return review_correlated_assessment_setup_once(
            root,
            reviewed,
            session,
            actor=actor,
            dependencies=dependencies,
            input_fn=input_fn,
            output=output,
        )
    except (ReturnToMainMenu, QuitPDS):
        raise
    except Exception:
        return refuse("assessment_setup_context_unavailable")


def run_teacher_assessment_discovery_menu(
    *,
    session_context: TeacherSessionContext,
    input_fn: InputFunction = input,
    output: TextIO,
    clear_fn: ClearFunction = clear_screen,
    workspace_resolver: WorkspaceResolver = resolve_workspace_root,
    assessment_bridge_dependencies: GuidedGradeItemBridgeDependencies | None = None,
) -> None:
    """Browse Core registration hints; setup requires separate fresh review.

    The selected catalog row never becomes write authority. Only when
    trusted bridge dependencies are supplied does an explicit teacher
    selection enter the E2G3O2 correlated one-confirmation workflow.
    """
    if not isinstance(session_context, TeacherSessionContext):
        write_lines(output, "Assessment discovery requires a teacher session.")
        return
    class_id = session_context.active_class_id
    if class_id is None:
        write_lines(
            output,
            "Select a class in Teacher Settings before discovering assessments.",
            "No assessment setup or academic selection was requested.",
        )
        pause_for_user(input_fn)
        return
    try:
        root = Path(workspace_resolver()).resolve()
        metadata = load_class_metadata(class_metadata_path(root, class_id))
        if metadata.class_id != class_id:
            raise ValueError("Class metadata differs from the selected class.")
        year = metadata.school_year
        calendar = load_current_academic_period_calendar(root, year)
        if calendar is None or calendar.school_year != year:
            raise ValueError("Current school-year calendar is unavailable.")
        periods = tuple(
            sorted(
                (
                    period
                    for period in calendar.periods
                    if period.period_type == "marking_period"
                    and period.lifecycle != "cancelled"
                ),
                key=lambda period: (period.sequence, period.period_id),
            )
        )
        if not periods:
            raise ValueError("No named marking periods are available.")
    except Exception:
        write_lines(
            output,
            "Assessment discovery cannot verify the selected class/calendar.",
            "Inspect Core class metadata and academic periods before retrying.",
            "No academic record was changed.",
        )
        pause_for_user(input_fn)
        return

    while True:
        clear_fn()
        print_menu_header(output, "Discover Registered Assessments")
        write_lines(
            output,
            f"Class: {class_id}",
            f"School year: {year}",
            "Choose a marking period to inspect registered assessments.",
            "",
        )
        for index, period in enumerate(periods, start=1):
            print(f"{index}. {period.label}", file=output)
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return
        if not (raw.isascii() and raw.isdigit()):
            write_lines(output, "Select a numbered marking period, B, M, or Q.")
            pause_for_user(input_fn)
            continue
        ordinal = int(raw)
        if not 1 <= ordinal <= len(periods):
            write_lines(output, "The marking period number is unavailable.")
            pause_for_user(input_fn)
            continue
        selected_period = periods[ordinal - 1]
        try:
            named = load_named_assessment_choices(
                root,
                class_id=class_id,
                school_year=year,
                period_id=selected_period.period_id,
            )
            if (
                named.class_id != class_id
                or named.school_year != year
                or named.period_id != selected_period.period_id
            ):
                raise ValueError("Named assessment results escaped the selected scope.")
            by_identity = {item.choice.identity: item for item in named.items}
            if len(by_identity) != len(named.items) or len(named.choices) != len(
                named.items
            ):
                raise ValueError("Named assessment choices are ambiguous.")
        except Exception:
            write_lines(
                output,
                "Registered assessment choices could not be verified safely.",
                "Refresh Core's derived academic catalog and try again.",
                "No setup or academic selection was attempted.",
            )
            pause_for_user(input_fn)
            continue

        search = ""
        page_index = 0
        while True:
            page = page_teacher_choices(
                named.choices, query=search, page_index=page_index
            )
            page_index = page.page_number - 1
            clear_fn()
            print_menu_header(
                output,
                (
                    "Registered Assessments — Review Setup"
                    if assessment_bridge_dependencies is not None
                    else "Registered Assessments — Read Only"
                ),
            )
            write_lines(
                output,
                f"Class: {class_id}",
                f"Period: {selected_period.label} ({selected_period.period_id})",
                f"Matches: {page.match_count} | "
                f"Page {page.page_number} of {page.page_count}",
                "Catalog statuses are hints, not verified Grade Item readiness.",
                "",
            )
            for index, choice in enumerate(page.items, start=1):
                print(f"{index}. {choice.display}", file=output)
            if not page.items:
                write_lines(output, "No assessments match this search.")
            write_lines(
                output,
                "",
                "F. Find by name   C. Clear search",
                "N. Next page   P. Previous page",
                "B. Back to marking periods",
                "",
                (
                    "Open an assessment to review its setup."
                    if assessment_bridge_dependencies is not None
                    else "Setup execution is not enabled in this read-only view."
                ),
            )
            print_standard_navigation(output, back=False)
            raw = read_choice(input_fn)
            navigation = parse_navigation_choice(raw)
            if navigation is NavigationChoice.BACK or raw == "":
                break
            lowered = raw.casefold()
            if lowered == "n":
                if page.has_next:
                    page_index += 1
                continue
            if lowered == "p":
                if page.has_previous:
                    page_index -= 1
                continue
            if lowered == "c":
                search, page_index = "", 0
                continue
            if lowered == "f":
                value = read_choice(input_fn, "Assessment name search: ")
                if len(value) > 120 or any(ord(ch) < 32 for ch in value):
                    write_lines(
                        output, "Search must be at most 120 visible characters."
                    )
                    pause_for_user(input_fn)
                else:
                    search, page_index = value, 0
                continue
            if raw.isascii() and raw.isdigit():
                choice_number = int(raw)
                if 1 <= choice_number <= len(page.items):
                    choice = page.items[choice_number - 1]
                    selected = by_identity.get(choice.identity)
                    if selected is None:
                        write_lines(
                            output,
                            "Assessment identity changed; reopen discovery.",
                        )
                        pause_for_user(input_fn)
                        return
                    clear_fn()
                    print_menu_header(output, "Assessment Registration Detail")
                    write_lines(
                        output,
                        f"Assessment: {selected.candidate.title}",
                        f"Producer: {choice.source or 'Unknown'}",
                        f"Registration revision: "
                        f"{selected.candidate.registration_revision}",
                        f"Publication: {selected.publication_state}",
                        f"Catalog setup hint: {selected.candidate.setup_state}",
                        f"Marking period: {selected_period.label}",
                        "",
                        "The catalog is a hint, not Grade Item authority.",
                    )
                    if assessment_bridge_dependencies is None:
                        write_lines(
                            output,
                            "Setup execution is not enabled on this screen.",
                        )
                        pause_for_user(input_fn)
                        continue
                    write_lines(
                        output,
                        "S. Review setup or verify current relationship",
                        "B. Back to assessment list",
                    )
                    detail_choice = read_choice(input_fn)
                    detail_navigation = parse_navigation_choice(detail_choice)
                    if (
                        detail_navigation is NavigationChoice.BACK
                        or detail_choice == ""
                    ):
                        continue
                    if detail_choice.casefold() != "s":
                        write_lines(output, "Choose S or B to return.")
                        pause_for_user(input_fn)
                        continue
                    outcome = _offer_selected_assessment_setup(
                        root,
                        session_context,
                        selected.candidate.work,
                        year=year,
                        period_id=selected_period.period_id,
                        registration_revision=selected.candidate.registration_revision,
                        setup_state=selected.candidate.setup_state,
                        active_unlinked_ids=getattr(
                            selected.candidate, "active_unlinked_grade_item_ids", ()
                        ),
                        dependencies=assessment_bridge_dependencies,
                        input_fn=input_fn,
                        output=output,
                    )
                    if outcome is None or outcome.status == "cancelled":
                        continue
                    pause_for_user(input_fn)
                    # A completed or uncertain APPLY ends this discovery
                    # snapshot. Reopening requires new Core discovery/review.
                    return
            write_lines(output, "Choose a displayed number, F, C, N, P, B, M or Q.")
            pause_for_user(input_fn)


__all__ = ("run_teacher_assessment_discovery_menu",)
