"""Installed Meridian module-operations profile for Core v1."""

from __future__ import annotations

from pds_core.module_operations import (
    MODULE_OPERATIONS_CONTRACT_VERSION,
    ModuleAttentionReport,
    ModuleOperationsProfile,
    ModuleOperationsRequest,
    validate_module_operations_profile,
)

MERIDIAN_MODULE_ID = "meridian"


def evaluate_meridian_attention(
    request: ModuleOperationsRequest,
    /,
) -> ModuleAttentionReport:
    """Lazily evaluate Meridian-owned attention for one neutral Core request."""

    from meridian.attention_provider import evaluate_meridian_attention as _evaluate

    return _evaluate(request)


def get_module_operations_profile() -> ModuleOperationsProfile:
    """Return Meridian's validated Core v1 attention-only operations profile."""

    return validate_module_operations_profile(
        ModuleOperationsProfile(
            module_id=MERIDIAN_MODULE_ID,
            supported_core_operations_contract_versions=frozenset(
                {MODULE_OPERATIONS_CONTRACT_VERSION}
            ),
            readiness_provider=None,
            attention_provider=evaluate_meridian_attention,
        )
    )


__all__ = ["evaluate_meridian_attention", "get_module_operations_profile"]
