"""#124 E2G1: safe prompt input boundaries."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

from meridian.assessment_setup_recovery_prompt import offer_assessment_setup_recovery


def test_invalid_context_never_prompts_or_selects(tmp_path: Path) -> None:
    with patch(
        "meridian.assessment_setup_recovery_prompt.resume_restored_assessment_setup_selection"
    ) as resume:
        out = StringIO()
        result = offer_assessment_setup_recovery(
            tmp_path,
            None,
            None,
            input_fn=lambda _: "RESUME",
            output=out,  # type: ignore[arg-type]
        )
    assert result.status == "requires_review"
    resume.assert_not_called()


def test_relative_workspace_never_prompts() -> None:
    with patch(
        "meridian.assessment_setup_recovery_prompt.inspect_original_assessment_setup_receipt"
    ) as inspect:
        outcome = offer_assessment_setup_recovery(
            Path("relative"),
            None,
            None,
            input_fn=lambda _: "RESUME",
            output=StringIO(),  # type: ignore[arg-type]
        )
    assert outcome.status == "requires_review"
    inspect.assert_not_called()
