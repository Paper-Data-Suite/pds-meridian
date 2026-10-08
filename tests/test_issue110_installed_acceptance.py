from __future__ import annotations

from pathlib import Path

import pytest

import scripts.smoke_test_guided_evidence_issue110 as guided


@pytest.mark.parametrize("producer", ("scoreform", "quillan"))
def test_issue110_guided_installed_wrapper_runs_one_fresh_process(
    producer: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(
        guided,
        "_run",
        lambda command, cwd: calls.append((command, cwd)),
    )

    guided.run_prepared_smoke(
        Path("prepared-python"),
        tmp_path,
        tmp_path / "workspace",
        producer,  # type: ignore[arg-type]
    )

    assert calls == [
        (
            [
                "prepared-python",
                str(guided.PROGRAM.resolve()),
                producer,
                str(tmp_path / "workspace"),
            ],
            tmp_path,
        )
    ]


def test_issue110_installed_smoke_is_wired_to_existing_isolated_matrices() -> None:
    source = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )

    assert '"issue110-guided-evidence-scoreform"' in source
    assert '"issue110-guided-evidence-quillan"' in source
    assert source.count("run_issue110_guided_evidence_prepared_smoke(") == 2
    assert "DependencyMatrixId.SCOREFORM" in source
    assert "DependencyMatrixId.QUILLAN" in source


def test_issue110_exact_reader_versions_remain_frozen() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    scoreform = Path("meridian/scoreform_adapter.py").read_text(encoding="utf-8")
    quillan = Path("meridian/quillan_adapter.py").read_text(encoding="utf-8")
    concord = Path("meridian/concord_adapter.py").read_text(encoding="utf-8")

    assert '"scoreform==0.12.1"' in pyproject
    assert '"quillan==0.10.5"' in pyproject
    assert '"pds-concord==0.3.0"' in pyproject
    assert 'SCOREFORM_READER_VERSION: Final = "0.12.1"' in scoreform
    assert 'QUILLAN_READER_VERSION: Final = "0.10.5"' in quillan
    assert 'CONCORD_READER_VERSION: Final = "0.3.0"' in concord


def test_issue110_core_remains_only_unconditional_runtime_dependency() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    dependencies = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]

    assert '"pds-core>=0.6.3,<0.7"' in dependencies
    assert "scoreform" not in dependencies
    assert "quillan" not in dependencies
    assert "concord" not in dependencies


def test_issue110_smoke_program_requires_installed_package_origins() -> None:
    source = Path(
        "scripts/smoke_program_guided_evidence_issue110.py"
    ).read_text(encoding="utf-8")

    assert "_assert_installed_origin(meridian)" in source
    assert "_assert_installed_origin(pds_core)" in source
    assert "_assert_installed_origin(scoreform)" in source
    assert "_assert_installed_origin(quillan)" in source
    assert 'version("scoreform") != "0.12.1"' in source
    assert 'version("quillan") != "0.10.5"' in source
    assert 'version("pds-core") != "0.6.4"' in source


def test_issue110_smoke_uses_real_catalog_projection_and_guided_menu() -> None:
    source = Path(
        "scripts/smoke_program_guided_evidence_issue110.py"
    ).read_text(encoding="utf-8")

    for required in (
        "register_academic_work(",
        "publish_manifest_revision(",
        "rebuild_academic_catalog(",
        "default_diagnostics_dependencies(",
        "default_teacher_evidence_inbox_menu_dependencies(",
        "run_teacher_evidence_inbox_menu(",
    ):
        assert required in source
