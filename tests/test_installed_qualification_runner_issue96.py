from __future__ import annotations

import subprocess
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

import scripts.installed_qualification_runner as runner
from scripts.installed_qualification_harness import InstalledWheelSet
from scripts.installed_qualification_matrix import DependencyMatrixId


class FakePreparedEnvironment:
    entered: list[DependencyMatrixId] = []
    immutable: list[tuple[DependencyMatrixId, str]] = []
    roots: list[tuple[DependencyMatrixId, str, Path]] = []

    def __init__(
        self,
        matrix: Any,
        wheels: InstalledWheelSet,
        *,
        temp_parent: Path | None = None,
    ) -> None:
        del wheels, temp_parent
        self.matrix = matrix
        self.python = Path(f"python-{matrix.matrix_id.value}")
        self.meridian = Path(f"meridian-{matrix.matrix_id.value}")
        self._counter = 0

    def __enter__(self) -> FakePreparedEnvironment:
        type(self).entered.append(self.matrix.matrix_id)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    def fresh_working_directory(self, smoke_name: str) -> Path:
        self._counter += 1
        path = Path(
            f"prepared-{self.matrix.matrix_id.value}-"
            f"{self._counter:02d}-{smoke_name}"
        )
        type(self).roots.append((self.matrix.matrix_id, smoke_name, path))
        return path

    def assert_package_set_immutable(self, smoke_name: str) -> None:
        type(self).immutable.append((self.matrix.matrix_id, smoke_name))


@pytest.fixture(autouse=True)
def _reset_fake_state() -> None:
    FakePreparedEnvironment.entered.clear()
    FakePreparedEnvironment.immutable.clear()
    FakePreparedEnvironment.roots.clear()


def _wheels(tmp_path: Path) -> InstalledWheelSet:
    paths = []
    for filename in (
        "pds_meridian-0.3.0-py3-none-any.whl",
        "pds_core-0.6.3-py3-none-any.whl",
        "scoreform-0.11.0-py3-none-any.whl",
        "quillan-0.10.2-py3-none-any.whl",
        "pds_concord-0.3.0-py3-none-any.whl",
    ):
        path = tmp_path / filename
        path.write_bytes(b"synthetic")
        paths.append(path)
    return InstalledWheelSet(*paths)


def test_issue96_central_runner_prepares_exact_migrated_matrix_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []

    monkeypatch.setattr(
        runner,
        "PreparedInstalledEnvironment",
        FakePreparedEnvironment,
    )

    def record(name: str):
        def action(*args: object) -> None:
            calls.append((name, args))
        return action

    monkeypatch.setattr(runner, "run_core_foundation_prepared_smoke", record("core"))
    monkeypatch.setattr(runner, "run_core_inline_smokes", record("core-inline"))
    monkeypatch.setattr(runner, "run_core_program_smokes", record("core-programs"))
    monkeypatch.setattr(
        runner,
        "run_scoreform_adapter_prepared_smoke",
        record("scoreform"),
    )
    monkeypatch.setattr(
        runner,
        "run_quillan_adapter_prepared_smoke",
        record("quillan"),
    )
    monkeypatch.setattr(
        runner,
        "run_concord_adapter_prepared_smoke",
        record("concord"),
    )
    monkeypatch.setattr(
        runner,
        "run_all_adapters_prepared_smoke",
        record("all-adapters"),
    )
    monkeypatch.setattr(Path, "mkdir", lambda self: None)

    runner.run_migrated_matrices(_wheels(tmp_path), temp_parent=tmp_path)

    assert FakePreparedEnvironment.entered == [
        DependencyMatrixId.CORE,
        DependencyMatrixId.SCOREFORM,
        DependencyMatrixId.QUILLAN,
        DependencyMatrixId.CONCORD,
        DependencyMatrixId.ALL_ADAPTERS,
    ]
    assert [name for name, _ in calls] == [
        "core",
        "core-inline",
        "core-programs",
        "scoreform",
        "quillan",
        "concord",
        "all-adapters",
    ]
    assert FakePreparedEnvironment.immutable == [
        (DependencyMatrixId.CORE, "wheel-foundation"),
        (DependencyMatrixId.SCOREFORM, "scoreform-adapter"),
        (DependencyMatrixId.QUILLAN, "quillan-adapter"),
        (DependencyMatrixId.CONCORD, "concord-adapter"),
        (DependencyMatrixId.ALL_ADAPTERS, "all-adapters-composition"),
    ]


def test_issue96_adapter_helpers_receive_their_prepared_interpreters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Path] = {}

    monkeypatch.setattr(
        runner,
        "PreparedInstalledEnvironment",
        FakePreparedEnvironment,
    )
    monkeypatch.setattr(Path, "mkdir", lambda self: None)
    monkeypatch.setattr(runner, "run_core_inline_smokes", lambda prepared: None)
    monkeypatch.setattr(runner, "run_core_program_smokes", lambda prepared: None)

    def capture(name: str):
        def action(python: Path, *args: object) -> None:
            del args
            observed[name] = python
        return action

    monkeypatch.setattr(
        runner,
        "run_core_foundation_prepared_smoke",
        capture("core"),
    )
    monkeypatch.setattr(
        runner,
        "run_scoreform_adapter_prepared_smoke",
        capture("scoreform"),
    )
    monkeypatch.setattr(
        runner,
        "run_quillan_adapter_prepared_smoke",
        capture("quillan"),
    )
    monkeypatch.setattr(
        runner,
        "run_concord_adapter_prepared_smoke",
        capture("concord"),
    )
    monkeypatch.setattr(
        runner,
        "run_all_adapters_prepared_smoke",
        capture("all-adapters"),
    )

    runner.run_migrated_matrices(_wheels(tmp_path))

    assert observed == {
        "core": Path("python-core"),
        "scoreform": Path("python-scoreform"),
        "quillan": Path("python-quillan"),
        "concord": Path("python-concord"),
        "all-adapters": Path("python-all-adapters"),
    }


def test_issue96_central_runner_wraps_matrix_smoke_command_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "PreparedInstalledEnvironment",
        FakePreparedEnvironment,
    )
    monkeypatch.setattr(Path, "mkdir", lambda self: None)
    monkeypatch.setattr(runner, "run_core_inline_smokes", lambda prepared: None)
    monkeypatch.setattr(runner, "run_core_program_smokes", lambda prepared: None)

    def fail_core(*args: object) -> None:
        del args
        raise subprocess.CalledProcessError(
            7,
            ["python-core", "-c", "broken"],
        )

    monkeypatch.setattr(runner, "run_core_foundation_prepared_smoke", fail_core)

    with pytest.raises(Exception) as captured:
        runner.run_migrated_matrices(_wheels(tmp_path))

    message = str(captured.value)
    assert "core" in message
    assert "wheel-foundation" in message
    assert "python-core" in message
    assert "broken" in message


def test_issue96_central_runner_contains_no_environment_setup_commands() -> None:
    source = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )

    assert "venv.EnvBuilder" not in source
    assert "pip install" not in source
    assert "pip check" not in source


def test_issue96_validator_uses_central_runner_once() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")

    assert validator.count("scripts.installed_qualification_runner") == 1
    assert "scripts/smoke_test_wheel.py" not in validator
    assert "scripts.installed_qualification_core_programs" not in validator


def test_issue96_smoke_test_wheel_keeps_standalone_five_environment_path() -> None:
    source = Path("scripts/smoke_test_wheel.py").read_text(encoding="utf-8")

    assert source.count("venv.EnvBuilder(with_pip=True).create(environment)") == 5
    for helper in (
        "run_core_foundation_prepared_smoke",
        "run_scoreform_adapter_prepared_smoke",
        "run_quillan_adapter_prepared_smoke",
        "run_concord_adapter_prepared_smoke",
        "run_all_adapters_prepared_smoke",
    ):
        assert f"def {helper}(" in source
