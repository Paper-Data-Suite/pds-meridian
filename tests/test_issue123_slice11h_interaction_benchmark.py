"""#123 Slice 11H: measured, equivalent legacy/named read-only controllers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.issue123_interaction_benchmark import (
    REPORT_SCHEMA,
    benchmark,
    main,
    one_workload,
)


def test_pair_observes_same_domain_records_and_scope_without_raw_inputs(
    tmp_path: Path,
) -> None:
    old = one_workload("legacy", tmp_path)
    new = one_workload("named", tmp_path)
    assert (
        old["completed_domain_reads"]
        == new["completed_domain_reads"]
        == {
            "grade_item_review": 2,
            "proficiency_explanation": 2,
        }
    )
    assert old["inputs"] == 16
    assert new["inputs"] == 13
    assert old["technical_id_prompts"] == 12
    assert new["technical_id_prompts"] == 0
    assert old["repeated_class_id_prompts"] == 3
    assert new["repeated_class_id_prompts"] == 0
    assert old["catalog_reads_total"] == 0
    assert new["catalog_reads_by_scope"]["class"] == 3
    assert new["catalog_reads_by_scope"]["student"] >= 4
    assert new["catalog_reads_by_scope"]["standard"] >= 4
    assert new["elapsed_ns"] > 0 and old["elapsed_ns"] > 0


def test_benchmark_reports_observed_counts_and_local_timings(tmp_path: Path) -> None:
    report = benchmark(repeats=3, warmups=1, pairs=2)
    assert report["schema"] == REPORT_SCHEMA
    assert report["measured_samples_per_mode"] == 3
    assert report["delta"]["inputs_named_minus_legacy"] == -3
    assert report["observed"]["named"]["technical_id_prompts"] == 0
    for mode in ("legacy", "named"):
        values = report["observed"][mode]
        assert 0 < values["latency_min_ns"] <= values["latency_median_ns"]
        assert values["latency_median_ns"] <= values["latency_max_ns"]
        assert (
            values["latency_min_ns"]
            <= values["latency_p95_ns"]
            <= values["latency_max_ns"]
        )
        assert values["completed_domain_reads"] == {
            "grade_item_review": 2,
            "proficiency_explanation": 2,
        }
    assert "synthetic" in report["scope"]
    assert "not installed-wheel" in report["scope"]
    assert not list(tmp_path.iterdir())  # no academic records or cache writes


def test_cli_writes_only_requested_synthetic_measurement_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "controller-metrics.json"
    assert (
        main(
            [
                "--repeats",
                "1",
                "--pairs",
                "1",
                "--warmups",
                "0",
                "--output",
                str(destination),
            ]
        )
        == 0
    )
    report = json.loads(destination.read_text(encoding="utf-8"))
    assert json.loads(capsys.readouterr().out) == report
    assert report["paired_repetitions_per_sample"] == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "controller-metrics.json"
    ]


@pytest.mark.parametrize(
    "options",
    [
        {"repeats": 0},
        {"repeats": 102},
        {"pairs": 0},
        {"pairs": 11},
        {"warmups": -1},
        {"warmups": 21},
    ],
)
def test_benchmark_fails_closed_on_unbounded_measurement(
    options: dict[str, int],
) -> None:
    with pytest.raises(ValueError, match="exceed safe bounds"):
        benchmark(**options)


def test_unknown_controller_mode_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported workload"):
        one_workload("fake", tmp_path)
