from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

import scripts.installed_qualification_core_programs as core_programs
from scripts.installed_qualification_harness import PreparedInstalledEnvironment
from scripts.installed_qualification_matrix import DependencyMatrixId, matrix_for


@dataclass
class FakePreparedEnvironment:
    root: Path
    matrix_id: DependencyMatrixId = DependencyMatrixId.CORE
    python: Path = Path("prepared-python")
    meridian: Path = Path("prepared-meridian")
    counter: int = 0
    immutable_checks: list[str] = field(default_factory=list)

    @property
    def matrix(self):  # type: ignore[no-untyped-def]
        return matrix_for(self.matrix_id)

    def fresh_working_directory(self, smoke_name: str) -> Path:
        self.counter += 1
        path = self.root / f"{self.counter:02d}-{smoke_name}"
        path.mkdir(parents=True)
        return path

    def assert_package_set_immutable(self, smoke_name: str) -> None:
        self.immutable_checks.append(smoke_name)


def test_issue96_inline_core_smokes_use_fresh_roots_and_prepared_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = FakePreparedEnvironment(tmp_path)
    calls: list[tuple[str, tuple[Path, ...]]] = []

    def record(name: str):
        def runner(*args: Path) -> None:
            calls.append((name, args))
        return runner

    monkeypatch.setattr(
        core_programs,
        "run_grade_items_prepared",
        record("grade-items"),
    )
    monkeypatch.setattr(
        core_programs,
        "run_academic_period_prepared",
        record("academic-period-proficiency"),
    )
    monkeypatch.setattr(
        core_programs,
        "run_grouping_contract_prepared",
        record("grouping-signal-contract"),
    )
    monkeypatch.setattr(
        core_programs,
        "run_grouping_policy_prepared",
        record("grouping-signal-policy"),
    )
    monkeypatch.setattr(
        core_programs,
        "run_explanation_traces_prepared",
        record("explanation-traces"),
    )

    core_programs.run_core_inline_smokes(
        cast(PreparedInstalledEnvironment, prepared)
    )

    assert [name for name, _ in calls] == [
        "grade-items",
        "academic-period-proficiency",
        "grouping-signal-contract",
        "grouping-signal-policy",
        "explanation-traces",
    ]
    roots = [args[-2] for _, args in calls]
    outsides = [args[-1] for _, args in calls]
    assert len(set(roots)) == 5
    assert len(set(outsides)) == 5
    assert all(outside.parent == root for root, outside in zip(roots, outsides))
    assert all(args[0] == Path("prepared-python") for _, args in calls)
    assert calls[-1][1][1] == Path("prepared-meridian")
    assert prepared.immutable_checks == [
        "grade-items",
        "academic-period-proficiency",
        "grouping-signal-contract",
        "grouping-signal-policy",
        "explanation-traces",
    ]


def test_issue96_inline_core_smokes_reject_wrong_matrix(tmp_path: Path) -> None:
    prepared = FakePreparedEnvironment(
        tmp_path,
        matrix_id=DependencyMatrixId.SCOREFORM,
    )

    with pytest.raises(ValueError, match="requires the core dependency matrix"):
        core_programs.run_core_inline_smokes(
            cast(PreparedInstalledEnvironment, prepared)
        )


def test_issue96_inline_wrapper_prepared_paths_do_not_install() -> None:
    for relative in (
        "scripts/smoke_test_grade_items_wheel.py",
        "scripts/smoke_test_academic_period_proficiency_wheel.py",
        "scripts/smoke_test_grouping_signal_contract_wheel.py",
        "scripts/smoke_test_grouping_signal_policy_wheel.py",
        "scripts/smoke_test_explanation_traces_wheel.py",
    ):
        source = Path(relative).read_text(encoding="utf-8")
        helper_start = source.index("def run_prepared_smoke(")
        smoke_start = source.index("def smoke_test(", helper_start)
        helper = source[helper_start:smoke_start]

        assert "venv.EnvBuilder" not in helper
        assert "pip install" not in helper
        assert "pip check" not in helper

        standalone = source[smoke_start:]
        assert "venv.EnvBuilder(with_pip=True).create(environment)" in standalone
        assert "run_prepared_smoke(" in standalone


def test_issue96_validator_no_longer_invokes_migrated_inline_wrappers() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")

    for wrapper in (
        "smoke_test_grade_items_wheel.py",
        "smoke_test_academic_period_proficiency_wheel.py",
        "smoke_test_grouping_signal_contract_wheel.py",
        "smoke_test_grouping_signal_policy_wheel.py",
        "smoke_test_explanation_traces_wheel.py",
    ):
        assert wrapper not in validator
    assert validator.count("scripts.installed_qualification_core_programs") == 1
