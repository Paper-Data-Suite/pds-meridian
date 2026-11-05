"""#124 E2G3O8: check real installed wheel imports and registered entrypoints.

The source-tree suite skips this test. The E2G3O8 isolated runner turns it on
with PDS_ISSUE124_INSTALLED_TEST=1, using five built, non-editable wheels.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PDS_ISSUE124_INSTALLED_TEST") != "1",
    reason="Runs only in the E2G3O8 isolated five-wheel environment",
)

DISTRIBUTIONS = {
    "pds-core": "pds_core",
    "scoreform": "scoreform",
    "quillan": "quillan",
    "pds-concord": "concord",
    "pds-meridian": "meridian",
}


def _installation() -> tuple[Path, dict[str, str]]:
    prefix = Path(os.environ["PDS_ISSUE124_ISOLATED_PREFIX"]).resolve()
    expected = json.loads(os.environ["PDS_ISSUE124_VERSIONS_JSON"])
    assert isinstance(expected, dict)
    assert set(expected) == set(DISTRIBUTIONS)
    assert Path(sys.prefix).resolve() == prefix
    return prefix, expected


@pytest.mark.parametrize("distribution,module", sorted(DISTRIBUTIONS.items()))
def test_all_five_packages_import_from_isolated_wheels(
    distribution: str, module: str
) -> None:
    prefix, expected = _installation()
    installed = importlib.metadata.distribution(distribution)
    assert installed.version == expected[distribution]
    imported = importlib.import_module(module)
    origin = Path(imported.__file__).resolve()
    assert origin.is_relative_to(prefix)
    assert "site-packages" in origin.parts
    assert "Paper-Data-Suite" not in str(origin)


@pytest.mark.parametrize("name", ("scoreform", "quillan", "concord", "meridian"))
def test_installed_module_operations_entrypoint(name: str) -> None:
    _installation()
    matching = importlib.metadata.entry_points().select(
        group="paper_data_suite.module_operations", name=name
    )
    assert len(matching) == 1
    assert callable(next(iter(matching)).load())


@pytest.mark.parametrize("name", ("scoreform", "quillan", "concord"))
def test_producer_publication_entrypoint(name: str) -> None:
    _installation()
    matching = importlib.metadata.entry_points().select(
        group="paper_data_suite.publication_producers", name=name
    )
    assert len(matching) == 1
    assert callable(next(iter(matching)).load())


def test_installed_meridian_has_correlated_teacher_setup() -> None:
    prefix, _ = _installation()
    module = importlib.import_module("meridian.menu_teacher_assessment_discovery")
    review = importlib.import_module("meridian.menu_teacher_assessment_setup_review")
    assert Path(module.__file__).resolve().is_relative_to(prefix)
    assert Path(review.__file__).resolve().is_relative_to(prefix)
    assert callable(module.run_teacher_assessment_discovery_menu)
    assert callable(review.review_correlated_assessment_setup_once)
