"""#122 measurable one-confirmation ordinary review; synthetic action only."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
from typing import cast

import pytest

from meridian.menu_teacher_grade_items import _review_apply
from meridian.teacher_action_guided import PreparedGuidedAction


def test_confirmed_single_prepared_action_has_one_teacher_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    applications: list[bool] = []
    output = StringIO()

    def input_fn(prompt: str = "") -> str:
        prompts.append(prompt)
        return "1"

    action = SimpleNamespace(
        apply=lambda *, confirmed: (
            applications.append(confirmed)
            or SimpleNamespace(succeeded=True, status="applied")
        )
    )
    monkeypatch.setattr(
        "meridian.menu_teacher_grade_items.teacher_action_outcome_message",
        lambda _: "Saved and made current",
    )
    success = _review_apply(
        cast(PreparedGuidedAction, action),  # type: ignore[arg-type]
        input_fn=input_fn,
        output=output,
        clear_fn=lambda: None,
    )
    assert success and applications == [True]
    # Historical pre-#122 path required separate write and selection accepts.
    assert len(prompts) == 1
    assert "Saved and made current" in output.getvalue()


def test_cancelled_prepared_action_does_not_apply() -> None:
    prompts: list[str] = []
    applications: list[bool] = []

    def input_fn(prompt: str = "") -> str:
        prompts.append(prompt)
        return "2"

    action = SimpleNamespace(apply=lambda *, confirmed: applications.append(confirmed))
    result = _review_apply(
        cast(PreparedGuidedAction, action),  # type: ignore[arg-type]
        input_fn=input_fn,
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert not result and applications == []
    assert len(prompts) == 1
