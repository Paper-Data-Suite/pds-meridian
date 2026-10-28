"""Issue #123 Slice 11D: isolated wheel-navigation harness contracts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts import smoke_test_issue123_navigation_wheel as wheel


def test_installed_cases_cover_eight_domains_and_nested_planning() -> None:
    cases = wheel._menu_cases()
    assert len(cases) == 9
    assert len({case[0] for case in cases}) == 9
    assert cases[-1][0] == "nested-planning"
    assert "14" not in cases[-1][1]  # No academic action is triggered.
    assert all(case[1].endswith("q\n") for case in cases)
    assert all("b\n" in case[1] for case in cases)
    assert all(len(case[2]) >= 3 for case in cases)


def test_source_paths_and_developer_wheel_variables_are_removed(
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
        monkeypatch.setenv(key, "unexpected")
    environment = wheel._environment()
    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    assert "PYTHONSTARTUP" not in environment
    assert all(key not in environment for key in os.environ if key.endswith("_WHEEL"))
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTHONNOUSERSITE"] == "1"


def test_verifier_rejects_bad_status_traceback_missing_route_and_raw_prompt() -> None:
    valid = subprocess.CompletedProcess([], 0, "Named route", "")
    wheel._require_pass("probe", valid, ("Named route",))
    with pytest.raises(RuntimeError, match="exited"):
        wheel._require_pass("probe", subprocess.CompletedProcess([], 2, "", ""), ())
    with pytest.raises(RuntimeError, match="traceback"):
        wheel._require_pass(
            "probe", subprocess.CompletedProcess([], 0, "", "Traceback"), ()
        )
    with pytest.raises(RuntimeError, match="missing"):
        wheel._require_pass("probe", valid, ("Other",))
    with pytest.raises(RuntimeError, match="technical input"):
        wheel._require_pass(
            "probe", subprocess.CompletedProcess([], 0, "Class ID: ", ""), ()
        )


def test_prepared_smoke_runs_from_outside_and_never_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[tuple[str, ...], str | None, Path]] = []

    def fake_run(
        command: list[str], *, cwd: Path, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        seen.append((tuple(command), stdin, cwd))
        if len(command) > 2 and command[1] == "-c":
            return subprocess.CompletedProcess(command, 0, "", "")
        required = ()
        if stdin == "8\nm\nq\n":
            required = ("Explain", "1. Review New Evidence", "1. Review New Evidence")
        elif stdin == "2\nq\n":
            required = ("Manage Grade Items",)
        else:
            required = next(case[2] for case in wheel._menu_cases() if case[1] == stdin)
        return subprocess.CompletedProcess(
            command, 0, "\n".join((*required, "1. Review New Evidence")), ""
        )

    monkeypatch.setattr(wheel, "_run", fake_run)
    wheel.run_prepared_smoke(
        Path("/isolated/python"), Path("/isolated/meridian"), tmp_path
    )
    assert len(seen) == 12  # origin, nine menus, M, nested Q
    assert all(cwd == tmp_path for _, _, cwd in seen)
    assert not tuple(tmp_path.iterdir())


def test_prepared_smoke_fails_before_menu_if_wheel_origin_is_wrong(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def bad_import(
        command: list[str], *, cwd: Path, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return subprocess.CompletedProcess(command, 1, "", "origin violation")

    monkeypatch.setattr(wheel, "_run", bad_import)
    with pytest.raises(RuntimeError, match="installed imports"):
        wheel.run_prepared_smoke(Path("python"), Path("meridian"), tmp_path)
    assert len(seen) == 1


def test_all_adapters_harness_is_reused_without_changing_issue96_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.installed_qualification_matrix import DependencyMatrixId

    calls: list[tuple[object, ...]] = []

    class Prepared:
        def __init__(self, matrix: object, wheels: object) -> None:
            calls.append(("create", matrix, wheels))
            self.python = Path("/prepared/python")
            self.meridian = Path("/prepared/meridian")

        def __enter__(self) -> "Prepared":
            return self

        def __exit__(self, *_args: object) -> None:
            calls.append(("exit",))

        def fresh_working_directory(self, smoke_name: str) -> Path:
            calls.append(("folder", smoke_name))
            return tmp_path

        def assert_package_set_immutable(self, smoke_name: str) -> None:
            calls.append(("immutable", smoke_name))

    monkeypatch.setattr(wheel, "PreparedInstalledEnvironment", Prepared)
    monkeypatch.setattr(
        wheel,
        "run_prepared_smoke",
        lambda python, meridian, outside: calls.append(
            ("smoke", python, meridian, outside)
        ),
    )
    from scripts.installed_qualification_harness import InstalledWheelSet

    paths = [
        Path(name)
        for name in ("meridian.whl", "core.whl", "sf.whl", "quillan.whl", "concord.whl")
    ]
    wheel.smoke_test(InstalledWheelSet(*paths))
    assert calls[0][0] == "create"
    assert calls[0][1].matrix_id is DependencyMatrixId.ALL_ADAPTERS
    assert calls[1] == ("folder", "issue123-navigation")
    assert calls[2] == (
        "smoke",
        Path("/prepared/python"),
        Path("/prepared/meridian"),
        tmp_path / "outside",
    )
    assert calls[3] == ("immutable", "issue123-navigation")
    assert calls[4] == ("exit",)
    assert (tmp_path / "outside").is_dir()


def test_standalone_cli_requires_all_five_wheel_paths() -> None:
    with pytest.raises(SystemExit) as error:
        wheel.main([])
    assert error.value.code == 2
