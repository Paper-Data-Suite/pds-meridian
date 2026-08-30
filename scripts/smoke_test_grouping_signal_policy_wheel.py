"""Smoke-test #37 grouping-signal policy from an installed Meridian wheel."""

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
    """Install exact Core + Meridian and exercise the complete #37 boundary."""

    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-grouping-signal-policy-smoke-"
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
            import importlib.util
            import pathlib
            from datetime import UTC, date, datetime

            from pds_core.academic_period_storage import (
                write_academic_period_calendar,
            )
            from pds_core.academic_periods import (
                AcademicPeriod,
                AcademicPeriodCalendar,
                AcademicPeriodRef,
            )
            from pds_core.class_metadata import ClassMetadata, write_class_metadata
            from pds_core.grouping_signal_storage import list_grouping_signal_ids
            from pds_core.routes import class_dir, class_metadata_path
            from pds_core.standards import (
                StandardDefinition,
                StandardsLibrary,
                write_workspace_standards_library,
            )

            from meridian.academic_period_proficiency import (
                ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
                ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
                AcademicPeriodProficiencyAggregationPolicy,
                AcademicPeriodProficiencyTarget,
                academic_period_proficiency_aggregation_policy_reference,
            )
            from meridian.academic_period_proficiency_storage import (
                write_academic_period_proficiency_policy_revision,
            )
            from meridian.grouping_signal_policy import (
                GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
                GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
                GroupingSignalAcademicBasis,
                GroupingSignalBandDefinition,
                GroupingSignalDerivationPolicy,
                GroupingSignalPolicyActor,
            )
            from meridian.grouping_signal_policy_storage import (
                get_current_grouping_signal_policy_revision,
                load_current_grouping_signal_policy,
                select_grouping_signal_policy_revision,
                write_grouping_signal_policy_revision,
            )
            from meridian.proficiency_mapping import (
                PROFICIENCY_SCALE_RECORD_TYPE,
                PROFICIENCY_SCALE_SCHEMA_VERSION,
                MappingActor,
                ProficiencyLevel,
                ProficiencyScale,
                proficiency_scale_reference,
            )
            from meridian.proficiency_mapping_storage import (
                write_proficiency_scale_revision,
            )
            from meridian.standards_proficiency import StandardProficiencyActor

            assert importlib.util.find_spec("concord") is None

            workspace = pathlib.Path("workspace").resolve()
            class_id = "synthetic_class_2026"
            school_year = "2026-2027"
            standard_id = "urn:njsls:ela:RL.CR.9-10.1"
            now = datetime(2026, 8, 30, 21, 0, tzinfo=UTC)

            class_dir(workspace, class_id).mkdir(parents=True)
            write_class_metadata(
                class_metadata_path(workspace, class_id),
                ClassMetadata(
                    class_id=class_id,
                    school_year=school_year,
                    created_at=now,
                    updated_at=now,
                    module_details={},
                ),
            )
            write_academic_period_calendar(
                workspace,
                AcademicPeriodCalendar(
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
                ),
                expected_current_revision=None,
            )
            write_workspace_standards_library(
                workspace,
                StandardsLibrary(
                    standards=(
                        StandardDefinition(
                            standard_id=standard_id,
                            code="RL.CR.9-10.1",
                            source="NJSLS-ELA-2023",
                            short_name="Textual evidence",
                            description="Synthetic installed-wheel standard.",
                            subject="ELA",
                            grade_band="9-10",
                            active=True,
                            available_modules=("meridian",),
                        ),
                    )
                ),
            )

            scale = ProficiencyScale(
                schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
                record_type=PROFICIENCY_SCALE_RECORD_TYPE,
                class_id=class_id,
                scale_id="teacher_scale",
                scale_revision=1,
                supersedes_revision=None,
                title="Teacher proficiency scale",
                description="Synthetic criterion-referenced scale.",
                levels=(
                    ProficiencyLevel("level_1", 1, "Beginning", "Beginning."),
                    ProficiencyLevel("level_2", 2, "Developing", "Developing."),
                    ProficiencyLevel("level_3", 3, "Proficient", "Proficient."),
                    ProficiencyLevel("level_4", 4, "Extending", "Extending."),
                ),
                proficiency_threshold_level_id="level_3",
                actor=MappingActor("teacher", "teacher_local"),
                rationale=None,
                revised_at=now,
            )
            exact_scale = write_proficiency_scale_revision(
                workspace,
                scale,
            ).stored.scale

            source_policy = AcademicPeriodProficiencyAggregationPolicy(
                schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
                record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
                class_id=class_id,
                policy_id="period_proficiency_policy",
                policy_revision=1,
                supersedes_revision=None,
                title="Academic Period proficiency",
                target_scale=proficiency_scale_reference(exact_scale),
                strategy="highest",
                period_membership_scope="direct",
                minimum_calculated_results=1,
                mode_tie_rule=None,
                median_even_rule=None,
                missing_result_handling="noncontributing",
                insufficient_result_handling="noncontributing",
                actor=StandardProficiencyActor("teacher", "teacher_local"),
                rationale=None,
                revised_at=now,
            )
            exact_source_policy = write_academic_period_proficiency_policy_revision(
                workspace,
                source_policy,
            ).stored.policy

            grouping_policy = GroupingSignalDerivationPolicy(
                schema_version=GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
                record_type=GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
                class_id=class_id,
                policy_id="reading_planning_signal",
                policy_revision=1,
                supersedes_revision=None,
                title="Reading planning signal",
                academic_basis=GroupingSignalAcademicBasis(
                    basis_kind="academic_period_proficiency",
                    target_period=AcademicPeriodProficiencyTarget(
                        AcademicPeriodRef(school_year, "mp1"),
                        1,
                    ),
                    standard_id=standard_id,
                    source_policy=(
                        academic_period_proficiency_aggregation_policy_reference(
                            exact_source_policy
                        )
                    ),
                    target_scale=proficiency_scale_reference(exact_scale),
                ),
                dimension_id="reading_planning",
                band_count=3,
                band_definitions=(
                    GroupingSignalBandDefinition(1, 1, 1),
                    GroupingSignalBandDefinition(2, 2, 3),
                    GroupingSignalBandDefinition(3, 4, 4),
                ),
                tie_handling="same_level_same_band",
                missing_result_handling="noncontributing",
                insufficient_result_handling="blocking",
                actor=GroupingSignalPolicyActor("teacher", "teacher_local"),
                rationale="Temporary contextual planning support.",
                revised_at=now,
            )

            created = write_grouping_signal_policy_revision(
                workspace,
                grouping_policy,
            )
            assert created.disposition == "created"
            assert (
                get_current_grouping_signal_policy_revision(
                    workspace,
                    class_id,
                    grouping_policy.policy_id,
                )
                is None
            )
            replay = write_grouping_signal_policy_revision(
                workspace,
                grouping_policy,
            )
            assert replay.disposition == "existing"
            assert replay.stored.reference == created.stored.reference

            selected = select_grouping_signal_policy_revision(
                workspace,
                class_id,
                grouping_policy.policy_id,
                1,
                expected_current_policy_revision=None,
            )
            assert selected.disposition == "created"
            current = load_current_grouping_signal_policy(
                workspace,
                class_id,
                grouping_policy.policy_id,
            )
            assert current is not None
            assert current.reference == created.stored.reference

            assert list_grouping_signal_ids(workspace, class_id) == ()
            assert importlib.util.find_spec("concord") is None
            print("Installed grouping-signal policy smoke passed.")
            """
        )
        smoke_program = root / "installed_grouping_signal_policy_smoke.py"
        smoke_program.write_text(code, encoding="utf-8", newline="\n")
        _run([str(python), str(smoke_program)], outside)


def main(argv: list[str] | None = None) -> int:
    """Parse wheel paths and run the isolated #37 installed-wheel smoke."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(args.meridian_wheel, args.core_wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
