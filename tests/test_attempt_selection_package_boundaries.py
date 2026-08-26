from __future__ import annotations

from pathlib import Path


def test_wheel_boundary_requires_attempt_selection_modules() -> None:
    checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    assert '"meridian/attempt_selection.py"' in checker
    assert '"meridian/attempt_selection_storage.py"' in checker


def test_sdist_boundary_requires_attempt_selection_surface() -> None:
    checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        '"docs/architecture/attempt-selection-policy-and-decisions.md"',
        '"meridian/attempt_selection.py"',
        '"meridian/attempt_selection_storage.py"',
        '"tests/test_attempt_selection.py"',
        '"tests/test_attempt_selection_storage.py"',
        '"tests/test_attempt_selection_integration.py"',
        '"tests/test_attempt_selection_package_boundaries.py"',
        '"scripts/smoke_test_grade_items_wheel.py"',
    ):
        assert member in checker


def test_read_only_imports_cover_attempt_selection_modules() -> None:
    test = Path("tests/test_read_only_imports.py").read_text(encoding="utf-8")
    assert '"meridian.attempt_selection"' in test
    assert '"meridian.attempt_selection_storage"' in test


def test_documentation_validation_guards_issue30_boundaries() -> None:
    checker = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    assert "attempt-selection-policy-and-decisions.md" in checker
    assert "AttemptObservationReference" in checker
    assert "eligibility != attempt selection" in checker
    assert "attempt selection != reassessment" in checker
    assert "issue #30 — implemented" in checker
    assert "issue #31 — next" in checker


def test_installed_wheel_smoke_covers_core_only_attempt_selection_flow() -> None:
    smoke = Path("scripts/smoke_test_grade_items_wheel.py").read_text(encoding="utf-8")
    assert "AttemptSelectionPolicy" in smoke
    assert "write_attempt_selection_policy_revision" in smoke
    assert "select_attempt_selection_policy_revision" in smoke
    assert "write_attempt_selection_decision_revision" in smoke
    assert "select_attempt_selection_decision_revision" in smoke
    assert "resolve_current_attempt_selection" in smoke
    for producer in ("scoreform", "quillan", "concord", "portia", "vitrine"):
        assert f"import {producer}" not in smoke
        assert f"from {producer}" not in smoke
