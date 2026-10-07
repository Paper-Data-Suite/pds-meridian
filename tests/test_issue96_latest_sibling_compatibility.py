from __future__ import annotations

from pathlib import Path

from meridian.quillan_adapter import QUILLAN_READER_VERSION
from scripts.check_package import EXPECTED_QUILLAN_EXTRA
from scripts.verify_quillan_wheel import (
    EXPECTED_QUILLAN_VERSION,
    EXPECTED_QUILLAN_WHEEL_FILENAME,
    EXPECTED_QUILLAN_WHEEL_SHA256,
)


def test_issue96_latest_stable_quillan_identity_is_exact() -> None:
    assert QUILLAN_READER_VERSION == "0.10.5"
    assert EXPECTED_QUILLAN_VERSION == "0.10.5"
    assert EXPECTED_QUILLAN_WHEEL_FILENAME == "quillan-0.10.5-py3-none-any.whl"
    assert EXPECTED_QUILLAN_WHEEL_SHA256 == (
        "031e5a5455c222da6b9a7d8f72e7823dd4c61acde7d90ddce94b49d9bcbe123f"
    )
    assert str(EXPECTED_QUILLAN_EXTRA) == (
        'quillan==0.10.5; extra == "quillan"'
    )


def test_issue96_ci_uses_authenticated_quillan_0105_release() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "quillan-0.10.5-py3-none-any.whl" in workflow
    assert "pds-quillan/releases/download/v0.10.5/" in workflow
    assert "quillan-0.10.3-py3-none-any.whl" not in workflow


def test_issue96_documentation_preserves_0103_qualification_history() -> None:
    adapter = Path("docs/architecture/quillan-adapter.md").read_text(
        encoding="utf-8"
    )
    matrix = Path("docs/development/installed-qualification-matrix.md").read_text(
        encoding="utf-8"
    )

    assert "# Quillan v0.10.3 adapter" in adapter
    assert "356ab008c3a80e74b30cade4254ae4c05e07c205" in adapter
    assert "v0.10.2 -> v0.10.3" in adapter
    assert "Quillan | `0.10.3`" in matrix
    assert "2026-09-26" in matrix


def test_issue96_cross_producer_test_authority_tracks_quillan_0105() -> None:
    support = Path("tests/cross_producer_test_support.py").read_text(
        encoding="utf-8"
    )
    native = Path("tests/cross_producer_native_states_support.py").read_text(
        encoding="utf-8"
    )
    issue51 = Path("tests/test_issue51_installed_acceptance.py").read_text(
        encoding="utf-8"
    )
    issue52 = Path("tests/test_issue52_installed_acceptance.py").read_text(
        encoding="utf-8"
    )

    assert '"quillan": "0.10.5"' in support
    assert 'lambda _: "0.10.5"' in native
    assert 'metadata.version("quillan") == "0.10.5"' in issue51
    assert 'metadata.version("quillan") == "0.10.5"' in issue52


def test_issue96_package_metadata_test_tracks_quillan_0105() -> None:
    package_test = Path("tests/test_package_metadata.py").read_text(
        encoding="utf-8"
    )

    assert 'quillan==0.10.5; extra == \'quillan\'' in package_test
    assert 'quillan==0.10.3; extra == \'quillan\'' not in package_test
