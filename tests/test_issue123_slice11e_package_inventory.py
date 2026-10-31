"""Issue #123 Slice 11E: exact installed Meridian module allowlist contract."""

from __future__ import annotations

import ast
import zipfile
from pathlib import Path

import pytest

from scripts.check_package import PackageValidationError, validate_wheel

# Only these 44 were absent at the frozen e944e17 packaging gate.
EXPECTED_ADDITIONS = frozenset(
    {
        "meridian/menu_teacher_named_definition_create.py",
        "meridian/menu_teacher_named_definition_revision.py",
        "meridian/menu_teacher_named_definitions.py",
        "meridian/menu_teacher_named_explain_comparison.py",
        "meridian/menu_teacher_named_explain_derivation.py",
        "meridian/menu_teacher_named_explain_export.py",
        "meridian/menu_teacher_named_explain_grade.py",
        "meridian/menu_teacher_named_explain_item_proficiency.py",
        "meridian/menu_teacher_named_explain_period_proficiency.py",
        "meridian/menu_teacher_named_explain_preview_review.py",
        "meridian/menu_teacher_named_explain_report_receipt.py",
        "meridian/menu_teacher_named_export_delivery.py",
        "meridian/menu_teacher_named_export_preview.py",
        "meridian/menu_teacher_named_export_profile_selection.py",
        "meridian/menu_teacher_named_export_profiles.py",
        "meridian/menu_teacher_named_export_receipts.py",
        "meridian/menu_teacher_named_grade_report.py",
        "meridian/menu_teacher_named_grades.py",
        "meridian/menu_teacher_named_membership_selection.py",
        "meridian/menu_teacher_named_override_authoring.py",
        "meridian/menu_teacher_named_override_review.py",
        "meridian/menu_teacher_named_override_selection.py",
        "meridian/menu_teacher_named_override_withdrawal.py",
        "meridian/menu_teacher_named_period.py",
        "meridian/menu_teacher_named_planning_derivation_write.py",
        "meridian/menu_teacher_named_planning_diagnostics.py",
        "meridian/menu_teacher_named_planning_export.py",
        "meridian/menu_teacher_named_planning_preview_write.py",
        "meridian/menu_teacher_named_planning_readiness.py",
        "meridian/menu_teacher_named_planning_review_authoring.py",
        "meridian/menu_teacher_named_planning_review_selection.py",
        "meridian/menu_teacher_named_review.py",
        "meridian/menu_teacher_named_revision.py",
        "meridian/menu_teacher_named_snapshot_selection.py",
        "meridian/menu_teacher_named_snapshots.py",
        "meridian/menu_teacher_named_work.py",
        "meridian/teacher_navigation_choices.py",
        "meridian/teacher_navigation_context.py",
        "meridian/teacher_navigation_domain.py",
        "meridian/teacher_navigation_membership_revisions.py",
        "meridian/teacher_navigation_period.py",
        "meridian/teacher_navigation_revisions.py",
        "meridian/teacher_navigation_terminal.py",
        "meridian/teacher_navigation_work.py",
    }
)


def _required() -> frozenset[str]:
    source = Path("scripts/check_package.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "validate_wheel"
    )
    declaration = next(
        node
        for node in method.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "required"
    )
    literal = ast.literal_eval(declaration.value)
    assert isinstance(literal, set)
    assert all(isinstance(item, str) for item in literal)
    return frozenset(literal)


def _actual() -> frozenset[str]:
    return frozenset(
        {p.as_posix() for p in Path("meridian").glob("*.py")} | {"meridian/py.typed"}
    )


def test_exact_current_meridian_modules_are_explicitly_allowlisted() -> None:
    required = _required()
    actual = _actual()
    assert len(EXPECTED_ADDITIONS) == 44
    assert len(actual) == 272
    assert actual == required
    assert EXPECTED_ADDITIONS.issubset(required)
    assert all(Path(path).is_file() for path in required)


def test_allowlist_is_a_literal_and_validator_still_rejects_unknown() -> None:
    source = Path("scripts/check_package.py").read_text(encoding="utf-8")
    assert "allowed_meridian = {item.lower() for item in required}" in source
    assert (
        'normalized.startswith("meridian/") and normalized not in allowed_meridian'
        in source
    )
    assert "Wheel contains an unexpected Meridian module" in source
    assert "Wheel contains forbidden content" in source
    assert "FORBIDDEN_PREFIXES" in source
    assert "FORBIDDEN_PARTS" in source
    assert "for name in names:" in source


def _sample_metadata() -> bytes:
    # Exactly the currently reviewed publication contract.
    items = [
        "Metadata-Version: 2.4",
        "Name: pds-meridian",
        "Version: 0.4.2",
        (
            "Summary: Teacher-controlled evidence, proficiency, Grades, reporting, "
            "and planning for Paper Data Suite"
        ),
        "Requires-Python: >=3.11",
        "Description-Content-Type: text/markdown",
        "Requires-Dist: pds-core>=0.6.5,<0.7",
        "Requires-Dist: scoreform>=0.13.0; extra == 'scoreform'",
        "Requires-Dist: quillan>=0.10.6; extra == 'quillan'",
        "Requires-Dist: pds-concord>=0.3.2; extra == 'concord'",
    ]
    return ("\n".join(items) + "\n\n").encode("utf-8")


def _sample_wheel(path: Path, *, extra: str | None = None) -> None:
    entries = set(_required())
    if extra is not None:
        entries.add(extra)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for name in sorted(entries):
            wheel.writestr(name, b"pass\n")
        wheel.writestr("pds_meridian-0.4.2.dist-info/METADATA", _sample_metadata())
        wheel.writestr(
            "pds_meridian-0.4.2.dist-info/entry_points.txt",
            (
                "[console_scripts]\nmeridian = meridian.cli:main\n"
                "[paper_data_suite.module_operations]\n"
                "meridian = meridian.pds_operations:get_module_operations_profile\n"
            ),
        )
        wheel.writestr("pds_meridian-0.4.2.dist-info/licenses/LICENSE", "MIT\n")


def test_exact_candidate_inventory_passes_validator(tmp_path: Path) -> None:
    wheel = tmp_path / "candidate.whl"
    _sample_wheel(wheel)
    validate_wheel(wheel)


@pytest.mark.parametrize(
    "unexpected",
    [
        "meridian/unreviewed_navigation.py",
        "meridian/secrets.py",
        "tests/test_private.py",
        "classes/synthetic_roster.csv",
    ],
)
def test_wheel_rejects_unreviewed_and_forbidden_members(
    tmp_path: Path, unexpected: str
) -> None:
    wheel = tmp_path / "candidate.whl"
    _sample_wheel(wheel, extra=unexpected)
    with pytest.raises(PackageValidationError, match="unexpected|forbidden"):
        validate_wheel(wheel)
