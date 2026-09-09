from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import meridian
from meridian.pds_operations import get_module_operations_profile
from meridian.teacher_workflows import (
    TEACHER_WORKFLOW_TASK_IDS,
    teacher_workflow_catalog,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

PRODUCER_IMPORT_BOUNDARIES = {
    "scoreform_adapter.py": (
        "scoreform",
        {
            "scoreform.academic_result_manifest",
            "scoreform.academic_result_reader",
        },
    ),
    "quillan_adapter.py": (
        "quillan",
        {
            "quillan.academic_result_manifest",
            "quillan.academic_result_reader",
        },
    ),
    "concord_adapter.py": (
        "concord",
        {
            "concord.academic_result_manifest",
            "concord.academic_result_reader",
        },
    ),
}

CALCULATION_AND_PLANNING_MODULES = (
    "standards_proficiency.py",
    "academic_period_proficiency.py",
    "grouping_signal_policy.py",
    "grouping_signal_derivation.py",
    "grouping_signal_generation.py",
    "grouping_signal_export.py",
)


def _package_root() -> Path:
    assert meridian.__file__ is not None
    return Path(meridian.__file__).resolve().parent


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _producer_imports(path: Path, producer: str) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == producer or module.startswith(f"{producer}."):
                imported.add(module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == producer or alias.name.startswith(f"{producer}."):
                    imported.add(alias.name)
    return imported


def test_distribution_dependency_direction_remains_core_plus_optional_readers() -> None:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    project = pyproject["project"]

    assert project["dependencies"] == ["pds-core>=0.6.3,<0.7"]
    optional = project["optional-dependencies"]
    assert optional["scoreform"] == ["scoreform==0.11.0"]
    assert optional["quillan"] == ["quillan==0.10.0"]
    assert optional["concord"] == ["pds-concord==0.3.0"]


def test_producer_adapters_import_only_academic_result_read_contracts() -> None:
    package_root = _package_root()

    for filename, (producer, allowed) in PRODUCER_IMPORT_BOUNDARIES.items():
        imported = _producer_imports(package_root / filename, producer)
        assert imported
        assert imported <= allowed


def test_teacher_workflow_catalog_preserves_explicit_v02_authority_boundaries() -> None:
    catalog = teacher_workflow_catalog()
    assert tuple(task.task_id for task in catalog.tasks) == TEACHER_WORKFLOW_TASK_IDS

    by_id = {task.task_id: task for task in catalog.tasks}
    assert "highest/latest/best" in by_id["attempt-decisions"].summary
    assert "separate explicit actions" in by_id["grade-items"].write_boundary
    assert "Preview is read-only" in by_id["calculation-preview"].write_boundary
    assert "without invoking Concord" in by_id["create-planning-signal"].summary
    assert "no Concord state is created" in (
        by_id["create-planning-signal"].write_boundary
    )


def test_module_operations_profile_is_attention_only() -> None:
    profile = get_module_operations_profile()

    assert profile.module_id == "meridian"
    assert profile.readiness_provider is None
    assert profile.attention_provider is not None


def test_reserved_weighting_metadata_is_not_executed_by_v02_calculation_or_planning(
) -> None:
    package_root = _package_root()
    forbidden: list[tuple[str, int, str]] = []

    for filename in CALCULATION_AND_PLANNING_MODULES:
        path = package_root / filename
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Attribute) and node.attr in {
                "relative_weight",
                "weighting",
            }:
                forbidden.append((filename, node.lineno, node.attr))

    assert forbidden == []


def test_no_v03_override_or_reporting_snapshot_runtime_family_exists() -> None:
    names = {path.name for path in _package_root().glob("*.py")}

    assert not any("override" in name for name in names)
    assert not any(
        "report" in name and "snapshot" in name
        for name in names
    )
    assert "grade_calculation.py" not in names
    assert "conventional_grade.py" not in names
