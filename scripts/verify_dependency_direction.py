"""Verify authenticated upstream wheels do not depend on Meridian."""

from __future__ import annotations

import argparse
import zipfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

MERIDIAN_DISTRIBUTION = canonicalize_name("pds-meridian")


class DependencyDirectionVerificationError(ValueError):
    """Raised when an upstream artifact reverses the Meridian dependency boundary."""


def _wheel_metadata(archive: zipfile.ZipFile) -> Message:
    matches: list[str] = []
    for name in archive.namelist():
        parts = PurePosixPath(name).parts
        if (
            len(parts) == 2
            and parts[0].endswith(".dist-info")
            and parts[1] == "METADATA"
        ):
            matches.append(name)
    if len(matches) != 1:
        raise DependencyDirectionVerificationError(
            "Upstream wheel must contain exactly one top-level METADATA file."
        )
    return BytesParser().parsebytes(archive.read(matches[0]))


def verify_no_meridian_dependency(path: str | Path) -> None:
    """Reject one authenticated upstream wheel that requires pds-meridian."""
    wheel = Path(path)
    if not wheel.is_file():
        raise DependencyDirectionVerificationError(
            f"Upstream wheel does not exist: {wheel}"
        )
    try:
        with zipfile.ZipFile(wheel) as archive:
            corrupt = archive.testzip()
            if corrupt is not None:
                raise DependencyDirectionVerificationError(
                    f"Upstream wheel has a corrupt ZIP member: {corrupt}"
                )
            metadata = _wheel_metadata(archive)
    except zipfile.BadZipFile as error:
        raise DependencyDirectionVerificationError(
            "Upstream wheel is not a readable ZIP archive."
        ) from error

    distribution = metadata["Name"] or wheel.name
    for raw_requirement in metadata.get_all("Requires-Dist") or []:
        try:
            requirement = Requirement(raw_requirement)
        except InvalidRequirement as error:
            raise DependencyDirectionVerificationError(
                f"Upstream wheel {distribution!r} has invalid dependency metadata."
            ) from error
        if canonicalize_name(requirement.name) == MERIDIAN_DISTRIBUTION:
            raise DependencyDirectionVerificationError(
                f"Upstream wheel {distribution!r} must not depend on pds-meridian."
            )


def main(argv: list[str] | None = None) -> int:
    """Audit one or more already-authenticated upstream wheels."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheels", nargs="+", type=Path)
    args = parser.parse_args(argv)
    for wheel in args.wheels:
        verify_no_meridian_dependency(wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
