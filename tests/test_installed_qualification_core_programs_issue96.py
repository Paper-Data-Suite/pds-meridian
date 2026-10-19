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

    legacy_runs = prepared.runs[:10]
    issue122_runs = prepared.runs[10:]
    assert [run.name for run in legacy_runs] == [
        "storage-paths-issue102",
        "grouping-signal-generation",
        "grouping-signal-preview-review",
        "grouping-signal-export",
        "teacher-workflows-seed",
        "teacher-workflows",
        "attention-seed",
        "attention",
        "issue59-operations-seed",
        "issue59-operations",
    ]
    assert all(run.command[0] == "prepared-python" for run in prepared.runs)

    (
        storage_paths,
        generation,
        preview,
        exported,
        teacher_seed,
        teacher,
        attention_seed,
        attention,
        issue59_seed,
        issue59_operations,
    ) = legacy_runs
    independent = {
        storage_paths.cwd,
        generation.cwd,
        preview.cwd,
        exported.cwd,
    }
    assert len(independent) == 4
    assert teacher_seed.cwd == teacher.cwd
    assert attention_seed.cwd == attention.cwd
    assert teacher.cwd != attention.cwd
    assert issue59_seed.cwd == issue59_operations.cwd
    assert issue59_operations.cwd != teacher.cwd
    assert issue59_operations.cwd != attention.cwd
    assert teacher.cwd not in independent
    assert attention.cwd not in independent
    assert issue59_operations.cwd not in independent

    assert storage_paths.command[1].endswith("smoke_program_storage_paths_issue102.py")
    assert teacher_seed.command[1].endswith("smoke_program_grouping_signal_export.py")
    assert teacher.command[1].endswith("smoke_program_teacher_workflows.py")
    assert attention_seed.command[1].endswith(
        "smoke_program_grouping_signal_preview_review.py"
    )
    assert attention.command[1].endswith("smoke_program_attention.py")
    assert issue59_seed.command[1].endswith(
        "smoke_program_grouping_signal_preview_review.py"
    )
    assert issue59_operations.command[1].endswith("smoke_program_issue59_operations.py")
    assert attention_seed.env == {
        "PDS_MERIDIAN_SMOKE_SOURCE_ROOT": str(SOURCE_ROOT),
    }
    assert attention.env == attention_seed.env
    assert issue59_seed.env == attention_seed.env
    assert issue59_operations.env == attention_seed.env

    # #122 extends the matrix but cannot change its older smoke boundaries.
    stories = (
        ("normal", ("seed", "cancel", "one_save", "verify")),
        ("restart", ("seed", "interrupt", "replay_blocked", "resume", "verify")),
        ("cas-race", ("seed", "interrupt", "supersede", "reject_superseded")),
        (
            "corrupt-receipt",
            ("seed", "interrupt", "corrupt_receipt", "reject_corrupt_receipt"),
        ),
    )
    expected_names = [
        f"issue122-{story}-{phase}" for story, phases in stories for phase in phases
    ]
    assert [run.name for run in issue122_runs] == expected_names
    assert len(issue122_runs) == 17
    assert all(
        run.command[1].endswith("smoke_program_issue122_multi_process.py")
        for run in issue122_runs
    )
    assert all(run.env == {} for run in issue122_runs)
    story_workspaces: set[str] = set()
    index = 0
    for story, phases in stories:
        batch = issue122_runs[index : index + len(phases)]
        index += len(phases)
        assert [run.command[2] for run in batch] == list(phases)
        assert len({run.cwd for run in batch}) == 1
        outside = batch[0].cwd
        assert outside.name == "outside"
        assert len({run.command[3] for run in batch}) == 1
        workspace = Path(batch[0].command[3])
        assert workspace == outside.parent / "synthetic-academic-workspace"
        assert story in str(workspace)
        assert str(workspace) not in story_workspaces
        story_workspaces.add(str(workspace))
        assert outside not in independent
        assert outside not in {teacher.cwd, attention.cwd, issue59_operations.cwd}


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

    assert validator.count("scripts.installed_qualification_runner") == 1
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
