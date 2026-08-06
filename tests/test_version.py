from __future__ import annotations

import importlib.metadata

import meridian
from meridian._version import __version__


def test_version_has_one_authoritative_value() -> None:
    assert __version__ == "0.1.1.dev0"
    assert meridian.__version__ is __version__


def test_imported_and_distribution_versions_agree() -> None:
    assert importlib.metadata.version("pds-meridian") == meridian.__version__
