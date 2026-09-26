from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import scripts.smoke_test_grade_report_preview_wheel as grade_preview
import scripts.smoke_test_report_exports_wheel as report_exports
import scripts.smoke_test_reporting_snapshot_wheel as snapshot
import scripts.smoke_test_teacher_menu_wheel as teacher_menu


def test_issue96_grade_preview_prepared_smoke_keeps_reload_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(
        grade_preview,
        "_run",
        lambda command, cwd: calls.append((command, cwd)),
    )

    grade_preview.run_prepared_smoke(Path("prepared-python"), tmp_path)

    assert calls == [
        (
            [
                "prepared-python",
                str(grade_preview.PROGRAM.resolve()),
                str(tmp_path),
            ],
            tmp_path,
        ),
        (
            [
                "prepared-python",
                str(grade_preview.RELOAD_PROGRAM.resolve()),
                str(tmp_path),
            ],
            tmp_path,
        ),
    ]


def test_issue96_reporting_snapshot_prepared_smoke_keeps_reload_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(
        snapshot,
        "_run",
        lambda command, cwd: calls.append((command, cwd)),
    )

    snapshot.run_prepared_smoke(Path("prepared-python"), tmp_path)

    assert calls == [
        (
            [
                "prepared-python",
                str(snapshot.PROGRAM.resolve()),
                str(tmp_path),
            ],
            tmp_path,
        ),
        (
            [
                "prepared-python",
                str(snapshot.RELOAD_PROGRAM.resolve()),
                str(tmp_path),
            ],
            tmp_path,
        ),
    ]


def test_issue96_report_exports_prepared_smoke_keeps_seed_and_reload_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(
        report_exports,
        "_run",
        lambda command, cwd: calls.append((command, cwd)),
    )

    report_exports.run_prepared_smoke(Path("prepared-python"), tmp_path)

    assert calls == [
        (
            [
                "prepared-python",
                "-m",
                "meridian",
                "reporting",
                "exports",
                "--help",
            ],
            tmp_path,
        ),
        (
            [
                "prepared-python",
                str(report_exports.SNAPSHOT_PROGRAM.resolve()),
                str(tmp_path),
            ],
            tmp_path,
        ),
        (
            [
                "prepared-python",
                str(report_exports.PROGRAM.resolve()),
                str(tmp_path),
            ],
            tmp_path,
        ),
        (
            [
                "prepared-python",
                str(report_exports.RELOAD_PROGRAM.resolve()),
                str(tmp_path),
            ],
            tmp_path,
        ),
    ]


def test_issue96_teacher_menu_prepared_smoke_preserves_workspace_immutability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu_text = (
        "Review New Evidence\n"
        "Manage Grade Items\n"
        "Review Proficiency\n"
        "Preview Grades\n"
        "Overrides\n"
        "Snapshots\n"
        "Export\n"
        "Explain\n"
        "1. Review New Evidence\n"
        "1. Review New Evidence\n"
        "Review Proficiency\n"
        "Create Planning Signal\n"
        "Meridian\n"
        "Review Proficiency\n"
    )
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, stdin
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=menu_text,
            stderr="",
        )

    monkeypatch.setattr(teacher_menu, "_run", fake_run)

    teacher_menu.run_prepared_smoke(
        Path("prepared-python"),
        Path("prepared-meridian"),
        tmp_path,
    )

    assert not tuple(tmp_path.rglob("*"))
    assert ["prepared-meridian"] in calls
    assert ["prepared-python", "-m", "meridian"] in calls
    assert ["prepared-meridian", "--help"] in calls
    assert ["prepared-meridian", "--version"] in calls


def test_issue96_all_adapter_wrappers_keep_standalone_environment_setup() -> None:
    for relative in (
        "scripts/smoke_test_grade_report_preview_wheel.py",
        "scripts/smoke_test_reporting_snapshot_wheel.py",
        "scripts/smoke_test_report_exports_wheel.py",
        "scripts/smoke_test_teacher_menu_wheel.py",
    ):
        source = Path(relative).read_text(encoding="utf-8")
        helper_start = source.index("def run_prepared_smoke(")
        smoke_start = source.index("def smoke_test(", helper_start)
        helper = source[helper_start:smoke_start]
        standalone = source[smoke_start:]

        assert "venv.EnvBuilder" not in helper
        assert "pip install" not in helper
        assert "pip check" not in helper
        assert "venv.EnvBuilder(with_pip=True).create(environment)" in standalone
        assert "run_prepared_smoke(" in standalone


def test_issue96_teacher_menu_prepared_helper_keeps_mutation_guards() -> None:
    source = Path("scripts/smoke_test_teacher_menu_wheel.py").read_text(
        encoding="utf-8"
    )
    helper_start = source.index("def run_prepared_smoke(")
    smoke_start = source.index("def smoke_test(", helper_start)
    helper = source[helper_start:smoke_start]

    assert "after == before" in helper
    assert "Installed navigation created workspace state." in helper
    assert "Direct CLI help/version created workspace state." in helper


def test_issue96_validator_has_exact_six_prepared_matrix_environments() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")

    for wrapper in (
        "smoke_test_grade_report_preview_wheel.py",
        "smoke_test_reporting_snapshot_wheel.py",
        "smoke_test_report_exports_wheel.py",
        "smoke_test_teacher_menu_wheel.py",
    ):
        assert wrapper not in validator
    assert validator.count("scripts.installed_qualification_runner") == 1
