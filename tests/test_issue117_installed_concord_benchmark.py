"""Focused source/boundary regressions for installed Concord Report 9 acceptance."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.smoke_test_concord_benchmark_issue117 as wrapper
from scripts.smoke_program_concord_benchmark_issue117 import (
    _SyntheticTeacherAuthorization,
)


def test_teacher_reporting_is_explicitly_authorized_only() -> None:
    authorize = _SyntheticTeacherAuthorization()
    request = SimpleNamespace(purpose_id="teacher_reporting")
    assert authorize.authorize(request).allowed  # type: ignore[arg-type]
    with pytest.raises(AssertionError, match="Unexpected"):
        authorize.authorize(  # type: ignore[arg-type]
            SimpleNamespace(purpose_id="project_evidence")
        )


def test_wrapper_uses_existing_prepared_concord_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def invoke(*args: object, **kwargs: object) -> None:
        command = args[0]
        assert isinstance(command, list)
        cwd = kwargs["cwd"]
        env = kwargs["env"]
        assert isinstance(cwd, Path)
        assert isinstance(env, dict)
        calls.append((command, cwd, env))  # type: ignore[arg-type]

    monkeypatch.setattr(wrapper.subprocess, "run", invoke)
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "workspace"
    wrapper.run_prepared_smoke(Path("candidate-python"), outside, workspace)
    assert len(calls) == 1
    command, cwd, env = calls[0]
    assert command == [
        "candidate-python", str(wrapper.PROGRAM.resolve()), str(workspace)
    ]
    assert cwd == outside
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    assert "PYTHONSTARTUP" not in env


def test_concord_matrix_wires_one_additional_process_not_new_matrix() -> None:
    runner = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )
    assert runner.count("run_concord_benchmark_prepared_smoke(") == 1
    assert runner.index('"concord-adapter"') < runner.index(
        '"issue117-concord-benchmark"'
    ) < runner.index("DependencyMatrixId.ALL_ADAPTERS")
    assert runner.count("matrix_for(DependencyMatrixId.CONCORD)") == 1
    assert runner.count("with PreparedInstalledEnvironment(") == 6


def test_installed_concord_manifest_includes_shared_and_individual_evidence() -> None:
    source = Path(
        "scripts/smoke_program_concord_benchmark_issue117.py"
    ).read_text(encoding="utf-8")
    for required in (
        'version("pds-concord") != "0.3.2"',
        'version("pds-core") != "0.6.6"',
        '"core_student", "student_alpha", "core"',
        '"concord_group", "group_alpha", "concord"',
        'score_kind="standard_backed"',
        'score_kind="local"',
        'privacy=PrivacyProjection("teacher_restricted"',
        "with_semantic_projection_digest(",
        "read_academic_result_manifest(",
        "derive_manifest_capabilities(",
        "register_academic_work(",
        "publish_manifest_revision(",
        "setup_installed_benchmark_records(",
        "run_installed_benchmark_teacher_journey(",
    ):
        assert required in source


def test_concord_qualifier_is_separate_from_scoreform_quillan() -> None:
    program = Path(
        "scripts/smoke_program_concord_benchmark_issue117.py"
    ).read_text(encoding="utf-8")
    assert "_assert_installed_origin(concord)" in program
    assert "_assert_installed_origin(meridian)" in program
    assert "_assert_installed_origin(pds_core)" in program
    assert "PDS_WORKSPACE_ROOT" in program
    for absent in ("import quillan", "import scoreform"):
        assert absent not in program
