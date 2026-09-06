"""Core v1 adapter for Meridian's native proficiency-attention projection.

Issue #43 keeps the native attention vocabulary in ``proficiency_attention``
and maps those bounded facts into Core's neutral module-operations contract.
Workspace orchestration is owned by the native attention service.
"""

from __future__ import annotations

from typing import Final

from pds_core.module_operations import (
    ModuleAttentionReport,
    ModuleAttentionSummary,
    ModuleOperationsNotice,
    ModuleOperationsRequest,
    ModuleOwnerActionRef,
    validate_module_attention_report,
    validate_module_operations_request,
)

from meridian.attention_service import (
    MeridianAttentionReadError,
    inspect_meridian_attention,
)
from meridian.proficiency_attention import MeridianAttentionSummary

MERIDIAN_MODULE_ID: Final[str] = "meridian"
MERIDIAN_ATTENTION_PARTIAL_NOTICE_CODE: Final[str] = "meridian_attention_partial"
MERIDIAN_ATTENTION_UNAVAILABLE_NOTICE_CODE: Final[str] = (
    "meridian_attention_unavailable"
)


class MeridianAttentionProviderError(ValueError):
    """Raised when a native attention projection cannot map safely to Core."""


def project_meridian_attention_to_core(
    summary: MeridianAttentionSummary,
    request: ModuleOperationsRequest,
    /,
    *,
    partial: bool = False,
) -> ModuleAttentionReport:
    """Project one successful native attention summary into Core v1.

    This is a pure adapter: it does not inspect or mutate the workspace. A
    partial result remains ``evaluation='evaluated'`` and carries one bounded
    notice, preserving Core's distinction between partial success and total
    unavailability.
    """

    if not isinstance(summary, MeridianAttentionSummary):
        raise TypeError("summary must be a MeridianAttentionSummary.")
    validate_module_operations_request(request)
    _validate_native_request_context(summary, request)

    notices: tuple[ModuleOperationsNotice, ...] = ()
    if partial:
        notices = (
            ModuleOperationsNotice(
                code=MERIDIAN_ATTENTION_PARTIAL_NOTICE_CODE,
                summary=(
                    "Some Meridian attention sources could not be inspected "
                    "safely; available summaries are partial."
                ),
            ),
        )

    report = ModuleAttentionReport(
        evaluation="evaluated",
        summaries=tuple(
            ModuleAttentionSummary(
                code=item.code,
                label=item.definition.label,
                count=item.count,
                class_id=item.class_id,
                action=ModuleOwnerActionRef(
                    module_id=MERIDIAN_MODULE_ID,
                    action_id=item.definition.action_id,
                ),
            )
            for item in summary.items
        ),
        notices=notices,
    )
    return validate_module_attention_report(
        report,
        expected_module_id=MERIDIAN_MODULE_ID,
    )


def unavailable_meridian_attention_report(summary: str) -> ModuleAttentionReport:
    """Return one bounded fail-closed Core report without raw exception text."""

    report = ModuleAttentionReport(
        evaluation="unavailable",
        summaries=(),
        notices=(
            ModuleOperationsNotice(
                code=MERIDIAN_ATTENTION_UNAVAILABLE_NOTICE_CODE,
                summary=summary,
            ),
        ),
    )
    return validate_module_attention_report(
        report,
        expected_module_id=MERIDIAN_MODULE_ID,
    )


def evaluate_meridian_attention(
    request: ModuleOperationsRequest,
    /,
) -> ModuleAttentionReport:
    """Evaluate native Meridian attention over one exact or workspace scope."""

    if not isinstance(request, ModuleOperationsRequest):
        raise TypeError("request must be a ModuleOperationsRequest.")
    validate_module_operations_request(request)

    if request.workspace_root is None:
        return unavailable_meridian_attention_report(
            "Meridian attention requires an explicit workspace."
        )

    try:
        inspection = inspect_meridian_attention(
            request.workspace_root,
            class_id=request.class_id,
            active_school_year=request.active_school_year,
        )
    except MeridianAttentionReadError:
        return unavailable_meridian_attention_report(
            "The requested Meridian attention scope cannot be inspected safely."
        )
    return project_meridian_attention_to_core(
        inspection.summary,
        request,
        partial=inspection.partial,
    )


def _validate_native_request_context(
    summary: MeridianAttentionSummary,
    request: ModuleOperationsRequest,
) -> None:
    if request.class_id is None:
        return
    for item in summary.items:
        if item.class_id is not None and item.class_id != request.class_id:
            raise MeridianAttentionProviderError(
                "native attention item class_id must match the requested class_id."
            )


__all__ = [
    "MERIDIAN_ATTENTION_PARTIAL_NOTICE_CODE",
    "MERIDIAN_ATTENTION_UNAVAILABLE_NOTICE_CODE",
    "MERIDIAN_MODULE_ID",
    "MeridianAttentionProviderError",
    "evaluate_meridian_attention",
    "project_meridian_attention_to_core",
    "unavailable_meridian_attention_report",
]
