from __future__ import annotations

from pathlib import Path

from scripts.installed_qualification_matrix import (
    DEPENDENCY_MATRICES,
    TARGET_SHARED_ENVIRONMENT_COUNT,
    DependencyMatrixId,
)


def test_issue60_preserves_exact_six_matrix_topology() -> None:
    assert TARGET_SHARED_ENVIRONMENT_COUNT == 6
    assert len(DEPENDENCY_MATRICES) == 6
    assert tuple(matrix.matrix_id for matrix in DEPENDENCY_MATRICES) == (
        DependencyMatrixId.CORE,
        DependencyMatrixId.SCOREFORM,
        DependencyMatrixId.QUILLAN,
        DependencyMatrixId.CONCORD,
        DependencyMatrixId.SCOREFORM_QUILLAN,
        DependencyMatrixId.ALL_ADAPTERS,
    )


def test_issue60_installed_smoke_is_wired_only_into_all_adapters() -> None:
    runner = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )
    assert "run_issue60_cross_policy_prepared_smoke" in runner
    assert '"issue60-cross-policy-adversarial"' in runner
    all_adapters = runner.index(
        "matrix_for(DependencyMatrixId.ALL_ADAPTERS)"
    )
    issue60 = runner.index('"issue60-cross-policy-adversarial"')
    assert issue60 > all_adapters
    assert runner.count('"issue60-cross-policy-adversarial"') == 2


def test_issue60_wrapper_reuses_prepared_environment_and_fresh_process() -> None:
    wrapper = Path(
        "scripts/smoke_test_cross_policy_adversarial_wheel.py"
    ).read_text(encoding="utf-8")
    for token in (
        "run_prepared_smoke",
        '"pip", "check"',
        '"PYTHONPATH"',
        '"PYTHONNOUSERSITE": "1"',
        "PROGRAM",
        "RELOAD_PROGRAM",
        "scoreform_wheel",
        "quillan_wheel",
        "concord_wheel",
    ):
        assert token in wrapper
    assert '"--no-index"' not in wrapper
    assert '"--no-deps"' not in wrapper


def test_issue60_installed_program_covers_cross_policy_authorities() -> None:
    program = Path(
        "scripts/smoke_program_cross_policy_adversarial.py"
    ).read_text(encoding="utf-8")
    for token in (
        '"pds-core": "0.6.4"',
        '"scoreform": "0.11.0"',
        '"quillan": "0.10.3"',
        '"pds-concord": "0.3.0"',
        "issue54._conventional_state",
        "issue54._standards_state",
        "profile99._calculate",
        "profile_state = _profile_state(profile_workspace)",
        "weighted_target = issue54._standards_state(weighted_workspace)",
        "issue54._hybrid_state",
        "preview_teacher_grade_override_withdrawal",
        "Writing Issue #60 withdrawal silently changed override selection.",
        "freeze_reporting_snapshot",
        "ConcordAcademicResultAdapter",
        'target_kind="concord_group"',
        "cache_projected_inventory",
        "group.subject is None",
    ):
        assert token in program


def test_issue60_fresh_reload_reopens_exact_persisted_state_read_only() -> None:
    reload_program = Path(
        "scripts/smoke_program_cross_policy_adversarial_reload.py"
    ).read_text(encoding="utf-8")
    for token in (
        "load_current_conventional_grade_result",
        "calculate_conventional_grade",
        "load_current_standards_grade_result",
        '"weighted_mean"',
        '"profile_constrained_mean"',
        'Decimal("90")',
        'Decimal("95.00")',
        "calculate_standards_grade",
        "load_current_hybrid_grade_result",
        "calculate_hybrid_grade",
        "load_current_teacher_grade_override",
        'selected_override.decision.decision == "withdraw"',
        "load_teacher_grade_override_revision",
        "load_reporting_snapshot",
        "hashlib.sha256(snapshot.content).hexdigest()",
        "load_authorized_projection_snapshot",
        'item.target.target_kind != "concord_group"',
        "Known Concord group item leaked into student-scoped cache.",
        "after == before",
    ):
        assert token in reload_program


def test_issue60_assets_are_guarded_by_sdist_validation() -> None:
    checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        "scripts/smoke_program_cross_policy_adversarial.py",
        "scripts/smoke_program_cross_policy_adversarial_reload.py",
        "scripts/smoke_test_cross_policy_adversarial_wheel.py",
        "tests/test_issue60_installed_acceptance.py",
    ):
        assert member in checker
