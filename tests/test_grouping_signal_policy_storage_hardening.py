from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from test_grouping_signal_policy_storage import CLASS_ID, policy

from meridian import grouping_signal_policy_storage as storage
from meridian.grouping_signal_policy import (
    grouping_signal_derivation_policy_to_json_bytes,
)


def allow_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        storage,
        "validate_grouping_signal_policy_dependencies",
        lambda *args, **kwargs: object(),
    )


def stored_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> storage.StoredGroupingSignalDerivationPolicy:
    allow_dependencies(monkeypatch)
    return storage.write_grouping_signal_policy_revision(
        tmp_path,
        policy(),
    ).stored


def test_recomputed_digest_does_not_make_noncanonical_crlf_valid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stored = stored_policy(monkeypatch, tmp_path)
    crlf = stored.content.replace(b"\n", b"\r\n")
    stored.path.write_bytes(crlf)
    stored.path.with_suffix(".json.sha256").write_text(
        hashlib.sha256(crlf).hexdigest() + "\n",
        encoding="ascii",
        newline="\n",
    )
    with pytest.raises(
        storage.GroupingSignalPolicyStorageIntegrityError,
        match="noncanonical",
    ):
        storage.load_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
            1,
        )


def test_malformed_and_tampered_digest_sidecars_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stored = stored_policy(monkeypatch, tmp_path)
    sidecar = stored.path.with_suffix(".json.sha256")

    sidecar.write_text("not-a-digest\n", encoding="ascii", newline="\n")
    with pytest.raises(storage.GroupingSignalPolicyStorageIntegrityError):
        storage.load_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
            1,
        )

    sidecar.write_text("0" * 64 + "\n", encoding="ascii", newline="\n")
    with pytest.raises(
        storage.GroupingSignalPolicyStorageIntegrityError,
        match="digest",
    ):
        storage.load_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
            1,
        )


def test_path_model_identity_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stored = stored_policy(monkeypatch, tmp_path)
    other = storage.grouping_signal_policy_revision_path(
        tmp_path,
        CLASS_ID,
        "other_policy",
        1,
    )
    other.parent.mkdir(parents=True)
    other.write_bytes(stored.content)
    other.with_suffix(".json.sha256").write_text(
        stored.policy_sha256 + "\n",
        encoding="ascii",
        newline="\n",
    )
    with pytest.raises(
        storage.GroupingSignalPolicyStorageIntegrityError,
        match="identity",
    ):
        storage.load_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            "other_policy",
            1,
        )


def test_malformed_noncanonical_and_oversized_pointers_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stored = stored_policy(monkeypatch, tmp_path)
    storage.select_grouping_signal_policy_revision(
        tmp_path,
        CLASS_ID,
        stored.policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    pointer = storage.grouping_signal_policy_current_path(
        tmp_path,
        CLASS_ID,
        stored.policy.policy_id,
    )

    pointer.write_bytes(b'{"schema_version":"1"}\n')
    with pytest.raises(storage.GroupingSignalPolicyStorageIntegrityError):
        storage.get_current_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
        )

    data = {
        "schema_version": storage.GROUPING_SIGNAL_POLICY_CURRENT_SCHEMA_VERSION,
        "record_type": storage.GROUPING_SIGNAL_POLICY_CURRENT_RECORD_TYPE,
        "class_id": CLASS_ID,
        "policy_id": stored.policy.policy_id,
        "policy_revision": 1,
        "policy_sha256": stored.policy_sha256,
    }
    noncanonical = json.dumps(data, sort_keys=False).encode("utf-8") + b"\n"
    pointer.write_bytes(noncanonical)
    with pytest.raises(
        storage.GroupingSignalPolicyStorageIntegrityError,
        match="canonical",
    ):
        storage.get_current_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
        )

    pointer.write_bytes(
        b"{" + b" " * (storage.DEFAULT_MAXIMUM_GROUPING_SIGNAL_POLICY_POINTER_BYTES + 1)
        + b"}"
    )
    with pytest.raises(storage.GroupingSignalPolicyStorageTooLargeError):
        storage.get_current_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
        )


def test_current_pointer_digest_must_match_exact_selected_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stored = stored_policy(monkeypatch, tmp_path)
    storage.select_grouping_signal_policy_revision(
        tmp_path,
        CLASS_ID,
        stored.policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    pointer = storage.grouping_signal_policy_current_path(
        tmp_path,
        CLASS_ID,
        stored.policy.policy_id,
    )
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["policy_sha256"] = "0" * 64
    pointer.write_text(
        json.dumps(data, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(
        storage.GroupingSignalPolicyStorageIntegrityError,
        match="digest",
    ):
        storage.load_current_grouping_signal_policy(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
        )


@pytest.mark.parametrize(
    "unsafe",
    [
        "../escape",
        "/absolute",
        r"C:\\absolute",
        r"..\\escape",
        "policy/name",
    ],
)
def test_identifier_path_injection_is_rejected(
    tmp_path: Path,
    unsafe: str,
) -> None:
    with pytest.raises(storage.GroupingSignalPolicyStorageValidationError):
        storage.grouping_signal_policy_revision_path(
            tmp_path,
            unsafe,
            "policy_id",
            1,
        )
    with pytest.raises(storage.GroupingSignalPolicyStorageValidationError):
        storage.grouping_signal_policy_revision_path(
            tmp_path,
            CLASS_ID,
            unsafe,
            1,
        )


def test_revision_symlink_is_rejected_where_supported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stored = stored_policy(monkeypatch, tmp_path)
    target = tmp_path / "symlink-target.json"
    target.write_bytes(grouping_signal_derivation_policy_to_json_bytes(stored.policy))
    stored.path.unlink()
    try:
        os.symlink(target, stored.path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")

    with pytest.raises(storage.GroupingSignalPolicyStorageIntegrityError):
        storage.load_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
            1,
        )


def test_revision_directory_rejects_unexpected_visible_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stored = stored_policy(monkeypatch, tmp_path)
    (stored.path.parent / "README.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(
        storage.GroupingSignalPolicyStorageIntegrityError,
        match="unexpected filename",
    ):
        storage.list_grouping_signal_policy_revisions(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
        )
