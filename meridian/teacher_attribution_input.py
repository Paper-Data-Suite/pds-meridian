"""Explicit teacher-menu attribution adapter for Issue #121.

Only the composed interactive teacher application installs this adapter.  It
recognizes the two *existing* actor-entry prompt contracts; other prompts are
forwarded without modification.  Direct CLI commands are deliberately outside
this path.  This is a transitional menu bridge, not an authority mechanism.
"""

from __future__ import annotations

from typing import Final, TextIO

from pds_core.menu_navigation import ReturnToMainMenu

from meridian.menu_ui import InputFunction
from meridian.teacher_profile import (
    TeacherIdentityProvider,
    TeacherProfileError,
    TeacherProfileNotConfiguredError,
)

ATTRIBUTION_PROMPTS: Final[frozenset[str]] = frozenset(
    {
        "Teacher name for attribution: ",
        "Teacher actor ID: ",
    }
)


class TeacherAttributionInput:
    """Read the saved actor for a *known* teacher input, with no extra keystroke.

    Every canonical authoring service still gets an explicit concrete actor ID.
    The name is for display only; self-declared identity grants no permission.
    Missing or damaged local profiles abort the current teacher action rather
    than submitting a blank actor to an unknown service validation path.
    """

    def __init__(
        self,
        *,
        input_fn: InputFunction,
        provider: TeacherIdentityProvider,
        output: TextIO,
    ) -> None:
        self._input_fn = input_fn
        self._provider = provider
        self._output = output

    def __call__(self, prompt: str) -> str:
        if prompt not in ATTRIBUTION_PROMPTS:
            return self._input_fn(prompt)
        try:
            identity = self._provider.resolve()
        except TeacherProfileNotConfiguredError:
            print(
                "Teacher attribution is not configured. Open S. Teacher Settings "
                "to set up your profile. No actor is supplied.",
                file=self._output,
            )
            self._input_fn("Press Enter to return to Main Menu...")
            raise ReturnToMainMenu
        except TeacherProfileError:
            print(
                "The saved teacher profile cannot be safely read. "
                "Open S. Teacher Settings to resolve it. No actor is supplied.",
                file=self._output,
            )
            self._input_fn("Press Enter to return to Main Menu...")
            raise ReturnToMainMenu
        print(f"Recorded by: {identity.display_name}", file=self._output)
        return identity.actor_id


__all__ = ("ATTRIBUTION_PROMPTS", "TeacherAttributionInput")
