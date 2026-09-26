"""Reusable prepared installed-environment harness for Issue #96.

The harness owns one temporary virtual environment for one explicit dependency
matrix. It installs the exact candidate/released wheel inputs once, runs one
``pip check``, verifies source/package isolation, fingerprints the installed
package set, and exposes fresh per-smoke working directories and processes.

Smoke migration into this harness is intentionally handled by later slices.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import venv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from scripts.installed_qualification_matrix import DependencyMatrix, DependencyMatrixId


@dataclass(frozen=True)
class InstalledWheelSet:
    """Exact local wheel artifacts available to prepared matrices."""

    meridian: Path
    core: Path
    scoreform: Path
    quillan: Path
    concord: Path

    def resolved(self) -> InstalledWheelSet:
        """Return the same wheel set with absolute paths."""
        return InstalledWheelSet(
            meridian=self.meridian.resolve(),
            core=self.core.resolve(),
            scoreform=self.scoreform.resolve(),
            quillan=self.quillan.resolve(),
            concord=self.concord.resolve(),
        )

    def for_matrix(self, matrix: DependencyMatrix) -> tuple[Path, ...]:
        """Return exact wheel install order for one dependency matrix."""
        producer_wheels = {
            "scoreform": self.scoreform,
            "quillan": self.quillan,
            "concord": self.concord,
        }
        return (
            self.core,
            *(producer_wheels[producer] for producer in matrix.producers),
            self.meridian,
        )


@dataclass(frozen=True)
class PreparedSmokeRun:
    """Diagnostic record for one command run in a prepared matrix."""

    matrix_id: DependencyMatrixId
    smoke_name: str
    command: tuple[str, ...]
    working_directory: Path


class PreparedEnvironmentError(RuntimeError):
    """Raised when prepared installed qualification fails closed."""


class PreparedInstalledEnvironment:
    """One temporary installed environment for one dependency matrix."""

    def __init__(
        self,
        matrix: DependencyMatrix,
        wheels: InstalledWheelSet,
        *,
        temp_parent: Path | None = None,
    ) -> None:
        self.matrix = matrix
        self.wheels = wheels.resolved()
        self.temp_parent = temp_parent
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._root: Path | None = None
        self._venv: Path | None = None
        self._outside: Path | None = None
        self._python: Path | None = None
        self._meridian: Path | None = None
        self._package_fingerprint: tuple[str, ...] | None = None
        self._smoke_counter = 0

    @property
    def root(self) -> Path:
        """Return the bounded temporary root after preparation."""
        if self._root is None:
            raise PreparedEnvironmentError("Prepared environment is not active.")
        return self._root

    @property
    def python(self) -> Path:
        """Return the prepared environment's Python executable."""
        if self._python is None:
            raise PreparedEnvironmentError("Prepared environment is not active.")
        return self._python

    @property
    def meridian(self) -> Path:
        """Return the prepared environment's Meridian executable."""
        if self._meridian is None:
            raise PreparedEnvironmentError("Prepared environment is not active.")
        return self._meridian

    @property
    def package_fingerprint(self) -> tuple[str, ...]:
        """Return the frozen package fingerprint captured after setup."""
        if self._package_fingerprint is None:
            raise PreparedEnvironmentError(
                "Prepared package fingerprint is not available."
            )
        return self._package_fingerprint

    def __enter__(self) -> PreparedInstalledEnvironment:
        self.prepare()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def prepare(self) -> None:
        """Create, install, check, verify, and freeze one matrix exactly once."""
        if self._temporary is not None:
            raise PreparedEnvironmentError(
                f"Matrix {self.matrix.matrix_id.value!r} is already prepared."
            )

        self._validate_wheel_inputs()
        prefix = f"pds-meridian-{self.matrix.matrix_id.value}-"
        parent = str(self.temp_parent.resolve()) if self.temp_parent else None
        self._temporary = tempfile.TemporaryDirectory(prefix=prefix, dir=parent)
        self._root = Path(self._temporary.name)
        self._venv = self.root / "venv"
        self._outside = self.root / "outside"
        self._outside.mkdir()

        try:
            venv.EnvBuilder(with_pip=True).create(self._venv)
            scripts = self._venv / ("Scripts" if os.name == "nt" else "bin")
            self._python = scripts / ("python.exe" if os.name == "nt" else "python")
            self._meridian = scripts / (
                "meridian.exe" if os.name == "nt" else "meridian"
            )

            install_command = [
                str(self.python),
                "-m",
                "pip",
                "install",
                *(
                    str(path)
                    for path in self.wheels.for_matrix(self.matrix)
                ),
            ]
            self._run_setup("package installation", install_command)
            self._run_setup(
                "pip check",
                [str(self.python), "-m", "pip", "check"],
            )
            self._verify_origins_and_absence()
            self._package_fingerprint = self._read_package_fingerprint()
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """Destroy the bounded temporary matrix environment."""
        temporary = self._temporary
        self._temporary = None
        self._root = None
        self._venv = None
        self._outside = None
        self._python = None
        self._meridian = None
        self._package_fingerprint = None
        self._smoke_counter = 0
        if temporary is not None:
            temporary.cleanup()

    def isolated_environment(
        self,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Return source-isolated subprocess state for installed qualification."""
        environment = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
        for variable in (
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONSTARTUP",
            "PDS_CORE_WHEEL",
            "SCOREFORM_WHEEL",
            "QUILLAN_WHEEL",
            "CONCORD_WHEEL",
        ):
            environment.pop(variable, None)
        if extra:
            environment.update(extra)
        return environment

    def fresh_working_directory(self, smoke_name: str) -> Path:
        """Create a unique empty working directory for one smoke workflow."""
        self._smoke_counter += 1
        safe_name = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in smoke_name
        ).strip("-")
        if not safe_name:
            safe_name = "smoke"
        directory = (
            self.root
            / "smokes"
            / f"{self._smoke_counter:02d}-{safe_name}"
        )
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def run_smoke(
        self,
        smoke_name: str,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run one smoke in a fresh process and enforce package immutability."""
        working_directory = cwd or self.fresh_working_directory(smoke_name)
        normalized_command = tuple(str(item) for item in command)
        print(
            f"[matrix={self.matrix.matrix_id.value}] "
            f"[smoke={smoke_name}] "
            f"+ {subprocess.list2cmdline(list(normalized_command))}",
            flush=True,
        )
        try:
            result = subprocess.run(
                list(normalized_command),
                cwd=working_directory,
                check=True,
                env=self.isolated_environment(env),
                input=input_text,
                text=True,
                capture_output=capture_output,
            )
        except subprocess.CalledProcessError as exc:
            raise PreparedEnvironmentError(
                f"Matrix {self.matrix.matrix_id.value!r} smoke "
                f"{smoke_name!r} failed: "
                f"{subprocess.list2cmdline(list(normalized_command))}"
            ) from exc

        self.assert_package_set_immutable(smoke_name)
        return result

    def assert_package_set_immutable(self, smoke_name: str) -> None:
        """Fail if a smoke changed any installed distribution in the matrix."""
        current = self._read_package_fingerprint()
        if current != self.package_fingerprint:
            raise PreparedEnvironmentError(
                f"Matrix {self.matrix.matrix_id.value!r} smoke "
                f"{smoke_name!r} changed the prepared package set."
            )

    def _validate_wheel_inputs(self) -> None:
        for path in self.wheels.for_matrix(self.matrix):
            if not path.is_file():
                raise PreparedEnvironmentError(
                    f"Matrix {self.matrix.matrix_id.value!r} wheel does not exist: "
                    f"{path}"
                )
            if path.suffix != ".whl":
                raise PreparedEnvironmentError(
                    f"Matrix {self.matrix.matrix_id.value!r} requires wheel input: "
                    f"{path}"
                )

    def _outside_directory(self) -> Path:
        if self._outside is None:
            raise PreparedEnvironmentError("Prepared environment is not active.")
        return self._outside

    def _run_setup(self, stage: str, command: list[str]) -> None:
        print(
            f"[matrix={self.matrix.matrix_id.value}] "
            f"[stage={stage}] + {subprocess.list2cmdline(command)}",
            flush=True,
        )
        try:
            subprocess.run(
                command,
                cwd=self._outside_directory(),
                check=True,
                env=self.isolated_environment(),
            )
        except subprocess.CalledProcessError as exc:
            raise PreparedEnvironmentError(
                f"Matrix {self.matrix.matrix_id.value!r} failed during {stage}: "
                f"{subprocess.list2cmdline(command)}"
            ) from exc

    def _verify_origins_and_absence(self) -> None:
        present_modules = ("meridian", "pds_core", *self.matrix.producers)
        absent_modules = self.matrix.excluded_producers
        code = (
            "import importlib.util, pathlib, sys; "
            "root=pathlib.Path(sys.prefix).resolve(); "
            f"present={present_modules!r}; absent={absent_modules!r}; "
            "mods=[__import__(name) for name in present]; "
            "assert all("
            "pathlib.Path(module.__file__).resolve().is_relative_to(root) "
            "for module in mods"
            "); "
            "assert all(importlib.util.find_spec(name) is None for name in absent)"
        )
        self._run_setup(
            "origin/isolation verification",
            [str(self.python), "-I", "-c", code],
        )

    def _read_package_fingerprint(self) -> tuple[str, ...]:
        try:
            result = subprocess.run(
                [str(self.python), "-m", "pip", "freeze", "--all"],
                cwd=self._outside_directory(),
                check=True,
                env=self.isolated_environment(),
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise PreparedEnvironmentError(
                f"Matrix {self.matrix.matrix_id.value!r} could not fingerprint "
                "the installed package set."
            ) from exc
        return tuple(
            sorted(
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip()
            )
        )
