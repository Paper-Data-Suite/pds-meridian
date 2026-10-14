from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.sis_reconciliation_cli as reconciliation_cli
from meridian.cli import main
from meridian.external_gradebook_mapping import (
    external_gradebook_mapping_from_json_bytes,
)
from meridian.proficiency_mapping import proficiency_scale_reference
from tests.test_external_gradebook_mapping_issue111 import scale


def test_reconciliation_group_is_registered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("reports", "reconciliation")) == 0
    output = capsys.readouterr().out
    assert "profile" in output
    assert "preview" in output
    assert "No SIS/LMS" in output


def test_profile_command_uses_canonical_scale_and_arbitrary_system_label(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = scale()
    reference = proficiency_scale_reference(target)
    monkeypatch.setattr(
        reconciliation_cli,
        "load_proficiency_scale_revision",
        lambda *args: SimpleNamespace(
            scale=target,
            scale_sha256=reference.scale_sha256,
        ),
    )

    assert (
        main(
            (
                "reports",
                "reconciliation",
                "profile",
                target.class_id,
                "2026-2027",
                "q1",
                "district_gradebook",
                "1",
                target.scale_id,
                "1",
                "--title",
                "District Reporting",
                "--system-label",
                "Skyward",
                "--map",
                "developing",
                "65",
                "--map",
                "approaching",
                "75",
                "--map",
                "meeting",
                "87",
                "--map",
                "exceeding",
                "97",
                "--actor-id",
                "teacher_local",
                "--revised-at",
                "2026-10-12T21:00:00Z",
            )
        )
        == 0
    )
    profile = external_gradebook_mapping_from_json_bytes(
        capsys.readouterr().out.encode("utf-8")
    )
    assert profile.system_label == "Skyward"
    assert profile.target_scale == reference
