from __future__ import annotations

from pathlib import Path

import pytest

import scripts.smoke_test_hybrid_grade_wheel as hybrid
import scripts.smoke_test_proficiency_signal_export_wheel as proficiency
import scripts.smoke_test_standards_grade_wheel as standards


def test_issue96_proficiency_export_prepared_smoke_keeps_reload_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(
        proficiency,
        "_run",
        lambda command, cwd: calls.append((command, cwd)),
    )

    proficiency.run_prepared_smoke(Path("prepared-python"), tmp_path)

    assert calls == [
        (
            ["prepared-python", str(proficiency.PROGRAM.resolve())],
            tmp_path,
        ),
        (
            ["prepared-python", str(proficiency.RELOAD_PROGRAM.resolve())],
            tmp_path,
        ),
    ]


@pytest.mark.parametrize(
    ("module", "program_name", "reload_name"),
    (
        (standards, "PROGRAM", "RELOAD_PROGRAM"),
        (hybrid, "PROGRAM", "RELOAD_PROGRAM"),
    ),
)
def test_issue96_grade_prepared_smoke_keeps_workspace_and_reload_process(
    module: object,
    program_name: str,
    reload_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(
        module,
        "_run",
        lambda command, cwd: calls.append((command, cwd)),
    )
    workspace = tmp_path / "workspace"

    module.run_prepared_smoke(  # type: ignore[attr-defined]
        Path("prepared-python"),
        tmp_path,
        workspace,
    )

    program = getattr(module, program_name)
    reload_program = getattr(module, reload_name)
    assert calls == [
        (
            ["prepared-python", str(program.resolve()), str(workspace)],
            tmp_path,
        ),
        (
            ["prepared-python", str(reload_program.resolve()), str(workspace)],
            tmp_path,
        ),
    ]


def test_issue96_scoreform_quillan_wrappers_keep_standalone_setup() -> None:
    for relative in (
        "scripts/smoke_test_proficiency_signal_export_wheel.py",
        "scripts/smoke_test_standards_grade_wheel.py",
        "scripts/smoke_test_hybrid_grade_wheel.py",
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
        assert "CONCORD_WHEEL" in source


def test_issue96_concord_absence_evidence_remains_in_installed_programs() -> None:
    proficiency_main = Path(
        "scripts/smoke_program_proficiency_signal_export.py"
    ).read_text(encoding="utf-8")
    proficiency_reload = Path(
        "scripts/smoke_program_proficiency_signal_export_reload.py"
    ).read_text(encoding="utf-8")
    standards_main = Path("scripts/smoke_program_standards_grade.py").read_text(
        encoding="utf-8"
    )
    hybrid_main = Path("scripts/smoke_program_hybrid_grade.py").read_text(
        encoding="utf-8"
    )

    for source in (
        proficiency_main,
        proficiency_reload,
        standards_main,
        hybrid_main,
    ):
        assert "pds-concord" in source
        assert 'find_spec("concord") is None' in source


def test_issue96_validator_no_longer_invokes_scoreform_quillan_wrappers() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")

    for wrapper in (
        "smoke_test_proficiency_signal_export_wheel.py",
        "smoke_test_standards_grade_wheel.py",
        "smoke_test_hybrid_grade_wheel.py",
    ):
        assert wrapper not in validator
    assert validator.count("scripts.installed_qualification_runner") == 1
