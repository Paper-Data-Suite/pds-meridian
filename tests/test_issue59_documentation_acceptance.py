from pathlib import Path

DOC = Path("docs/architecture/suite-operations-integration.md")


def test_issue59_architecture_document_records_operations_boundaries() -> None:
    text = DOC.read_text(encoding="utf-8")

    for token in (
        "Suite orchestration != Meridian policy ownership",
        "paper_data_suite.module_operations",
        "meridian.pds_operations:get_module_operations_profile",
        "readiness_provider",
        "attention_provider",
        "meridian_readiness_unavailable",
        "meridian_workspace_not_ready",
        "meridian_class_not_ready",
        "open_new_evidence",
        "open_grade_items",
        "open_attempt_decisions",
        "open_exclusions",
        "open_standards_review",
        "open_calculation_preview",
        "open_preview_grades",
        "open_snapshots",
        "open_create_planning_signal",
        "Meridian defines no Suite-specific doctor API.",
        "meridian = meridian.cli:main",
        "module-specific backup provider",
        "Teacher-selected external report files are not canonical "
        "Meridian backup state.",
        "pds-core>=0.6.3,<0.7",
        "Core 0.6.4",
        "ScoreForm, Quillan, Concord, Portia, Vitrine, and Paper Data Suite",
        "Issue #59 Suite operations integration — implemented and qualified.",
    ):
        assert token in text


def test_issue59_active_docs_changelog_and_release_guards_link_contract() -> None:
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    docs_index = Path("docs/README.md").read_text(encoding="utf-8")
    readme = Path("README").read_text(encoding="utf-8")
    documentation_checker = Path("scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    filename = "suite-operations-integration.md"
    document = f"docs/architecture/{filename}"

    assert (
        "Issue #59 integrates Meridian with Paper Data Suite operations"
        in changelog
    )
    assert filename in docs_index
    assert "Suite operations integration" in readme
    assert document in documentation_checker
    assert document in sdist_checker
    assert "tests/test_issue59_documentation_acceptance.py" in sdist_checker


def test_issue59_final_repository_qualification_reaches_installed_core_smoke() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    runner = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )
    core_programs = Path(
        "scripts/installed_qualification_core_programs.py"
    ).read_text(encoding="utf-8")
    installed_smoke = Path(
        "scripts/smoke_program_issue59_operations.py"
    ).read_text(encoding="utf-8")

    assert "scripts.installed_qualification_runner" in validator
    assert "run_core_program_smokes" in runner
    assert "ISSUE59_OPERATIONS_PROGRAM" in core_programs
    assert "issue59-operations" in core_programs
    assert 'metadata.version("pds-core") != "0.6.4"' in installed_smoke
    assert "paper_data_suite" in installed_smoke
    assert "meridian.cli:main" in installed_smoke
