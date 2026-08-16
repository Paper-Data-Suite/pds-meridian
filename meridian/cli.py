"""Side-effect-free command-line entry point for the Meridian foundation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from meridian import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the baseline command parser without touching workspace state."""
    return argparse.ArgumentParser(
        prog="meridian",
        description=(
            "Meridian is the Paper Data Suite publication-ingestion, grading-policy, "
            "and reporting module. Grades are not implemented yet. The tested "
            "ingestion "
            "foundation includes exact "
            "optional ScoreForm and Quillan evidence adapters. Proficiency, Grades, "
            "and reporting policy stages remain later work."
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse baseline arguments and return a process exit status."""
    effective_argv = tuple(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    if not effective_argv:
        parser.print_help()
        return 0
    parser.parse_args(effective_argv)
    return 0
