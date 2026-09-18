"""Create and select a real installed issue #53 teacher Grade override."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import smoke_program_conventional_grade as issue50  # type: ignore[import-not-found]

from meridian.conventional_grade import create_conventional_grade_result_snapshot
from meridian.conventional_grade_assembly import assemble_conventional_grade_calculation
from meridian.conventional_grade_storage import (
    load_current_conventional_grade_result,
    select_conventional_grade_result_revision,
    write_conventional_grade_result_revision,
)
from meridian.effective_grade import resolve_current_effective_grade
from meridian.teacher_grade_override_lifecycle import (
    commit_teacher_grade_override_selection_preview,
    preview_teacher_grade_override_selection,
)
from meridian.teacher_grade_override_storage import (
    get_current_teacher_grade_override_reference,
)
from meridian.teacher_grade_override_workflow import (
    commit_teacher_grade_override_authoring_preview,
    preview_teacher_grade_override_authoring,
)

BASELINE_NAME = "issue53-teacher-grade-override-baseline.json"
REPLACEMENT_GRADE = Decimal("105.25")


def _verify_override_module_origins() -> None:
    prefix = Path(sys.prefix).resolve()
    for module_name in (
        "meridian.teacher_grade_override",
        "meridian.teacher_grade_override_storage",
        "meridian.teacher_grade_override_workflow",
        "meridian.teacher_grade_override_lifecycle",
        "meridian.effective_grade",
    ):
        module = importlib.import_module(module_name)
        raw = getattr(module, "__file__", None)
        issue50._require(
            isinstance(raw, str) and bool(raw),
            f"{module_name} has no installed origin.",
        )
        assert isinstance(raw, str)
        origin = Path(raw).resolve()
        issue50._require(
            origin.is_relative_to(prefix),
            f"{module_name} is outside the isolated venv.",
        )
        issue50._require(
            "site-packages" in {part.lower() for part in origin.parts},
            f"{module_name} is not installed from site-packages.",
        )


def _write_baseline(
    root: Path,
    source_content: bytes,
    source_digest_bytes: bytes,
    source_revision: int,
    source_sha256: str,
    override_revision: int,
    override_sha256: str,
    producer: issue50.ProducerBaseline,
) -> None:
    producer_files = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(expected).hexdigest(),
        }
        for path, expected in producer.native_files
    ]
    producer_files.append(
        {
            "path": producer.manifest_path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(producer.manifest_bytes).hexdigest(),
        }
    )
    payload = {
        "schema_version": "1",
        "workspace": "workspace",
        "class_id": issue50.CLASS_ID,
        "student_id": issue50.STUDENT_ID,
        "school_year": issue50.SCHOOL_YEAR,
        "period_id": issue50.PERIOD_ID,
        "calendar_revision": 1,
        "source_revision": source_revision,
        "source_sha256": source_sha256,
        "source_content_sha256": hashlib.sha256(source_content).hexdigest(),
        "source_digest_file_sha256": hashlib.sha256(source_digest_bytes).hexdigest(),
        "active_override_revision": override_revision,
        "active_override_sha256": override_sha256,
        "replacement_grade": str(REPLACEMENT_GRADE),
        "producer_files": producer_files,
    }
    (root / BASELINE_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    issue50._verify_installed_composition()
    _verify_override_module_origins()
    root = Path(".").resolve()
    workspace = root / "workspace"
    issue50._seed_core_context(workspace)
    producer = issue50._publish(workspace)
    projected = issue50._project(workspace, producer)
    authorized = issue50._authorized(workspace, projected)
    work_evidence = issue50._configure(workspace, projected, authorized)

    assembly = assemble_conventional_grade_calculation(
        workspace,
        issue50.CLASS_ID,
        issue50.STUDENT_ID,
        issue50.PERIOD,
        1,
        work_evidence,
    )
    issue50._require(
        assembly.outcome.rounded_grade == Decimal("100.00"),
        "Issue #53 base Grade must be the exact installed 100.00 result.",
    )
    snapshot = create_conventional_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=issue50.NOW,
    )
    written = write_conventional_grade_result_revision(
        workspace,
        snapshot,
        work_evidence=work_evidence,
    )
    select_conventional_grade_result_revision(
        workspace,
        issue50.CLASS_ID,
        issue50.STUDENT_ID,
        issue50.PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    current = load_current_conventional_grade_result(
        workspace,
        issue50.CLASS_ID,
        issue50.STUDENT_ID,
        issue50.PERIOD,
        1,
    )
    issue50._require(current is not None, "Base Grade result did not reload.")
    assert current is not None
    source_content = current.content
    source_digest_path = current.path.with_suffix(".json.sha256")
    source_digest_bytes = source_digest_path.read_bytes()

    base_effective = resolve_current_effective_grade(
        workspace,
        issue50.CLASS_ID,
        issue50.STUDENT_ID,
        issue50.PERIOD,
        1,
        "conventional",
        work_evidence=work_evidence,
    )
    issue50._require(
        base_effective.effective_grade == Decimal("100.00")
        and base_effective.effective_source == "base",
        "Base Grade did not govern before override authoring.",
    )

    preview = preview_teacher_grade_override_authoring(
        workspace,
        issue50.CLASS_ID,
        issue50.STUDENT_ID,
        issue50.PERIOD,
        1,
        "conventional",
        replacement_grade=REPLACEMENT_GRADE,
        actor_id=issue50.ACTOR_ID,
        rationale="Installed issue #53 exact final Grade override.",
        decided_at=issue50.NOW + timedelta(minutes=10),
        work_evidence=work_evidence,
    )
    authored = commit_teacher_grade_override_authoring_preview(workspace, preview)
    issue50._require(
        authored.write_disposition == "created",
        "Active override was not created.",
    )
    issue50._require(
        get_current_teacher_grade_override_reference(
            workspace,
            issue50.CLASS_ID,
            issue50.STUDENT_ID,
            issue50.PERIOD,
            1,
            "conventional",
        )
        is None,
        "Writing an override must not select it.",
    )
    still_base = resolve_current_effective_grade(
        workspace,
        issue50.CLASS_ID,
        issue50.STUDENT_ID,
        issue50.PERIOD,
        1,
        "conventional",
        work_evidence=work_evidence,
    )
    issue50._require(
        still_base.effective_grade == Decimal("100.00")
        and still_base.effective_source == "base",
        "Unselected override changed effective Grade authority.",
    )

    selection = preview_teacher_grade_override_selection(
        workspace,
        authored.stored_reference,
    )
    selected = commit_teacher_grade_override_selection_preview(workspace, selection)
    issue50._require(
        selected.target_reference == authored.stored_reference,
        "Selected override differs from authored override.",
    )
    overridden = resolve_current_effective_grade(
        workspace,
        issue50.CLASS_ID,
        issue50.STUDENT_ID,
        issue50.PERIOD,
        1,
        "conventional",
        work_evidence=work_evidence,
    )
    issue50._require(
        overridden.effective_grade == REPLACEMENT_GRADE
        and overridden.effective_source == "override",
        "Selected active override did not take precedence.",
    )

    issue50._require(current.content == source_content, "Source result bytes changed.")
    issue50._require(
        current.path.read_bytes() == source_content,
        "Persisted source result JSON changed.",
    )
    issue50._require(
        source_digest_path.read_bytes() == source_digest_bytes,
        "Persisted source result digest changed.",
    )
    issue50._assert_unchanged(producer)
    _write_baseline(
        root,
        source_content,
        source_digest_bytes,
        current.snapshot.result_revision,
        current.result_sha256,
        authored.stored_reference.override_revision,
        authored.stored_reference.override_sha256,
        producer,
    )
    issue50._assert_absent_producers()
    issue50._require(
        written.stored.result_sha256 == current.result_sha256,
        "Source result identity changed during override workflow.",
    )
    print("Issue #53 installed active teacher Grade override acceptance passed.")


if __name__ == "__main__":
    main()
