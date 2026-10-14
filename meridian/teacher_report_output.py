"""Safe local-file output for deterministic Meridian teacher reports."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.report_export_commit import write_or_verify_local_artifact
from meridian.teacher_report import TeacherReportPreview
from meridian.teacher_report_render import (
    TeacherReportRenderFormat,
    render_teacher_report,
)

TeacherReportFileDisposition: TypeAlias = Literal["created", "existing"]


@dataclass(frozen=True, slots=True)
class TeacherReportFileResult:
    disposition: TeacherReportFileDisposition
    path: Path = field(repr=False)
    payload_sha256: str


def write_teacher_report_file(
    path: str | Path,
    preview: TeacherReportPreview,
    format: TeacherReportRenderFormat,
) -> TeacherReportFileResult:
    target = Path(path)
    payload = render_teacher_report(preview, format)
    disposition = write_or_verify_local_artifact(target, payload)
    return TeacherReportFileResult(
        disposition=disposition,
        path=target,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )


__all__ = [
    "TeacherReportFileDisposition",
    "TeacherReportFileResult",
    "write_teacher_report_file",
]
