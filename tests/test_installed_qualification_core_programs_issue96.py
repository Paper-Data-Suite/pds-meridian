from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

import pytest

from scripts.installed_qualification_core_programs import (
    SOURCE_ROOT,
    run_core_program_smokes,
)
from scripts.installed_qualification_matrix import DependencyMatrixId, matrix_for


@dataclass
class RecordedRun:
    name: str
    command: tuple[str, ...]
    cwd: Path
    env: dict[str, str]


@dataclass
class FakePreparedEnvironment:
    root: Path
    matrix_id: DependencyMatrixId = DependencyMatrixId.CORE
    python: Path = Path("prepared-python")
    runs: list[RecordedRun] = field(default_factory=list)
    counter: int = 0

    @property
    def matrix(self):  # type: ignore[no-untyped-def]
        return matrix_for(self.matrix_id)

    def fresh_working_directory(self, smoke_name: str) -> Path:
        self.counter += 1
        path = self.root / f"{self.counter:02d}-{smoke_name}"
        path.mkdir(parents=True)
        return path

    def run_smoke(
        self,
        smoke_name: str,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        capture_output: bool = False,
    ) -> None:
        del input_text, capture_output
        working = cwd or self.fresh_working_directory(smoke_name)
        self.runs.append(
            RecordedRun(
                name=smoke_name,
                command=tuple(command),
                cwd=working,
                env=dict(env or {}),
            )
        )


def test_issue96_core_program_batch_preserves_process_and_workspace_boundaries(
    tmp_path: Path,
) -> None:
    prepared = FakePreparedEnvironment(tmp_path)

    run_core_program_smokes(prepared)  # type: ignore[arg-type]

    assert [run.name for run in prepared.runs] == [
        "grouping-signal-generation",
        "grouping-signal-preview-review",
        "grouping-signal-export",
        "teacher-workflows-seed",
        "teacher-workflows",
        "attention-seed",
        "attention",
    ]
    assert all(run.command[0] == "prepared-python" for run in prepared.runs)

    generation, preview, exported, teacher_seed, teacher, attention_seed, attention = (
        prepared.runs
    )
    assert len({generation.cwd, preview.cwd, exported.cwd}) == 3
    assert teacher_seed.cwd == teacher.cwd
    assert attention_seed.cwd == attention.cwd
    assert teacher.cwd != attention.cwd
    assert teacher.cwd not in {generation.cwd, preview.cwd, exported.cwd}
    assert attention.cwd not in {generation.cwd, preview.cwd, exported.cwd}

    assert teacher_seed.command[1].endswith(
        "smoke_program_grouping_signal_export.py"
    )
    assert teacher.command[1].endswith("smoke_program_teacher_workflows.py")
    assert attention_seed.command[1].endswith(
        "smoke_program_grouping_signal_preview_review.py"
    )
    assert attention.command[1].endswith("smoke_program_attention.py")
    assert attention_seed.env == {
        "PDS_MERIDIAN_SMOKE_SOURCE_ROOT": str(SOURCE_ROOT),
    }
    assert attention.env == attention_seed.env


def test_issue96_core_program_batch_rejects_wrong_matrix(tmp_path: Path) -> None:
    prepared = FakePreparedEnvironment(
        tmp_path,
        matrix_id=DependencyMatrixId.SCOREFORM,
    )

    with pytest.raises(ValueError, match="requires the core dependency matrix"):
        run_core_program_smokes(prepared)  # type: ignore[arg-type]


def test_issue96_core_orchestrator_cannot_create_nested_environment() -> None:
    source = Path("scripts/installed_qualification_core_programs.py").read_text(
        encoding="utf-8"
    )

    assert "venv.EnvBuilder" not in source
    assert "pip install" not in source
    assert "pip uninstall" not in source
    assert "pip check" not in source


def test_issue96_validator_uses_one_prepared_core_program_batch() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")

    assert validator.count("scripts.installed_qualification_core_programs") == 1
    for legacy_wrapper in (
        "smoke_test_grouping_signal_generation_wheel.py",
        "smoke_test_grouping_signal_preview_review_wheel.py",
        "smoke_test_grouping_signal_export_wheel.py",
        "smoke_test_teacher_workflows_wheel.py",
        "smoke_test_attention_wheel.py",
    ):
        assert legacy_wrapper not in validator


def test_issue96_migrated_standalone_wrappers_remain_available() -> None:
    for wrapper in (
        "smoke_test_grouping_signal_generation_wheel.py",
        "smoke_test_grouping_signal_preview_review_wheel.py",
        "smoke_test_grouping_signal_export_wheel.py",
        "smoke_test_teacher_workflows_wheel.py",
        "smoke_test_attention_wheel.py",
    ):
        path = Path("scripts") / wrapper
        source = path.read_text(encoding="utf-8")
        assert path.is_file()
        assert "venv.EnvBuilder(with_pip=True).create(environment)" in source
