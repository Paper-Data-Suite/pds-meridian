"""Smoke-test Core grouping-signal interoperability from an installed Meridian wheel."""

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
    """Install exact Core + Meridian and exercise the #36 neutral contract."""
    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-grouping-signal-contract-smoke-"
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
            r"""
            import hashlib
            import importlib.metadata
            import importlib.util
            import pathlib
            import shutil
            import tempfile
            from datetime import UTC, datetime

            from pds_core.classes import write_class_roster
            from pds_core.grouping_signal_csv import (
                GROUPING_SIGNAL_CSV_CONTRACT_NAME,
                grouping_signal_set_from_csv,
                grouping_signal_set_to_csv,
                grouping_signal_set_to_csv_bytes,
                parse_grouping_signal_csv,
            )
            from pds_core.grouping_signal_diagnostics import diagnose_grouping_signal
            from pds_core.grouping_signal_storage import (
                GroupingSignalConflictError,
                calculate_grouping_signal_digest,
                list_grouping_signal_ids,
                load_grouping_signal,
                write_grouping_signal,
            )
            from pds_core.grouping_signals import (
                GROUPING_SIGNAL_CONTRACT_NAME,
                GROUPING_SIGNAL_RECORD_TYPE,
                GROUPING_SIGNAL_SCHEMA_VERSION,
                GroupingSignalDimension,
                GroupingSignalSet,
                GroupingSignalSource,
                GroupingSignalStudentBand,
                grouping_signal_set_from_json,
                grouping_signal_set_to_json_bytes,
            )
            from pds_core.rosters import create_roster

            assert importlib.metadata.version("pds-core") == "0.6.3"
            assert importlib.metadata.version("pds-meridian") == "0.1.1"
            assert GROUPING_SIGNAL_CONTRACT_NAME == "grouping_signal_set_v1"
            assert GROUPING_SIGNAL_CSV_CONTRACT_NAME == "grouping_signal_csv_v1"

            try:
                importlib.metadata.version("pds-concord")
            except importlib.metadata.PackageNotFoundError:
                pass
            else:
                raise AssertionError(
                    "Grouping-signal smoke must run without pds-concord."
                )
            assert importlib.util.find_spec("concord") is None

            workspace = pathlib.Path(
                tempfile.mkdtemp(prefix="meridian-grouping-signal-contract-")
            )
            try:
                alpha = create_roster(
                    "synthetic_class_alpha",
                    (
                        {
                            "student_id": "student_001",
                            "last_name": "Alpha",
                            "first_name": "One",
                            "period": "1",
                        },
                        {
                            "student_id": "student_002",
                            "last_name": "Alpha",
                            "first_name": "Two",
                            "period": "1",
                        },
                        {
                            "student_id": "student_003",
                            "last_name": "Alpha",
                            "first_name": "Three",
                            "period": "1",
                        },
                    ),
                )
                beta = create_roster(
                    "synthetic_class_beta",
                    (
                        {
                            "student_id": "student_wrong",
                            "last_name": "Beta",
                            "first_name": "Wrong",
                            "period": "2",
                        },
                    ),
                )
                write_class_roster(workspace, alpha)
                write_class_roster(workspace, beta)

                source_digest = "1" * 64
                signal = GroupingSignalSet(
                    schema_version=GROUPING_SIGNAL_SCHEMA_VERSION,
                    record_type=GROUPING_SIGNAL_RECORD_TYPE,
                    signal_set_id="meridian_signal_001",
                    class_id="synthetic_class_alpha",
                    created_at=datetime(2026, 9, 3, 15, 0, tzinfo=UTC),
                    source=GroupingSignalSource(
                        kind="module_generated",
                        module_id="meridian",
                        snapshot_id="meridian_derivation_001",
                        snapshot_digest_algorithm="sha256",
                        snapshot_digest=source_digest,
                    ),
                    dimensions=(
                        GroupingSignalDimension("analysis", 4),
                        GroupingSignalDimension("composition", 3),
                    ),
                    student_bands=(
                        GroupingSignalStudentBand("student_001", "analysis", 1),
                        GroupingSignalStudentBand("student_002", "analysis", 4),
                        GroupingSignalStudentBand("student_wrong", "analysis", 3),
                        GroupingSignalStudentBand("student_unknown", "analysis", 2),
                        GroupingSignalStudentBand("student_001", "composition", 2),
                        GroupingSignalStudentBand("student_002", "composition", 3),
                    ),
                )

                canonical = grouping_signal_set_to_json_bytes(signal)
                assert grouping_signal_set_to_json_bytes(signal) == canonical
                assert grouping_signal_set_from_json(canonical) == signal
                signal_digest = calculate_grouping_signal_digest(signal)
                assert signal_digest == hashlib.sha256(canonical).hexdigest()
                assert signal_digest != source_digest

                analysis_csv = grouping_signal_set_to_csv(signal, "analysis")
                analysis_document = parse_grouping_signal_csv(analysis_csv)
                assert analysis_document.csv_contract == "grouping_signal_csv_v1"
                assert analysis_document.representation_scope == "dimension_projection"
                assert analysis_document.requires_new_identity
                try:
                    grouping_signal_set_from_csv(analysis_csv)
                except Exception as error:
                    assert "new signal_set_id" in str(error)
                else:
                    raise AssertionError(
                        "Multi-dimension CSV projection reused immutable identity."
                    )
                projected = grouping_signal_set_from_csv(
                    analysis_csv,
                    new_signal_set_id="meridian_signal_analysis_projection",
                    new_created_at=datetime(2026, 9, 3, 15, 5, tzinfo=UTC),
                )
                assert projected.signal_set_id == "meridian_signal_analysis_projection"
                assert tuple(item.dimension_id for item in projected.dimensions) == (
                    "analysis",
                )

                single = GroupingSignalSet(
                    schema_version=GROUPING_SIGNAL_SCHEMA_VERSION,
                    record_type=GROUPING_SIGNAL_RECORD_TYPE,
                    signal_set_id="meridian_signal_single",
                    class_id="synthetic_class_alpha",
                    created_at=datetime(2026, 9, 3, 16, 0, tzinfo=UTC),
                    source=GroupingSignalSource(
                        kind="module_generated",
                        module_id="meridian",
                        snapshot_id="meridian_derivation_single",
                        snapshot_digest_algorithm="sha256",
                        snapshot_digest="2" * 64,
                    ),
                    dimensions=(GroupingSignalDimension("analysis", 4),),
                    student_bands=(
                        GroupingSignalStudentBand("student_001", "analysis", 1),
                        GroupingSignalStudentBand("student_002", "analysis", 4),
                    ),
                )
                single_csv = grouping_signal_set_to_csv(single, "analysis")
                single_document = parse_grouping_signal_csv(single_csv)
                assert single_document.representation_scope == "complete_signal"
                assert not single_document.requires_new_identity
                assert grouping_signal_set_from_csv(single_csv) == single
                assert grouping_signal_set_to_csv_bytes(single, "analysis") == (
                    single_csv.encode("utf-8")
                )

                first_write = write_grouping_signal(workspace, signal)
                assert first_write.disposition == "created"
                assert first_write.stored.digest == signal_digest
                replay_write = write_grouping_signal(workspace, signal)
                assert replay_write.disposition == "existing"
                assert replay_write.stored == first_write.stored
                assert load_grouping_signal(
                    workspace,
                    signal.class_id,
                    signal.signal_set_id,
                ) == first_write.stored

                conflict = GroupingSignalSet(
                    schema_version=signal.schema_version,
                    record_type=signal.record_type,
                    signal_set_id=signal.signal_set_id,
                    class_id=signal.class_id,
                    created_at=signal.created_at,
                    source=signal.source,
                    dimensions=signal.dimensions,
                    student_bands=tuple(
                        GroupingSignalStudentBand(
                            entry.student_id,
                            entry.dimension_id,
                            2
                            if (
                                entry.student_id == "student_001"
                                and entry.dimension_id == "analysis"
                            )
                            else entry.band,
                        )
                        for entry in signal.student_bands
                    ),
                )
                try:
                    write_grouping_signal(workspace, conflict)
                except GroupingSignalConflictError:
                    pass
                else:
                    raise AssertionError(
                        "Same signal identity accepted different canonical contents."
                    )

                write_grouping_signal(workspace, single)
                assert list_grouping_signal_ids(
                    workspace,
                    "synthetic_class_alpha",
                ) == ("meridian_signal_001", "meridian_signal_single")

                report = diagnose_grouping_signal(workspace, signal)
                assert report.has_errors
                assert report.has_warnings
                assert tuple(item.code for item in report.findings) == (
                    "wrong_class_student",
                    "unknown_student",
                    "missing_student_signal",
                    "missing_student_signal",
                )
                assert tuple(
                    (item.dimension_id, item.band_counts)
                    for item in report.dimensions
                ) == (
                    ("analysis", ((1, 1), (2, 0), (3, 0), (4, 1))),
                    ("composition", ((1, 0), (2, 1), (3, 1))),
                )

                mismatch = diagnose_grouping_signal(
                    workspace,
                    single,
                    expected_class_id="synthetic_class_beta",
                )
                assert mismatch.has_errors
                assert mismatch.findings[0].code == "class_mismatch"

                # Core v1 has exact immutable identities, not a selected/current alias.
                assert "current" not in list_grouping_signal_ids(
                    workspace,
                    "synthetic_class_alpha",
                )
                assert "latest" not in list_grouping_signal_ids(
                    workspace,
                    "synthetic_class_alpha",
                )
            finally:
                shutil.rmtree(workspace, ignore_errors=True)
            """
        )
        smoke_program = root / "grouping_signal_contract_smoke.py"
        smoke_program.write_text(code, encoding="utf-8", newline="\n")
        _run([str(python), "-I", str(smoke_program)], outside)


def main(argv: list[str] | None = None) -> int:
    """Run the isolated installed grouping-signal contract smoke."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    args = parser.parse_args(argv)

    smoke_test(args.meridian_wheel, args.core_wheel)
    print("Installed grouping-signal contract smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
