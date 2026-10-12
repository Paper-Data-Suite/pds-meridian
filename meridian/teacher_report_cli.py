"""Direct CLI shell for the Issue #111 teacher-report suite."""

from __future__ import annotations

import argparse
import json

from meridian.diagnostics import DiagnosticsDependencies
from meridian.teacher_report import TEACHER_REPORT_KINDS

_LABELS = (
    "SIS Gradebook Reconciliation",
    "Student Current Grade Justification",
    "Class Standards Profile",
    "Student Proficiency Growth / Trajectory",
    "Evidence Coverage / Sufficiency",
    "Grade Checkpoint Comparison",
    "Marking-Period Readiness",
    "Grade Item / Assessment Impact",
)


def add_teacher_reports_cli(
    groups: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    reports = groups.add_parser(
        "reports",
        help="Preview and render read-only teacher reports.",
        description=(
            "Teacher reports are deterministic read-only views over "
            "Meridian authority. "
            "They do not create Grades or proficiency and do not write to an SIS/LMS."
        ),
    )
    commands = reports.add_subparsers(dest="teacher_report_command")
    kinds = commands.add_parser("kinds", help="List Issue #111 report families.")
    kinds.add_argument("--format", choices=("text", "json"), default="text")
    kinds.set_defaults(handler=_handle_report_kinds, show_group_help=None)
    reports.set_defaults(show_group_help=reports)


def _handle_report_kinds(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    rows = [
        {
            "report_kind": kind,
            "title": title,
            "generator_status": "pending_report_specific_slice",
        }
        for kind, title in zip(TEACHER_REPORT_KINDS, _LABELS, strict=True)
    ]
    if args.format == "json":
        print(
            json.dumps(
                {
                    "surface": "teacher_reports",
                    "framework_schema_version": "1",
                    "academic_mutation": False,
                    "external_system_write": False,
                    "report_kinds": rows,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    print("Meridian Teacher Reports")
    print()
    for index, row in enumerate(rows, start=1):
        print(f"{index}. {row['title']}")
    print()
    print("Report-specific generators are added in subsequent Issue #111 slices.")
    print("Reports are read-only and do not write to an SIS/LMS.")
    return 0


__all__ = ["add_teacher_reports_cli"]
