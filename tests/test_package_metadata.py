from __future__ import annotations

import importlib.metadata

from packaging.requirements import Requirement


def test_distribution_metadata() -> None:
    distribution = importlib.metadata.distribution("pds-meridian")
    metadata = distribution.metadata
    assert metadata["Name"] == "pds-meridian"
    assert metadata["Version"] == "0.1.1"
    assert metadata["Summary"] == (
        "Publication ingestion and typed evidence diagnostics for Paper Data Suite"
    )
    assert metadata["Requires-Python"] == ">=3.11"
    assert metadata["Description-Content-Type"] == "text/markdown"
    assert metadata["License-Expression"] == "MIT"

    requirements = [
        Requirement(value) for value in (metadata.get_all("Requires-Dist") or [])
    ]
    runtime = [item for item in requirements if item.marker is None]
    assert runtime == [Requirement("pds-core>=0.6.3,<0.7")]
    assert all(
        item.name not in {"scoreform", "quillan", "pds-concord", "pds-portia"}
        for item in runtime
    )
    scoreform = [item for item in requirements if item.name == "scoreform"]
    assert scoreform == [Requirement("scoreform==0.11.0; extra == 'scoreform'")]
    quillan = [item for item in requirements if item.name == "quillan"]
    assert quillan == [Requirement("quillan==0.10.0; extra == 'quillan'")]
    concord = [item for item in requirements if item.name == "pds-concord"]
    assert concord == [
        Requirement("pds-concord==0.2.0; extra == 'concord'")
    ]


def test_console_and_plugin_entry_points() -> None:
    distribution = importlib.metadata.distribution("pds-meridian")
    entry_points = tuple(distribution.entry_points)
    console = [
        item
        for item in entry_points
        if item.group == "console_scripts" and item.name == "meridian"
    ]
    assert len(console) == 1
    assert console[0].value == "meridian.cli:main"
    assert not [
        item
        for item in entry_points
        if item.group
        in {
            "paper_data_suite.modules",
            "paper_data_suite.publication_producers",
        }
        or "adapter" in item.group.lower()
    ]
