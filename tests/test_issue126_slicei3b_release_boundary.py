"""#126 I3B: installed evidence truth and measured synthetic teacher interaction.

No release wheel or Suite composition is created/claimed. The one synthetic
classroom run reuses the accepted real #122 receipt and canonical #30 adapter.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pds_core.routes import module_work_dir
from test_issue126_slicei1_native_scoreform_29x6 import FIRST, RETAKE, WORK, _read
from test_issue126_slicei2a_native_correction_current import GRADE_ITEM
from test_issue126_slicei2b_native_teacher_receipt_menu import (
    _current,
    _history,
    _receipt_store,
    _run,
    _world,
)

from meridian.assessment_attempt_inventory import project_assessment_attempt_inventory
from meridian.menu_teacher_verified_continuation import (
    VerifiedContinuationPorts,
    verify_student_current_use,
)
from scripts.issue126_i3b_release_evidence import (
    ReleaseEvidenceError,
    classify_meridian_origin,
    collect_evidence,
    editable_direct_url,
    release_claims,
)


def test_installed_release_inventory_preserves_source_checkout_truth() -> None:
    report = collect_evidence(Path(__file__).resolve().parents[1])
    assert report["schema_version"] == 1
    assert report["meridian"]["source_origin"] == "source_checkout"
    assert report["meridian"]["official_wheel_attested"] is False
    assert report["synthetic_only"] is True
    assert set(report["installed"]) == {
        "pds-core",
        "scoreform",
        "quillan",
        "pds-concord",
    }
    for row in report["installed"].values():
        assert row["origin"] == "installed_distribution_owned_noneditable"
        assert len(row["reader_or_package_sha256"]) == 64
        assert row["hash_kind"] == "installed_module_file_not_original_wheel_archive"
    for claim in (
        "D3_official_meridian_wheel",
        "D4_full_suite_composition",
        "human_classroom",
        "physical_scoreform_scan",
        "A18_full_release_ci",
    ):
        assert report["evidence_levels"][claim] == "not_attested"


def test_installed_meridian_venv_is_not_mistaken_for_source_checkout(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "meridian_repo"
    src = repo / "meridian"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    site = repo / ".venv" / "Lib" / "site-packages" / "meridian"
    site.mkdir(parents=True)
    (site / "__init__.py").write_text("", encoding="utf-8")
    assert classify_meridian_origin(src / "__init__.py", repo) == "source_checkout"
    assert (
        classify_meridian_origin(site / "__init__.py", repo)
        == "other_origin_unqualified"
    )


@pytest.mark.parametrize(
    "raw",
    ['{"dir_info":{"editable":true}}', '{"dir_info":{"editable":false}}', None],
)
def test_editable_distribution_provenance_is_explicit(raw: str | None) -> None:
    assert editable_direct_url(raw) is (raw is not None and "true" in raw)


@pytest.mark.parametrize("raw", ["[1]", "not json", '{"dir_info":{"editable":"yes"}}'])
def test_malformed_origin_metadata_is_rejected(raw: str) -> None:
    with pytest.raises(ReleaseEvidenceError):
        editable_direct_url(raw)


def test_meridian_metadata_version_never_upgrades_to_release_attestation() -> None:
    # An installed distribution's *version label* alone is not a wheel hash,
    # a release origin, an official Core capability or a launcher test.
    levels = release_claims(meridian_origin="source_checkout")
    assert levels["D3_official_meridian_wheel"] == "not_attested"
    assert levels["D4_full_suite_composition"] == "not_attested"
    assert levels["D2_new_core_ui"] == "not_attested_by_core_0_6_6"
    assert levels["real_saved_teacher_profile"] == "not_attested"


def test_measured_scripted_29_student_teacher_correction_is_not_human_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scenario, inventory, row = _world(tmp_path)
    manifest = (
        module_work_dir(scenario.root, WORK)
        / "publications"
        / "academic_results"
        / "1.json"
    )
    before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert len(inventory.students) == 29
    assert _history(scenario) == ()
    assert _receipt_store(scenario).list_receipts() == ()
    output, input_counter = _run(
        monkeypatch,
        scenario,
        inventory,
        row,
        (
            "1",  # Teacher identifies original; never use score for inference.
            "1",  # Teacher explicitly chooses the corrected result.
            "Read paper and reviewed original scan; attempt 2 is a correction.",
            "1",  # One meaningful Save/Use academic confirmation.
            "",  # Read-only final-screen pause.
        ),
    )
    assert input_counter.requests == 5  # Scripted prompts, NOT real-teacher timing.
    for title in (
        "Original Attempt",
        "Corrected Attempt",
        "Teacher-Reviewed Correction Rationale",
        "Review and Use Correction Decision",
        "Correction Decision — Current Verified",
    ):
        assert title in output
    assert output.splitlines().count("1. Save and Use This Decision") == 1
    assert "teacher testimony, NOT producer-certified" in output
    assert (
        "No ScoreForm result, eligibility, Standard, Grade or report was changed"
        in output
    )
    current = _current(scenario)
    assert current is not None
    assert tuple(
        attempt.native.sequence for attempt in current.decision.selected_attempts
    ) == (2,)
    assert len(_history(scenario)) == 1
    (receipt,) = _receipt_store(scenario).list_receipts()
    assert receipt.preview.target.candidate_sha256 == current.decision_sha256
    assert receipt.checkpoints[-1].stage == "receipt_finalized"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == before
    refreshed = _read(scenario.root, scenario.publication_id)
    new_inventory = project_assessment_attempt_inventory(
        scenario.root, grade_item_id=GRADE_ITEM, prepared=refreshed
    )
    (affected,) = (s for s in new_inventory.students if s.student_id == FIRST)
    assert affected.selection_status == "selected"
    assert tuple(
        a.attempt.native.sequence for a in affected.attempts if a.current_selected
    ) == (2,)
    (other,) = (s for s in new_inventory.students if s.student_id == RETAKE)
    assert not any(a.current_selected for a in other.attempts)
    verification = verify_student_current_use(
        scenario.root,
        scenario.prepared,
        new_inventory,
        affected,
        ports=VerifiedContinuationPorts(
            fresh_projection=lambda root, _work, publication_id: _read(
                root, publication_id
            )
        ),
    )
    assert verification.selected_attempt_count == 1
    assert set(verification.included_item_ids).isdisjoint(affected.attempts[0].item_ids)
    print("I3B SYNTHETIC COUNTS: 29 students; 5 input responses; 1 Save/Use;")
    print("I3B SYNTHETIC COUNTS: 1 #30 selection; 1 #122 receipt; no human timing")
