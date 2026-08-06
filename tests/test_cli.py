from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from meridian import __version__
from meridian.cli import main


def test_main_without_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(()) == 0
    output = capsys.readouterr().out
    assert "usage: meridian" in output
    assert "publication-ingestion" in output
    assert "are not" in output
    assert "implemented yet." in output


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
    [(), ("--help",), ("--version",)],
)
def test_python_module_cli_is_read_only(
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


def test_console_script_is_read_only(tmp_path: Path) -> None:
    executable = Path(sys.executable).with_name(
        "meridian.exe" if os.name == "nt" else "meridian"
    )
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
