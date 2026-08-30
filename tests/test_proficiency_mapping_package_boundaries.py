from __future__ import annotations

from pathlib import Path


def test_wheel_boundary_requires_proficiency_mapping_modules() -> None:
    checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    assert '"meridian/proficiency_mapping.py"' in checker
    assert '"meridian/proficiency_mapping_storage.py"' in checker


def test_sdist_boundary_requires_proficiency_mapping_surface() -> None:
    checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        '"docs/architecture/proficiency-scales-and-native-value-mapping-profiles.md"',
        '"meridian/proficiency_mapping.py"',
        '"meridian/proficiency_mapping_storage.py"',
        '"tests/test_proficiency_mapping.py"',
        '"tests/test_proficiency_mapping_storage.py"',
        '"tests/test_proficiency_mapping_integration.py"',
        '"tests/test_proficiency_mapping_package_boundaries.py"',
    ):
        assert member in checker


def test_read_only_imports_cover_proficiency_mapping_modules() -> None:
    test = Path("tests/test_read_only_imports.py").read_text(encoding="utf-8")
    assert '"meridian.proficiency_mapping"' in test
    assert '"meridian.proficiency_mapping_storage"' in test


def test_documentation_validation_guards_issue32_boundaries() -> None:
    checker = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    assert "proficiency-scales-and-native-value-mapping-profiles.md" in checker
    assert "producer-native result != Meridian proficiency" in checker
    assert "reassessment != native-value mapping" in checker
    assert "native-value mapping != standards evidence association" in checker
    assert "issue #32 — implemented" in checker
    assert "issue #33 — implemented" in checker
    assert "issue #34 — implemented" in checker
    assert "issue #35 — implemented" in checker
    assert "issue #36 — implemented" in checker
    assert "issue #37 — next" in checker


def test_installed_wheel_smoke_covers_mapping_flow() -> None:
    smoke = Path("scripts/smoke_test_grade_items_wheel.py").read_text(encoding="utf-8")
    for token in (
        "ProficiencyScale",
        "NativeValueMappingProfile",
        "write_proficiency_scale_revision",
        "select_proficiency_scale_revision",
        "write_mapping_profile_revision",
        "map_native_value",
        "NativeStateValue",
        "points_possible=10",
    ):
        assert token in smoke


def test_installed_wheel_smoke_uses_script_file_for_large_payload() -> None:
    smoke = Path("scripts/smoke_test_grade_items_wheel.py").read_text(encoding="utf-8")
    assert 'smoke_program.write_bytes(code.encode("utf-8"))' in smoke
    assert '_run([str(python), "-c", code], outside)' not in smoke


def test_runtime_mapping_modules_do_not_import_producers() -> None:
    for filename in (
        "meridian/proficiency_mapping.py",
        "meridian/proficiency_mapping_storage.py",
    ):
        source = Path(filename).read_text(encoding="utf-8")
        for producer in ("scoreform", "quillan", "concord", "portia", "vitrine"):
            assert f"import {producer}" not in source
            assert f"from {producer}" not in source
