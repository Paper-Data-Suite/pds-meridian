"""Teacher-facing contextual proficiency continuation for Issue #110."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

from meridian.guided_proficiency import (
    GuidedMappingProfileChoice,
    GuidedProficiencyContext,
    GuidedProficiencyDependencies,
    GuidedProficiencyError,
    GuidedProficiencyPolicyChoice,
    build_guided_proficiency_preview,
    commit_guided_proficiency_result,
    commit_guided_proficiency_selection,
    load_guided_proficiency_context,
    preview_guided_proficiency_result,
    preview_guided_proficiency_selection,
    proficiency_level_label,
    reload_current_guided_proficiency_result,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.guided_standards import GuidedScaleChoice, GuidedStandardChoice
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem


def _humanize(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _show_error(
    error: GuidedProficiencyError,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Proficiency Continuation Unavailable")
    write_lines(
        output,
        "The selected evidence could not continue to proficiency safely.",
        "No proficiency result was written or selected.",
        "",
        f"Details: {error}",
    )
    pause_for_user(input_fn)


def _show_blocker(
    title: str,
    *lines: str,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, title)
    write_lines(output, *lines)
    pause_for_user(input_fn)


def _choose_policy(
    choices: tuple[GuidedProficiencyPolicyChoice, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GuidedProficiencyPolicyChoice | None:
    while True:
        clear_fn()
        print_menu_header(output, "Choose Proficiency Policy")
        write_lines(
            output,
            "Choose the configured calculation policy for this preview.",
            "Meridian will not choose a proficiency policy for you.",
            "",
        )
        for index, choice in enumerate(choices, start=1):
            print(f"{index}. {choice.display_label}", file=output)
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(choices):
                return choices[index - 1]
        write_lines(
            output,
            "",
            f"Please choose 1-{len(choices)}, B, M, or Q.",
        )
        pause_for_user(input_fn)


def _choose_mapping(
    choices: tuple[GuidedMappingProfileChoice, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GuidedMappingProfileChoice | None:
    while True:
        clear_fn()
        print_menu_header(output, "Choose Evidence Mapping")
        write_lines(
            output,
            "Choose how this producer-native evidence maps to the selected scale.",
            "Only current exact-signature mappings are shown.",
            "",
        )
        for index, choice in enumerate(choices, start=1):
            print(f"{index}. {choice.display_label}", file=output)
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(choices):
                return choices[index - 1]
        write_lines(
            output,
            "",
            f"Please choose 1-{len(choices)}, B, M, or Q.",
        )
        pause_for_user(input_fn)


def _show_preview(
    *,
    context: GuidedProficiencyContext,
    reviewed: object,
    subject_label: str,
    grade_item_label: str,
    standard: GuidedStandardChoice,
    scale: GuidedScaleChoice,
    policy: GuidedProficiencyPolicyChoice,
    mapping: GuidedMappingProfileChoice,
    evidence: TeacherEvidenceReviewItem,
    output: TextIO,
) -> None:
    calculation = getattr(reviewed, "calculation")
    outcome = calculation.outcome
    level = proficiency_level_label(context, outcome.proficiency_level_id)
    print_menu_header(output, "Proficiency Preview")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Grade Item: {grade_item_label}",
        f"Standard: {standard.label}",
        f"Scale: {scale.title}",
        f"Policy: {policy.title}",
        f"Strategy: {_humanize(policy.strategy)}",
        f"Mapping: {mapping.display_label}",
        f"Evidence: {evidence.evidence_label} · {evidence.value_label}",
        "",
        f"Status: {_humanize(outcome.status)}",
        f"Proficiency: {level or 'Not calculated'}",
        (
            "Evidence outcome: "
            f"{outcome.performance_observation_count} performance, "
            f"{outcome.native_state_count} native-state, "
            f"{outcome.excluded_count} excluded"
        ),
        "",
        "This preview uses only the evidence row you just reviewed.",
        "It is read-only; no proficiency result has been written or selected.",
    )


def run_guided_proficiency_menu(
    *,
    workspace_root: Path,
    prepared: GuidedProjectionResult,
    evidence: TeacherEvidenceReviewItem,
    subject_label: str,
    grade_item_id: str,
    grade_item_label: str,
    standard: GuidedStandardChoice,
    scale: GuidedScaleChoice,
    dependencies: GuidedProficiencyDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    """Preview and optionally persist/select one contextual proficiency result."""

    if evidence.student_id is None:
        _show_blocker(
            "Student Proficiency Not Applicable",
            "Shared evidence does not carry a roster student.",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    try:
        context = load_guided_proficiency_context(
            workspace_root,
            prepared,
            evidence,
            scale,
            dependencies=dependencies,
        )
    except GuidedProficiencyError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    if not context.policies:
        _show_blocker(
            "Proficiency Policy Needed",
            (
                f"No current calculation policy targets {scale.title}. "
                "Configure/select a proficiency policy before continuing."
            ),
            "No policy identifier is required in this guided route.",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    if not context.mappings:
        _show_blocker(
            "Evidence Mapping Needed",
            (
                "No current mapping profile matches this evidence type and "
                f"{scale.title}."
            ),
            "Configure/select a mapping profile before continuing.",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    policy = _choose_policy(
        context.policies,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if policy is None:
        return

    mapping = _choose_mapping(
        context.mappings,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if mapping is None:
        return

    try:
        reviewed = build_guided_proficiency_preview(
            workspace_root,
            prepared,
            context,
            grade_item_id=grade_item_id,
            student_id=evidence.student_id,
            standard=standard,
            policy=policy,
            mapping=mapping,
            dependencies=dependencies,
        )
    except GuidedProficiencyError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    _show_preview(
        context=context,
        reviewed=reviewed,
        subject_label=subject_label,
        grade_item_label=grade_item_label,
        standard=standard,
        scale=scale,
        policy=policy,
        mapping=mapping,
        evidence=evidence,
        output=output,
    )
    write_lines(
        output,
        "",
        "1. Write this proficiency result",
        "2. Finish for now",
    )
    if read_choice(input_fn) != "1":
        return

    teacher = read_choice(input_fn, "Teacher name for attribution: ").strip()
    if not teacher:
        return

    try:
        write_preview = preview_guided_proficiency_result(
            workspace_root,
            reviewed,
            teacher_attribution=teacher,
            dependencies=dependencies,
        )
    except GuidedProficiencyError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Review Proficiency Result Before Write")
    _show_preview(
        context=context,
        reviewed=reviewed,
        subject_label=subject_label,
        grade_item_label=grade_item_label,
        standard=standard,
        scale=scale,
        policy=policy,
        mapping=mapping,
        evidence=evidence,
        output=output,
    )
    write_lines(
        output,
        "",
        "Writing creates one immutable calculated result.",
        "It does not make that result current until you select it.",
        "",
        "1. Write this result",
        "2. Cancel",
    )
    if read_choice(input_fn) != "1":
        return

    try:
        written = commit_guided_proficiency_result(
            workspace_root,
            write_preview,
            dependencies=dependencies,
        )
        selection_preview = preview_guided_proficiency_selection(
            workspace_root,
            reviewed,
            written.written_revision,
            dependencies=dependencies,
        )
    except GuidedProficiencyError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Make Proficiency Result Current")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Standard: {standard.label}",
        "",
        "The calculated result was written but is not current yet.",
        "",
        "1. Make this result current",
        "2. Leave it unselected",
    )
    if read_choice(input_fn) != "1":
        return

    try:
        commit_guided_proficiency_selection(
            workspace_root,
            selection_preview,
            dependencies=dependencies,
        )
        current = reload_current_guided_proficiency_result(
            workspace_root,
            reviewed,
            dependencies=dependencies,
        )
        current_label = proficiency_level_label(
            context,
            current.snapshot.outcome.proficiency_level_id,
        )
    except GuidedProficiencyError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Proficiency Result Updated")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Grade Item: {grade_item_label}",
        f"Standard: {standard.label}",
        f"Current status: {_humanize(current.snapshot.outcome.status)}",
        f"Current proficiency: {current_label or 'Not calculated'}",
        "",
        "Current canonical proficiency state was reloaded after selection.",
    )
    pause_for_user(input_fn)


__all__ = ("run_guided_proficiency_menu",)
