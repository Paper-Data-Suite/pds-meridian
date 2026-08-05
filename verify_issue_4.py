from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent
EXPECTED = (
    Path("README"),
    Path("docs/README.md"),
    Path("docs/architecture/core-v0.6-publication-ingestion.md"),
    Path("docs/decisions/README.md"),
    Path("docs/decisions/0001-policy-driven-standards-proficiency-and-grade-calculation.md"),
    Path("docs/decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md"),
    Path("docs/decisions/0003-consumer-side-producer-adapters.md"),
    Path("docs/decisions/amendments/0001-core-v0.6-ingestion-reconciliation.md"),
    Path("docs/decisions/amendments/0002-core-v0.6-ingestion-reconciliation.md"),
)

LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
REQUIRED_TEXT = {
    Path("README"): (
        "pds-core>=0.6,<0.7",
        "Discovery is not authorization.",
        "producer-owned public contract or reader",
        "ScoreForm readiness",
        "Quillan readiness",
    ),
    Path("docs/architecture/core-v0.6-publication-ingestion.md"): (
        "Canonical verification precedes producer parsing",
        "Failure taxonomy",
        "Producer readiness matrix",
    ),
    Path("docs/decisions/0003-consumer-side-producer-adapters.md"): (
        "Status:** Accepted",
        "Unsupported states fail closed",
        "producer package -X-> pds-meridian",
    ),
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_expected() -> None:
    for relative in EXPECTED:
        path = ROOT / relative
        if not path.is_file():
            fail(f"missing expected file: {relative.as_posix()}")


def check_required_text() -> None:
    for relative, needles in REQUIRED_TEXT.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                fail(f"{relative.as_posix()} is missing required text: {needle!r}")


def check_links() -> None:
    failures: list[str] = []
    for relative in EXPECTED:
        if relative.suffix != ".md" and relative.name != "README":
            continue
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        for target in LINK.findall(text):
            target = target.strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            clean = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not clean:
                continue
            resolved = (path.parent / clean).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                failures.append(f"{relative.as_posix()}: link escapes repository: {target}")
                continue
            if not resolved.exists():
                failures.append(f"{relative.as_posix()}: missing link target: {target}")
    if failures:
        fail("broken repository-relative links:\n  " + "\n  ".join(failures))


def check_adr_reconciliation() -> None:
    for relative in (
        Path("docs/decisions/0001-policy-driven-standards-proficiency-and-grade-calculation.md"),
        Path("docs/decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md"),
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        heading = "## Core v0.6 publication-ingestion reconciliation (2026-08-04)"
        if text.count(heading) != 1:
            fail(f"{relative.as_posix()} must contain exactly one reconciliation section")


def check_privacy() -> None:
    forbidden = ("C:\\Users\\", "/home/", "student@example.com")
    for relative in EXPECTED:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for item in forbidden:
            if item in text:
                fail(f"{relative.as_posix()} contains a private-path/data marker: {item}")


def check_text_hygiene() -> None:
    for relative in EXPECTED:
        data = (ROOT / relative).read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            fail(f"{relative.as_posix()} is not valid UTF-8: {error}")
        if "\r" in text.replace("\r\n", ""):
            fail(f"{relative.as_posix()} contains bare CR characters")
        if not text.endswith("\n"):
            fail(f"{relative.as_posix()} must end with one newline")
        for number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip() != line:
                fail(f"{relative.as_posix()}:{number} contains trailing whitespace")


def check_git_diff() -> None:
    result = subprocess.run(
        ["git", "diff", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        fail("git diff --check failed")


def main() -> int:
    check_expected()
    check_required_text()
    check_links()
    check_adr_reconciliation()
    check_privacy()
    check_text_hygiene()
    check_git_diff()
    print("Issue #4 documentation validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
