"""Reusable prepared installed-environment harness for Issue #96.

The harness owns one temporary virtual environment for one explicit dependency
matrix. It installs the exact candidate/released wheel inputs once, runs one
``pip check``, verifies source/package isolation, fingerprints the installed
package set, and exposes fresh per-smoke working directories and processes.

Smoke migration into this harness is intentionally handled by later slices.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import venv
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from types import TracebackType

from scripts.installed_qualification_matrix import DependencyMatrix, DependencyMatrixId


@dataclass(frozen=True)
class WheelIdentity:
    """Distribution identity declared by one exact supplied wheel artifact."""

    wheel: Path
    distribution: str
    version: str


def _normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_wheel_identity(
    wheel: Path,
    expected_distribution: str,
) -> WheelIdentity:
    """Read and validate one wheel's distribution identity from METADATA."""
    resolved = wheel.resolve()
    if not resolved.is_file():
        raise PreparedEnvironmentError(f"wheel does not exist: {resolved}")
    if resolved.suffix != ".whl":
        raise PreparedEnvironmentError(f"Expected wheel input: {resolved}")

    try:
        with zipfile.ZipFile(resolved) as archive:
            metadata_members = tuple(
                member
                for member in archive.namelist()
                if member.endswith(".dist-info/METADATA")
            )
            if len(metadata_members) != 1:
                raise PreparedEnvironmentError(
                    f"Wheel must contain exactly one dist-info METADATA file: "
                    f"{resolved}"
                )
            raw_metadata = archive.read(metadata_members[0]).decode("utf-8")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise PreparedEnvironmentError(
            f"Could not read wheel metadata: {resolved}"
        ) from exc

    metadata = Parser().parsestr(raw_metadata)
    distribution = metadata.get("Name")
    version = metadata.get("Version")
    if not distribution or not version:
        raise PreparedEnvironmentError(
            f"Wheel metadata is missing Name/Version: {resolved}"
        )

    normalized = _normalize_distribution_name(distribution)
    expected = _normalize_distribution_name(expected_distribution)
    if normalized != expected:
        raise PreparedEnvironmentError(
            f"Wheel distribution identity mismatch for {resolved}: "
            f"expected {expected_distribution!r}, found {distribution!r}."
        )
    return WheelIdentity(
        wheel=resolved,
        distribution=expected,
        version=version,
    )


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

    def identities_for_matrix(
        self,
        matrix: DependencyMatrix,
    ) -> tuple[WheelIdentity, ...]:
        """Return artifact-derived PDS distribution identities for one matrix."""
        wheel_roles = {
            "scoreform": (self.scoreform, "scoreform"),
            "quillan": (self.quillan, "quillan"),
            "concord": (self.concord, "pds-concord"),
        }
        return (
            read_wheel_identity(self.core, "pds-core"),
            *(
                read_wheel_identity(*wheel_roles[producer])
                for producer in matrix.producers
            ),
            read_wheel_identity(self.meridian, "pds-meridian"),
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
        try:
            self.wheels.identities_for_matrix(self.matrix)
        except PreparedEnvironmentError as exc:
            raise PreparedEnvironmentError(
                f"Matrix {self.matrix.matrix_id.value!r} has invalid wheel input: "
                f"{exc}"
            ) from exc

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
        identities = self.wheels.identities_for_matrix(self.matrix)
        expected_distributions = tuple(
            (identity.distribution, identity.version)
            for identity in identities
        )
        producer_distributions = {
            "scoreform": "scoreform",
            "quillan": "quillan",
            "concord": "pds-concord",
        }
        absent_distributions = tuple(
            producer_distributions[producer]
            for producer in self.matrix.excluded_producers
        )
        code = (
            "import importlib.util, pathlib, sys; "
            "from importlib import metadata; "
            "root=pathlib.Path(sys.prefix).resolve(); "
            f"present={present_modules!r}; absent={absent_modules!r}; "
            f"expected_distributions={expected_distributions!r}; "
            f"absent_distributions={absent_distributions!r}; "
            "mods=[__import__(name) for name in present]; "
            "assert all("
            "pathlib.Path(module.__file__).resolve().is_relative_to(root) "
            "for module in mods"
            "); "
            "assert all("
            "metadata.version(distribution) == version "
            "for distribution, version in expected_distributions"
            "); "
            "assert all("
            "pathlib.Path(metadata.distribution(distribution).locate_file(''))"
            ".resolve().is_relative_to(root) "
            "for distribution, _version in expected_distributions"
            "); "
            "assert all(importlib.util.find_spec(name) is None for name in absent); "
            "exec("
            "\"def _distribution_absent(distribution):\\n"
            "    try:\\n"
            "        metadata.version(distribution)\\n"
            "    except metadata.PackageNotFoundError:\\n"
            "        return True\\n"
            "    return False\""
            "); "
            "assert all(_distribution_absent(name) "
            "for name in absent_distributions)"
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
