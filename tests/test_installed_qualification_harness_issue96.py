from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.installed_qualification_harness import (
    InstalledWheelSet,
    PreparedEnvironmentError,
    PreparedInstalledEnvironment,
)
from scripts.installed_qualification_matrix import DependencyMatrixId, matrix_for


def _wheels(tmp_path: Path) -> InstalledWheelSet:
    paths = {
        name: tmp_path / filename
        for name, filename in (
            ("meridian", "pds_meridian-0.3.0-py3-none-any.whl"),
            ("core", "pds_core-0.6.3-py3-none-any.whl"),
            ("scoreform", "scoreform-0.11.0-py3-none-any.whl"),
            ("quillan", "quillan-0.10.2-py3-none-any.whl"),
            ("concord", "pds_concord-0.3.0-py3-none-any.whl"),
        )
    }
    for path in paths.values():
        path.write_bytes(b"synthetic")
    return InstalledWheelSet(**paths)


def test_issue96_wheel_set_selects_exact_matrix_inputs(tmp_path: Path) -> None:
    wheels = _wheels(tmp_path).resolved()

    assert wheels.for_matrix(matrix_for(DependencyMatrixId.CORE)) == (
        wheels.core,
        wheels.meridian,
    )
    assert wheels.for_matrix(matrix_for(DependencyMatrixId.SCOREFORM_QUILLAN)) == (
        wheels.core,
        wheels.scoreform,
        wheels.quillan,
        wheels.meridian,
    )
    assert wheels.for_matrix(matrix_for(DependencyMatrixId.ALL_ADAPTERS)) == (
        wheels.core,
        wheels.scoreform,
        wheels.quillan,
        wheels.concord,
        wheels.meridian,
    )


def test_issue96_isolated_environment_neutralizes_source_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "repo-source")
    monkeypatch.setenv("PYTHONHOME", "repo-home")
    monkeypatch.setenv("PYTHONSTARTUP", "startup.py")
    monkeypatch.setenv("PDS_CORE_WHEEL", "ambient-core.whl")
    monkeypatch.setenv("SCOREFORM_WHEEL", "ambient-scoreform.whl")
    monkeypatch.setenv("QUILLAN_WHEEL", "ambient-quillan.whl")
    monkeypatch.setenv("CONCORD_WHEEL", "ambient-concord.whl")

    prepared = PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.CORE),
        _wheels(tmp_path),
    )
    environment = prepared.isolated_environment({"ISSUE96_MARKER": "yes"})

    for variable in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PDS_CORE_WHEEL",
        "SCOREFORM_WHEEL",
        "QUILLAN_WHEEL",
        "CONCORD_WHEEL",
    ):
        assert variable not in environment
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["ISSUE96_MARKER"] == "yes"


def test_issue96_missing_wheel_fails_before_environment_creation(
    tmp_path: Path,
) -> None:
    wheels = _wheels(tmp_path)
    wheels.scoreform.unlink()
    prepared = PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.SCOREFORM),
        wheels,
    )

    with pytest.raises(PreparedEnvironmentError, match="wheel does not exist"):
        prepared.prepare()


def test_issue96_prepare_installs_and_checks_matrix_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheels = _wheels(tmp_path).resolved()
    matrix = matrix_for(DependencyMatrixId.SCOREFORM_QUILLAN)
    prepared = PreparedInstalledEnvironment(matrix, wheels, temp_parent=tmp_path)
    created: list[Path] = []
    commands: list[list[str]] = []
    freeze_count = 0

    def fake_create(_builder: object, path: Path) -> None:
        created.append(Path(path))
        scripts = Path(path) / ("Scripts" if os.name == "nt" else "bin")
        scripts.mkdir(parents=True)

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal freeze_count
        commands.append(command)
        if command[-3:] == ["pip", "freeze", "--all"]:
            freeze_count += 1
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="pds-core==0.6.3\npds-meridian==0.3.0\n"
                "quillan==0.10.2\nscoreform==0.11.0\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("venv.EnvBuilder.create", fake_create)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with prepared:
        assert len(created) == 1
        assert prepared.package_fingerprint == (
            "pds-core==0.6.3",
            "pds-meridian==0.3.0",
            "quillan==0.10.2",
            "scoreform==0.11.0",
        )

        install_commands = [
            command
            for command in commands
            if command[1:4] == ["-m", "pip", "install"]
        ]
        check_commands = [
            command
            for command in commands
            if command[1:] == ["-m", "pip", "check"]
        ]
        origin_commands = [
            command
            for command in commands
            if command[1:3] == ["-I", "-c"]
        ]

        assert len(install_commands) == 1
        assert len(check_commands) == 1
        assert len(origin_commands) == 1
        assert freeze_count == 1
        assert install_commands[0][-4:] == [
            str(wheels.core),
            str(wheels.scoreform),
            str(wheels.quillan),
            str(wheels.meridian),
        ]
        origin_code = origin_commands[0][-1]
        assert "('meridian', 'pds_core', 'scoreform', 'quillan')" in origin_code
        assert "absent=('concord',)" in origin_code

    assert not any(tmp_path.glob("pds-meridian-scoreform-quillan-*"))


def test_issue96_prepared_matrix_cannot_be_prepared_twice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.CORE),
        _wheels(tmp_path),
        temp_parent=tmp_path,
    )

    monkeypatch.setattr(
        "venv.EnvBuilder.create",
        lambda _builder, path: Path(path).mkdir(),
    )

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[-3:] == ["pip", "freeze", "--all"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="pds-core==0.6.3\npds-meridian==0.3.0\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    try:
        prepared.prepare()
        with pytest.raises(PreparedEnvironmentError, match="already prepared"):
            prepared.prepare()
    finally:
        prepared.close()


def test_issue96_fresh_working_directories_do_not_share_state(
    tmp_path: Path,
) -> None:
    prepared = PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.CORE),
        _wheels(tmp_path),
    )
    prepared._root = tmp_path / "matrix"  # noqa: SLF001
    prepared.root.mkdir()

    first = prepared.fresh_working_directory("first smoke")
    (first / "state.json").write_text("first", encoding="utf-8")
    second = prepared.fresh_working_directory("second smoke")

    assert first != second
    assert list(second.iterdir()) == []
    assert not (second / "state.json").exists()


def test_issue96_run_smoke_uses_fresh_process_and_rechecks_packages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.CORE),
        _wheels(tmp_path),
    )
    prepared._root = tmp_path / "matrix"  # noqa: SLF001
    prepared.root.mkdir()
    prepared._outside = prepared.root / "outside"  # noqa: SLF001
    prepared._outside.mkdir()  # noqa: SLF001
    prepared._python = Path("python")  # noqa: SLF001
    prepared._package_fingerprint = ("pds-core==0.6.3",)  # noqa: SLF001
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[-3:] == ["pip", "freeze", "--all"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="pds-core==0.6.3\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    prepared.run_smoke("alpha", ["python", "alpha.py"])
    prepared.run_smoke("beta", ["python", "beta.py"])

    smoke_calls = [call for call in calls if call[-1] in {"alpha.py", "beta.py"}]
    freeze_calls = [call for call in calls if call[-3:] == ["pip", "freeze", "--all"]]

    assert smoke_calls == [["python", "alpha.py"], ["python", "beta.py"]]
    assert len(freeze_calls) == 2
    assert (prepared.root / "smokes" / "01-alpha").is_dir()
    assert (prepared.root / "smokes" / "02-beta").is_dir()


def test_issue96_package_mutation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.CORE),
        _wheels(tmp_path),
    )
    prepared._root = tmp_path / "matrix"  # noqa: SLF001
    prepared.root.mkdir()
    prepared._outside = prepared.root / "outside"  # noqa: SLF001
    prepared._outside.mkdir()  # noqa: SLF001
    prepared._python = Path("python")  # noqa: SLF001
    prepared._package_fingerprint = ("pds-core==0.6.3",)  # noqa: SLF001

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[-3:] == ["pip", "freeze", "--all"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="pds-core==0.6.3\nsurprise==1.0\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(PreparedEnvironmentError, match="changed the prepared package"):
        prepared.run_smoke("mutating-smoke", ["python", "smoke.py"])


def test_issue96_failure_diagnostic_names_matrix_smoke_and_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.CORE),
        _wheels(tmp_path),
    )
    prepared._root = tmp_path / "matrix"  # noqa: SLF001
    prepared.root.mkdir()
    prepared._python = Path("python")  # noqa: SLF001
    prepared._package_fingerprint = ()  # noqa: SLF001

    def fail(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(9, command)

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(PreparedEnvironmentError) as captured:
        prepared.run_smoke("broken-workflow", ["python", "broken.py"])

    message = str(captured.value)
    assert "core" in message
    assert "broken-workflow" in message
    assert "broken.py" in message
