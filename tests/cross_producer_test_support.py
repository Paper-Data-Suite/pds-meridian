"""Shared cross-producer synthetic scenario support for Meridian issue #13."""

from __future__ import annotations

from dataclasses import dataclass

from meridian.adapters import AdapterProjectionRequest, AdapterRegistry
from meridian.concord_adapter import ConcordAcademicResultAdapter
from meridian.quillan_adapter import QuillanAcademicResultAdapter
from meridian.scoreform_adapter import ScoreFormAcademicResultAdapter
from tests.concord_test_support import (
    concord_manifest_bytes,
    concord_publication,
    concord_registration,
)
from tests.quillan_test_support import (
    quillan_manifest_bytes,
    quillan_publication,
    quillan_registration,
)
from tests.scoreform_test_support import (
    scoreform_manifest_bytes,
    scoreform_publication,
    scoreform_registration,
)

SHARED_STUDENT_ID = "student_synthetic_001"
SECONDARY_STUDENT_ID = "student_synthetic_002"
SHARED_STANDARD_ID = "standard_ela_1"

EXACT_READER_VERSIONS = {
    "scoreform": "0.10.0",
    "quillan": "0.10.0",
    "pds-concord": "0.2.0",
}


@dataclass(frozen=True, slots=True)
class CrossProducerRequests:
    """One exact projection request for every currently supported producer."""

    scoreform: AdapterProjectionRequest
    quillan: AdapterProjectionRequest
    concord: AdapterProjectionRequest

    @property
    def ordered(self) -> tuple[AdapterProjectionRequest, ...]:
        return (self.scoreform, self.quillan, self.concord)


def exact_reader_version(distribution_name: str) -> str:
    """Return the frozen released reader version for one supported producer."""
    return EXACT_READER_VERSIONS[distribution_name]


def cross_producer_registry() -> AdapterRegistry:
    """Return the explicit immutable registry used by mixed synthetic scenarios."""
    return AdapterRegistry(
        (
            ScoreFormAcademicResultAdapter(),
            QuillanAcademicResultAdapter(),
            ConcordAcademicResultAdapter(),
        )
    )


def cross_producer_requests() -> CrossProducerRequests:
    """Build three released-reader requests sharing a student and Standard."""
    scoreform_manifest = scoreform_manifest_bytes(
        primary_student_id=SHARED_STUDENT_ID,
        secondary_student_id=SECONDARY_STUDENT_ID,
        primary_standard_id=SHARED_STANDARD_ID,
    )
    quillan_manifest = quillan_manifest_bytes(
        primary_student_id=SHARED_STUDENT_ID,
        secondary_student_id=SECONDARY_STUDENT_ID,
        evidence_standard_id=SHARED_STANDARD_ID,
        rating_value=2,
    )
    concord_manifest = concord_manifest_bytes(
        primary_student_id=SHARED_STUDENT_ID,
        secondary_student_id=SECONDARY_STUDENT_ID,
    )
    return CrossProducerRequests(
        scoreform=AdapterProjectionRequest(
            scoreform_publication(scoreform_manifest),
            scoreform_registration(),
            None,
            scoreform_manifest,
        ),
        quillan=AdapterProjectionRequest(
            quillan_publication(quillan_manifest),
            quillan_registration(),
            None,
            quillan_manifest,
        ),
        concord=AdapterProjectionRequest(
            concord_publication(concord_manifest),
            concord_registration(),
            None,
            concord_manifest,
        ),
    )
