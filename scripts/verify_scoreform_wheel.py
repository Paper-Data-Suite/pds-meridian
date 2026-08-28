"""Authenticate the exact released ScoreForm v0.11.0 wheel and installation."""

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
EXPECTED_SCOREFORM_VERSION = "0.11.0"
EXPECTED_SCOREFORM_WHEEL_FILENAME = "scoreform-0.11.0-py3-none-any.whl"
EXPECTED_SCOREFORM_WHEEL_SHA256 = (
    "8248c6a1cc8254b5f9df46440131d524f80da8662a0dc7864fdc982e501b4c44"
)
EXPECTED_READER_MEMBER = "scoreform/academic_result_reader.py"


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


def verify_scoreform_wheel(path: str | Path) -> None:
    wheel = Path(path)
    if wheel.name != EXPECTED_SCOREFORM_WHEEL_FILENAME:
        raise ScoreFormVerificationError(
            f"Expected {EXPECTED_SCOREFORM_WHEEL_FILENAME!r}, got {wheel.name!r}."
        )
    if not wheel.is_file():
        raise ScoreFormVerificationError(f"ScoreForm wheel does not exist: {wheel}")
    actual = _sha256(wheel)
    if actual != EXPECTED_SCOREFORM_WHEEL_SHA256:
        raise ScoreFormVerificationError(
            "ScoreForm wheel SHA-256 mismatch: expected "
            f"{EXPECTED_SCOREFORM_WHEEL_SHA256}, got {actual}."
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
    if metadata["Version"] != EXPECTED_SCOREFORM_VERSION:
        raise ScoreFormVerificationError(
            "ScoreForm wheel version is not exactly 0.11.0."
        )
    if EXPECTED_READER_MEMBER not in names:
        raise ScoreFormVerificationError(
            "ScoreForm wheel does not contain the public academic-result reader."
        )


def verify_installed_scoreform() -> None:
    try:
        version = importlib.metadata.version(SCOREFORM_DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError as error:
        raise ScoreFormVerificationError(
            "Installed scoreform metadata is missing."
        ) from error
    if version != EXPECTED_SCOREFORM_VERSION:
        raise ScoreFormVerificationError(
            f"Installed scoreform must be exactly 0.11.0; found {version}."
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
    args = parser.parse_args(argv)
    if args.wheel is None and not args.installed:
        parser.error("provide a wheel path, --installed, or both")
    if args.wheel is not None:
        verify_scoreform_wheel(args.wheel)
    if args.installed:
        verify_installed_scoreform()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
