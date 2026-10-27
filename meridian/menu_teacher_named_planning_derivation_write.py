"""Teacher-named reviewed write of one exact planning derivation (#123 10B).

The selected policy is only a navigation witness. Existing #38 persistence
preview/commit services own canonical candidate validation and fresh-read CAS.
No preview, review, selection, Core signal or CSV is implicitly created.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.menu_teacher_named_grades import _current_choice, _ScopeChanged
from meridian.menu_teacher_named_planning_readiness import (
    PlanningReadinessPolicyCatalog,
    PlanningReadinessPolicySummary,
    _checked_readiness,
    _PlanningPolicyChanged,
)
from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    read_choice,
    write_lines,
)
from meridian.planning_signal_derivation_persistence_workflow import (
    PlanningSignalDerivationPersistencePreview,
    PlanningSignalDerivationPersistenceResult,
)
from meridian.planning_signal_workflow import PlanningSignalReadinessProjection
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

ReadinessReader: TypeAlias = Callable[
    [Path, str, str], PlanningSignalReadinessProjection
]
DerivationPreviewer: TypeAlias = Callable[
    [PlanningSignalReadinessProjection], PlanningSignalDerivationPersistencePreview
]
DerivationCommitter: TypeAlias = Callable[
    [Path, PlanningSignalDerivationPersistencePreview],
    PlanningSignalDerivationPersistenceResult,
]


class _DerivationWriteChanged(RuntimeError):
    """The named policy or reviewed derivation ceased to be an exact target."""


def _checked_preview(
    preview: PlanningSignalDerivationPersistencePreview,
    readiness: PlanningSignalReadinessProjection,
    summary: PlanningReadinessPolicySummary,
    class_id: str,
) -> tuple[int, int, int]:
    """Prove the reviewed preview binds only the named current-policy candidate."""
    candidate = preview.candidate
    policy = readiness.policy
    if (
        policy is None
        or preview.readiness != readiness
        or preview.class_id != class_id
        or preview.policy_id != summary.policy_id
        or candidate.class_id != class_id
        or candidate.policy_reference != policy.reference
        or candidate.derivation_id != preview.derivation_id
        or candidate.calculation_fingerprint != preview.calculation_fingerprint
        or preview.derivation_id != readiness.candidate_derivation_id
        or (
            preview.calculation_fingerprint
            != readiness.candidate_calculation_fingerprint
        )
    ):
        raise _DerivationWriteChanged("Derivation preview provenance changed.")
    counts = (
        preview.roster_student_count,
        preview.contributing_student_count,
        preview.noncontributing_student_count,
    )
    if (
        any(type(n) is not int or n < 0 for n in counts)
        or sum(counts[1:]) != counts[0]
        or counts
        != (
            readiness.roster_student_count,
            readiness.contributing_student_count,
            readiness.noncontributing_student_count,
        )
    ):
        raise _DerivationWriteChanged("Derivation preview student counts changed.")
    return counts


def run_named_planning_derivation_write(
    *,
    navigation: TeacherNavigationContext,
    readiness_projector: ReadinessReader,
    derivation_previewer: DerivationPreviewer,
    derivation_committer: DerivationCommitter,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    policy_catalog: PlanningReadinessPolicyCatalog | None = None,
) -> None:
    """Require deliberate WRITE after validating a name-bound #38 preview."""
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        catalog = policy_catalog or PlanningReadinessPolicyCatalog(navigation)
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
            raise _DerivationWriteChanged("Class context changed.")
        chosen = select_teacher_choice(
            catalog=catalog,
            scope="planning_readiness_policy",
            selected={"class": class_id},
            title="Selected Planning Policies",
            question="Which policy should produce a saved planning derivation?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen is None:
            return

        def check_scope() -> PlanningReadinessPolicySummary:
            if navigation.current_class() != verified:
                raise _DerivationWriteChanged("Class changed during review.")
            _current_choice(
                catalog,
                scope="planning_readiness_policy",
                selected={"class": class_id},
                choice=chosen,
            )
            current = catalog.inspect(root, class_id, chosen.identity[0])
            if (
                current is None
                or current.school_year != verified.school_year
                or current.choice() != chosen
            ):
                raise _DerivationWriteChanged("Selected policy changed.")
            return current

        summary = check_scope()
        readiness = readiness_projector(root, class_id, summary.policy_id)
        ordinary = _checked_readiness(readiness, summary, class_id)
        if check_scope() != summary:
            raise _DerivationWriteChanged("Policy changed during readiness.")
        if (
            not readiness.ready_for_derivation_persistence
            or readiness.generation_status != "generated"
            or readiness.blocker_codes
        ):
            clear_fn()
            print_menu_header(output, "Planning Derivation — Not Ready")
            write_lines(
                output,
                f"Policy: {summary.title}",
                *ordinary,
                "",
                "A derivation cannot be written until readiness is satisfied.",
                "No planning or academic record was changed.",
            )
            pause_for_user(input_fn)
            return
        preview = derivation_previewer(readiness)
        roster, contributing, noncontributing = _checked_preview(
            preview, readiness, summary, class_id
        )
        if check_scope() != summary:
            raise _DerivationWriteChanged("Policy changed during derivation preview.")
        while True:
            if check_scope() != summary:
                raise _DerivationWriteChanged("Policy changed before confirmation.")
            clear_fn()
            print_menu_header(output, "Review Planning Derivation Before Write")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Marking period: {summary.period_label}",
                f"Standard: {summary.standard_id}",
                f"Dimension: {summary.dimension_id}",
                f"Bands: {summary.band_count}",
                f"Students: {roster} rostered, {contributing} contributing, "
                f"{noncontributing} noncontributing",
                "",
                "WRITE saves only this immutable Planning Derivation.",
                "It does not create a preview, review, grouping or Core export.",
                "Type WRITE to save. B or blank cancels; M or Q navigates.",
                "T. Technical details of the exact candidate",
            )
            choice = read_choice(input_fn, "Confirmation: ")
            if choice.casefold() == "t":
                if check_scope() != summary:
                    raise _DerivationWriteChanged("Policy changed before details.")
                clear_fn()
                print_menu_header(output, "Planning Derivation — Technical Candidate")
                write_lines(
                    output,
                    f"class_id: {class_id}",
                    f"policy_id: {summary.policy_id}",
                    f"policy_revision: {summary.policy_revision}",
                    f"policy_sha256: {summary.policy_sha256}",
                    f"derivation_id: {preview.derivation_id}",
                    f"calculation_fingerprint: {preview.calculation_fingerprint}",
                )
                pause_for_user(input_fn)
                continue
            command = parse_navigation_choice(choice)
            if command is NavigationChoice.BACK or not choice:
                write_lines(output, "No planning derivation was written.")
                return
            if choice != "WRITE":
                write_lines(output, "No planning derivation was written.")
                pause_for_user(input_fn)
                return
            if check_scope() != summary:
                raise _DerivationWriteChanged("Policy changed before persistence.")
            # The existing committer reprojects readiness and checks the complete
            # candidate against the teacher-reviewed preview before any write.
            result = derivation_committer(root, preview)
            if (
                result.preview != preview
                or result.derivation_id != preview.derivation_id
                or result.calculation_fingerprint != preview.calculation_fingerprint
                or result.write_disposition not in {"created", "existing"}
            ):
                raise _DerivationWriteChanged("Persistence result was inconsistent.")
            clear_fn()
            print_menu_header(output, "Planning Derivation Saved")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Marking period: {summary.period_label}",
                f"Students: {roster} rostered",
                f"Save outcome: {result.write_disposition}",
                "",
                "No Planning Preview, review, selection, Core signal or CSV was made.",
            )
            pause_for_user(input_fn)
            return
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_DerivationWriteChanged, _PlanningPolicyChanged, _ScopeChanged):
        write_lines(
            output,
            "Class, Planning Signal policy or reviewed derivation changed.",
            "No new action is authorized. Refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Planning Derivation could not be saved or verified safely.",
            "Check selected policy/readiness or use Advanced for diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_planning_derivation_write",)
