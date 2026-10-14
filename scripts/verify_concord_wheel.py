"""Authenticate historical legacy and current contract Concord releases."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import sys
import zipfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

CONCORD_DISTRIBUTION_NAME = "pds-concord"
CONCORD_IMPORT_NAME = "concord"
EXPECTED_CONCORD_VERSION = "0.3.0"
EXPECTED_CONCORD_WHEEL_FILENAME = "pds_concord-0.3.0-py3-none-any.whl"
EXPECTED_CONCORD_WHEEL_SHA256 = (
    "dd827f7059c91c79bd69b6190b3c673d6b3bbc02bc25fa666286bbf5883c5e12"
)
EXPECTED_PUBLIC_MEMBERS = frozenset(
    {
        "concord/academic_result_manifest.py",
        "concord/academic_result_reader.py",
        "concord/pds_publication.py",
    }
)
EXPECTED_CORE_REQUIREMENTS = frozenset(
    {
        "pds-core>=0.6.3,<0.7",
        "pds-core<0.7,>=0.6.3",
    }
)
CURRENT_CONCORD_VERSION = "0.3.2"
CURRENT_CONCORD_RELEASE_TAG = "v0.3.2"
CURRENT_CONCORD_RELEASE_COMMIT = (
    "ba69d05148c625d3440d7d26ea07193715e237e3"
)
CURRENT_CONCORD_WHEEL_FILENAME = "pds_concord-0.3.2-py3-none-any.whl"
CURRENT_CONCORD_WHEEL_SHA256 = (
    "825b27bc6142cc8bce8c3b9381a3337c4a55e983f6f3f2e7e4b1a10f980e83ce"
)


class ConcordVerificationError(ValueError):
    """Raised when a Concord artifact or installation is not authoritative."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_metadata(archive: zipfile.ZipFile) -> Message:
    matches = []
    for name in archive.namelist():
        parts = PurePosixPath(name).parts
        if (
            len(parts) == 2
            and parts[0].endswith(".dist-info")
            and parts[1] == "METADATA"
        ):
            matches.append(name)
    if len(matches) != 1:
        raise ConcordVerificationError(
            "Concord wheel must contain exactly one top-level METADATA file."
        )
    return BytesParser().parsebytes(archive.read(matches[0]))


def verify_concord_wheel(path: str | Path, *, current: bool = False) -> None:
    """Authenticate an exact published legacy or current Concord wheel."""
    wheel = Path(path)
    filename = (
        CURRENT_CONCORD_WHEEL_FILENAME
        if current
        else EXPECTED_CONCORD_WHEEL_FILENAME
    )
    version = CURRENT_CONCORD_VERSION if current else EXPECTED_CONCORD_VERSION
    expected_sha256 = (
        CURRENT_CONCORD_WHEEL_SHA256
        if current
        else EXPECTED_CONCORD_WHEEL_SHA256
    )
    if wheel.name != filename:
        raise ConcordVerificationError(
            f"Expected {filename!r}, got {wheel.name!r}."
        )
    if not wheel.is_file():
        raise ConcordVerificationError(f"Concord wheel does not exist: {wheel}")
    actual = _sha256(wheel)
    if actual != expected_sha256:
        raise ConcordVerificationError(
            "Concord wheel SHA-256 mismatch: expected "
            f"{expected_sha256}, got {actual}."
        )
    try:
        with zipfile.ZipFile(wheel) as archive:
            corrupt = archive.testzip()
            if corrupt is not None:
                raise ConcordVerificationError(
                    f"Concord wheel has a corrupt ZIP member: {corrupt}"
                )
            names = archive.namelist()
            metadata = _wheel_metadata(archive)
    except zipfile.BadZipFile as error:
        raise ConcordVerificationError(
            "Concord wheel is not a readable ZIP archive."
        ) from error
    if metadata["Name"] != CONCORD_DISTRIBUTION_NAME:
        raise ConcordVerificationError(
            "Concord wheel distribution name is not pds-concord."
        )
    if metadata["Version"] != version:
        raise ConcordVerificationError(
            f"Concord wheel version is not exactly {version}."
        )
    missing_members = sorted(EXPECTED_PUBLIC_MEMBERS - set(names))
    if missing_members:
        raise ConcordVerificationError(
            "Concord wheel is missing required public contract modules: "
            f"{missing_members!r}."
        )
    core_requirements = {
        item.replace(" ", "").lower()
        for item in (metadata.get_all("Requires-Dist") or [])
        if item.replace(" ", "").lower().startswith("pds-core")
    }
    floor = "0.6.5" if current else "0.6.3"
    if core_requirements not in (
        {f"pds-core>={floor},<0.7"},
        {f"pds-core<0.7,>={floor}"},
    ):
        raise ConcordVerificationError(
            f"Concord wheel must require exactly pds-core>={floor},<0.7."
        )


def verify_installed_concord(*, current: bool = False) -> None:
    """Verify the active environment resolves the requested Concord release."""
    try:
        version = importlib.metadata.version(CONCORD_DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError as error:
        raise ConcordVerificationError(
            "Installed pds-concord metadata is missing."
        ) from error
    expected_version = CURRENT_CONCORD_VERSION if current else EXPECTED_CONCORD_VERSION
    if version != expected_version:
        raise ConcordVerificationError(
            "Installed pds-concord must be exactly "
            f"{expected_version}; found {version}."
        )

    import concord
    from concord import academic_result_reader

    if concord.__file__ is None or academic_result_reader.__file__ is None:
        raise ConcordVerificationError(
            "Installed Concord package or reader does not resolve to a file."
        )
    imported = Path(concord.__file__).resolve()
    reader = Path(academic_result_reader.__file__).resolve()
    environment = Path(sys.prefix).resolve()
    if not imported.is_relative_to(environment) or not reader.is_relative_to(
        imported.parent
    ):
        raise ConcordVerificationError(
            "Installed Concord reader is shadowed outside the active environment."
        )

    distribution = importlib.metadata.distribution(CONCORD_DISTRIBUTION_NAME)
    metadata_package = Path(
        str(distribution.locate_file(CONCORD_IMPORT_NAME))
    ).resolve()
    if imported.parent != metadata_package:
        raise ConcordVerificationError(
            "Installed Concord metadata and imported package disagree."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", nargs="?", type=Path)
    parser.add_argument("--installed", action="store_true")
    parser.add_argument(
        "--current",
        action="store_true",
        help="Authenticate the current reader-contract release instead of legacy.",
    )
    args = parser.parse_args(argv)
    if args.wheel is None and not args.installed:
        parser.error("provide a wheel path, --installed, or both")
    if args.wheel is not None:
        verify_concord_wheel(args.wheel, current=args.current)
    if args.installed:
        verify_installed_concord(current=args.current)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
