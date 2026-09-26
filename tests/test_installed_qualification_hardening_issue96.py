from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts.installed_qualification_harness import (
    InstalledWheelSet,
    PreparedEnvironmentError,
    PreparedInstalledEnvironment,
    read_wheel_identity,
)
from scripts.installed_qualification_matrix import DependencyMatrixId, matrix_for


def _write_wheel(path: Path, distribution: str, version: str) -> None:
    stem = distribution.replace("-", "_")
    metadata_path = f"{stem}-{version}.dist-info/METADATA"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            metadata_path,
            (
                "Metadata-Version: 2.1\n"
                f"Name: {distribution}\n"
                f"Version: {version}\n"
                "\n"
            ),
        )


def _wheels(tmp_path: Path) -> InstalledWheelSet:
    specs = (
        ("meridian", "pds_meridian-0.3.0-py3-none-any.whl", "pds-meridian", "0.3.0"),
        ("core", "pds_core-0.6.3-py3-none-any.whl", "pds-core", "0.6.3"),
        ("scoreform", "scoreform-0.11.0-py3-none-any.whl", "scoreform", "0.11.0"),
        ("quillan", "quillan-0.10.2-py3-none-any.whl", "quillan", "0.10.2"),
        ("concord", "pds_concord-0.3.0-py3-none-any.whl", "pds-concord", "0.3.0"),
    )
    paths: dict[str, Path] = {}
    for field, filename, distribution, version in specs:
        path = tmp_path / filename
        _write_wheel(path, distribution, version)
        paths[field] = path
    return InstalledWheelSet(**paths)


def test_issue96_wheel_identity_is_read_from_artifact_metadata(
    tmp_path: Path,
) -> None:
    wheels = _wheels(tmp_path)

    identity = read_wheel_identity(wheels.quillan, "quillan")

    assert identity.distribution == "quillan"
    assert identity.version == "0.10.2"
    assert identity.wheel == wheels.quillan.resolve()


def test_issue96_wheel_identity_rejects_wrong_distribution_name(
    tmp_path: Path,
) -> None:
    path = tmp_path / "scoreform-0.11.0-py3-none-any.whl"
    _write_wheel(path, "not-scoreform", "0.11.0")

    with pytest.raises(PreparedEnvironmentError, match="distribution identity"):
        read_wheel_identity(path, "scoreform")


def test_issue96_matrix_expected_distributions_come_from_supplied_wheels(
    tmp_path: Path,
) -> None:
    wheels = _wheels(tmp_path).resolved()

    identities = wheels.identities_for_matrix(
        matrix_for(DependencyMatrixId.SCOREFORM_QUILLAN)
    )

    assert tuple((item.distribution, item.version) for item in identities) == (
        ("pds-core", "0.6.3"),
        ("scoreform", "0.11.0"),
        ("quillan", "0.10.2"),
        ("pds-meridian", "0.3.0"),
    )


def test_issue96_origin_probe_checks_distribution_versions_and_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheels = _wheels(tmp_path)
    prepared = PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.SCOREFORM_QUILLAN),
        wheels,
    )
    prepared._root = tmp_path / "matrix"  # noqa: SLF001
    prepared.root.mkdir()
    prepared._outside = prepared.root / "outside"  # noqa: SLF001
    prepared._outside.mkdir()  # noqa: SLF001
    prepared._python = Path("python")  # noqa: SLF001
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    prepared._verify_origins_and_absence()  # noqa: SLF001

    assert len(commands) == 1
    code = commands[0][-1]
    assert "('pds-core', '0.6.3')" in code
    assert "('scoreform', '0.11.0')" in code
    assert "('quillan', '0.10.2')" in code
    assert "('pds-meridian', '0.3.0')" in code
    assert "absent_distributions=('pds-concord',)" in code
    assert "metadata.version(distribution) == version" in code
    assert "metadata.PackageNotFoundError" in code
    assert "metadata.distribution(distribution).locate_file('')" in code


def test_issue96_prepare_failure_cleans_bounded_matrix_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.CORE),
        _wheels(tmp_path),
        temp_parent=tmp_path,
    )

    def fake_create(_builder: object, path: Path) -> None:
        scripts = Path(path) / ("Scripts" if os.name == "nt" else "bin")
        scripts.mkdir(parents=True)

    def fail_install(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(17, command)

    monkeypatch.setattr("venv.EnvBuilder.create", fake_create)
    monkeypatch.setattr(subprocess, "run", fail_install)

    with pytest.raises(
        PreparedEnvironmentError,
        match="failed during package installation",
    ):
        prepared.prepare()

    assert not any(tmp_path.glob("pds-meridian-core-*"))


def test_issue96_normal_validator_has_no_legacy_smoke_wrapper_execution() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    runner = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )

    assert validator.count("scripts.installed_qualification_runner") == 1
    assert "scripts/smoke_test_" not in validator
    assert "venv.EnvBuilder" not in runner
    assert "pip install" not in runner
    assert "pip uninstall" not in runner
    assert "pip check" not in runner


def test_issue96_structural_counts_are_exactly_six_after_consolidation() -> None:
    document = Path("docs/development/installed-qualification-matrix.md").read_text(
        encoding="utf-8"
    )

    assert "| Temporary installed venvs | 24 | 6 |" in document
    assert "| Package-install setups | 24 | 6 |" in document
    assert "| `pip check` runs | 24 | 6 |" in document
