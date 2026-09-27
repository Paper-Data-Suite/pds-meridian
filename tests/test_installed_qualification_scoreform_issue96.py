from __future__ import annotations

from pathlib import Path

import pytest

import scripts.smoke_test_conventional_grade_wheel as conventional
import scripts.smoke_test_teacher_grade_override_wheel as override


def test_issue96_conventional_grade_prepared_smoke_keeps_reload_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(
        conventional,
        "_run",
        lambda command, cwd: calls.append((command, cwd)),
    )

    conventional.run_prepared_smoke(Path("prepared-python"), tmp_path)

    assert calls == [
        (
            [
                "prepared-python",
                str(conventional.PROGRAM.resolve()),
            ],
            tmp_path,
        ),
        (
            [
                "prepared-python",
                str(conventional.RELOAD_PROGRAM.resolve()),
            ],
            tmp_path,
        ),
    ]


def test_issue96_teacher_override_prepared_smoke_keeps_reload_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(
        override,
        "_run",
        lambda command, cwd: calls.append((command, cwd)),
    )

    override.run_prepared_smoke(Path("prepared-python"), tmp_path)

    assert calls == [
        (
            [
                "prepared-python",
                str(override.PROGRAM.resolve()),
            ],
            tmp_path,
        ),
        (
            [
                "prepared-python",
                str(override.ACTIVE_RELOAD.resolve()),
            ],
            tmp_path,
        ),
        (
            [
                "prepared-python",
                str(override.WITHDRAWN_RELOAD.resolve()),
            ],
            tmp_path,
        ),
    ]


def test_issue96_scoreform_wrappers_keep_standalone_environment_setup() -> None:
    for relative in (
        "scripts/smoke_test_conventional_grade_wheel.py",
        "scripts/smoke_test_teacher_grade_override_wheel.py",
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
        assert "run_prepared_smoke(python, outside)" in standalone


def test_issue96_validator_no_longer_invokes_scoreform_only_wrappers() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")

    assert "smoke_test_conventional_grade_wheel.py" not in validator
    assert "smoke_test_teacher_grade_override_wheel.py" not in validator
    assert validator.count("scripts.installed_qualification_runner") == 1
