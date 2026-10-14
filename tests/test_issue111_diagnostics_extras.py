from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement

from meridian.diagnostics import DIAGNOSTIC_OUTPUT_VERSION
from scripts.check_package import (
    EXPECTED_CONCORD_EXTRA,
    EXPECTED_QUILLAN_EXTRA,
    EXPECTED_SCOREFORM_EXTRA,
)

ROOT = Path(__file__).resolve().parents[1]


def test_slice5_optional_extras_are_contract_advertising_floors() -> None:
    with (ROOT / "pyproject.toml").open("rb") as source:
        optional = tomllib.load(source)["project"]["optional-dependencies"]

    assert optional["scoreform"] == ["scoreform>=0.13.0"]
    assert optional["quillan"] == ["quillan>=0.10.6"]
    assert optional["concord"] == ["pds-concord>=0.3.2"]

    assert EXPECTED_SCOREFORM_EXTRA == Requirement(
        "scoreform>=0.13.0; extra == 'scoreform'"
    )
    assert EXPECTED_QUILLAN_EXTRA == Requirement(
        "quillan>=0.10.6; extra == 'quillan'"
    )
    assert EXPECTED_CONCORD_EXTRA == Requirement(
        "pds-concord>=0.3.2; extra == 'concord'"
    )


def test_slice5_diagnostics_schema_is_v2() -> None:
    assert DIAGNOSTIC_OUTPUT_VERSION == "2"


def test_slice5_current_matrix_names_contract_and_legacy_boundaries() -> None:
    text = (
        ROOT / "docs/architecture/current-reader-compatibility.md"
    ).read_text(encoding="utf-8")

    for token in (
        "scoreform>=0.13.0",
        "quillan>=0.10.6",
        "pds-concord>=0.3.2",
        "scoreform_academic_result_reader_v1",
        "quillan_academic_result_reader_v1",
        "concord_academic_result_reader_v1",
        "`0.12.1`",
        "`0.10.5`",
        "`0.3.0`",
        "Exact release artifacts prove what Meridian tested.",
        "Reader contracts",
        "determine what Meridian may consume.",
    ):
        assert token in text
