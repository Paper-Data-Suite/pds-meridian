from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

import meridian.cli as cli_module
from meridian import __version__
from meridian.cli import main


def _console_script_path() -> Path:
    """Return the installed console launcher using Python's install scheme."""
    script_name = "meridian.exe" if os.name == "nt" else "meridian"
    return Path(sysconfig.get_path("scripts")) / script_name

def test_main_without_arguments_launches_teacher_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def fake_run_menu(*, diagnostics: object = None) -> int:
        calls.append(diagnostics)
        return 0

    monkeypatch.setattr(cli_module, "run_menu", fake_run_menu)

    assert main(()) == 0
    assert calls == [None]


def test_explicit_menu_command_launches_teacher_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def fake_run_menu(*, diagnostics: object = None) -> int:
        calls.append(diagnostics)
        return 0

    monkeypatch.setattr(cli_module, "run_menu", fake_run_menu)

    assert main(("menu",)) == 0
    assert calls == [None]


def test_menu_help_remains_noninteractive(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(**kwargs: object) -> int:
        raise AssertionError("menu --help must not enter the interactive menu")

    monkeypatch.setattr(cli_module, "run_menu", forbidden)
    with pytest.raises(SystemExit) as raised:
        main(("menu", "--help"))
    assert raised.value.code == 0
    assert "teacher-facing Meridian application" in capsys.readouterr().out


def test_main_help_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("--help",))
    assert raised.value.code == 0
    assert "usage: meridian" in capsys.readouterr().out


def test_main_version_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("--version",))
    assert raised.value.code == 0
    assert capsys.readouterr().out.strip() == f"meridian {__version__}"


def test_invalid_argument_returns_usage_failure() -> None:
    with pytest.raises(SystemExit) as raised:
        main(("--unknown",))
    assert raised.value.code == 2


@pytest.mark.parametrize(
    "arguments",
    [("--help",), ("--version",)],
)
def test_python_module_direct_cli_is_read_only(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    before = list(tmp_path.iterdir())
    result = subprocess.run(
        [sys.executable, "-m", "meridian", *arguments],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == before


@pytest.mark.parametrize("arguments", [(), ("menu",)])
def test_python_module_menu_entrypoints_are_read_only(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    before = list(tmp_path.iterdir())
    result = subprocess.run(
        [sys.executable, "-m", "meridian", *arguments],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        input="q\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "1. Review New Evidence" in result.stdout
    assert "8. Explain" in result.stdout
    assert list(tmp_path.iterdir()) == before

def test_console_script_path_uses_python_scripts_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripts_directory = Path("synthetic-scripts")

    def fake_get_path(name: str) -> str:
        assert name == "scripts"
        return str(scripts_directory)

    monkeypatch.setattr(sysconfig, "get_path", fake_get_path)

    expected_name = "meridian.exe" if os.name == "nt" else "meridian"
    assert _console_script_path() == scripts_directory / expected_name


def test_console_script_is_read_only(tmp_path: Path) -> None:
    executable = _console_script_path()
    assert executable.is_file()
    result = subprocess.run(
        [str(executable), "--version"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"meridian {__version__}"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("arguments", [(), ("menu",)])
def test_console_script_menu_entrypoints_are_read_only(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    executable = _console_script_path()
    assert executable.is_file()
    result = subprocess.run(
        [str(executable), *arguments],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        input="q\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "1. Review New Evidence" in result.stdout
    assert "8. Explain" in result.stdout
    assert not list(tmp_path.iterdir())


def test_named_direct_command_does_not_enter_menu(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(**kwargs: object) -> int:
        raise AssertionError("named direct commands must not enter the menu")

    monkeypatch.setattr(cli_module, "run_menu", forbidden)
    assert main(("workflow", "list", "--format", "json")) == 0
    output = capsys.readouterr().out
    assert '"task_id": "new-evidence"' in output
    assert "1. Review New Evidence" not in output
