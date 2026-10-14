"""Active release-artifact identity guards for Issue #111."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_concord_wheel import (
    CURRENT_CONCORD_RELEASE_COMMIT,
    CURRENT_CONCORD_RELEASE_TAG,
    CURRENT_CONCORD_VERSION,
    CURRENT_CONCORD_WHEEL_FILENAME,
    CURRENT_CONCORD_WHEEL_SHA256,
    ConcordVerificationError,
    verify_concord_wheel,
)
from scripts.verify_quillan_wheel import (
    CURRENT_QUILLAN_RELEASE_COMMIT,
    CURRENT_QUILLAN_RELEASE_TAG,
    CURRENT_QUILLAN_VERSION,
    CURRENT_QUILLAN_WHEEL_FILENAME,
    CURRENT_QUILLAN_WHEEL_SHA256,
    QuillanVerificationError,
    verify_quillan_wheel,
)
from scripts.verify_scoreform_wheel import (
    CURRENT_SCOREFORM_RELEASE_COMMIT,
    CURRENT_SCOREFORM_RELEASE_TAG,
    CURRENT_SCOREFORM_RELEASE_TREE,
    CURRENT_SCOREFORM_VERSION,
    CURRENT_SCOREFORM_WHEEL_FILENAME,
    CURRENT_SCOREFORM_WHEEL_SHA256,
    ScoreFormVerificationError,
    verify_scoreform_wheel,
)


def test_current_producer_release_identities_are_exact() -> None:
    assert (
        CURRENT_SCOREFORM_VERSION,
        CURRENT_SCOREFORM_RELEASE_TAG,
        CURRENT_SCOREFORM_RELEASE_COMMIT,
        CURRENT_SCOREFORM_RELEASE_TREE,
        CURRENT_SCOREFORM_WHEEL_FILENAME,
        CURRENT_SCOREFORM_WHEEL_SHA256,
    ) == (
        "0.13.0",
        "v0.13.0",
        "dbb4159bb2c4d04889742de746be42a394130170",
        "ef6bb4e4d37da25b317d1a2aebddebdf7edcdd28",
        "scoreform-0.13.0-py3-none-any.whl",
        "4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7",
    )
    assert (
        CURRENT_QUILLAN_VERSION,
        CURRENT_QUILLAN_RELEASE_TAG,
        CURRENT_QUILLAN_RELEASE_COMMIT,
        CURRENT_QUILLAN_WHEEL_FILENAME,
        CURRENT_QUILLAN_WHEEL_SHA256,
    ) == (
        "0.10.6",
        "v0.10.6",
        "93cf0ae84887d79377e6f77c1d0c818af24688a5",
        "quillan-0.10.6-py3-none-any.whl",
        "7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb",
    )
    assert (
        CURRENT_CONCORD_VERSION,
        CURRENT_CONCORD_RELEASE_TAG,
        CURRENT_CONCORD_RELEASE_COMMIT,
        CURRENT_CONCORD_WHEEL_FILENAME,
        CURRENT_CONCORD_WHEEL_SHA256,
    ) == (
        "0.3.2",
        "v0.3.2",
        "ba69d05148c625d3440d7d26ea07193715e237e3",
        "pds_concord-0.3.2-py3-none-any.whl",
        "825b27bc6142cc8bce8c3b9381a3337c4a55e983f6f3f2e7e4b1a10f980e83ce",
    )


@pytest.mark.parametrize(
    ("filename", "verify", "error"),
    (
        (
            CURRENT_SCOREFORM_WHEEL_FILENAME,
            verify_scoreform_wheel,
            ScoreFormVerificationError,
        ),
        (
            CURRENT_QUILLAN_WHEEL_FILENAME,
            verify_quillan_wheel,
            QuillanVerificationError,
        ),
        (
            CURRENT_CONCORD_WHEEL_FILENAME,
            verify_concord_wheel,
            ConcordVerificationError,
        ),
    ),
)
def test_current_verifiers_reject_unauthenticated_bytes(
    tmp_path: Path,
    filename: str,
    verify: object,
    error: type[ValueError],
) -> None:
    path = tmp_path / filename
    path.write_bytes(b"not the authenticated release wheel")
    with pytest.raises(error, match="SHA-256 mismatch"):
        verify(path, current=True)  # type: ignore[operator]


def test_active_validation_uses_current_mode_without_erasing_legacy() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    for producer in ("scoreform", "quillan", "concord"):
        assert f'"scripts/verify_{producer}_wheel.py"' in validator
    assert validator.count('"--current"') == 3
    assert workflow.count("--current") == 3
