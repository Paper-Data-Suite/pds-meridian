from pathlib import Path

ISSUE45_SDIST_MEMBERS = (
    "docs/architecture/installed-proficiency-signal-export-acceptance.md",
    "scripts/smoke_test_proficiency_signal_export_wheel.py",
    "scripts/smoke_program_proficiency_signal_export.py",
    "scripts/smoke_program_proficiency_signal_export_reload.py",
    "tests/test_issue45_installed_acceptance.py",
    "tests/test_issue45_documentation_acceptance.py",
    "tests/test_issue45_packaging_acceptance.py",
)


def test_issue45_source_surfaces_are_sdist_guarded() -> None:
    sdist = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in ISSUE45_SDIST_MEMBERS:
        assert member in sdist


def test_issue45_does_not_enlarge_runtime_wheel_allowlist() -> None:
    wheel = Path("scripts/check_package.py").read_text(encoding="utf-8")
    for member in ISSUE45_SDIST_MEMBERS:
        assert member not in wheel


def test_issue45_validator_keeps_concord_and_adds_no_concord_smoke() -> None:
    validator = Path("scripts/validate_repository.py").read_text(
        encoding="utf-8"
    )
    runner = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )
    matrix = Path("scripts/installed_qualification_matrix.py").read_text(
        encoding="utf-8"
    )

    assert 'parser.add_argument("--concord-wheel", required=True' in validator
    assert "verify_concord_wheel.py" in validator
    assert "scripts.installed_qualification_runner" in validator
    assert "proficiency-signal-export" in runner
    assert "DependencyMatrixId.SCOREFORM_QUILLAN" in runner

    marker = "DependencyMatrixId.SCOREFORM_QUILLAN"
    block = matrix.split(marker, maxsplit=1)[1]
    block = block.split("DependencyMatrix(", maxsplit=1)[0]
    assert '"scoreform", "quillan"' in block
    assert "concord" not in block


def test_issue45_producer_dependencies_remain_optional() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    project, optional = pyproject.split(
        "[project.optional-dependencies]",
        maxsplit=1,
    )
    dependencies = project.split("dependencies = [", maxsplit=1)[1]
    dependencies = dependencies.split("]", maxsplit=1)[0]

    assert "pds-core>=0.6.3,<0.7" in dependencies
    assert "scoreform" not in dependencies
    assert "quillan" not in dependencies
    assert "pds-concord" not in dependencies
    assert '"scoreform==0.12.1"' in optional
    assert '"quillan==0.10.5"' in optional
    assert '"pds-concord==0.3.0"' in optional


def test_issue45_wrapper_has_no_concord_wheel_parameter() -> None:
    wrapper = Path(
        "scripts/smoke_test_proficiency_signal_export_wheel.py"
    ).read_text(encoding="utf-8")
    assert "concord_wheel" not in wrapper
    assert '"CONCORD_WHEEL"' in wrapper
    assert "environment.pop(variable, None)" in wrapper
