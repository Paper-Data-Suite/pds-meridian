from __future__ import annotations

from pathlib import Path


def test_issue54_installed_wrapper_uses_all_exact_released_dependencies() -> None:
    wrapper = Path("scripts/smoke_test_grade_report_preview_wheel.py").read_text(
        encoding="utf-8"
    )
    for token in (
        '"PYTHONPATH"',
        '"PYTHONNOUSERSITE": "1"',
        '"pip", "check"',
        "scoreform_wheel",
        "quillan_wheel",
        "concord_wheel",
        "PROGRAM",
        "RELOAD_PROGRAM",
    ):
        assert token in wrapper


def test_issue54_installed_program_covers_all_preview_surfaces() -> None:
    program = Path("scripts/smoke_program_grade_report_preview.py").read_text(
        encoding="utf-8"
    )
    for token in (
        'metadata.version("pds-core")',
        '"pds-concord": "0.3.0"',
        "meridian.grade_preview_explanation",
        "meridian.current_grade_preview",
        "meridian.grade_preview_comparison",
        "meridian.grade_report_preview",
        "explain_current_grade_preview",
        "conventional_grade_observation",
        "standards_grade_observation",
        "hybrid_grade_observation",
        'REPLACEMENT_GRADE = Decimal("105.25")',
        "explain_grade_report_preview",
        "compare_grade_preview_basis",
        "Issue #54 preview mutated academic workspace state.",
        "grade_preview_observation_to_json_bytes",
    ):
        assert token in program


def test_issue54_standards_smoke_uses_provenance_complete_v02_state() -> None:
    program = Path("scripts/smoke_program_grade_report_preview.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "smoke_program_proficiency_signal_export as issue45",
        "issue45._calculate_grade_item_proficiency",
        "issue45._calculate_academic_period_proficiency",
        "issue51.select_proficiency_scale_revision",
        'assembly.outcome.rounded_grade == Decimal("90.00")',
        '"standards_target": {',
    ):
        assert token in program
    standards_call = "standards_target = _standards_state(standards_workspace)"
    hybrid_call = (
        "hybrid_producer, hybrid_evidence, hybrid_descriptor = _hybrid_state("
    )
    assert standards_call in program
    assert hybrid_call in program
    assert program.index(standards_call) < program.index(hybrid_call)



def test_issue54_hybrid_smoke_uses_provenance_complete_v02_state() -> None:
    program = Path("scripts/smoke_program_grade_report_preview.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "_align_issue45_hybrid_scope",
        "issue45._project_and_cache",
        "issue50._configure",
        "issue45._calculate_grade_item_proficiency",
        "issue45._calculate_academic_period_proficiency",
        "issue52.assemble_hybrid_grade_calculation",
        'assembly.standards_based.outcome.rounded_grade == Decimal("90.00")',
        'assembly.outcome.rounded_grade == Decimal("96.00")',
        '"authorization_profile": "issue45"',
        '"requested_student_ids": [',
    ):
        assert token in program


def test_issue54_fresh_process_reopens_authorized_evidence_without_writes() -> None:
    reload_program = Path(
        "scripts/smoke_program_grade_report_preview_reload.py"
    ).read_text(encoding="utf-8")
    for token in (
        "load_authorized_projection_snapshot",
        "ConventionalGradeWorkEvidenceSpec",
        "ModuleWorkRef",
        "explain_current_grade_preview",
        "Fresh-process GradePreviewObservation changed.",
        "Fresh-process report preview changed.",
        "Fresh-process comparison changed.",
        "Fresh-process issue #54 preview wrote workspace state.",
        'baseline.get("standards_target")',
        "AcademicPeriodRef",
        "authorization_profile",
        "requested_student_ids",
        "issue45.AllowInstalledProjection",
        "issue45._producer_registry",
        "issue45._adapter_registry",
    ):
        assert token in reload_program
    assert "cache_projected_inventory" not in reload_program
    assert "publish_scoreform_academic_results" not in reload_program
