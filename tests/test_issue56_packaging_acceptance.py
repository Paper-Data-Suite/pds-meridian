from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MODULES = (
    "meridian/export_profile.py",
    "meridian/export_profile_storage.py",
    "meridian/report_export_roster.py",
    "meridian/report_export_preview.py",
    "meridian/report_export_receipt.py",
    "meridian/report_export_commit.py",
    "meridian/report_export_cli.py",
)


def test_issue56_wheel_guard_requires_runtime_and_quillan_0101() -> None:
    text = (ROOT / "scripts" / "check_package.py").read_text(encoding="utf-8")

    assert 'Requirement("quillan==0.10.1; extra == \'quillan\'")' in text
    for module in RUNTIME_MODULES:
        assert f'"{module}"' in text


def test_issue56_sdist_guard_requires_runtime_docs_and_tests() -> None:
    text = (ROOT / "scripts" / "check_sdist.py").read_text(encoding="utf-8")

    for module in RUNTIME_MODULES:
        assert f'"{module}"' in text
    assert '"docs/architecture/reporting-exports.md"' in text
    assert '"tests/test_cli_report_exports_issue56.py"' in text
    assert '"tests/test_report_export_commit_issue56.py"' in text


def test_pyproject_uses_required_current_quillan_release() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"quillan==0.10.1"' in text
    assert '"quillan==0.10.0"' not in text
