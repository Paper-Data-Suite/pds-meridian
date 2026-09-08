from __future__ import annotations

from pathlib import Path

WRAPPER = Path("scripts/smoke_test_proficiency_signal_export_wheel.py")
PROGRAM = Path("scripts/smoke_program_proficiency_signal_export.py")


def test_issue45_wrapper_uses_four_pds_wheels_without_concord() -> None:
    wrapper = WRAPPER.read_text(encoding="utf-8")

    for required in (
        "meridian_wheel",
        "core_wheel",
        "scoreform_wheel",
        "quillan_wheel",
        '"PYTHONNOUSERSITE": "1"',
        '"PYTHONDONTWRITEBYTECODE": "1"',
        '"PYTHONPATH"',
        '"PYTHONHOME"',
        '"PYTHONSTARTUP"',
        '"CONCORD_WHEEL"',
        '"pip",',
        '"install",',
        '"check"',
        "smoke_program_proficiency_signal_export.py",
    ):
        assert required in wrapper

    assert "concord_wheel" not in wrapper
    assert '"--no-index"' not in wrapper
    assert '"--no-deps"' not in wrapper
    assert "system_site_packages=True" not in wrapper


def test_issue45_program_proves_physical_concord_absence() -> None:
    program = PROGRAM.read_text(encoding="utf-8")

    for required in (
        'metadata.version("pds-concord")',
        'importlib.util.find_spec("concord") is None',
        'name.split(".", 1)[0] == "concord"',
        '"CONCORD_WHEEL" not in',
        "_assert_no_concord()",
    ):
        assert required in program

    assert "meridian.concord_adapter" not in program
    assert "concord." not in program


def test_issue45_program_uses_released_producer_lifecycles_and_real_adapters() -> None:
    program = PROGRAM.read_text(encoding="utf-8")

    for required in (
        "register_scoreform_academic_work",
        "generate_scoreform_manifest",
        "publish_scoreform_academic_results",
        "export_scoreform_result_models",
        "register_quillan_academic_work",
        "generate_quillan_manifest",
        "publish_quillan_academic_results",
        "set_overall_standard_rating",
        "mark_overall_ratings_complete",
        "PublicationProducerRegistry",
        "ScoreFormAcademicResultAdapter",
        "QuillanAcademicResultAdapter",
        "discover_publication_candidates",
        "prepare_publication_invocation",
        "cache_projected_inventory",
        "attempt_points",
        "overall_standard_rating",
        "NONCONTRIBUTOR_ID",
        "_assert_producer_immutability",
    ):
        assert required in program


def test_issue45_program_pins_released_versions_and_installed_origins() -> None:
    program = PROGRAM.read_text(encoding="utf-8")

    for required in (
        '"pds-core": "0.6.3"',
        '"scoreform": "0.11.0"',
        '"quillan": "0.10.0"',
        'metadata.version("pds-meridian")',
        '"site-packages"',
        'CLASS_ID = "synthetic_class_2026"',
        'STUDENT_ID = "student_synthetic_001"',
        'NONCONTRIBUTOR_ID = "student_synthetic_002"',
        'STANDARD_ID = "standard_ela_1"',
        '"standards_profile_id": PROFILE_ID',
    ):
        assert required in program


def test_issue45_program_persists_explicit_grade_item_attempt_and_standard_state(
) -> None:
    program = PROGRAM.read_text(encoding="utf-8")

    for required in (
        "GradeItemRevision",
        "GradeItemMembershipDecision",
        "write_grade_item_revision",
        "select_grade_item_revision",
        "write_grade_item_membership_revision",
        "select_grade_item_membership_revision",
        "EvidenceEligibilityDecision",
        "write_evidence_eligibility_revision",
        "select_evidence_eligibility_revision",
        "derive_attempt_candidates",
        "AttemptSelectionPolicy",
        "AttemptSelectionDecision",
        "ReassessmentPolicy",
        "ReassessmentDecision",
        'mode="replace"',
        "StandardEvidenceAssociationDecision",
        'basis="producer_declared"',
    ):
        assert required in program


def test_issue45_program_calculates_contributor_and_missing_noncontributor() -> None:
    program = PROGRAM.read_text(encoding="utf-8")

    for required in (
        "write_proficiency_scale_revision",
        "write_mapping_profile_revision",
        "ScalarMappingRule(False, \"beginning\")",
        "ScalarMappingRule(True, \"proficient\")",
        'ScaledLevelMappingRule(3, "proficient")',
        "resolve_standard_aggregation_inputs",
        "calculate_standard_proficiency",
        'contributor.status == "calculated"',
        'contributor.proficiency_level_id == "proficient"',
        'noncontributor.status == "insufficient_evidence"',
        "noncontributor.proficiency_level_id is None",
        '== ("no_performance_evidence",)',
        "reassessment_noncontributing",
    ):
        assert required in program


def test_issue45_cache_reload_replays_original_student_scope() -> None:
    program = PROGRAM.read_text(encoding="utf-8")

    scope = "requested_student_ids=(STUDENT_ID, NONCONTRIBUTOR_ID),"
    assert program.count(scope) >= 2


def test_issue45_program_persists_and_explains_grade_item_results() -> None:
    program = PROGRAM.read_text(encoding="utf-8")

    for required in (
        "write_standard_proficiency_policy_revision",
        "select_standard_proficiency_policy_revision",
        "create_standard_proficiency_result_snapshot",
        "write_standard_proficiency_result_revision",
        "select_standard_proficiency_result_revision",
        "load_current_standard_proficiency_result",
        "GradeItemProficiencyTraceTarget",
        "explain_grade_item_proficiency",
        'contributor_trace.selection_state == "selected_current"',
        'noncontributor_trace.calculation.status == "insufficient_evidence"',
        "nested.result_sha256 == grade_result.result_sha256",
    ):
        assert required in program


def test_issue45_program_calculates_and_explains_academic_period_proficiency() -> None:
    program = PROGRAM.read_text(encoding="utf-8")

    for required in (
        "AcademicPeriodProficiencyAggregationPolicy",
        "write_academic_period_proficiency_policy_revision",
        "select_academic_period_proficiency_policy_revision",
        "build_academic_period_proficiency_aggregation_inputs",
        "calculate_academic_period_proficiency",
        "create_academic_period_proficiency_result_snapshot",
        "write_academic_period_proficiency_result_revision",
        "select_academic_period_proficiency_result_revision",
        "load_current_academic_period_proficiency_result",
        "AcademicPeriodProficiencyTraceTarget",
        "explain_academic_period_proficiency",
        'inputs.entries[0].status == "insufficient_evidence"',
        "outcome.insufficient_result_count == 1",
        'trace.selection_state == "selected_current"',
        "trace.grade_items[0].nested_grade_item_explanation is not None",
    ):
        assert required in program


def test_issue45_program_derives_reviews_and_exports_privacy_minimal_core_signal(
) -> None:
    program = PROGRAM.read_text(encoding="utf-8")

    for required in (
        "GroupingSignalDerivationPolicy",
        "write_grouping_signal_policy_revision",
        "select_grouping_signal_policy_revision",
        'dimension_id="ela_planning"',
        'missing_result_handling="noncontributing"',
        'insufficient_result_handling="noncontributing"',
        "generate_grouping_signal_derivation",
        'noncontributor.disposition == "noncontributing"',
        "generate_grouping_signal_preview",
        'decision="accepted_for_export"',
        "acknowledged_warning_ids=warning_ids",
        "select_grouping_signal_review_revision",
        "build_grouping_signal_teacher_projection",
        "export_grouping_signal",
        "load_grouping_signal_export_receipt",
        "grouping_signal_set_from_json",
        "grouping_signal_set_to_json_bytes",
        "hashlib.sha256(canonical).hexdigest()",
        "export_grouping_signal_csv",
        "parse_grouping_signal_csv",
        "grouping_signal_csv_to_signal_set",
        'document.representation_scope == "complete_signal"',
        '== "existing"',
        "Core signal leaked Meridian-private academic/proficiency provenance.",
    ):
        assert required in program

    assert 'signal.student_bands[0].student_id == STUDENT_ID' in program
    assert 'item.student_id != NONCONTRIBUTOR_ID' in program


def test_issue45_wrapper_runs_fresh_process_reload() -> None:
    wrapper = WRAPPER.read_text(encoding="utf-8")

    assert "smoke_program_proficiency_signal_export_reload.py" in wrapper
    assert "RELOAD_PROGRAM.resolve()" in wrapper
    assert wrapper.index("PROGRAM.resolve()") < wrapper.index(
        "RELOAD_PROGRAM.resolve()"
    )


def test_issue45_fresh_process_reload_verifies_persisted_history() -> None:
    reload_program = Path(
        "scripts/smoke_program_proficiency_signal_export_reload.py"
    ).read_text(encoding="utf-8")
    program = PROGRAM.read_text(encoding="utf-8")

    for required in (
        "issue45-reload-baseline.json",
        "publication_record_to_dict",
        '"cache_key": cached.cache_key',
        '"snapshot_digest": cached.snapshot_digest',
        '"csv_sha256"',
        "_write_reload_baseline(root, baselines, projected)",
    ):
        assert required in program

    for required in (
        "load_publication_record",
        "verify_publication_manifest",
        "load_authorized_projection_snapshot",
        'requested_student_ids=(STUDENT_ID, NONCONTRIBUTOR_ID)',
        'authorized.assessment.reuse_status == "reusable"',
        "GradeItemProficiencyTraceTarget",
        "AcademicPeriodProficiencyTraceTarget",
        "PlanningSignalExportTraceTarget",
        "PlanningSignalPreviewReviewTraceTarget",
        'path_state == "selected_and_export_eligible"',
        "grouping_signal_set_from_json",
        "parse_grouping_signal_csv",
        "grouping_signal_csv_to_signal_set",
        'metadata.version("pds-concord")',
        'importlib.util.find_spec("concord") is None',
        "producer-owned bytes changed after full workflow",
    ):
        assert required in reload_program
