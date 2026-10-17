"""Issue #121 Slice 5: one actor for teacher prompts, no implicit authority."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from pds_core.menu_navigation import ReturnToMainMenu

from meridian.teacher_attribution_input import (
    ATTRIBUTION_PROMPTS,
    TeacherAttributionInput,
)
from meridian.teacher_profile import TeacherIdentityProvider, TeacherProfileStore


class RecordingInput:
    def __init__(self, *replies: str) -> None:
        self.replies = iter(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self.replies)


@pytest.fixture
def profile(tmp_path: Path) -> tuple[TeacherProfileStore, TeacherIdentityProvider]:
    config = tmp_path / "config"
    config.mkdir(mode=0o700)
    store = TeacherProfileStore(
        config_directory=config, actor_id_factory=lambda: "teacher-121"
    )
    return store, TeacherIdentityProvider(store)


@pytest.mark.parametrize("prompt", sorted(ATTRIBUTION_PROMPTS))
def test_each_known_prompt_supplies_exact_saved_actor_without_input(
    profile: tuple[TeacherProfileStore, TeacherIdentityProvider], prompt: str
) -> None:
    store, provider = profile
    store.create("A. Teacher")
    delegate = RecordingInput()
    out = StringIO()
    adapter = TeacherAttributionInput(input_fn=delegate, provider=provider, output=out)
    assert adapter(prompt) == "teacher-121"
    assert delegate.prompts == []
    assert "Recorded by: A. Teacher" in out.getvalue()


def test_unrelated_questions_and_confirmations_pass_through_exactly(profile) -> None:
    _, provider = profile
    delegate = RecordingInput("yes", "SAVE", "H")
    out = StringIO()
    adapter = TeacherAttributionInput(input_fn=delegate, provider=provider, output=out)
    assert adapter("Rationale (optional): ") == "yes"
    assert adapter("Confirmation: ") == "SAVE"
    assert adapter("Choice: ") == "H"
    assert delegate.prompts == [
        "Rationale (optional): ",
        "Confirmation: ",
        "Choice: ",
    ]
    assert not out.getvalue()


def test_no_profile_fails_closed_without_asking_for_name(profile) -> None:
    _, provider = profile
    delegate = RecordingInput("", "")
    out = StringIO()
    adapter = TeacherAttributionInput(input_fn=delegate, provider=provider, output=out)
    for prompt in ATTRIBUTION_PROMPTS:
        with pytest.raises(ReturnToMainMenu):
            adapter(prompt)
    assert delegate.prompts == ["Press Enter to return to Main Menu..."] * 2
    assert "S. Teacher Settings" in out.getvalue()
    assert "No actor is supplied" in out.getvalue()


def test_corrupted_profile_fails_closed_without_guess_or_rewrite(profile) -> None:
    store, provider = profile
    store.create("Teacher")
    store.profile_path.write_bytes(b"corrupted profile")
    delegate = RecordingInput("")
    out = StringIO()
    adapter = TeacherAttributionInput(input_fn=delegate, provider=provider, output=out)
    with pytest.raises(ReturnToMainMenu):
        adapter("Teacher actor ID: ")
    assert delegate.prompts == ["Press Enter to return to Main Menu..."]
    assert store.profile_path.read_bytes() == b"corrupted profile"
    assert "cannot be safely read" in out.getvalue()


def test_display_name_update_keeps_canonical_actor_id(profile) -> None:
    store, provider = profile
    saved = store.create("Before")
    adapter = TeacherAttributionInput(
        input_fn=RecordingInput(), provider=provider, output=StringIO()
    )
    assert adapter("Teacher name for attribution: ") == "teacher-121"
    store.update_display_name(saved, "After")
    assert adapter("Teacher name for attribution: ") == "teacher-121"


def test_identity_replacement_is_seen_on_next_actor_request(profile) -> None:
    store, provider = profile
    saved = store.create("Before")
    out = StringIO()
    adapter = TeacherAttributionInput(
        input_fn=RecordingInput(), provider=provider, output=out
    )
    assert adapter("Teacher actor ID: ") == "teacher-121"
    store.replace_identity(
        saved,
        display_name="Replacement",
        actor_id="teacher-replacement",
        confirmed=True,
    )
    assert adapter("Teacher actor ID: ") == "teacher-replacement"
    assert "Recorded by: Replacement" in out.getvalue()


def test_reset_has_no_fallback_to_last_actor(profile) -> None:
    store, provider = profile
    saved = store.create("Before")
    adapter = TeacherAttributionInput(
        input_fn=RecordingInput(""), provider=provider, output=StringIO()
    )
    assert adapter("Teacher actor ID: ") == "teacher-121"
    store.reset(saved, confirmed=True)
    with pytest.raises(ReturnToMainMenu):
        adapter("Teacher actor ID: ")


def test_known_actor_prompt_contract_has_only_existing_entries() -> None:
    assert ATTRIBUTION_PROMPTS == frozenset(
        {"Teacher name for attribution: ", "Teacher actor ID: "}
    )


def test_source_inventory_is_explicit_and_complete() -> None:
    """A changed/new prompt cannot quietly evade the attribution bridge."""
    expected = {
        "menu_teacher_eligibility.py": (1, 0),
        "menu_teacher_attempts.py": (1, 0),
        "menu_teacher_grade_items.py": (1, 0),
        "menu_teacher_standards.py": (1, 0),
        "menu_teacher_proficiency.py": (1, 0),
        "menu_grade_items.py": (0, 2),
        "menu_proficiency.py": (0, 2),
        "menu_overrides.py": (0, 2),
        "menu_snapshots.py": (0, 2),
        "menu_export.py": (0, 3),
        "menu_planning_signal.py": (0, 1),
        "menu_evidence.py": (0, 3),
    }
    for name, (guided, legacy) in expected.items():
        text = (Path("meridian") / name).read_text(encoding="utf-8")
        assert text.count('"Teacher name for attribution: "') == guided
        assert text.count('"Teacher actor ID: "') == legacy
    assert sum(sum(pair) for pair in expected.values()) == 20


def test_main_menu_only_injects_actor_provider_into_teacher_routes() -> None:
    source = Path("meridian/menu.py").read_text(encoding="utf-8")
    factory = source.split("def default_teacher_menu_dependencies(", 1)[1]
    factory = factory.split("\ndef _task_for_choice(", 1)[0]
    assert "TeacherAttributionInput(" in factory
    assert factory.count("input_fn=teacher_input,") == 10
    assert "attribution_provider=attribution_provider," in factory
    assert (
        "attribution_provider=TeacherIdentityProvider(TeacherProfileStore())," in source
    )
    assert "attribution_provider=active.attribution_provider," in source
    # The Settings/first-use flow still handles human name entry normally.
    assert 'if choice.casefold() == "s":' in source
    assert "run_teacher_settings_menu(" in source
