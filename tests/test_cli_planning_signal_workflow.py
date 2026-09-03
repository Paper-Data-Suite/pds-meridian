from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "class_2026"
POLICY_ID = "reading_groups"


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "create-planning-signal",
        CLASS_ID,
        POLICY_ID,
        "--workspace",
        "synthetic-workspace",
        *extra,
    )


def _policy() -> object:
    return SimpleNamespace(
        reference=SimpleNamespace(
            class_id=CLASS_ID,
            policy_id=POLICY_ID,
            policy_revision=2,
            policy_sha256="a" * 64,
        ),
        title="Reading support bands",
        target_period=SimpleNamespace(
            period=SimpleNamespace(
                school_year="2026-2027",
                period_id="mp1",
            ),
            calendar_revision=4,
        ),
        standard_id="NJSLSA.R1",
        source_policy_reference=SimpleNamespace(
            class_id=CLASS_ID,
            policy_id="period_proficiency",
            policy_revision=3,
            policy_sha256="b" * 64,
        ),
        target_scale_reference=SimpleNamespace(
            class_id=CLASS_ID,
            scale_id="four_level",
            scale_revision=2,
            scale_sha256="c" * 64,
        ),
        dimension_id="reading_support",
        band_count=3,
        band_definitions=(
            SimpleNamespace(
                band=1,
                minimum_scale_position=1,
                maximum_scale_position=1,
            ),
            SimpleNamespace(
                band=2,
                minimum_scale_position=2,
                maximum_scale_position=3,
            ),
            SimpleNamespace(
                band=3,
                minimum_scale_position=4,
                maximum_scale_position=4,
            ),
        ),
        tie_handling="same_level_same_band",
        missing_result_handling="noncontributing",
        insufficient_result_handling="blocking",
        actor_kind="teacher",
        actor_id="teacher_42",
        rationale="Instructional planning only.",
        revised_at=SimpleNamespace(isoformat=lambda: "2026-09-03T03:00:00+00:00"),
    )


def _generated_projection() -> object:
    return SimpleNamespace(
        class_id=CLASS_ID,
        policy_id=POLICY_ID,
        policy=_policy(),
        generation=SimpleNamespace(
            status="generated",
            blockers=(),
            snapshot=SimpleNamespace(),
        ),
        generation_status="generated",
        blocker_codes=(),
        ready_for_derivation_persistence=True,
        candidate_derivation_id="gsd_" + "d" * 64,
        candidate_calculation_fingerprint="e" * 64,
        roster_student_count=24,
        contributing_student_count=21,
        noncontributing_student_count=3,
        derivation_write_action="not_performed",
        preview_write_action="not_performed",
        review_write_action="not_performed",
        review_selection_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )


def _blocked_projection() -> object:
    source = SimpleNamespace(
        class_id=CLASS_ID,
        school_year="2026-2027",
        period_id="mp1",
        student_id="student_001",
        standard_id="NJSLSA.R1",
        result_revision=3,
        result_sha256="f" * 64,
    )
    return SimpleNamespace(
        class_id=CLASS_ID,
        policy_id=POLICY_ID,
        policy=_policy(),
        generation=SimpleNamespace(
            status="blocked",
            blockers=(
                SimpleNamespace(
                    code="stale_result",
                    student_id="student_001",
                    source_result=source,
                    freshness_reasons=("inputs_changed",),
                ),
            ),
            snapshot=None,
        ),
        generation_status="blocked",
        blocker_codes=("stale_result",),
        ready_for_derivation_persistence=False,
        candidate_derivation_id=None,
        candidate_calculation_fingerprint=None,
        roster_student_count=None,
        contributing_student_count=None,
        noncontributing_student_count=None,
        derivation_write_action="not_performed",
        preview_write_action="not_performed",
        review_write_action="not_performed",
        review_selection_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )


def test_workflow_help_exposes_create_planning_signal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "create-planning-signal" in output
    assert (
        "Review planning-signal readiness from selected Academic "
        "Period proficiency" in output
    )


def test_generated_readiness_is_rendered_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def project(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _generated_projection()

    monkeypatch.setattr(cli, "project_planning_signal_readiness", project)
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_derivation_persistence",
        lambda readiness: SimpleNamespace(
            derivation_id=readiness.candidate_derivation_id,
            calculation_fingerprint=(
                readiness.candidate_calculation_fingerprint
            ),
            roster_student_count=readiness.roster_student_count,
            contributing_student_count=(
                readiness.contributing_student_count
            ),
            noncontributing_student_count=(
                readiness.noncontributing_student_count
            ),
        ),
    )
    monkeypatch.setattr(
        cli,
        "commit_planning_signal_derivation_persistence_preview",
        lambda *args, **kwargs: pytest.fail(
            "read-only readiness must not persist #38"
        ),
    )

    assert cli.main(_arguments()) == 0
    output = capsys.readouterr().out

    assert observed == [
        (("synthetic-workspace", CLASS_ID, POLICY_ID), {})
    ]
    assert "Create Planning Signal — readiness" in output
    assert "selected #37 policy: reading_groups@2" in output
    assert "Academic Period: 2026-2027/mp1 @ calendar revision 4" in output
    assert "Standard: NJSLSA.R1" in output
    assert "generation readiness: ready" in output
    assert "candidate derivation ID: gsd_" in output
    assert "roster students: 24" in output
    assert "contributing students: 21" in output
    assert "noncontributing students: 3" in output
    assert "NO #38 DERIVATION PERSISTED" in output
    assert "NO #39 PREVIEW OR REVIEW WRITTEN" in output
    assert "NO CORE GROUPING SIGNAL OR CSV EXPORTED" in output
    assert "NO CONCORD GROUP OR GROUPPLAN CREATED" in output


def test_blockers_are_rendered_with_exact_provenance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: _blocked_projection(),
    )

    assert cli.main(_arguments()) == 0
    output = capsys.readouterr().out

    assert "generation readiness: blocked" in output
    assert "stale_result | student=student_001" in output
    assert "result=3@" in output
    assert "freshness=inputs_changed" in output
    assert "NO #38 DERIVATION PERSISTED" in output


def test_json_output_preserves_all_write_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projection = _generated_projection()
    monkeypatch.setattr(
        cli,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: projection,
    )
    monkeypatch.setattr(
        cli,
        "preview_planning_signal_derivation_persistence",
        lambda readiness: SimpleNamespace(
            derivation_id=readiness.candidate_derivation_id,
            calculation_fingerprint=(
                readiness.candidate_calculation_fingerprint
            ),
            roster_student_count=readiness.roster_student_count,
            contributing_student_count=(
                readiness.contributing_student_count
            ),
            noncontributing_student_count=(
                readiness.noncontributing_student_count
            ),
        ),
    )

    assert cli.main(_arguments("--format", "json")) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["task"] == "create-planning-signal"
    assert data["class_id"] == CLASS_ID
    assert data["policy"]["policy_id"] == POLICY_ID
    assert data["policy"]["policy_revision"] == 2
    assert data["academic_basis"]["period_id"] == "mp1"
    assert data["academic_basis"]["standard_id"] == "NJSLSA.R1"
    assert data["generation"]["status"] == "generated"
    assert data["generation"]["ready_for_derivation_persistence"] is True
    assert data["generation"]["roster_student_count"] == 24
    assert data["actions"]["derivation_write"] == "not_performed"
    assert data["actions"]["preview_write"] == "not_performed"
    assert data["actions"]["review_write"] == "not_performed"
    assert data["actions"]["review_selection"] == "not_performed"
    assert data["actions"]["core_export"] == "not_performed"
    assert data["actions"]["csv_export"] == "not_performed"
    assert data["concord_action"] == "not_performed"


def test_missing_selected_policy_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projection = _blocked_projection()
    projection.policy = None
    projection.generation.blockers = (
        SimpleNamespace(
            code="no_selected_policy",
            student_id=None,
            source_result=None,
            freshness_reasons=(),
        ),
    )
    projection.blocker_codes = ("no_selected_policy",)
    monkeypatch.setattr(
        cli,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: projection,
    )

    assert cli.main(_arguments()) == 0
    output = capsys.readouterr().out

    assert "selected #37 policy: none" in output
    assert "no_selected_policy" in output
    assert "generation readiness: blocked" in output
