"""Validate the Meridian source distribution metadata and content boundary."""

from __future__ import annotations

import argparse
import tarfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

EXPECTED_DISTRIBUTION = "pds-meridian"
EXPECTED_VERSION = "0.1.1"
EXPECTED_SUMMARY = (
    "Publication ingestion and typed evidence diagnostics for Paper Data Suite"
)
EXPECTED_SDIST_FILENAME = f"pds_meridian-{EXPECTED_VERSION}.tar.gz"
EXPECTED_ROOT = f"pds_meridian-{EXPECTED_VERSION}"

REQUIRED_MEMBERS = frozenset(
    {
        "CHANGELOG.md",
        "LICENSE",
        "MANIFEST.in",
        "README",
        "Security.md",
        "pyproject.toml",
        "docs/README.md",
        "docs/architecture/evidence-eligibility-decisions.md",
        "docs/architecture/grade-item-membership-and-academic-period-assignment.md",
        "docs/architecture/grade-items-and-canonical-storage.md",
        "meridian/__init__.py",
        "meridian/_version.py",
        "meridian/evidence_eligibility.py",
        "meridian/evidence_eligibility_storage.py",
        "meridian/grade_item_membership_storage.py",
        "meridian/grade_item_memberships.py",
        "meridian/grade_item_storage.py",
        "meridian/grade_items.py",
        "meridian/py.typed",
        "scripts/smoke_test_grade_items_wheel.py",
        "scripts/validate_repository.py",
        "tests/test_evidence_eligibility.py",
        "tests/test_evidence_eligibility_storage.py",
        "tests/test_evidence_eligibility_package_boundaries.py",
        "tests/test_grade_item_membership_storage.py",
        "tests/test_grade_item_memberships.py",
        "tests/test_grade_item_storage.py",
        "tests/test_grade_items.py",
        "tests/test_validation_scripts.py",
    }
)
FORBIDDEN_PREFIXES = (
    ".git/",
    ".venv/",
    "venv/",
    "build/",
    "dist/",
    "pds_core/",
    "scoreform/",
    "quillan/",
    "concord/",
    "portia/",
    "vitrine/",
    "classes/",
    "registry/",
    "settings/",
)
FORBIDDEN_COMPONENTS = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".coverage",
        "htmlcov",
    }
)


class SdistValidationError(ValueError):
    """Raised when a source distribution violates the release boundary."""


def _relative_member(name: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise SdistValidationError(f"Source distribution has unsafe path: {name}")
    if not path.parts or path.parts[0] != EXPECTED_ROOT:
        raise SdistValidationError(
            f"Source distribution member is outside {EXPECTED_ROOT!r}: {name}"
        )
    if len(path.parts) == 1:
        return None
    return PurePosixPath(*path.parts[1:])


def _pkg_info(archive: tarfile.TarFile) -> Message:
    target = f"{EXPECTED_ROOT}/PKG-INFO"
    matches = [member for member in archive.getmembers() if member.name == target]
    if len(matches) != 1 or not matches[0].isfile():
        raise SdistValidationError(
            "Source distribution must contain exactly one top-level PKG-INFO."
        )
    source = archive.extractfile(matches[0])
    if source is None:
        raise SdistValidationError("Source distribution PKG-INFO is unreadable.")
    return BytesParser().parsebytes(source.read())


def validate_sdist(path: str | Path) -> None:
    """Validate one built Meridian sdist without extracting it."""
    sdist = Path(path)
    if sdist.name != EXPECTED_SDIST_FILENAME:
        raise SdistValidationError(
            f"Expected {EXPECTED_SDIST_FILENAME!r}, got {sdist.name!r}."
        )
    if not sdist.is_file():
        raise SdistValidationError(f"Source distribution does not exist: {sdist}")

    try:
        with tarfile.open(sdist, mode="r:gz") as archive:
            metadata = _pkg_info(archive)
            relative_files: set[str] = set()
            for member in archive.getmembers():
                relative = _relative_member(member.name)
                if member.issym() or member.islnk():
                    raise SdistValidationError(
                        f"Source distribution contains a link: {member.name}"
                    )
                if not (member.isfile() or member.isdir()):
                    raise SdistValidationError(
                        "Source distribution contains an unsupported tar member: "
                        f"{member.name}"
                    )
                if relative is None or member.isdir():
                    continue
                normalized = relative.as_posix()
                lowered = normalized.lower()
                components = {part.lower() for part in relative.parts}
                if lowered.startswith(FORBIDDEN_PREFIXES):
                    raise SdistValidationError(
                        f"Source distribution contains forbidden content: {normalized}"
                    )
                if components.intersection(FORBIDDEN_COMPONENTS) or any(
                    "credential" in part for part in components
                ):
                    raise SdistValidationError(
                        f"Source distribution contains forbidden content: {normalized}"
                    )
                relative_files.add(normalized)
    except (tarfile.TarError, OSError) as error:
        raise SdistValidationError(
            "Source distribution is not a readable gzip tar archive."
        ) from error

    if metadata["Name"] != EXPECTED_DISTRIBUTION:
        raise SdistValidationError("Source distribution name must be pds-meridian.")
    if metadata["Version"] != EXPECTED_VERSION:
        raise SdistValidationError(
            f"Source distribution version must be {EXPECTED_VERSION}."
        )
    if metadata["Summary"] != EXPECTED_SUMMARY:
        raise SdistValidationError(
            "Source distribution summary must describe only the implemented "
            "release surface."
        )

    missing = sorted(REQUIRED_MEMBERS - relative_files)
    if missing:
        raise SdistValidationError(
            f"Source distribution is missing required source members: {missing!r}."
        )


def main(argv: list[str] | None = None) -> int:
    """Validate one built Meridian source distribution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdist", type=Path)
    args = parser.parse_args(argv)
    validate_sdist(args.sdist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
