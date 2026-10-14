"""Authenticate historical legacy and current contract Quillan releases."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import sys
import zipfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

QUILLAN_DISTRIBUTION_NAME = "quillan"
QUILLAN_IMPORT_NAME = "quillan"
EXPECTED_QUILLAN_VERSION = "0.10.5"
EXPECTED_QUILLAN_WHEEL_FILENAME = "quillan-0.10.5-py3-none-any.whl"
EXPECTED_QUILLAN_WHEEL_SHA256 = (
    "031e5a5455c222da6b9a7d8f72e7823dd4c61acde7d90ddce94b49d9bcbe123f"
)
EXPECTED_READER_MEMBER = "quillan/academic_result_reader.py"
CURRENT_QUILLAN_VERSION = "0.10.6"
CURRENT_QUILLAN_RELEASE_TAG = "v0.10.6"
CURRENT_QUILLAN_RELEASE_COMMIT = (
    "93cf0ae84887d79377e6f77c1d0c818af24688a5"
)
CURRENT_QUILLAN_WHEEL_FILENAME = "quillan-0.10.6-py3-none-any.whl"
CURRENT_QUILLAN_WHEEL_SHA256 = (
    "7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb"
)


class QuillanVerificationError(ValueError):
    """Raised when a Quillan artifact or installation is not authoritative."""


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
        raise QuillanVerificationError(
            "Quillan wheel must contain exactly one top-level METADATA file."
        )
    return BytesParser().parsebytes(archive.read(matches[0]))


def verify_quillan_wheel(path: str | Path, *, current: bool = False) -> None:
    wheel = Path(path)
    filename = (
        CURRENT_QUILLAN_WHEEL_FILENAME
        if current
        else EXPECTED_QUILLAN_WHEEL_FILENAME
    )
    version = CURRENT_QUILLAN_VERSION if current else EXPECTED_QUILLAN_VERSION
    expected_sha256 = (
        CURRENT_QUILLAN_WHEEL_SHA256
        if current
        else EXPECTED_QUILLAN_WHEEL_SHA256
    )
    if wheel.name != filename:
        raise QuillanVerificationError(
            f"Expected {filename!r}, got {wheel.name!r}."
        )
    if not wheel.is_file():
        raise QuillanVerificationError(f"Quillan wheel does not exist: {wheel}")
    actual = _sha256(wheel)
    if actual != expected_sha256:
        raise QuillanVerificationError(
            "Quillan wheel SHA-256 mismatch: expected "
            f"{expected_sha256}, got {actual}."
        )
    try:
        with zipfile.ZipFile(wheel) as archive:
            corrupt = archive.testzip()
            if corrupt is not None:
                raise QuillanVerificationError(
                    f"Quillan wheel has a corrupt ZIP member: {corrupt}"
                )
            names = archive.namelist()
            metadata = _wheel_metadata(archive)
    except zipfile.BadZipFile as error:
        raise QuillanVerificationError(
            "Quillan wheel is not a readable ZIP archive."
        ) from error
    if metadata["Name"] != QUILLAN_DISTRIBUTION_NAME:
        raise QuillanVerificationError(
            "Quillan wheel distribution name is not quillan."
        )
    if metadata["Version"] != version:
        raise QuillanVerificationError(
            f"Quillan wheel version is not exactly {version}."
        )
    if EXPECTED_READER_MEMBER not in names:
        raise QuillanVerificationError(
            "Quillan wheel does not contain the public academic-result reader."
        )
    if current:
        requirements = {
            item.replace(" ", "").lower()
            for item in (metadata.get_all("Requires-Dist") or [])
            if item.replace(" ", "").lower().startswith("pds-core")
        }
        if requirements not in (
            {"pds-core>=0.6.5,<0.7"},
            {"pds-core<0.7,>=0.6.5"},
        ):
            raise QuillanVerificationError(
                "Current Quillan wheel must require pds-core>=0.6.5,<0.7."
            )


def verify_installed_quillan(*, current: bool = False) -> None:
    try:
        version = importlib.metadata.version(QUILLAN_DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError as error:
        raise QuillanVerificationError(
            "Installed quillan metadata is missing."
        ) from error
    expected_version = CURRENT_QUILLAN_VERSION if current else EXPECTED_QUILLAN_VERSION
    if version != expected_version:
        raise QuillanVerificationError(
            f"Installed quillan must be exactly {expected_version}; found {version}."
        )
    import quillan
    from quillan import academic_result_reader

    if quillan.__file__ is None or academic_result_reader.__file__ is None:
        raise QuillanVerificationError(
            "Installed Quillan package or reader does not resolve to a file."
        )
    imported = Path(quillan.__file__).resolve()
    reader = Path(academic_result_reader.__file__).resolve()
    environment = Path(sys.prefix).resolve()
    if not imported.is_relative_to(environment) or not reader.is_relative_to(
        imported.parent
    ):
        raise QuillanVerificationError(
            "Installed Quillan reader is shadowed outside the active environment."
        )
    distribution = importlib.metadata.distribution(QUILLAN_DISTRIBUTION_NAME)
    metadata_package = Path(
        str(distribution.locate_file(QUILLAN_IMPORT_NAME))
    ).resolve()
    if imported.parent != metadata_package:
        raise QuillanVerificationError(
            "Installed Quillan metadata and imported package disagree."
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
        verify_quillan_wheel(args.wheel, current=args.current)
    if args.installed:
        verify_installed_quillan(current=args.current)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
