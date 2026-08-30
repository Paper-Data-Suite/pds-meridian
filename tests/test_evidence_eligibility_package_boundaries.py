from __future__ import annotations

from pathlib import Path


def test_wheel_boundary_requires_evidence_eligibility_modules() -> None:
    checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    assert '"meridian/evidence_eligibility.py"' in checker
    assert '"meridian/evidence_eligibility_storage.py"' in checker


def test_sdist_boundary_requires_evidence_eligibility_surface() -> None:
    checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        '"docs/architecture/evidence-eligibility-decisions.md"',
        '"meridian/evidence_eligibility.py"',
        '"meridian/evidence_eligibility_storage.py"',
        '"tests/test_evidence_eligibility.py"',
        '"tests/test_evidence_eligibility_storage.py"',
        '"tests/test_evidence_eligibility_package_boundaries.py"',
        '"scripts/smoke_test_grade_items_wheel.py"',
    ):
        assert member in checker


def test_read_only_imports_cover_evidence_eligibility_modules() -> None:
    test = Path("tests/test_read_only_imports.py").read_text(encoding="utf-8")
    assert '"meridian.evidence_eligibility"' in test
    assert '"meridian.evidence_eligibility_storage"' in test


def test_documentation_validation_guards_issue29_boundaries() -> None:
    checker = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    assert "evidence-eligibility-decisions.md" in checker
    assert "EvidenceSourceReference" in checker
    assert "projection != canonical eligibility decision" in checker
    assert "membership != evidence eligibility" in checker
    assert "eligibility != attempt selection" in checker
    assert "issue #29 — implemented" in checker
    assert "issue #30 — implemented" in checker
    assert "issue #31 — implemented" in checker
    assert "issue #32 — implemented" in checker
    assert "issue #33 — implemented" in checker
    assert "issue #34 — implemented" in checker
    assert "issue #35 — implemented" in checker
    assert "issue #36 — implemented" in checker
    assert "issue #37 — next" in checker


def test_installed_wheel_smoke_covers_core_only_eligibility_flow() -> None:
    smoke = Path("scripts/smoke_test_grade_items_wheel.py").read_text(encoding="utf-8")
    assert "EvidenceEligibilityDecision" in smoke
    assert "write_evidence_eligibility_revision" in smoke
    assert "select_evidence_eligibility_revision" in smoke
    assert "resolve_current_evidence_eligibility" in smoke
    for producer in ("scoreform", "quillan", "concord", "portia", "vitrine"):
        assert f"import {producer}" not in smoke
        assert f"from {producer}" not in smoke
