from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from meridian.concord_adapter import CONCORD_READER_VERSION
from meridian.quillan_adapter import QUILLAN_READER_VERSION
from meridian.scoreform_adapter import SCOREFORM_READER_VERSION
from scripts.installed_qualification_matrix import (
    DEPENDENCY_MATRICES,
    DependencyMatrixId,
)
from scripts.verify_concord_wheel import EXPECTED_CONCORD_VERSION
from scripts.verify_core_wheel import EXPECTED_CORE_VERSION
from scripts.verify_quillan_wheel import EXPECTED_QUILLAN_VERSION
from scripts.verify_scoreform_wheel import EXPECTED_SCOREFORM_VERSION

REPO_ROOT = Path(__file__).resolve().parents[1]


def _project() -> dict[str, object]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as source:
        return tomllib.load(source)["project"]


def _runtime_import_roots() -> set[str]:
    observed: set[str] = set()
    for path in sorted((REPO_ROOT / "meridian").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                observed.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                observed.add(node.module.split(".", 1)[0])
    return observed


def test_issue61_exact_direct_interoperability_versions_remain_aligned() -> None:
    assert EXPECTED_CORE_VERSION == "0.6.4"
    assert EXPECTED_SCOREFORM_VERSION == SCOREFORM_READER_VERSION == "0.12.0"
    assert EXPECTED_QUILLAN_VERSION == QUILLAN_READER_VERSION == "0.10.5"
    assert EXPECTED_CONCORD_VERSION == CONCORD_READER_VERSION == "0.3.0"


def test_issue61_package_dependency_direction_is_core_plus_exact_optional_readers(
) -> None:
    project = _project()

    assert project["dependencies"] == ["pds-core>=0.6.3,<0.7"]
    optional = project["optional-dependencies"]
    assert optional["scoreform"] == ["scoreform==0.12.0"]
    assert optional["quillan"] == ["quillan==0.10.5"]
    assert optional["concord"] == ["pds-concord==0.3.0"]


def test_issue61_ecosystem_peers_are_not_meridian_runtime_dependencies() -> None:
    project = _project()
    serialized = repr(project["dependencies"]) + repr(
        project["optional-dependencies"]
    )

    for forbidden in (
        "pds-vitrine",
        "vitrine",
        "paper-data-suite",
        "paper_data_suite",
        "pds-portia",
        "portia",
        "pds-clavis",
        "clavis",
    ):
        assert forbidden not in serialized


def test_issue61_runtime_does_not_import_ecosystem_coexistence_packages() -> None:
    imports = _runtime_import_roots()

    assert imports.isdisjoint(
        {
            "vitrine",
            "paper_data_suite",
            "portia",
            "clavis",
        }
    )


def test_issue61_direct_producers_remain_optional_not_core_requirements() -> None:
    project = _project()
    required = " ".join(project["dependencies"])

    assert "scoreform" not in required
    assert "quillan" not in required
    assert "concord" not in required


def test_issue61_six_matrix_topology_preserves_presence_absence_authority() -> None:
    observed = {
        matrix.matrix_id: (matrix.producers, matrix.excluded_producers)
        for matrix in DEPENDENCY_MATRICES
    }

    assert observed == {
        DependencyMatrixId.CORE: (
            (),
            ("scoreform", "quillan", "concord"),
        ),
        DependencyMatrixId.SCOREFORM: (
            ("scoreform",),
            ("quillan", "concord"),
        ),
        DependencyMatrixId.QUILLAN: (
            ("quillan",),
            ("scoreform", "concord"),
        ),
        DependencyMatrixId.CONCORD: (
            ("concord",),
            ("scoreform", "quillan"),
        ),
        DependencyMatrixId.SCOREFORM_QUILLAN: (
            ("scoreform", "quillan"),
            ("concord",),
        ),
        DependencyMatrixId.ALL_ADAPTERS: (
            ("scoreform", "quillan", "concord"),
            (),
        ),
    }


def test_issue61_package_checker_rejects_bundled_sibling_packages() -> None:
    checker = (REPO_ROOT / "scripts/check_package.py").read_text(encoding="utf-8")

    for forbidden_directory in (
        '"scoreform/"',
        '"quillan/"',
        '"concord/"',
        '"portia/"',
        '"vitrine/"',
    ):
        assert forbidden_directory in checker


def test_issue61_interoperability_audit_supports_promoted_candidate() -> None:
    version = (REPO_ROOT / "meridian/_version.py").read_text(encoding="utf-8")
    audit = (
        REPO_ROOT / "docs/development/v0.3.0-release-audit.md"
    ).read_text(encoding="utf-8")

    assert '__version__: Final[str] = "0.3.0"' in version
    assert "Interoperability and ecosystem-coexistence audit — CONFORMS" in audit
    assert "Final inventory pass: **CONFORMS — 2026-10-06**" in audit
    assert "Candidate qualification: **PENDING**" in audit
