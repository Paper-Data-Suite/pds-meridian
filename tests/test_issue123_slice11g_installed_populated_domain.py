"""#123 Slice 11G: additive installed populated-domain acceptance boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import smoke_test_issue123_populated_domain_wheel as wheel


def test_isolated_environment_excludes_developer_python_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PDS_CORE_WHEEL",
        "SCOREFORM_WHEEL",
        "QUILLAN_WHEEL",
        "CONCORD_WHEEL",
    ):
        monkeypatch.setenv(key, "hostile-source-path")
    result = wheel.isolated_environment()
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PDS_CORE_WHEEL",
        "SCOREFORM_WHEEL",
        "QUILLAN_WHEEL",
        "CONCORD_WHEEL",
    ):
        assert key not in result
    assert result["PYTHONDONTWRITEBYTECODE"] == "1"
    assert result["PYTHONNOUSERSITE"] == "1"


def test_success_requires_installed_program_and_external_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs["cwd"], kwargs["env"]))  # type: ignore[arg-type]
        return subprocess.CompletedProcess(
            command,
            0,
            "Meridian #123 11G populated installed domain acceptance passed.\n",
            "",
        )

    monkeypatch.setattr(wheel.subprocess, "run", run)
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "synthetic-root"
    wheel.run_prepared_smoke(Path("/venv/python"), outside, root)
    assert len(calls) == 1
    command, cwd, env = calls[0]
    assert Path(command[0]) == Path("/venv/python")
    assert command[1].endswith("smoke_program_issue123_populated_domain.py")
    assert command[2] == str(root)
    assert cwd == outside
    assert "PYTHONPATH" not in env
    assert not root.exists()


def test_program_error_and_missing_success_marker_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "synthetic-root"
    for code, stdout, stderr in (
        (1, "", "AssertionError"),
        (0, "silent success", ""),
        (0, "Traceback", ""),
    ):
        monkeypatch.setattr(
            wheel.subprocess,
            "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, stdout, stderr),
        )
        with pytest.raises(RuntimeError):
            wheel.run_prepared_smoke(Path("/venv/python"), outside, root)
    assert not root.exists()


def test_existing_synthetic_root_is_never_reused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "synthetic-root"
    root.mkdir()
    with pytest.raises(RuntimeError, match="new synthetic workspace"):
        wheel.run_prepared_smoke(Path("python"), outside, root)


def test_prepared_environment_reuses_exact_all_adapters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[object, ...]] = []

    class Prepared:
        def __init__(self, matrix: object, wheels: object) -> None:
            seen.append(("prepare", matrix, wheels))
            self.python = Path("/venv/python")

        def __enter__(self) -> "Prepared":
            return self

        def __exit__(self, *_args: object) -> None:
            seen.append(("exit",))

        def fresh_working_directory(self, name: str) -> Path:
            seen.append(("working", name))
            return tmp_path

        def assert_package_set_immutable(self, name: str) -> None:
            seen.append(("immutable", name))

    monkeypatch.setattr(wheel, "PreparedInstalledEnvironment", Prepared)
    monkeypatch.setattr(
        wheel,
        "run_prepared_smoke",
        lambda python, outside, root: seen.append(("smoke", python, outside, root)),
    )
    from scripts.installed_qualification_harness import InstalledWheelSet

    inputs = InstalledWheelSet(*(Path(str(i) + ".whl") for i in range(5)))
    wheel.smoke_test(inputs)
    assert seen[0][0] == "prepare"
    assert seen[0][1].matrix_id is wheel.DependencyMatrixId.ALL_ADAPTERS
    assert seen[1] == ("working", "issue123-11g-populated")
    assert seen[2] == (
        "smoke",
        Path("/venv/python"),
        tmp_path / "outside",
        tmp_path / "synthetic-root",
    )
    assert seen[3] == ("immutable", "issue123-11g-populated")
    assert seen[4] == ("exit",)


def test_program_is_bounded_to_synthetic_records_and_read_only_actions() -> None:
    source = wheel.PROGRAM.read_text(encoding="utf-8")
    for marker in (
        "trace_fixture._write_calculated_grade_item_result",
        "run_named_grade_item_review",
        "run_named_grade_item_proficiency",
        "NavigationScopeUnavailable",
        "read-only",
        "overwrite=True",
        "len(roster) == 29",
        "synthetic-private-evidence-token",
    ):
        assert marker in source
    assert "main()" in source
