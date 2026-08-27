from __future__ import annotations

from dataclasses import replace

import pytest

from meridian.adapters import (
    AdapterNotFoundError,
    ProducerReaderVersionUnsupportedError,
)
from tests.cross_producer_test_support import (
    SHARED_STUDENT_ID,
    cross_producer_registry,
    cross_producer_requests,
)


def test_cross_producer_failures_do_not_dump_manifest_or_student_data() -> None:
    requests = cross_producer_requests()
    registry = cross_producer_registry()

    with pytest.raises(ProducerReaderVersionUnsupportedError) as reader_failure:
        registry.invoke(
            requests.quillan,
            lambda distribution: (
                "0.10.1" if distribution == "quillan" else "unreachable"
            ),
        )

    future = replace(
        requests.quillan.publication,
        manifest_contract_version="quillan_academic_result_manifest_v2",
    )
    with pytest.raises(AdapterNotFoundError) as contract_failure:
        registry.select(future, requests.quillan.registration)

    sensitive_fragments = (
        SHARED_STUDENT_ID,
        requests.quillan.manifest_bytes.decode("utf-8"),
        '"students"',
        '"submissions"',
    )
    for failure in (reader_failure.value, contract_failure.value):
        message = str(failure)
        assert message
        assert all(fragment not in message for fragment in sensitive_fragments)
