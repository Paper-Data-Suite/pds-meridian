from __future__ import annotations

import ast
from pathlib import Path

import meridian.standards_evidence_storage as standards_storage
from tests.cross_producer_aggregation_support import (
    prepare_aggregation_scenario,
)
from tests.cross_producer_test_support import (
    SECONDARY_STUDENT_ID,
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)
from tests.cross_producer_workspace_support import CLASS_ID

GENERIC_PROFICIENCY_MODULES = (
    Path("meridian/proficiency_mapping.py"),
    Path("meridian/standards_evidence.py"),
    Path("meridian/standards_evidence_storage.py"),
    Path("meridian/standards_proficiency.py"),
    Path("meridian/standards_proficiency_storage.py"),
    Path("meridian/grade_item_proficiency_explanation.py"),
    Path("meridian/academic_period_proficiency.py"),
    Path("meridian/academic_period_proficiency_storage.py"),
    Path("meridian/academic_period_calculation_assembly_workflow.py"),
    Path("meridian/academic_period_calculation_preview_workflow.py"),
)

PRODUCER_IMPORT_ROOTS = {
    "scoreform",
    "quillan",
    "concord",
    "pds_concord",
}

GROUPING_IMPORT_PREFIXES = (
    "meridian.grouping_signal",
    "meridian.planning_signal",
)


def _imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return tuple(modules)


def _root_module(module: str) -> str:
    return module.split(".", 1)[0]


def test_generic_proficiency_runtime_has_no_producer_package_imports() -> None:
    offenders: list[str] = []
    for path in GENERIC_PROFICIENCY_MODULES:
        assert path.is_file(), path
        for module in _imported_modules(path):
            if _root_module(module) in PRODUCER_IMPORT_ROOTS:
                offenders.append(f"{path}: {module}")
    assert offenders == []


def test_proficiency_runtime_does_not_import_grouping_or_planning_signal() -> None:
    offenders: list[str] = []
    for path in GENERIC_PROFICIENCY_MODULES:
        for module in _imported_modules(path):
            if module.startswith(GROUPING_IMPORT_PREFIXES):
                offenders.append(f"{path}: {module}")
    assert offenders == []


def test_producer_readers_remain_optional_not_base_dependencies() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    project_section, optional_section = pyproject.split(
        "[project.optional-dependencies]",
        maxsplit=1,
    )
    dependencies = project_section.split("dependencies = [", maxsplit=1)[1]
    dependencies = dependencies.split("]", maxsplit=1)[0]

    assert "pds-core>=0.6.3,<0.7" in dependencies
    assert "scoreform" not in dependencies
    assert "quillan" not in dependencies
    assert "pds-concord" not in dependencies

    assert 'scoreform = [' in optional_section
    assert '"scoreform==0.11.0"' in optional_section
    assert 'quillan = [' in optional_section
    assert '"quillan==0.10.0"' in optional_section
    assert 'concord = [' in optional_section
    assert '"pds-concord==0.3.0"' in optional_section


def test_concord_group_path_excludes_before_student_proficiency(
    tmp_path: Path,
) -> None:
    scenario = prepare_aggregation_scenario(tmp_path)
    inputs = standards_storage.resolve_standard_aggregation_inputs(
        scenario.workspace.mixed.root,
        scenario.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        scenario.target_scale.reference,
        scenario.bindings,
        standards_library=scenario.standard_library,
    )

    entry = next(
        value
        for value in inputs.entries
        if value.source.work.module_id == "concord"
        and value.target_kind == "concord_group"
    )
    assert entry.status == "excluded"
    assert entry.exclusion_reason == "nonstudent_target"
    assert entry.mapping_status == "mapped"
    assert entry.proficiency_level_id is None
    assert entry.native_state is None


def test_cross_producer_fixture_identity_is_synthetic_and_bounded(
    tmp_path: Path,
) -> None:
    scenario = prepare_aggregation_scenario(tmp_path)

    assert CLASS_ID == "synthetic_class_2026"
    assert SHARED_STUDENT_ID == "student_synthetic_001"
    assert SECONDARY_STUDENT_ID == "student_synthetic_002"

    allowed_students = {SHARED_STUDENT_ID, SECONDARY_STUDENT_ID}
    for projected in scenario.workspace.projected.values():
        for item in projected.inventory.items:
            if item.subject is not None:
                assert item.subject.student_id in allowed_students
            assert item.provenance.publication.work.class_id == CLASS_ID
