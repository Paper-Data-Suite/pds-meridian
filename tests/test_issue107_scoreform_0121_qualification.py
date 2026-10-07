from __future__ import annotations

import tomllib
from pathlib import Path

from meridian.scoreform_adapter import (
    SCOREFORM_ADAPTER_DESCRIPTOR,
    SCOREFORM_READER_VERSION,
)
from scripts.installed_qualification_matrix import DEPENDENCY_MATRICES
from scripts.verify_core_wheel import (
    EXPECTED_CORE_VERSION,
    EXPECTED_CORE_WHEEL_FILENAME,
    EXPECTED_CORE_WHEEL_SHA256,
)
from scripts.verify_scoreform_wheel import (
    EXPECTED_SCOREFORM_RELEASE_COMMIT,
    EXPECTED_SCOREFORM_RELEASE_TAG,
    EXPECTED_SCOREFORM_RELEASE_TREE,
    EXPECTED_SCOREFORM_VERSION,
    EXPECTED_SCOREFORM_WHEEL_FILENAME,
    EXPECTED_SCOREFORM_WHEEL_SHA256,
)

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_issue107_exact_upstream_release_authority_is_frozen() -> None:
    assert EXPECTED_SCOREFORM_VERSION == "0.12.1"
    assert EXPECTED_SCOREFORM_RELEASE_TAG == "v0.12.1"
    assert EXPECTED_SCOREFORM_RELEASE_COMMIT == (
        "8c3decf64040fd1da839b6f59f19c9ed344ce579"
    )
    assert EXPECTED_SCOREFORM_RELEASE_TREE == (
        "bcc6270319b6234f000d348452072ab8943a2558"
    )
    assert EXPECTED_SCOREFORM_WHEEL_FILENAME == (
        "scoreform-0.12.1-py3-none-any.whl"
    )
    assert EXPECTED_SCOREFORM_WHEEL_SHA256 == (
        "0f71b709eafe351052eac3e4f0d474b7bef36aeec347df05361b0a8995d44d32"
    )
    assert EXPECTED_CORE_VERSION == "0.6.4"
    assert EXPECTED_CORE_WHEEL_FILENAME == "pds_core-0.6.4-py3-none-any.whl"
    assert EXPECTED_CORE_WHEEL_SHA256 == (
        "48cea9317f2967bdc0f2d4c14349a56677c7c3f8211f0f33978ccb1a1c75859b"
    )


def test_issue107_reader_rule_remains_exact_and_optional() -> None:
    project = tomllib.loads(_read("pyproject.toml"))["project"]

    assert project["dependencies"] == ["pds-core>=0.6.3,<0.7"]
    assert project["optional-dependencies"]["scoreform"] == [
        "scoreform==0.12.1"
    ]
    assert SCOREFORM_READER_VERSION == "0.12.1"
    assert SCOREFORM_ADAPTER_DESCRIPTOR.supported_producer_reader_versions == (
        frozenset({"0.12.1"})
    )


def test_issue107_installed_acceptance_reuses_the_six_matrices() -> None:
    assert tuple(matrix.matrix_id.value for matrix in DEPENDENCY_MATRICES) == (
        "core",
        "scoreform",
        "quillan",
        "concord",
        "scoreform-quillan",
        "all-adapters",
    )

    smoke = _read("scripts/smoke_test_wheel.py")
    sdist = _read("scripts/check_sdist.py")
    program = "smoke_program_scoreform_standards_identity.py"
    assert program in smoke
    assert program in sdist


def test_issue107_installed_program_guards_authority_boundaries() -> None:
    source = _read("scripts/smoke_program_scoreform_standards_identity.py")

    for required in (
        "scoreform_academic_result_manifest_v1",
        "english12.njsls.2023",
        "njsls-ela.TS.11-12.4",
        "njsls-ela.NW.11-12.3.D",
        "njsls-ela:RL.TS.11-12.4",
        "njsls-ela:W.NW.11-12.3.D",
        "Meridian mutated source manifest bytes.",
        "selected or dropped",
        "unevaluated",
        '"proficiency", "mastery", "grade", "official", "current"',
    ):
        assert required in source


def test_issue107_preserves_v030_scoreform_release_evidence() -> None:
    for relative in (
        "docs/development/v0.3.0-release-notes.md",
        "docs/development/v0.3.0-release-audit.md",
    ):
        historical = _read(relative)
        assert "0.12.0" in historical
        assert "0.12.1" not in historical
