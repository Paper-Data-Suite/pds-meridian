from __future__ import annotations

from pathlib import Path


def test_wheel_boundary_requires_reassessment_modules() -> None:
    checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    assert '"meridian/reassessment.py"' in checker
    assert '"meridian/reassessment_storage.py"' in checker


def test_sdist_boundary_requires_reassessment_surface() -> None:
    checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        '"docs/architecture/reassessment-and-replacement-relationships.md"',
        '"meridian/reassessment.py"',
        '"meridian/reassessment_storage.py"',
        '"tests/test_reassessment.py"',
        '"tests/test_reassessment_storage.py"',
        '"tests/test_reassessment_integration.py"',
        '"tests/test_reassessment_package_boundaries.py"',
        '"scripts/smoke_test_grade_items_wheel.py"',
    ):
        assert member in checker


def test_read_only_imports_cover_reassessment_modules() -> None:
    test = Path("tests/test_read_only_imports.py").read_text(encoding="utf-8")
    assert '"meridian.reassessment"' in test
    assert '"meridian.reassessment_storage"' in test


def test_documentation_validation_guards_issue31_boundaries() -> None:
    checker = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    assert "reassessment-and-replacement-relationships.md" in checker
    assert "AttemptSelectionDecisionReference" in checker
    assert "attempt selection != reassessment" in checker
    assert "reassessment != native-value mapping" in checker
    assert "issue #31 — implemented" in checker
    assert "issue #32 — implemented" in checker
    assert "issue #33 — implemented" in checker
    assert "issue #34 — implemented" in checker
    assert "issue #35 — implemented" in checker
    assert "issue #36 — implemented" in checker
    assert "issue #37 — implemented" in checker
    assert "issue #38 — implemented" in checker


def test_installed_wheel_smoke_covers_reassessment_flow() -> None:
    smoke = Path("scripts/smoke_test_grade_items_wheel.py").read_text(encoding="utf-8")
    assert "ReassessmentPolicy" in smoke
    assert "write_reassessment_policy_revision" in smoke
    assert "select_reassessment_policy_revision" in smoke
    assert "write_reassessment_decision_revision" in smoke
    assert "select_reassessment_decision_revision" in smoke
    assert "resolve_current_reassessment" in smoke
    for producer in ("scoreform", "quillan", "concord", "portia", "vitrine"):
        assert f"import {producer}" not in smoke
        assert f"from {producer}" not in smoke


def test_runtime_reassessment_modules_do_not_import_producers() -> None:
    for filename in ("meridian/reassessment.py", "meridian/reassessment_storage.py"):
        source = Path(filename).read_text(encoding="utf-8")
        for producer in ("scoreform", "quillan", "concord", "portia", "vitrine"):
            assert f"import {producer}" not in source
            assert f"from {producer}" not in source
