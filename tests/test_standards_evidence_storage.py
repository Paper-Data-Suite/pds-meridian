from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef
from pds_core.standards import StandardDefinition, StandardsLibrary

from meridian import standards_evidence_storage as storage
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.standards_evidence import (
    STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
    STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
    StandardEvidenceActor,
    StandardEvidenceAssociationDecision,
)

NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)
WORK = ModuleWorkRef("scoreform", "synthetic_class_2026", "quiz_1")
STANDARD = "urn:state:ELA/9-10:RL.1?edition=2026"


def source() -> EvidenceSourceReference:
    return EvidenceSourceReference(
        WORK, "pub_" + "1" * 32, "2" * 64, "3" * 64, "item_1"
    )


def decision(revision: int = 1) -> StandardEvidenceAssociationDecision:
    return StandardEvidenceAssociationDecision(
        STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
        STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
        WORK.class_id,
        "grade_item_1",
        source(),
        STANDARD,
        revision,
        None if revision == 1 else revision - 1,
        "associated" if revision == 1 else "not_associated",
        "producer_declared",
        StandardEvidenceActor("teacher", "teacher_local"),
        None,
        NOW,
    )


def allow_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        storage,
        "validate_standard_evidence_association_dependencies",
        lambda *args, **kwargs: object(),
    )


def test_write_is_immutable_and_does_not_auto_select(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow_dependencies(monkeypatch)
    result = storage.write_standard_evidence_association_revision(
        tmp_path,
        decision(),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert result.disposition == "created"
    assert result.stored.content.endswith(b"\n")
    assert result.stored.path.with_suffix(".json.sha256").is_file()
    assert (
        storage.get_current_standard_evidence_association_revision(
            tmp_path, WORK.class_id, "grade_item_1", source(), STANDARD
        )
        is None
    )
    replay = storage.write_standard_evidence_association_revision(
        tmp_path,
        decision(),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    assert replay.disposition == "existing"


def test_explicit_selection_cas_and_historical_reselection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow_dependencies(monkeypatch)
    for value in (decision(), decision(2)):
        storage.write_standard_evidence_association_revision(
            tmp_path,
            value,
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )
    first = storage.select_standard_evidence_association_revision(
        tmp_path,
        WORK.class_id,
        "grade_item_1",
        source(),
        STANDARD,
        2,
        expected_current_association_revision=None,
    )
    assert first.selection.decision_sha256 == first.stored.decision_sha256
    with pytest.raises(storage.StandardsEvidenceStorageConflictError):
        storage.select_standard_evidence_association_revision(
            tmp_path,
            WORK.class_id,
            "grade_item_1",
            source(),
            STANDARD,
            1,
            expected_current_association_revision=None,
        )
    historical = storage.select_standard_evidence_association_revision(
        tmp_path,
        WORK.class_id,
        "grade_item_1",
        source(),
        STANDARD,
        1,
        expected_current_association_revision=2,
    )
    assert historical.stored.decision.association_revision == 1


def test_raw_standard_id_is_absent_from_canonical_path(tmp_path: Path) -> None:
    path = storage.standard_evidence_association_revision_path(
        tmp_path, WORK.class_id, "grade_item_1", source(), STANDARD, 1
    )
    assert STANDARD not in str(path)
    assert path.parent.parent.name == storage.standard_evidence_association_key(
        WORK.class_id, "grade_item_1", source(), STANDARD
    )


def test_same_revision_different_content_conflicts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow_dependencies(monkeypatch)
    storage.write_standard_evidence_association_revision(
        tmp_path,
        decision(),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(storage.StandardsEvidenceStorageConflictError):
        storage.write_standard_evidence_association_revision(
            tmp_path,
            replace(decision(), rationale="different"),
            authorized_snapshot=object(),  # type: ignore[arg-type]
        )


def test_digest_and_bounded_read_tampering_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow_dependencies(monkeypatch)
    stored = storage.write_standard_evidence_association_revision(
        tmp_path,
        decision(),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    ).stored
    with pytest.raises(storage.StandardsEvidenceStorageTooLargeError):
        storage.load_standard_evidence_association_revision(
            tmp_path,
            WORK.class_id,
            "grade_item_1",
            source(),
            STANDARD,
            1,
            maximum_revision_bytes=8,
        )
    stored.path.with_suffix(".json.sha256").write_text("0" * 64 + "\n")
    with pytest.raises(storage.StandardsEvidenceStorageIntegrityError, match="digest"):
        storage.load_standard_evidence_association_revision(
            tmp_path, WORK.class_id, "grade_item_1", source(), STANDARD, 1
        )


def test_dependency_validation_distinguishes_producer_declared_and_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    definition = StandardDefinition(
        STANDARD,
        "RL.1",
        "state_ela",
        "Evidence",
        "Synthetic standard.",
    )
    library = StandardsLibrary((definition,))
    monkeypatch.setattr(
        storage,
        "load_class_metadata",
        lambda path: SimpleNamespace(class_id=WORK.class_id),
    )
    monkeypatch.setattr(
        storage,
        "load_current_grade_item_revision",
        lambda *args: SimpleNamespace(),
    )
    monkeypatch.setattr(
        storage,
        "load_current_grade_item_membership_decision",
        lambda *args: SimpleNamespace(
            decision=SimpleNamespace(decision="included")
        ),
    )
    producer_target = SimpleNamespace(standard_ids=("another:standard",))
    monkeypatch.setattr(
        storage,
        "validate_authorized_evidence_source",
        lambda *args: SimpleNamespace(
            provenance=SimpleNamespace(work=WORK), target=producer_target
        ),
    )
    with pytest.raises(storage.StandardsEvidenceDependencyError, match="exact source"):
        storage.validate_standard_evidence_association_dependencies(
            tmp_path,
            decision(),
            object(),  # type: ignore[arg-type]
            standards_library=library,
        )
    explicit = replace(decision(), basis="explicit")
    dependencies = storage.validate_standard_evidence_association_dependencies(
        tmp_path,
        explicit,
        object(),  # type: ignore[arg-type]
        standards_library=library,
    )
    assert dependencies.standard_resolution.standard == definition
    assert producer_target.standard_ids == ("another:standard",)


def test_dependency_validation_binds_class_metadata_to_requested_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        storage,
        "load_class_metadata",
        lambda path: SimpleNamespace(class_id="another_valid_class"),
    )
    with pytest.raises(storage.StandardsEvidenceDependencyError, match="class_id"):
        storage.validate_standard_evidence_association_dependencies(
            tmp_path,
            decision(),
            object(),  # type: ignore[arg-type]
            standards_library=StandardsLibrary(()),
        )


def test_pointer_noncanonical_bytes_and_unexpected_entries_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow_dependencies(monkeypatch)
    stored = storage.write_standard_evidence_association_revision(
        tmp_path,
        decision(),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    ).stored
    storage.select_standard_evidence_association_revision(
        tmp_path,
        WORK.class_id,
        "grade_item_1",
        source(),
        STANDARD,
        1,
        expected_current_association_revision=None,
    )
    current_path = storage.standard_evidence_association_current_path(
        tmp_path, WORK.class_id, "grade_item_1", source(), STANDARD
    )
    current_path.write_bytes(current_path.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(storage.StandardsEvidenceStorageIntegrityError):
        storage.load_current_standard_evidence_association_decision(
            tmp_path, WORK.class_id, "grade_item_1", source(), STANDARD
        )

    canonical = stored.content
    noncanonical = canonical.replace(b"\n", b"\r\n")
    stored.path.write_bytes(noncanonical)
    stored.path.with_suffix(".json.sha256").write_text(
        hashlib.sha256(noncanonical).hexdigest() + "\n", encoding="ascii"
    )
    with pytest.raises(storage.StandardsEvidenceStorageIntegrityError):
        storage.load_standard_evidence_association_revision(
            tmp_path, WORK.class_id, "grade_item_1", source(), STANDARD, 1
        )


def test_hashed_path_contains_hostile_standard_and_rejects_unexpected_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hostile = "../..\\CON:<standard>?edition=2026"
    path = storage.standard_evidence_association_revision_path(
        tmp_path, WORK.class_id, "grade_item_1", source(), hostile, 1
    )
    assert hostile not in str(path)
    assert path.resolve().is_relative_to(tmp_path.resolve())

    allow_dependencies(monkeypatch)
    storage.write_standard_evidence_association_revision(
        tmp_path,
        decision(),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    relation = storage.standard_evidence_association_directory(
        tmp_path, WORK.class_id, "grade_item_1", source(), STANDARD
    )
    relation.joinpath("unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(
        storage.StandardsEvidenceStorageIntegrityError, match="unexpected"
    ):
        storage.list_standard_evidence_association_revisions(
            tmp_path, WORK.class_id, "grade_item_1", source(), STANDARD
        )


def test_resolution_model_rejects_impossible_state_combinations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow_dependencies(monkeypatch)
    stored = storage.write_standard_evidence_association_revision(
        tmp_path,
        decision(),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    ).stored
    definition = StandardDefinition(
        STANDARD, "RL.1", "state_ela", "Evidence", "Synthetic standard."
    )
    core = storage.CoreStandardResolution(definition, ())
    valid = storage.StandardEvidenceAssociationResolution(
        "associated",
        stored,
        stored.reference,
        stored.decision.basis,
        core,
        True,
        True,
    )
    with pytest.raises(storage.StandardsEvidenceStorageValidationError):
        replace(valid, reference=None)
    with pytest.raises(storage.StandardsEvidenceStorageValidationError):
        replace(valid, operative_associated=False)
    with pytest.raises(storage.StandardsEvidenceStorageValidationError):
        replace(
            valid,
            status="no_decision",
            selected=None,
            reference=None,
            basis=None,
        )
    with pytest.raises(storage.StandardsEvidenceStorageValidationError):
        replace(valid, source_verifiable=1)  # type: ignore[arg-type]

    unresolved = storage.StandardEvidenceAssociationResolution(
        "standard_unresolved",
        stored,
        stored.reference,
        stored.decision.basis,
        storage.CoreStandardResolution(None, ()),
        True,
        False,
    )
    assert unresolved.reference == stored.reference
    unverifiable = storage.StandardEvidenceAssociationResolution(
        "source_unverifiable",
        stored,
        stored.reference,
        stored.decision.basis,
        core,
        False,
        False,
    )
    assert unverifiable.reference == stored.reference


def test_selection_verifies_the_published_pointer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow_dependencies(monkeypatch)
    storage.write_standard_evidence_association_revision(
        tmp_path,
        decision(),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )
    original = storage._load_current_selection
    calls = 0

    def mismatched_second_load(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        selected = original(*args, **kwargs)  # type: ignore[arg-type]
        if calls == 2 and selected is not None:
            return replace(selected, decision_sha256="0" * 64)
        return selected

    monkeypatch.setattr(storage, "_load_current_selection", mismatched_second_load)
    with pytest.raises(
        storage.StandardsEvidenceStorageIntegrityError, match="Published"
    ):
        storage.select_standard_evidence_association_revision(
            tmp_path,
            WORK.class_id,
            "grade_item_1",
            source(),
            STANDARD,
            1,
            expected_current_association_revision=None,
        )
