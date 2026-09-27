from __future__ import annotations

from pathlib import Path


def test_issue57_wheel_guard_requires_complete_menu_runtime() -> None:
    text = Path("scripts/check_package.py").read_text(encoding="utf-8")
    for module in (
        "meridian/menu.py",
        "meridian/menu_ui.py",
        "meridian/menu_evidence.py",
        "meridian/menu_grade_items.py",
        "meridian/menu_proficiency.py",
        "meridian/menu_planning_signal.py",
        "meridian/menu_grades.py",
        "meridian/menu_overrides.py",
        "meridian/menu_snapshots.py",
        "meridian/menu_export.py",
        "meridian/menu_explain.py",
    ):
        assert f'"{module}"' in text
    assert 'Requirement("quillan==0.10.3; extra == \'quillan\'")' in text


def test_issue57_sdist_guard_requires_docs_smoke_and_menu_runtime() -> None:
    text = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        "docs/architecture/teacher-main-menu.md",
        "meridian/menu_planning_signal.py",
        "scripts/smoke_test_teacher_menu_wheel.py",
        "tests/test_issue57_installed_acceptance.py",
        "tests/test_issue57_packaging_acceptance.py",
        "tests/test_issue57_documentation_acceptance.py",
    ):
        assert f'"{member}"' in text


def test_issue57_current_quillan_release_is_exact_0103() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    verifier = Path("scripts/verify_quillan_wheel.py").read_text(encoding="utf-8")
    adapter = Path("meridian/quillan_adapter.py").read_text(encoding="utf-8")
    assert '"quillan==0.10.3"' in pyproject
    assert 'EXPECTED_QUILLAN_VERSION = "0.10.3"' in verifier
    assert (
        'EXPECTED_QUILLAN_WHEEL_FILENAME = "quillan-0.10.3-py3-none-any.whl"'
        in verifier
    )
    assert (
        "eb8f527d2dd43c3961374ac6a3f34a732827ce0bd3260943667160f8d2bf3e3b"
        in verifier
    )
    assert 'QUILLAN_READER_VERSION: Final = "0.10.3"' in adapter
