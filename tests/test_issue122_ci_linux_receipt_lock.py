"""#122 Linux mypy guard for Windows receipt-journal byte locks."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from meridian.teacher_action_receipts import _windows_file_lock


def test_windows_crt_nonblocking_and_unlock_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise real facade dispatch on Linux without acquiring OS locks."""
    calls: list[tuple[int, int, int]] = []
    crt = ModuleType("msvcrt")
    setattr(crt, "LK_NBLCK", 17)
    setattr(crt, "LK_UNLCK", 18)

    def locking(fd: int, operation: int, length: int) -> None:
        calls.append((fd, operation, length))

    setattr(crt, "locking", locking)
    monkeypatch.setitem(sys.modules, "msvcrt", crt)

    _windows_file_lock(23, unlock=False)
    _windows_file_lock(23, unlock=True)
    assert calls == [(23, 17, 1), (23, 18, 1)]


def test_missing_windows_crt_lock_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No fallback to an unguarded write if required CRT lock is absent."""
    crt = ModuleType("msvcrt")
    setattr(crt, "LK_NBLCK", 17)
    monkeypatch.setitem(sys.modules, "msvcrt", crt)
    with pytest.raises(AttributeError):
        _windows_file_lock(23, unlock=False)
