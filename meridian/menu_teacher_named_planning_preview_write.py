"""Teacher-named, deliberately confirmed Planning Preview write (#123 10C).

Select an exact immutable saved #38 derivation by policy title, not canonical
identifiers. The existing #39 preview/commit services own source validation,
revalidation and persistence. No review, selection, Core or Concord write occurs.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.menu_teacher_named_explain_derivation import (
    PlanningDerivationChoiceCatalog,
    PlanningDerivationSummary,
)
from meridian.menu_teacher_named_grades import _current_choice, _ScopeChanged
from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    read_choice,
    write_lines,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.planning_signal_preview_write_workflow import (
        PlanningSignalPreviewWritePreview,
        PlanningSignalPreviewWriteResult,
    )

PreviewPreparer: TypeAlias = Callable[
    [Path, str, str, str, str], "PlanningSignalPreviewWritePreview"
]
PreviewCommitter: TypeAlias = Callable[
    [Path, "PlanningSignalPreviewWritePreview"], "PlanningSignalPreviewWriteResult"
]
_SHA = re.compile(r"^[0-9a-f]{64}$")


class _PreviewWriteChanged(RuntimeError):
    """Named source, prepared preview, or result failed exact verification."""


def _checked_preview(
    preview: PlanningSignalPreviewWritePreview,
    summary: PlanningDerivationSummary,
    class_id: str,
) -> tuple[int, int, int]:
    """Prove the prepared #39 operation uses the exact selected saved #38."""
    reference = preview.derivation_reference
    policy = preview.policy_reference
    counts = (
        preview.roster_student_count,
        preview.contributing_student_count,
        preview.noncontributing_student_count,
    )
    if (
        preview.class_id != class_id
        or preview.policy_id != summary.policy_id
        or preview.derivation_id != summary.derivation_id
        or preview.derivation_sha256 != summary.derivation_sha256
        or preview.calculation_fingerprint != summary.calculation_fingerprint
        or reference.class_id != class_id
        or reference.derivation_id != summary.derivation_id
        or reference.derivation_sha256 != summary.derivation_sha256
        or preview.stored_derivation.reference != reference
        or policy.class_id != class_id
        or policy.policy_id != summary.policy_id
        or policy.policy_revision != summary.policy_revision
        or policy.policy_sha256 != summary.policy_sha256
        or preview.stored_derivation.snapshot.policy_reference != policy
        or any(type(number) is not int or number < 0 for number in counts)
        or sum(counts[1:]) != counts[0]
        or counts[0] != summary.student_count
    ):
        raise _PreviewWriteChanged(
            "Prepared preview source differs from named derivation."
        )
    return counts


def _checked_result(
    result: PlanningSignalPreviewWriteResult,
    preview: PlanningSignalPreviewWritePreview,
    counts: tuple[int, int, int],
) -> None:
    """Validate the result before claiming an immutable preview was saved."""
    if (
        result.preview != preview
        or result.generation.derivation_reference != preview.derivation_reference
        or result.write_disposition not in {"created", "existing"}
        or not isinstance(result.preview_id, str)
        or not result.preview_id.startswith("gsp_")
        or not _SHA.fullmatch(result.preview_id[4:])
        or not isinstance(result.preview_sha256, str)
        or not _SHA.fullmatch(result.preview_sha256)
        or not isinstance(result.preview_fingerprint, str)
        or not _SHA.fullmatch(result.preview_fingerprint)
        or (
            result.roster_student_count,
            result.contributing_student_count,
            result.noncontributing_student_count,
        )
        != counts
        or result.review_write_action != "not_performed"
        or result.review_selection_action != "not_performed"
        or result.core_export_action != "not_performed"
        or result.csv_export_action != "not_performed"
    ):
        raise _PreviewWriteChanged(
            "Saved preview result failed provenance verification."
        )


def run_named_planning_preview_write(
    *,
    navigation: TeacherNavigationContext,
    preview_preparer: PreviewPreparer,
    preview_committer: PreviewCommitter,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    derivation_catalog: PlanningDerivationChoiceCatalog | None = None,
) -> None:
    """One named saved derivation, one reviewed #39 write, no chained actions."""
    attempted = False
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        catalog = derivation_catalog or PlanningDerivationChoiceCatalog(navigation)
        active = _class(
            navigation, classes, input_fn=input_fn, output=output, clear_fn=clear_fn
        )
        if active is None:
            return
        root, class_id = active
        verified = navigation.current_class()
        if (
            verified is None
            or verified.workspace != root
            or verified.class_id != class_id
        ):
            raise _PreviewWriteChanged("Class context changed before selection.")
        chosen = select_teacher_choice(
            catalog=catalog,
            scope="planning_derivation",
            selected={"class": class_id},
            title="Saved Planning Derivations",
            question="Which saved derivation should have a Planning Preview?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen is None:
            return

        def check_scope() -> PlanningDerivationSummary:
            if navigation.current_class() != verified:
                raise _PreviewWriteChanged("Selected class changed.")
            _current_choice(
                catalog,
                scope="planning_derivation",
                selected={"class": class_id},
                choice=chosen,
            )
            if len(chosen.identity) != 1:
                raise _PreviewWriteChanged("Derivation selection identity is invalid.")
            current = catalog.inspect(root, class_id, chosen.identity[0])
            if (
                current.school_year != verified.school_year
                or current.choice() != chosen
            ):
                raise _PreviewWriteChanged("Saved derivation selection changed.")
            return current

        summary = check_scope()
        preview = preview_preparer(
            root,
            class_id,
            summary.policy_id,
            summary.derivation_id,
            summary.derivation_sha256,
        )
        counts = _checked_preview(preview, summary, class_id)
        if check_scope() != summary:
            raise _PreviewWriteChanged("Saved derivation changed during preparation.")
        while True:
            if check_scope() != summary:
                raise _PreviewWriteChanged(
                    "Saved derivation changed before confirmation."
                )
            clear_fn()
            print_menu_header(output, "Review Planning Preview Before Write")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Marking period: {summary.period_label} ({summary.school_year})",
                f"Standard: {summary.standard_id}",
                f"Dimension: {summary.dimension_id}",
                f"Bands: {summary.band_count}",
                f"Students: {counts[0]} rostered, {counts[1]} contributing, "
                f"{counts[2]} noncontributing",
                "",
                "This is an immutable saved derivation, not a current policy decision.",
                "WRITE creates only its Planning Preview.",
                "No teacher review, selection, Core export or Concord group is made.",
                "Type WRITE to save. B or blank cancels; M or Q navigates.",
                "T. Technical details of the selected derivation",
            )
            choice = read_choice(input_fn, "Confirmation: ")
            if choice.casefold() == "t":
                if check_scope() != summary:
                    raise _PreviewWriteChanged(
                        "Saved derivation changed before details."
                    )
                clear_fn()
                print_menu_header(output, "Planning Preview — Technical Source")
                write_lines(
                    output,
                    f"class_id: {class_id}",
                    f"policy_id: {summary.policy_id}",
                    f"policy_revision: {summary.policy_revision}",
                    f"policy_sha256: {summary.policy_sha256}",
                    f"derivation_id: {summary.derivation_id}",
                    f"derivation_sha256: {summary.derivation_sha256}",
                    f"calculation_fingerprint: {summary.calculation_fingerprint}",
                )
                pause_for_user(input_fn)
                continue
            navigation_choice = parse_navigation_choice(choice)
            if navigation_choice is NavigationChoice.BACK or not choice:
                write_lines(output, "No Planning Preview was written.")
                return
            if choice != "WRITE":
                write_lines(output, "No Planning Preview was written.")
                pause_for_user(input_fn)
                return
            if check_scope() != summary:
                raise _PreviewWriteChanged(
                    "Saved derivation changed before persistence."
                )
            attempted = True
            # Existing commit service checks the exact saved #38 source again.
            result = preview_committer(root, preview)
            _checked_result(result, preview, counts)
            clear_fn()
            print_menu_header(output, "Planning Preview Saved")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Marking period: {summary.period_label}",
                f"Students: {counts[0]} rostered",
                f"Save outcome: {result.write_disposition}",
                f"Snapshot currentness: {result.currentness_state.replace('_', ' ')}",
                f"Warning diagnostics: {len(result.warning_diagnostic_ids)}",
                f"Blocking diagnostics: {len(result.blocking_diagnostic_ids)}",
                "",
                "No teacher review, selection, Core export or Concord group was made.",
            )
            pause_for_user(input_fn)
            return
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_PreviewWriteChanged, _ScopeChanged):
        write_lines(
            output,
            "Class, saved derivation, or reviewed Planning Preview changed.",
            (
                "Check saved previews before retrying."
                if attempted
                else "No save was requested; refresh the named choices."
            ),
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Planning Preview could not be saved or verified safely.",
            (
                "A write may have completed; inspect saved previews before retrying."
                if attempted
                else "No save was requested; use Advanced for exact diagnostics."
            ),
        )
        pause_for_user(input_fn)


__all__ = ("run_named_planning_preview_write",)
