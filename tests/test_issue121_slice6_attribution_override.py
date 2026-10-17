"""Issue #121 Slice 6: one-shot attribution, no secret persistence or authority."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from pds_core.menu_navigation import ReturnToMainMenu

from meridian.menu_teacher_settings import run_teacher_settings_menu
from meridian.teacher_attribution_input import (
    OneActionAttributionOverride,
    TeacherAttributionInput,
)
from meridian.teacher_profile import (
    TeacherIdentityProvider,
    TeacherProfileNotConfiguredError,
    TeacherProfileStore,
    TeacherProfileValidationError,
)
from meridian.teacher_session import TeacherSessionContext


class Responses:
    def __init__(self, *values: str) -> None:
        self.values = iter(values)
        self.asked: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.asked.append(prompt)
        return next(self.values)


@pytest.fixture
def configured(tmp_path: Path) -> tuple[TeacherProfileStore, TeacherIdentityProvider]:
    config = tmp_path / "config"
    config.mkdir(mode=0o700)
    store = TeacherProfileStore(
        config_directory=config, actor_id_factory=lambda: "teacher-saved"
    )
    store.create("Saved Teacher")
    return store, TeacherIdentityProvider(store)


def _override(provider: TeacherIdentityProvider) -> OneActionAttributionOverride:
    return OneActionAttributionOverride(provider)


def test_advanced_override_is_one_attribution_and_does_not_persist(configured) -> None:
    store, provider = configured
    state = _override(provider)
    state.arm(
        actor_id="teacher-guest",
        display_name="Guest Teacher",
        confirmation="OVERRIDE",
    )
    out = StringIO()
    adapter = TeacherAttributionInput(
        input_fn=Responses(), provider=provider, output=out, override=state
    )
    assert state.pending_name == "Guest Teacher"
    assert adapter("Teacher name for attribution: ") == "teacher-guest"
    assert not state.pending
    assert adapter("Teacher actor ID: ") == "teacher-saved"
    assert "Recorded by (one-action override): Guest Teacher" in out.getvalue()
    assert "Recorded by: Saved Teacher" in out.getvalue()
    assert store.load().profile.actor_id == "teacher-saved"  # type: ignore[union-attr]
    assert b"teacher-guest" not in store.profile_path.read_bytes()


def test_cancellation_or_invalid_confirmation_never_arms(configured) -> None:
    _, provider = configured
    state = _override(provider)
    for confirmation in ("", "override", "SAVE"):
        with pytest.raises(TeacherProfileValidationError):
            state.arm(
                actor_id="teacher-guest",
                display_name="Guest",
                confirmation=confirmation,
            )
    assert not state.pending
    assert state.resolve_next().actor_id == "teacher-saved"


@pytest.mark.parametrize(
    "actor", ["", "teacher other", "../other", " teacher", "a" * 129]
)
def test_invalid_temporary_actor_is_rejected(configured, actor: str) -> None:
    _, provider = configured
    state = _override(provider)
    with pytest.raises(TeacherProfileValidationError):
        state.arm(actor_id=actor, display_name="Guest", confirmation="OVERRIDE")
    assert not state.pending


def test_no_saved_profile_cannot_be_bypassed_by_temporary_actor(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir(mode=0o700)
    provider = TeacherIdentityProvider(TeacherProfileStore(config_directory=config))
    state = _override(provider)
    with pytest.raises(TeacherProfileNotConfiguredError):
        state.arm(
            actor_id="teacher-guest", display_name="Guest", confirmation="OVERRIDE"
        )
    assert not state.pending


@pytest.mark.parametrize("operation", ["name", "identity", "reset", "damage"])
def test_saved_profile_mutation_invalidates_pending_override(
    configured, operation: str
) -> None:
    store, provider = configured
    state = _override(provider)
    state.arm(actor_id="teacher-guest", display_name="Guest", confirmation="OVERRIDE")
    current = store.load()
    assert current is not None
    if operation == "name":
        store.update_display_name(current, "Changed Name")
    elif operation == "identity":
        store.replace_identity(
            current, display_name="Another", actor_id="teacher-another", confirmed=True
        )
    elif operation == "reset":
        store.reset(current, confirmed=True)
    else:
        store.profile_path.write_bytes(b"broken")
    out = StringIO()
    adapter = TeacherAttributionInput(
        input_fn=Responses(""), provider=provider, output=out, override=state
    )
    with pytest.raises(ReturnToMainMenu):
        adapter("Teacher actor ID: ")
    assert not state.pending
    assert "teacher-guest" not in out.getvalue()


def test_reviewed_identity_cannot_be_swapped_before_override_confirmation(
    configured,
) -> None:
    store, provider = configured
    state = _override(provider)
    reviewed = store.load()
    assert reviewed is not None
    store.update_display_name(reviewed, "Changed Since Review")
    from meridian.teacher_profile import TeacherProfileConflictError

    with pytest.raises(TeacherProfileConflictError):
        state.arm(
            actor_id="teacher-guest",
            display_name="Guest",
            confirmation="OVERRIDE",
            expected_profile_sha256=reviewed.sha256,
        )
    assert not state.pending


def test_user_can_clear_queued_actor_without_using_it(configured) -> None:
    _, provider = configured
    state = _override(provider)
    state.arm(actor_id="teacher-guest", display_name="Guest", confirmation="OVERRIDE")
    state.clear()
    assert not state.pending
    assert state.resolve_next().actor_id == "teacher-saved"


def test_unrelated_inputs_cannot_consume_pending_actor(configured) -> None:
    _, provider = configured
    state = _override(provider)
    state.arm(actor_id="teacher-guest", display_name="Guest", confirmation="OVERRIDE")
    responses = Responses("grade justification")
    adapter = TeacherAttributionInput(
        input_fn=responses, provider=provider, output=StringIO(), override=state
    )
    assert adapter("Rationale: ") == "grade justification"
    assert state.pending
    assert adapter("Teacher actor ID: ") == "teacher-guest"
    assert responses.asked == ["Rationale: "]


def test_settings_arm_and_cancel_one_action_with_injected_profile(configured) -> None:
    store, provider = configured
    state = _override(provider)
    scripted = Responses(
        "8", "Temporary Teacher", "teacher-temp", "OVERRIDE", "", "9", "", "b"
    )
    out = StringIO()
    run_teacher_settings_menu(
        session_context=TeacherSessionContext(),
        profile_store=store,
        attribution_override=state,
        input_fn=scripted,
        output=out,
        clear_fn=lambda: None,
    )
    assert not state.pending
    assert "One-Action Attribution Armed" in out.getvalue()
    assert "Temporary Attribution Cleared" in out.getvalue()
    assert store.load().profile.actor_id == "teacher-saved"  # type: ignore[union-attr]


def test_canceling_advanced_review_never_arms(configured) -> None:
    store, provider = configured
    state = _override(provider)
    scripted = Responses("8", "Guest", "teacher-guest", "no", "", "b")
    run_teacher_settings_menu(
        session_context=TeacherSessionContext(),
        profile_store=store,
        attribution_override=state,
        input_fn=scripted,
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert not state.pending


def test_noninteractive_and_normal_prompts_still_unmodified(configured) -> None:
    _, provider = configured
    state = _override(provider)
    scripted = Responses("YES", "SAVE")
    adapter = TeacherAttributionInput(
        input_fn=scripted, provider=provider, output=StringIO(), override=state
    )
    assert adapter("Continue? ") == "YES"
    assert adapter("Confirmation: ") == "SAVE"
    assert scripted.asked == ["Continue? ", "Confirmation: "]


def test_source_wiring_retains_override_across_evidence_authorization() -> None:
    source = Path("meridian/menu.py").read_text(encoding="utf-8")
    assert "attribution_override=active.attribution_override," in source
    assert "attribution_override=next_attribution," in source
    assert "pending_override=active.attribution_override," in source
    assert "active.attribution_override.clear()" in source
    assert "active.attribution_provider.store" in source
