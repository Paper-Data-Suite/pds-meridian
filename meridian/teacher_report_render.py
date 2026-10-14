"""Deterministic JSON, Markdown, CSV, and TSV teacher-report rendering."""

from __future__ import annotations

import csv
import io
from typing import Literal, TypeAlias

from meridian.teacher_report import (
    TeacherReportPreview,
    teacher_report_preview_to_json_bytes,
    validate_teacher_report_preview,
)

TeacherReportRenderFormat: TypeAlias = Literal["json", "markdown", "csv", "tsv"]


def render_teacher_report(
    value: TeacherReportPreview,
    format: TeacherReportRenderFormat,
) -> bytes:
    preview = validate_teacher_report_preview(value)
    if format == "json":
        return teacher_report_preview_to_json_bytes(preview)
    if format == "markdown":
        return render_teacher_report_markdown(preview)
    if format == "csv":
        return _render_delimited(preview, ",")
    if format == "tsv":
        return _render_delimited(preview, "\t")
    raise ValueError("unsupported teacher-report render format.")


def render_teacher_report_markdown(value: TeacherReportPreview) -> bytes:
    preview = validate_teacher_report_preview(value)
    period = preview.target_period
    lines = [
        f"# {preview.title}",
        "",
        f"- Report: `{preview.report_kind}`",
        f"- Class: `{preview.class_id}`",
        f"- Period: `{period.school_year}` / `{period.period_id}`",
        f"- Calendar revision: `{preview.calendar_revision}`",
        f"- Generated: `{preview.generated_at.isoformat()}`",
        f"- Preview SHA-256: `{preview.preview_sha256}`",
    ]
    if preview.summary:
        lines.extend(["", "## Summary", "", *preview.summary])
    if preview.report_kind == "benchmark_analysis_instructional_response":
        _append_benchmark_sections(lines, preview)
    else:
        lines.extend(["", "## Report", ""])
        _append_table(lines, preview)
    if preview.diagnostics:
        lines.extend(["", "## Diagnostics", ""])
        for item in preview.diagnostics:
            lines.append(f"- `{item.severity}` `{item.code}` — {item.message}")
    lines.extend(
        [
            "",
            "_Meridian teacher report. This local artifact does not prove that "
            "an SIS, LMS, or district gradebook was updated, or that this plan "
            "was officially submitted or approved._",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def _append_table(lines: list[str], preview: TeacherReportPreview) -> None:
    headers = [item.title for item in preview.columns]
    lines.append("| " + " | ".join(_md(item) for item in headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in preview.rows:
        values = ["" if item is None else item for item in row.values]
        lines.append("| " + " | ".join(_md(item) for item in values) + " |")


def _append_benchmark_sections(
    lines: list[str], preview: TeacherReportPreview
) -> None:
    """Give the planner a print-friendly four-section Markdown layout."""
    sections: dict[str, list[tuple[str | None, ...]]] = {}
    for row in preview.rows:
        section = row.values[0]
        if section is not None:
            sections.setdefault(section, []).append(row.values[1:])
    headings = [item.title for item in preview.columns[1:]]
    for section, rows in sections.items():
        lines.extend(["", f"## {section}", ""])
        lines.append("| " + " | ".join(_md(item) for item in headings) + " |")
        lines.append("| " + " | ".join("---" for _ in headings) + " |")
        for values_row in rows:
            values = ["" if item is None else item for item in values_row]
            lines.append("| " + " | ".join(_md(item) for item in values) + " |")


def _render_delimited(preview: TeacherReportPreview, delimiter: str) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
    writer.writerow([item.title for item in preview.columns])
    for row in preview.rows:
        writer.writerow(["" if item is None else item for item in row.values])
    return stream.getvalue().encode("utf-8")


def _md(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\r", "<br>")
        .replace("\n", "<br>")
    )


__all__ = [
    "TeacherReportRenderFormat",
    "render_teacher_report",
    "render_teacher_report_markdown",
]
