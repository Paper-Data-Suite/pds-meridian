from __future__ import annotations

from pathlib import Path


def test_wheel_boundary_requires_grade_item_modules() -> None:
    checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    assert '"meridian/grade_items.py"' in checker
    assert '"meridian/grade_item_storage.py"' in checker
    assert '"meridian/grade_item_memberships.py"' in checker
    assert '"meridian/grade_item_membership_storage.py"' in checker


def test_sdist_boundary_requires_grade_item_sources_and_documentation() -> None:
    checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    assert '"meridian/grade_items.py"' in checker
    assert '"meridian/grade_item_storage.py"' in checker
    assert (
        '"docs/architecture/grade-item-membership-and-academic-period-assignment.md"'
        in checker
    )
    assert '"docs/architecture/grade-items-and-canonical-storage.md"' in checker
    assert '"meridian/grade_item_membership_storage.py"' in checker
    assert '"meridian/grade_item_memberships.py"' in checker
    assert '"tests/test_grade_item_membership_storage.py"' in checker
    assert '"tests/test_grade_item_memberships.py"' in checker
    assert '"scripts/smoke_test_grade_items_wheel.py"' in checker


def test_repository_validation_runs_installed_grade_item_smoke() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    assert '"scripts/smoke_test_grade_items_wheel.py"' in validator


def test_documentation_validation_guards_grade_item_boundary() -> None:
    checker = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    assert "grade-items-and-canonical-storage.md" in checker
    assert "GradeItemWorkReference" in checker
    assert "Grade Item creation != membership" in checker
    assert "no decision != excluded" in checker
    assert "issue #27 — implemented" in checker
    assert "issue #28 — implemented" in checker
