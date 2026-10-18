"""Issue #121 Slice 1: preserve the characterized attribution baseline.

This gate permits removal of legacy prompts, but prohibits newly introduced
prompt sites without updating the intended migration contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pds_core.workspace as core_workspace

from meridian.teacher_session import TeacherSessionContext

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs/architecture/issue121-teacher-profile-preferences-contract.md"

# File -> (guided human-readable name count, legacy actor ID count).
# This is the October 17 baseline, not a minimum: later slices remove prompts.
BASELINE_PROMPTS: dict[str, tuple[int, int]] = {
    "menu_teacher_eligibility.py": (1, 0),
    "menu_teacher_attempts.py": (1, 0),
    "menu_teacher_grade_items.py": (1, 0),
    "menu_teacher_standards.py": (1, 0),
    "menu_teacher_proficiency.py": (1, 0),
    "menu_evidence.py": (0, 3),
    "menu_grade_items.py": (0, 2),
    "menu_proficiency.py": (0, 2),
    "menu_overrides.py": (0, 2),
    "menu_snapshots.py": (0, 2),
    "menu_export.py": (0, 3),
    "menu_planning_signal.py": (0, 1),
}
_PROMPTS = ("Teacher name for attribution: ", "Teacher actor ID: ")


def _actor_prompt_sites() -> dict[str, tuple[int, int]]:
    actual: dict[str, tuple[int, int]] = {}
    for path in sorted((ROOT / "meridian").glob("menu*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        counts = [0, 0]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "read_choice" or len(node.args) < 2:
                continue
            prompt = node.args[1]
            if not isinstance(prompt, ast.Constant) or not isinstance(
                prompt.value, str
            ):
                continue
            for index, text in enumerate(_PROMPTS):
                if prompt.value == text:
                    counts[index] += 1
        if any(counts):
            actual[path.name] = (counts[0], counts[1])
    return actual


def test_known_actor_prompt_sites_may_only_shrink() -> None:
    current = _actor_prompt_sites()
    assert sum(sum(v) for v in BASELINE_PROMPTS.values()) == 20
    assert sum(sum(v) for v in current.values()) <= 20
    for filename, counts in current.items():
        assert filename in BASELINE_PROMPTS, f"New actor prompt site: {filename}"
        expected = BASELINE_PROMPTS[filename]
        assert counts[0] <= expected[0], (filename, "teacher name", counts)
        assert counts[1] <= expected[1], (filename, "actor ID", counts)


def test_contract_documents_identity_authority_separation() -> None:
    content = DOCUMENT.read_text(encoding="utf-8")
    for requirement in (
        "**zero**",
        "Core-owned shared convention",
        "get_workspace_config_path()",
        "not authentication",
        "a **hint**",
        "without protected reads",
        "direct noninteractive CLI",
        "five guided prompt sites",
        "fifteen legacy prompt sites",
    ):
        assert requirement.casefold() in content.casefold(), requirement


def test_core_only_supplies_existing_workspace_config_convention() -> None:
    assert callable(core_workspace.get_workspace_config_path)
    assert callable(core_workspace.resolve_workspace_root)


def test_current_session_remains_process_local_navigation() -> None:
    session = TeacherSessionContext()
    assert session.active_class_id is None
    assert session.active_student_id is None
    assert not hasattr(session, "save")
    assert not hasattr(session, "workspace_root")
