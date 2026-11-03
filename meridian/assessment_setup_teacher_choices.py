"""#124 E2G3E: explicit teacher choices for restart review, never replay authority.

The receipt does not supply any of these choices. The teacher enters them in
this review, and E2G3D independently reloads the canonical assessment preview.
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO, cast

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_fresh_review_caller import (
    ChoiceProvider,
    FreshAssessmentChoices,
)
from meridian.grade_items import GRADE_ITEM_PURPOSES, GradeItemPurpose
from meridian.menu_ui import InputFunction, print_menu_header, write_lines
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import resolve_menu_actor
from meridian.teacher_action_recovery_inventory import RecoveryInboxEntry
from meridian.teacher_session import TeacherSessionContext


def make_interactive_assessment_choice_provider(
    *, input_fn: InputFunction, output: TextIO
) -> ChoiceProvider:
    """Build a conservative, explicit terminal choice provider for E2G3D.

    B cancels the choice wizard. M and Q retain PDS-wide navigation. No
    receipt data is used to populate choices or infer an original intent.
    """

    def ask(label: str, *, optional: bool = False) -> str | None:
        raw = input_fn(f"{label}: ").strip()
        if raw.upper() == "B":
            return None
        if raw.upper() == "M":
            raise ReturnToMainMenu()
        if raw.upper() == "Q":
            raise QuitPDS()
        if not optional and not raw:
            raise ValueError(f"Explicit {label.lower()} required")
        if len(raw) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
            raise ValueError("Invalid teacher choice")
        return raw

    def choose(
        root: Path, session: TeacherSessionContext, entry: RecoveryInboxEntry
    ) -> tuple[FreshAssessmentChoices, TeacherActionActor] | None:
        del root, entry
        class_id = session.active_class_id
        if class_id is None:
            raise ValueError("Select a class before assessment recovery")
        print_menu_header(output, "Reconstruct Assessment Review")
        write_lines(
            output,
            "Enter the original choices explicitly.",
            "The journal cannot supply them.",
            "B. Back   M. Main Menu   Q. Quit",
        )
        module_id = ask("Producer (scoreform/quillan/concord)")
        if module_id is None:
            return None
        if module_id not in ("scoreform", "quillan", "concord"):
            raise ValueError("Unsupported producer")
        work_id = ask("Registered work ID")
        if work_id is None:
            return None
        year = ask("School year")
        if year is None:
            return None
        period = ask("Marking period ID")
        if period is None:
            return None
        purpose = ask(
            "Purpose (standards_proficiency/conventional_grade/"
            "standards_and_conventional/reporting_only)"
        )
        if purpose is None:
            return None
        if purpose not in GRADE_ITEM_PURPOSES:
            raise ValueError("Unsupported Grade Item purpose")
        mode = ask("Mode (existing/new)")
        if mode is None:
            return None
        if mode not in ("existing", "new"):
            raise ValueError("Choose existing or new")
        existing = None
        title = None
        if mode == "existing":
            existing = ask("Existing Grade Item ID")
            if existing is None:
                return None
        else:
            title = ask("Original new Grade Item title")
            if title is None:
                return None
        rationale = ask("Original rationale (blank if none)", optional=True)
        if rationale is None:
            return None
        actor_id = ask("Saved teacher attribution ID")
        if actor_id is None:
            return None
        # Current saved profile verifier, not an actor reconstructed from a receipt.
        actor = resolve_menu_actor(actor_id, input_fn)
        choices = FreshAssessmentChoices(
            ModuleWorkRef(module_id, class_id, work_id),
            year,
            period,
            cast(GradeItemPurpose, purpose),
            existing,
            title,
            actor_id,
            rationale or None,
        )
        return choices, actor

    return choose


__all__ = ("make_interactive_assessment_choice_provider",)
