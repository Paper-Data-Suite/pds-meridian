"""Issue #121 CI repair: exact wheel contents and cross-platform lock calls."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import ModuleType

from meridian.teacher_profile import _windows_lock

TEACHER_MODULES = frozenset(
    {
        "meridian/menu_teacher_settings.py",
        "meridian/teacher_attribution_input.py",
        "meridian/teacher_preferences.py",
        "meridian/teacher_profile.py",
    }
)


def test_exact_teacher_modules_are_explicitly_whitelisted_for_wheel() -> None:
    source = Path("scripts/check_package.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    validator = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "validate_wheel"
    )
    assigned = next(
        node
        for node in validator.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "required"
    )
    required = ast.literal_eval(assigned.value)
    assert TEACHER_MODULES.issubset(required)
    assert len({name for name in required if name in TEACHER_MODULES}) == 4
    assert 'normalized.startswith("meridian/")' in source
    assert "unexpected Meridian module" in source
    for name in TEACHER_MODULES:
        assert Path(name).is_file(), name


def test_windows_lock_facade_uses_real_crt_operations(monkeypatch) -> None:
    """Exercise the 1-byte lock contract on non-Windows without granting I/O."""
    calls: list[tuple[int, int, int]] = []
    module = ModuleType("msvcrt")
    module.LK_LOCK = 1  # type: ignore[attr-defined]
    module.LK_UNLCK = 2  # type: ignore[attr-defined]

    def locking(fd: int, mode: int, count: int) -> None:
        calls.append((fd, mode, count))

    module.locking = locking  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "msvcrt", module)
    _windows_lock(15, unlock=False)
    _windows_lock(15, unlock=True)
    assert calls == [(15, 1, 1), (15, 2, 1)]


def test_windows_locking_calls_are_isolated_from_posix_branch() -> None:
    source = Path("meridian/teacher_profile.py").read_text(encoding="utf-8")
    assert "msvcrt.locking(fd, msvcrt." not in source
    assert "_windows_lock(fd, unlock=False)" in source
    assert "_windows_lock(fd, unlock=True)" in source
    assert "_posix_flock(fd, unlock=False)" in source
    assert "_posix_flock(fd, unlock=True)" in source
