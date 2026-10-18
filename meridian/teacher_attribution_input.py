"""Explicit teacher-menu attribution adapter for Issue #121.

Only the composed interactive teacher application installs this adapter.  It
recognizes the two *existing* actor-entry prompt contracts; other prompts are
forwarded without modification.  Direct CLI commands are deliberately outside
this path.  This is a transitional menu bridge, not an authority mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TextIO

from pds_core.menu_navigation import ReturnToMainMenu

from meridian.menu_ui import InputFunction
from meridian.teacher_profile import (
    TeacherIdentity,
    TeacherIdentityProvider,
    TeacherProfileConflictError,
    TeacherProfileError,
    TeacherProfileNotConfiguredError,
    TeacherProfileValidationError,
)

ATTRIBUTION_PROMPTS: Final[frozenset[str]] = frozenset(
    {
        "Teacher name for attribution: ",
        "Teacher actor ID: ",
    }
)


@dataclass(frozen=True, slots=True)
class _PendingAttribution:
    identity: TeacherIdentity
    expected_profile_sha256: str


class OneActionAttributionOverride:
    """Session-only, one-consumption actor override with stale-profile guard.

    This is a *next attribution request* override, not a guarantee the subsequent
    academic write succeeds. An abandoned action cannot leave a used override;
    any unconsumed override is discarded when this process exits. No persistence.
    """

    def __init__(self, provider: TeacherIdentityProvider) -> None:
        self._provider = provider
        self._pending: _PendingAttribution | None = None

    @property
    def pending(self) -> bool:
        return self._pending is not None

    @property
    def pending_name(self) -> str | None:
        value = self._pending
        return None if value is None else value.identity.display_name

    def clear(self) -> None:
        self._pending = None

    def arm(
        self,
        *,
        actor_id: str,
        display_name: str,
        confirmation: str,
        expected_profile_sha256: str | None = None,
    ) -> None:
        """Require Advanced confirmation against the reviewed saved profile."""
        if confirmation != "OVERRIDE":
            raise TeacherProfileValidationError(
                "Temporary attribution override requires OVERRIDE confirmation."
            )
        identity = self._provider.temporary_override(
            actor_id=actor_id, display_name=display_name
        )
        _, fingerprint = self._provider.resolve_with_fingerprint()
        if (
            expected_profile_sha256 is not None
            and expected_profile_sha256 != fingerprint
        ):
            raise TeacherProfileConflictError(
                "Saved identity changed while Advanced attribution was reviewed."
            )
        self._pending = _PendingAttribution(identity, fingerprint)

    def resolve_next(self) -> TeacherIdentity:
        """Use exactly one armed actor, or fall back to current saved identity."""
        pending = self._pending
        if pending is None:
            return self._provider.resolve()
        # Disarm before any I/O: errors and rejected downstream operations do
        # not accidentally leave an override armed for another decision.
        self._pending = None
        _, latest_fingerprint = self._provider.resolve_with_fingerprint()
        if latest_fingerprint != pending.expected_profile_sha256:
            raise TeacherProfileConflictError(
                "Saved teacher profile changed after temporary attribution review."
            )
        return pending.identity


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
        override: OneActionAttributionOverride | None = None,
    ) -> None:
        self._input_fn = input_fn
        self._provider = provider
        self._output = output
        self._override = override
        self._last_attribution: tuple[TeacherIdentity, str] | None = None

    def take_last_attribution(self) -> tuple[TeacherIdentity, str] | None:
        """Consume the most recent verified attribution, including an override."""
        value = self._last_attribution
        self._last_attribution = None
        return value

    def __call__(self, prompt: str) -> str:
        if prompt not in ATTRIBUTION_PROMPTS:
            return self._input_fn(prompt)
        self._last_attribution = None
        try:
            identity = (
                self._override.resolve_next()
                if self._override is not None
                else self._provider.resolve()
            )
        except TeacherProfileNotConfiguredError:
            print(
                "Teacher attribution is not configured. Open S. Teacher Settings "
                "to set up your profile. No actor is supplied.",
                file=self._output,
            )
            self._input_fn("Press Enter to return to Main Menu...")
            raise ReturnToMainMenu
        except TeacherProfileConflictError:
            print(
                "Saved teacher identity changed after an Advanced override "
                "was confirmed. The override was discarded. "
                "Review your current profile before trying again.",
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
        if identity.source == "temporary":
            print(
                f"Recorded by (one-action override): {identity.display_name}",
                file=self._output,
            )
        else:
            print(f"Recorded by: {identity.display_name}", file=self._output)
        try:
            _, digest = self._provider.resolve_with_fingerprint()
        except TeacherProfileError:
            raise ReturnToMainMenu from None
        self._last_attribution = (identity, digest)
        return identity.actor_id


__all__ = (
    "ATTRIBUTION_PROMPTS",
    "OneActionAttributionOverride",
    "TeacherAttributionInput",
)
