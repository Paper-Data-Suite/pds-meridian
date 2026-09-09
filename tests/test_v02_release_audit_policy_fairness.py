from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

import pytest

import meridian
from meridian.adapters import AdapterProjectionRequest, AdapterRegistry
from meridian.concord_adapter import ConcordAcademicResultAdapter
from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationValidationError,
    GroupingSignalStudentDerivation,
)
from meridian.grouping_signal_policy import (
    GroupingSignalResultHandling,
    GroupingSignalTieHandling,
)
from tests.concord_test_support import (
    concord_manifest_bytes,
    concord_publication,
    concord_registration,
)


def test_v02_grouping_policy_keeps_fairness_vocabularies_bounded() -> None:
    assert get_args(GroupingSignalTieHandling) == ("same_level_same_band",)
    assert set(get_args(GroupingSignalResultHandling)) == {
        "noncontributing",
        "blocking",
    }


def test_missing_grouping_source_cannot_be_encoded_as_a_low_band() -> None:
    missing = GroupingSignalStudentDerivation(
        student_id="student_synthetic_002",
        source_state="missing",
        disposition="noncontributing",
        source_result=None,
        proficiency_level_id=None,
        scale_position=None,
        band=None,
    )
    assert missing.band is None
    assert missing.proficiency_level_id is None
    assert missing.scale_position is None

    with pytest.raises(
        GroupingSignalDerivationValidationError,
        match="missing student derivation",
    ):
        GroupingSignalStudentDerivation(
            student_id="student_synthetic_002",
            source_state="missing",
            disposition="noncontributing",
            source_result=None,
            proficiency_level_id=None,
            scale_position=None,
            band=1,
        )


def test_concord_group_targets_remain_nonstudent_evidence() -> None:
    manifest = concord_manifest_bytes()
    request = AdapterProjectionRequest(
        concord_publication(manifest),
        concord_registration(),
        None,
        manifest,
    )
    inventory = AdapterRegistry((ConcordAcademicResultAdapter(),)).invoke(
        request,
        lambda _: "0.3.0",
    )

    group_items = tuple(
        item
        for item in inventory.items
        if item.target.target_kind == "concord_group"
    )
    assert group_items
    assert all(item.subject is None for item in group_items)
    assert all(
        item.target.owning_system == "concord"
        for item in group_items
    )


def test_grouping_signal_runtime_has_no_concord_planning_import() -> None:
    assert meridian.__file__ is not None
    package_root = Path(meridian.__file__).resolve().parent
    planning_modules = tuple(sorted(package_root.glob("grouping_signal*.py")))
    assert planning_modules

    forbidden: list[tuple[str, str]] = []
    for path in planning_modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_names: tuple[str, ...]
            if isinstance(node, ast.Import):
                imported_names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_names = (node.module or "",)
            else:
                continue
            for imported in imported_names:
                if (
                    imported == "concord"
                    or imported.startswith("concord.")
                    or imported == "pds_concord"
                    or imported.startswith("pds_concord.")
                    or imported == "meridian.concord_adapter"
                    or imported.startswith("meridian.concord_adapter.")
                ):
                    forbidden.append((path.name, imported))

    assert forbidden == []
