from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.check_sdist import (
    EXPECTED_ROOT,
    EXPECTED_SDIST_FILENAME,
    SdistValidationError,
    validate_sdist,
)
from scripts.smoke_test_wheel import _isolated_environment
from scripts.verify_dependency_direction import (
    DependencyDirectionVerificationError,
    verify_no_meridian_dependency,
)


def _write_metadata_wheel(path: Path, requirements: tuple[str, ...]) -> None:
    metadata = [
        "Metadata-Version: 2.4",
        "Name: synthetic-upstream",
        "Version: 1.0.0",
        *(f"Requires-Dist: {requirement}" for requirement in requirements),
        "",
        "",
    ]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "synthetic_upstream-1.0.0.dist-info/METADATA", "\n".join(metadata)
        )


def _add_tar_file(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    archive.addfile(info, io.BytesIO(content))


def _write_minimal_sdist(path: Path, *, extra_member: str | None = None) -> None:
    required = {
        "CHANGELOG.md": b"# Changelog\n",
        "LICENSE": b"synthetic license\n",
        "MANIFEST.in": b"include README\n",
        "README": b"# Meridian\n",
        "Security.md": b"# Security\n",
        "pyproject.toml": b"[build-system]\n",
        "docs/README.md": b"# Documentation\n",
        "meridian/__init__.py": b"",
        "meridian/_version.py": b'__version__ = "0.1.1.dev0"\n',
        "meridian/py.typed": b"",
        "scripts/validate_repository.py": b"",
        "tests/test_validation_scripts.py": b"",
    }
    pkg_info = (
        "Metadata-Version: 2.4\n"
        "Name: pds-meridian\n"
        "Version: 0.1.1.dev0\n\n"
    ).encode()
    with tarfile.open(path, "w:gz") as archive:
        _add_tar_file(archive, f"{EXPECTED_ROOT}/PKG-INFO", pkg_info)
        for relative, content in required.items():
            _add_tar_file(archive, f"{EXPECTED_ROOT}/{relative}", content)
        if extra_member is not None:
            _add_tar_file(
                archive,
                f"{EXPECTED_ROOT}/{extra_member}",
                b"synthetic private residue\n",
            )


def test_upstream_dependency_direction_allows_core_dependency(tmp_path: Path) -> None:
    wheel = tmp_path / "synthetic.whl"
    _write_metadata_wheel(wheel, ("pds-core>=0.6,<0.7",))
    verify_no_meridian_dependency(wheel)


def test_upstream_dependency_direction_rejects_meridian_dependency(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "synthetic.whl"
    _write_metadata_wheel(
        wheel,
        ("pds-core>=0.6,<0.7", "pds_meridian>=0.1.1; python_version >= '3.11'"),
    )
    with pytest.raises(
        DependencyDirectionVerificationError, match="must not depend on pds-meridian"
    ):
        verify_no_meridian_dependency(wheel)


def test_sdist_checker_accepts_intentional_source_surface(tmp_path: Path) -> None:
    sdist = tmp_path / EXPECTED_SDIST_FILENAME
    _write_minimal_sdist(sdist)
    validate_sdist(sdist)


def test_sdist_checker_rejects_private_workspace_content(tmp_path: Path) -> None:
    sdist = tmp_path / EXPECTED_SDIST_FILENAME
    _write_minimal_sdist(sdist, extra_member="classes/class_2026/student.json")
    with pytest.raises(SdistValidationError, match="forbidden content"):
        validate_sdist(sdist)


def test_smoke_environment_drops_source_path_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "synthetic-source-tree")
    monkeypatch.setenv("PYTHONHOME", "synthetic-python-home")
    monkeypatch.setenv("PYTHONSTARTUP", "synthetic-startup.py")
    environment = _isolated_environment()
    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    assert "PYTHONSTARTUP" not in environment
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"


def test_release_validator_wires_all_issue14_qualification_gates() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    smoke = Path("scripts/smoke_test_wheel.py").read_text(encoding="utf-8")

    assert "scripts/verify_dependency_direction.py" in validator
    assert "scripts/check_sdist.py" in validator
    assert 'sdists = list(dist.glob("*.tar.gz"))' in validator
    assert "_all_adapters_smoke(" in smoke
    assert "'scoreform.academic_result'" in smoke
    assert "'quillan.academic_result'" in smoke
    assert "'concord.academic_result'" in smoke
    assert "import meridian, pathlib, pds_core, scoreform, sys;" in smoke


def test_release_qualification_documentation_is_validation_guarded() -> None:
    checker = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    package_doc = Path("docs/development/package-foundation.md").read_text(
        encoding="utf-8"
    )

    for phrase in (
        "upstream dependency-direction audit",
        "source-distribution boundary",
        "all-adapter coexistence",
    ):
        assert phrase in checker
        assert phrase in package_doc
