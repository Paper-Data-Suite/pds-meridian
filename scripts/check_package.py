"""Validate built Meridian distribution metadata and archive isolation."""

from __future__ import annotations

import argparse
import configparser
import zipfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

EXPECTED_DISTRIBUTION = "pds-meridian"
EXPECTED_VERSION = "0.1.1.dev0"
EXPECTED_CORE_REQUIREMENT = Requirement("pds-core>=0.6,<0.7")
EXPECTED_SCOREFORM_EXTRA = Requirement("scoreform==0.10.0; extra == 'scoreform'")
ALLOWED_ENTRY_POINT_GROUPS = frozenset({"console_scripts"})
FORBIDDEN_PREFIXES = (
    "tests/",
    "pds_core/",
    "scoreform/",
    "quillan/",
    "concord/",
    "portia/",
    "vitrine/",
    "classes/",
    "registry/",
    "settings/",
    "scripts/",
    ".git/",
    ".venv/",
    "build/",
    "dist/",
)
FORBIDDEN_PARTS = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "credentials",
    "implementation_plan",
    "issue-4",
    "issue-5",
)


class PackageValidationError(ValueError):
    """Raised when a built package violates the distribution boundary."""


def _single_member(names: list[str], suffix: str) -> str:
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) != 1:
        raise PackageValidationError(
            f"Expected exactly one {suffix}, found {len(matches)}."
        )
    return matches[0]


def _metadata(archive: zipfile.ZipFile, names: list[str]) -> Message:
    return BytesParser().parsebytes(
        archive.read(_single_member(names, ".dist-info/METADATA"))
    )


def _entry_points(
    archive: zipfile.ZipFile, names: list[str]
) -> configparser.ConfigParser:
    member = _single_member(names, ".dist-info/entry_points.txt")
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(archive.read(member).decode("utf-8"))
    return parser


def _runtime_requirements(metadata: Message) -> list[Requirement]:
    requirements = [
        Requirement(item) for item in (metadata.get_all("Requires-Dist") or [])
    ]
    return [requirement for requirement in requirements if requirement.marker is None]


def _scoreform_requirements(metadata: Message) -> list[Requirement]:
    requirements = [
        Requirement(item) for item in (metadata.get_all("Requires-Dist") or [])
    ]
    return [
        requirement for requirement in requirements
        if requirement.name == "scoreform"
    ]


def validate_wheel(path: str | Path) -> None:
    """Validate metadata, intended files, and deliberately absent entry points."""
    wheel = Path(path)
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise PackageValidationError(
                    f"Wheel contains a corrupt ZIP member: {corrupt_member}"
                )
            metadata = _metadata(archive, names)
            entry_points = _entry_points(archive, names)
    except zipfile.BadZipFile as error:
        raise PackageValidationError("Wheel is not a readable ZIP archive.") from error

    if canonicalize_name(metadata["Name"] or "") != canonicalize_name(
        EXPECTED_DISTRIBUTION
    ):
        raise PackageValidationError("Distribution name must be pds-meridian.")
    if metadata["Version"] != EXPECTED_VERSION:
        raise PackageValidationError(
            f"Distribution version must be {EXPECTED_VERSION}."
        )
    if metadata["Requires-Python"] != ">=3.11":
        raise PackageValidationError("Requires-Python must be >=3.11.")
    if metadata["Description-Content-Type"] != "text/markdown":
        raise PackageValidationError(
            "README description content type must be Markdown."
        )

    runtime = _runtime_requirements(metadata)
    if runtime != [EXPECTED_CORE_REQUIREMENT]:
        raise PackageValidationError(
            "The only runtime requirement must be pds-core>=0.6,<0.7."
        )
    if _scoreform_requirements(metadata) != [EXPECTED_SCOREFORM_EXTRA]:
        raise PackageValidationError(
            "The scoreform extra must pin exactly scoreform==0.10.0."
        )

    groups = frozenset(entry_points.sections())
    if groups != ALLOWED_ENTRY_POINT_GROUPS:
        raise PackageValidationError(
            "Only the console_scripts entry-point group is permitted; "
            f"found {sorted(groups)!r}."
        )
    if entry_points.get("console_scripts", "meridian", fallback=None) != (
        "meridian.cli:main"
    ):
        raise PackageValidationError("The meridian console script is missing.")

    required = {
        "meridian/__init__.py",
        "meridian/__main__.py",
        "meridian/_version.py",
        "meridian/adapters.py",
        "meridian/cli.py",
        "meridian/evidence.py",
        "meridian/evidence_serialization.py",
        "meridian/ingestion.py",
        "meridian/projection_cache.py",
        "meridian/scoreform_adapter.py",
        "meridian/py.typed",
    }
    if not required.issubset(names):
        missing = sorted(required - set(names))
        raise PackageValidationError(
            f"Wheel is missing intended Meridian package files: {missing!r}."
        )
    if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
        raise PackageValidationError("Wheel does not include the MIT license file.")

    for name in names:
        normalized = PurePosixPath(name).as_posix().lower()
        if normalized.startswith(FORBIDDEN_PREFIXES) or any(
            part in normalized for part in FORBIDDEN_PARTS
        ):
            raise PackageValidationError(f"Wheel contains forbidden content: {name}")
        if normalized.startswith("meridian/") and normalized not in {
            item.lower() for item in required
        }:
            raise PackageValidationError(
                f"Wheel contains an unexpected Meridian module: {name}"
            )


def main(argv: list[str] | None = None) -> int:
    """Validate one built Meridian wheel."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args(argv)
    validate_wheel(args.wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
