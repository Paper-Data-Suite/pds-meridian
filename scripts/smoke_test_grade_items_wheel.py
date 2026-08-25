"""Smoke-test Grade Item and membership modules from an installed wheel."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import textwrap
import venv
from pathlib import Path


def _environment() -> dict[str, str]:
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    for variable in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        environment.pop(variable, None)
    return environment


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=_environment(),
    )


def smoke_test(meridian_wheel: Path, core_wheel: Path) -> None:
    """Install only Core and Meridian, then exercise Grade Item membership."""
    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-grade-item-smoke-"
    ) as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")

        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(core_wheel.resolve()),
                str(meridian_wheel.resolve()),
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)
        code = textwrap.dedent(
            """
            import pathlib
            import shutil
            import sys
            import tempfile
            from datetime import UTC, date, datetime
            from decimal import Decimal

            from pds_core.academic_period_storage import write_academic_period_calendar
            from pds_core.academic_periods import (
                AcademicPeriod,
                AcademicPeriodCalendar,
                AcademicPeriodRef,
            )
            from pds_core.academic_work_registration_storage import (
                write_academic_work_registration,
            )
            from pds_core.academic_work_registrations import AcademicWorkRegistration
            from pds_core.class_metadata import ClassMetadata, write_class_metadata
            from pds_core.routes import class_metadata_path, module_work_dir
            from pds_core.routing_models import ModuleWorkRef

            from meridian.grade_item_membership_storage import (
                load_current_grade_item_membership_decision,
                select_grade_item_membership_revision,
                write_grade_item_membership_revision,
            )
            from meridian.grade_item_memberships import (
                GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
                GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
                GradeItemAcademicPeriodAssignment,
                GradeItemMembershipDecision,
            )
            from meridian.grade_item_storage import write_grade_item_revision
            from meridian.grade_items import (
                GRADE_ITEM_RECORD_TYPE,
                GRADE_ITEM_SCHEMA_VERSION,
                GradeItemRevision,
                GradeItemWeightingMetadata,
                GradeItemWorkReference,
                grade_item_revision_from_json_bytes,
                grade_item_revision_to_json_bytes,
            )

            workspace = pathlib.Path(tempfile.mkdtemp(prefix="meridian-membership-"))
            try:
                class_id = "synthetic_class"
                school_year = "2026-2027"
                now = datetime(2026, 8, 25, tzinfo=UTC)
                metadata = ClassMetadata(
                    class_id=class_id,
                    school_year=school_year,
                    created_at=now,
                    updated_at=now,
                    module_details={},
                )
                write_class_metadata(class_metadata_path(workspace, class_id), metadata)

                work = ModuleWorkRef(
                    module_id="scoreform",
                    class_id=class_id,
                    work_id="essay_1",
                )
                module_work_dir(workspace, work).mkdir(parents=True, exist_ok=True)
                registration = AcademicWorkRegistration(
                    schema_version="1",
                    record_type="academic_work_registration",
                    work=work,
                    registration_revision=1,
                    producer_contract_version="v1",
                    title="Synthetic Essay",
                    work_kind="assessment",
                    academic_intent="summative",
                    lifecycle="active",
                    created_at=now,
                    updated_at=now,
                    source_records=(),
                )
                write_academic_work_registration(
                    workspace,
                    registration,
                    expected_current_revision=None,
                )

                calendar = AcademicPeriodCalendar(
                    schema_version="1",
                    record_type="academic_period_calendar",
                    school_year=school_year,
                    calendar_revision=1,
                    created_at=now,
                    updated_at=now,
                    periods=(
                        AcademicPeriod(
                            period_id="mp1",
                            period_type="marking_period",
                            label="Marking Period 1",
                            start_date=date(2026, 9, 1),
                            end_date=date(2026, 11, 8),
                            parent_period_id=None,
                            sequence=1,
                            lifecycle="active",
                        ),
                    ),
                )
                write_academic_period_calendar(
                    workspace,
                    calendar,
                    expected_current_revision=None,
                )

                item = GradeItemRevision(
                    schema_version=GRADE_ITEM_SCHEMA_VERSION,
                    record_type=GRADE_ITEM_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id="essay_grade_item",
                    grade_item_revision=1,
                    supersedes_revision=None,
                    title="Synthetic Essay",
                    purpose="standards_proficiency",
                    status="active",
                    weighting=GradeItemWeightingMetadata(
                        relative_weight=Decimal("1.5")
                    ),
                    created_at=now,
                    revised_at=now,
                )
                data = grade_item_revision_to_json_bytes(item)
                assert grade_item_revision_from_json_bytes(data) == item
                stored_item = write_grade_item_revision(workspace, item).stored

                membership = GradeItemMembershipDecision(
                    schema_version=GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
                    record_type=GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
                    class_id=class_id,
                    grade_item_id=item.grade_item_id,
                    grade_item_revision=1,
                    grade_item_revision_sha256=stored_item.revision_sha256,
                    work_reference=GradeItemWorkReference(
                        work=work,
                        registration_revision=1,
                    ),
                    membership_revision=1,
                    supersedes_revision=None,
                    decision="included",
                    academic_period=GradeItemAcademicPeriodAssignment(
                        period=AcademicPeriodRef(
                            school_year=school_year,
                            period_id="mp1",
                        ),
                        calendar_revision=1,
                    ),
                    actor_id="teacher_local",
                    rationale=None,
                    decided_at=now,
                )
                written = write_grade_item_membership_revision(
                    workspace, membership
                )
                assert written.disposition == "created"
                selected = select_grade_item_membership_revision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                    1,
                    expected_current_membership_revision=None,
                )
                assert selected.disposition == "created"
                current = load_current_grade_item_membership_decision(
                    workspace,
                    class_id,
                    item.grade_item_id,
                    work,
                )
                assert current is not None
                assert current.decision == membership
            finally:
                shutil.rmtree(workspace)

            import meridian
            import pds_core

            prefix = pathlib.Path(sys.prefix).resolve()
            assert pathlib.Path(meridian.__file__).resolve().is_relative_to(prefix)
            assert pathlib.Path(pds_core.__file__).resolve().is_relative_to(prefix)
            assert not (
                {"scoreform", "quillan", "concord", "portia", "vitrine"}
                & set(sys.modules)
            )
            """
        )
        _run([str(python), "-c", code], outside)
        if list(outside.iterdir()):
            raise RuntimeError("Grade Item smoke test left working-directory residue.")


def main(argv: list[str] | None = None) -> int:
    """Parse wheel paths and run the installed Grade Item smoke test."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(args.meridian_wheel, args.core_wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
