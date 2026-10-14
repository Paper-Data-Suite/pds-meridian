"""Authenticate historical legacy and current contract ScoreForm releases."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import sys
import zipfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

SCOREFORM_DISTRIBUTION_NAME = "scoreform"
SCOREFORM_IMPORT_NAME = "scoreform"
EXPECTED_SCOREFORM_VERSION = "0.12.1"
EXPECTED_SCOREFORM_RELEASE_TAG = "v0.12.1"
EXPECTED_SCOREFORM_RELEASE_COMMIT = (
    "8c3decf64040fd1da839b6f59f19c9ed344ce579"
)
EXPECTED_SCOREFORM_RELEASE_TREE = (
    "bcc6270319b6234f000d348452072ab8943a2558"
)
EXPECTED_SCOREFORM_WHEEL_FILENAME = "scoreform-0.12.1-py3-none-any.whl"
EXPECTED_SCOREFORM_WHEEL_SHA256 = (
    "0f71b709eafe351052eac3e4f0d474b7bef36aeec347df05361b0a8995d44d32"
)
EXPECTED_READER_MEMBER = "scoreform/academic_result_reader.py"
CURRENT_SCOREFORM_VERSION = "0.13.0"
CURRENT_SCOREFORM_RELEASE_TAG = "v0.13.0"
CURRENT_SCOREFORM_RELEASE_COMMIT = (
    "dbb4159bb2c4d04889742de746be42a394130170"
)
CURRENT_SCOREFORM_RELEASE_TREE = "ef6bb4e4d37da25b317d1a2aebddebdf7edcdd28"
CURRENT_SCOREFORM_WHEEL_FILENAME = "scoreform-0.13.0-py3-none-any.whl"
CURRENT_SCOREFORM_WHEEL_SHA256 = (
    "4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7"
)


class ScoreFormVerificationError(ValueError):
    """Raised when a ScoreForm artifact or installation is not authoritative."""


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
        raise ScoreFormVerificationError(
            "ScoreForm wheel must contain exactly one top-level METADATA file."
        )
    return BytesParser().parsebytes(archive.read(matches[0]))


def verify_scoreform_wheel(path: str | Path, *, current: bool = False) -> None:
    wheel = Path(path)
    filename = (
        CURRENT_SCOREFORM_WHEEL_FILENAME
        if current
        else EXPECTED_SCOREFORM_WHEEL_FILENAME
    )
    version = CURRENT_SCOREFORM_VERSION if current else EXPECTED_SCOREFORM_VERSION
    expected_sha256 = (
        CURRENT_SCOREFORM_WHEEL_SHA256
        if current
        else EXPECTED_SCOREFORM_WHEEL_SHA256
    )
    if wheel.name != filename:
        raise ScoreFormVerificationError(
            f"Expected {filename!r}, got {wheel.name!r}."
        )
    if not wheel.is_file():
        raise ScoreFormVerificationError(f"ScoreForm wheel does not exist: {wheel}")
    actual = _sha256(wheel)
    if actual != expected_sha256:
        raise ScoreFormVerificationError(
            "ScoreForm wheel SHA-256 mismatch: expected "
            f"{expected_sha256}, got {actual}."
        )
    try:
        with zipfile.ZipFile(wheel) as archive:
            corrupt = archive.testzip()
            if corrupt is not None:
                raise ScoreFormVerificationError(
                    f"ScoreForm wheel has a corrupt ZIP member: {corrupt}"
                )
            names = archive.namelist()
            metadata = _wheel_metadata(archive)
    except zipfile.BadZipFile as error:
        raise ScoreFormVerificationError(
            "ScoreForm wheel is not a readable ZIP archive."
        ) from error
    if metadata["Name"] != SCOREFORM_DISTRIBUTION_NAME:
        raise ScoreFormVerificationError(
            "ScoreForm wheel distribution name is not scoreform."
        )
    if metadata["Version"] != version:
        raise ScoreFormVerificationError(
            f"ScoreForm wheel version is not exactly {version}."
        )
    if EXPECTED_READER_MEMBER not in names:
        raise ScoreFormVerificationError(
            "ScoreForm wheel does not contain the public academic-result reader."
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
            raise ScoreFormVerificationError(
                "Current ScoreForm wheel must require pds-core>=0.6.5,<0.7."
            )


def verify_installed_scoreform(*, current: bool = False) -> None:
    try:
        version = importlib.metadata.version(SCOREFORM_DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError as error:
        raise ScoreFormVerificationError(
            "Installed scoreform metadata is missing."
        ) from error
    expected_version = (
        CURRENT_SCOREFORM_VERSION if current else EXPECTED_SCOREFORM_VERSION
    )
    if version != expected_version:
        raise ScoreFormVerificationError(
            f"Installed scoreform must be exactly {expected_version}; found {version}."
        )
    import scoreform
    from scoreform import academic_result_reader

    if scoreform.__file__ is None or academic_result_reader.__file__ is None:
        raise ScoreFormVerificationError(
            "Installed ScoreForm package or reader does not resolve to a file."
        )
    imported = Path(scoreform.__file__).resolve()
    reader = Path(academic_result_reader.__file__).resolve()
    environment = Path(sys.prefix).resolve()
    if not imported.is_relative_to(environment) or not reader.is_relative_to(
        imported.parent
    ):
        raise ScoreFormVerificationError(
            "Installed ScoreForm reader is shadowed outside the active environment."
        )
    distribution = importlib.metadata.distribution(SCOREFORM_DISTRIBUTION_NAME)
    metadata_package = Path(
        str(distribution.locate_file(SCOREFORM_IMPORT_NAME))
    ).resolve()
    if imported.parent != metadata_package:
        raise ScoreFormVerificationError(
            "Installed ScoreForm metadata and imported package disagree."
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
        verify_scoreform_wheel(args.wheel, current=args.current)
    if args.installed:
        verify_installed_scoreform(current=args.current)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
