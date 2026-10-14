"""Student Current Grade Justification report for Meridian Issue #111 Slice 8."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeAlias, cast

from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.conventional_grade_explanation import (
    ConventionalGradePreviewExplanation,
    conventional_grade_observation,
    conventional_grade_preview_explanation_to_dict,
)
from meridian.current_grade_preview import (
    CurrentGradePreviewExplanation,
    explain_current_grade_preview,
)
from meridian.grade_preview_explanation import (
    GradePreviewObservation,
    GradePreviewTarget,
    grade_preview_observation_sha256,
)
from meridian.hybrid_grade_explanation import (
    HybridGradePreviewExplanation,
    hybrid_grade_observation,
    hybrid_grade_preview_explanation_to_dict,
)
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_storage import (
    ReportingSnapshotStorageError,
    load_reporting_snapshot,
)
from meridian.standards_grade_explanation import (
    StandardsGradePreviewExplanation,
    standards_grade_observation,
    standards_grade_preview_explanation_to_dict,
)
from meridian.teacher_grade_override import (
    grade_override_source_result_reference_to_dict,
)
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportDiagnostic,
    TeacherReportPreview,
    TeacherReportRow,
    TeacherReportSourceReference,
    compose_teacher_report_preview,
)

StudentGradeJustificationMode: TypeAlias = Literal["current", "snapshot"]


class StudentGradeJustificationError(RuntimeError):
    code = "student_grade_justification.error"


class StudentGradeJustificationValidationError(
    StudentGradeJustificationError,
    ValueError,
):
    code = "student_grade_justification.invalid"


class StudentGradeJustificationNotFoundError(StudentGradeJustificationError):
    code = "student_grade_justification.not_found"


class StudentGradeJustificationAmbiguousError(StudentGradeJustificationError):
    code = "student_grade_justification.ambiguous"


class StudentGradeJustificationEvidenceRequiredError(
    StudentGradeJustificationError,
):
    code = "student_grade_justification.evidence_required"


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_current_student_grade_justification(
    workspace_root: str | Path,
    target: GradePreviewTarget,
    *,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None = None,
    generated_at: datetime | None = None,
) -> TeacherReportPreview:
    """Explain one current selected Grade without authoring new academic state."""

    if not isinstance(target, GradePreviewTarget):
        raise StudentGradeJustificationValidationError(
            "target must be a GradePreviewTarget."
        )
    if (
        target.calculation_family in {"conventional", "hybrid"}
        and work_evidence is None
    ):
        raise StudentGradeJustificationEvidenceRequiredError(
            "Current conventional/hybrid justification requires an explicit "
            "authorized work-evidence tuple; protected evidence is never opened "
            "implicitly."
        )
    explanation = explain_current_grade_preview(
        workspace_root,
        target,
        work_evidence=work_evidence,
    )
    data, observation = _live_explanation_payload(explanation)
    return compose_student_grade_justification(
        observation=observation,
        explanation=data,
        source_mode="current",
        generated_at=utc_now() if generated_at is None else generated_at,
    )


def build_snapshot_student_grade_justification(
    workspace_root: str | Path,
    snapshot_reference: ReportingSnapshotReference,
    student_id: str,
    *,
    calculation_family: str | None = None,
    generated_at: datetime | None = None,
) -> TeacherReportPreview:
    """Explain one frozen Grade row without consulting current Grade state."""

    if not isinstance(snapshot_reference, ReportingSnapshotReference):
        raise StudentGradeJustificationValidationError(
            "snapshot_reference must be ReportingSnapshotReference."
        )
    if not isinstance(student_id, str) or not student_id.strip():
        raise StudentGradeJustificationValidationError(
            "student_id must be nonblank text."
        )
    try:
        stored = load_reporting_snapshot(
            workspace_root,
            snapshot_reference.class_id,
            snapshot_reference.snapshot_id,
        )
    except ReportingSnapshotStorageError as error:
        raise StudentGradeJustificationError(
            f"Historical ReportingSnapshot could not be loaded: {error}"
        ) from error
    if stored.reference != snapshot_reference:
        raise StudentGradeJustificationError(
            "Historical ReportingSnapshot digest does not match the requested "
            "exact reference."
        )

    candidates = tuple(
        row
        for row in stored.snapshot.report_preview.rows
        if row.target.student_id == student_id
        and (
            calculation_family is None
            or row.target.calculation_family == calculation_family
        )
    )
    if not candidates:
        raise StudentGradeJustificationNotFoundError(
            "Student Grade row is absent from the exact ReportingSnapshot."
        )
    if len(candidates) > 1:
        raise StudentGradeJustificationAmbiguousError(
            "ReportingSnapshot contains multiple Grade families for this student; "
            "specify calculation_family."
        )
    row = candidates[0]
    if row.status != "available":
        raise StudentGradeJustificationNotFoundError(
            "Exact ReportingSnapshot records no selected Grade for this student."
        )
    if (
        row.observation is None
        or row.observation_sha256 is None
        or row.explanation_json is None
        or row.explanation_sha256 is None
    ):
        raise StudentGradeJustificationError(
            "Available frozen Grade row lacks exact explanation authority."
        )
    try:
        decoded = json.loads(row.explanation_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StudentGradeJustificationError(
            "Frozen Grade explanation bytes are invalid."
        ) from error
    if not isinstance(decoded, dict):
        raise StudentGradeJustificationError(
            "Frozen Grade explanation must be a JSON object."
        )

    return compose_student_grade_justification(
        observation=row.observation,
        explanation=cast(dict[str, object], decoded),
        source_mode="snapshot",
        generated_at=utc_now() if generated_at is None else generated_at,
        snapshot_reference=snapshot_reference,
        snapshot_created_at=stored.snapshot.created_at,
        exact_observation_sha256=row.observation_sha256,
        exact_explanation_sha256=row.explanation_sha256,
    )


def compose_student_grade_justification(
    *,
    observation: GradePreviewObservation,
    explanation: Mapping[str, object],
    source_mode: StudentGradeJustificationMode,
    generated_at: datetime,
    snapshot_reference: ReportingSnapshotReference | None = None,
    snapshot_created_at: datetime | None = None,
    exact_observation_sha256: str | None = None,
    exact_explanation_sha256: str | None = None,
) -> TeacherReportPreview:
    """Compose a concise report from already-authoritative Grade explanation data."""

    if not isinstance(observation, GradePreviewObservation):
        raise StudentGradeJustificationValidationError(
            "observation must be GradePreviewObservation."
        )
    if source_mode not in {"current", "snapshot"}:
        raise StudentGradeJustificationValidationError(
            "source_mode must be current or snapshot."
        )
    common = _mapping(explanation.get("common"), "common explanation")
    target_data = _mapping(common.get("target"), "common target")
    _require_target_matches_observation(target_data, observation)

    if source_mode == "snapshot":
        if snapshot_reference is None or snapshot_created_at is None:
            raise StudentGradeJustificationValidationError(
                "snapshot mode requires exact snapshot reference and timestamp."
            )
    elif snapshot_reference is not None or snapshot_created_at is not None:
        raise StudentGradeJustificationValidationError(
            "current mode must not carry snapshot authority."
        )

    rows: list[TeacherReportRow] = []
    target = observation.target
    _append(rows, "Scope", "Student ID", target.student_id)
    _append(rows, "Scope", "Class", target.class_id)
    _append(
        rows,
        "Scope",
        "Academic Period",
        f"{target.target_period.school_year} / {target.target_period.period_id}",
    )
    _append(rows, "Scope", "Calendar revision", target.calendar_revision)
    _append(rows, "Scope", "Calculation family", target.calculation_family)
    _append(rows, "Grade", "Effective Grade", common.get("effective_grade"))
    _append(rows, "Grade", "Effective source", common.get("effective_source"))
    _append(rows, "Grade", "Base result status", common.get("base_result_status"))
    _append(rows, "Grade", "Base Grade", common.get("base_grade"))
    _append(rows, "Grade", "Freshness", common.get("base_freshness_status"))
    _append(
        rows,
        "Grade",
        "Freshness reasons",
        _joined(common.get("base_freshness_reasons")),
    )

    policy = _mapping(common.get("policy"), "Grade policy explanation")
    policy_ref = _mapping(policy.get("policy_reference"), "Grade policy reference")
    _append(rows, "Policy", "Title", policy.get("title"))
    _append(
        rows,
        "Policy",
        "Identity",
        f"{policy_ref.get('policy_id')} r{policy_ref.get('policy_revision')}",
    )
    rounding = _mapping(policy.get("rounding"), "rounding")
    _append(
        rows,
        "Policy",
        "Rounding",
        f"{rounding.get('quantum')} / {rounding.get('mode')} / "
        f"{rounding.get('application_stage')}",
    )

    override = common.get("selected_override")
    _append(rows, "Override", "Applicability", common.get("override_applicability"))
    if override is None:
        _append(rows, "Override", "Selected decision", "none")
    else:
        override_map = _mapping(override, "selected override")
        _append(rows, "Override", "Selected decision", override_map.get("decision"))
        _append(
            rows, "Override", "Replacement Grade", override_map.get("replacement_grade")
        )
        _append(rows, "Override", "Rationale", override_map.get("rationale"))
        _append(rows, "Override", "Decided at", override_map.get("decided_at"))

    family = target.calculation_family
    if family == "conventional":
        _add_conventional_rows(rows, explanation)
    elif family == "standards_based":
        _add_standards_rows(rows, explanation)
    elif family == "hybrid":
        _add_hybrid_rows(rows, explanation)
    else:
        raise StudentGradeJustificationValidationError(
            "unsupported Grade calculation family."
        )

    if source_mode == "snapshot":
        assert snapshot_reference is not None
        assert snapshot_created_at is not None
        _append(rows, "Checkpoint", "Snapshot ID", snapshot_reference.snapshot_id)
        _append(
            rows,
            "Checkpoint",
            "Snapshot created at",
            snapshot_created_at.isoformat(),
        )

    explanation_digest = (
        exact_explanation_sha256
        if exact_explanation_sha256 is not None
        else hashlib.sha256(_canonical_mapping_bytes(explanation)).hexdigest()
    )
    observation_digest = (
        exact_observation_sha256
        if exact_observation_sha256 is not None
        else grade_preview_observation_sha256(observation)
    )
    sources = list(_common_sources(observation))
    sources.extend(
        (
            TeacherReportSourceReference(
                "grade_observation",
                f"{target.student_id}:{family}",
                observation_digest,
            ),
            TeacherReportSourceReference(
                "grade_explanation",
                f"{target.student_id}:{family}",
                explanation_digest,
            ),
        )
    )
    if snapshot_reference is not None:
        sources.append(
            TeacherReportSourceReference(
                "reporting_snapshot",
                snapshot_reference.snapshot_id,
                snapshot_reference.snapshot_sha256,
            )
        )

    return compose_teacher_report_preview(
        report_kind="student_current_grade_justification",
        title=f"Student Grade Justification — {target.student_id}",
        class_id=target.class_id,
        target_period=target.target_period,
        calendar_revision=target.calendar_revision,
        source_references=tuple(sources),
        generated_at=generated_at,
        summary=_summary_lines(common, observation, source_mode, snapshot_reference),
        columns=(
            TeacherReportColumn("section", "Section"),
            TeacherReportColumn("item", "Item"),
            TeacherReportColumn("value", "Value"),
        ),
        rows=tuple(rows),
        diagnostics=_diagnostics(common, source_mode),
    )


def _live_explanation_payload(
    explanation: CurrentGradePreviewExplanation,
) -> tuple[dict[str, object], GradePreviewObservation]:
    if isinstance(explanation, ConventionalGradePreviewExplanation):
        return (
            conventional_grade_preview_explanation_to_dict(explanation),
            conventional_grade_observation(explanation),
        )
    if isinstance(explanation, StandardsGradePreviewExplanation):
        return (
            standards_grade_preview_explanation_to_dict(explanation),
            standards_grade_observation(explanation),
        )
    if isinstance(explanation, HybridGradePreviewExplanation):
        return (
            hybrid_grade_preview_explanation_to_dict(explanation),
            hybrid_grade_observation(explanation),
        )
    raise StudentGradeJustificationValidationError(
        "unsupported current Grade explanation family."
    )


def _add_conventional_rows(
    rows: list[TeacherReportRow],
    explanation: Mapping[str, object],
    *,
    section_prefix: str = "Grade Items",
) -> None:
    _append(rows, "Calculation", "Conventional mode", explanation.get("mode"))
    for raw in _list(explanation.get("items"), "conventional items"):
        item = _mapping(raw, "conventional Grade Item")
        identity = _mapping(item.get("grade_item"), "Grade Item identity")
        title = str(identity.get("title") or "Grade Item")
        value = (
            f"action={item.get('action')}; state={item.get('source_state')}; "
            f"earned={item.get('earned')}; possible={item.get('possible')}; "
            f"percentage={item.get('percentage')}; "
            f"reasons={_joined(item.get('reason_codes')) or 'none'}"
        )
        _append(rows, section_prefix, title, value)
    formula = _mapping(explanation.get("formula"), "conventional formula")
    _append(
        rows,
        "Calculation",
        "Formula result",
        f"unrounded={formula.get('unrounded_grade')}; "
        f"rounded={formula.get('rounded_grade')}",
    )
    _add_reason_rows(rows, explanation.get("reasons"), "Grade reason")


def _add_standards_rows(
    rows: list[TeacherReportRow],
    explanation: Mapping[str, object],
    *,
    section_prefix: str = "Standards",
) -> None:
    target_scale = _mapping(explanation.get("target_scale"), "target scale")
    _append(
        rows,
        "Standards profile",
        "Target scale",
        f"{target_scale.get('scale_id')} r{target_scale.get('scale_revision')}",
    )
    for raw in _list(explanation.get("standards"), "standards"):
        standard = _mapping(raw, "standard explanation")
        nested = standard.get("nested_proficiency_explanation")
        grade_item_count = 0
        if isinstance(nested, Mapping):
            grade_items = nested.get("grade_items")
            if isinstance(grade_items, list):
                grade_item_count = len(grade_items)
        value = (
            f"proficiency={_proficiency_display(standard)}; "
            f"action={standard.get('action')}; "
            f"freshness={standard.get('freshness_status')}; "
            f"participating Grade Items={grade_item_count}; "
            f"reasons={_joined(standard.get('reason_codes')) or 'none'}"
        )
        _append(rows, section_prefix, str(standard.get("standard_id")), value)
    formula = _mapping(explanation.get("formula"), "standards formula")
    _append(
        rows,
        "Calculation",
        "Standards aggregation",
        f"strategy={formula.get('aggregation_strategy')}; "
        f"calculated={formula.get('actual_calculated_result_count')}; "
        f"minimum={formula.get('minimum_calculated_results')}; "
        f"rounded={formula.get('rounded_grade')}",
    )
    if formula.get("selected_profile_band_id") is not None:
        _append(
            rows,
            "Standards profile",
            "Selected profile band",
            f"{formula.get('selected_profile_band_id')} "
            f"[{formula.get('selected_profile_band_minimum_grade')}, "
            f"{formula.get('selected_profile_band_maximum_grade')}]; "
            f"adjustment={formula.get('profile_adjustment')}",
        )
    _add_reason_rows(rows, explanation.get("reasons"), "Standards reason")


def _add_hybrid_rows(
    rows: list[TeacherReportRow],
    explanation: Mapping[str, object],
) -> None:
    _append(rows, "Calculation", "Hybrid status", explanation.get("status"))
    conventional = _mapping(
        explanation.get("conventional_component"),
        "hybrid conventional component",
    )
    standards = _mapping(
        explanation.get("standards_component"),
        "hybrid standards component",
    )
    for component, label in (
        (conventional, "Conventional component"),
        (standards, "Standards component"),
    ):
        _append(
            rows,
            "Hybrid",
            label,
            f"status={component.get('source_status')}; "
            f"action={component.get('action')}; "
            f"weight={component.get('configured_weight')}; "
            f"contribution={component.get('weighted_contribution')}",
        )
    _add_conventional_rows(
        rows,
        _mapping(conventional.get("breakdown"), "hybrid conventional breakdown"),
        section_prefix="Hybrid Grade Items",
    )
    _add_standards_rows(
        rows,
        _mapping(standards.get("breakdown"), "hybrid standards breakdown"),
        section_prefix="Hybrid Standards",
    )
    formula = _mapping(explanation.get("formula"), "hybrid formula")
    _append(
        rows,
        "Calculation",
        "Hybrid formula result",
        f"unrounded={formula.get('unrounded_grade')}; "
        f"rounded={formula.get('rounded_grade')}",
    )
    _add_reason_rows(rows, explanation.get("reasons"), "Hybrid reason")


def _add_reason_rows(
    rows: list[TeacherReportRow],
    value: object,
    label: str,
) -> None:
    if not isinstance(value, list):
        return
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        code = raw.get("code")
        detail = {
            key: item
            for key, item in raw.items()
            if key != "code" and item not in (None, [], ())
        }
        rendered = (
            str(code) if not detail else f"{code}: {json.dumps(detail, sort_keys=True)}"
        )
        _append(rows, "Reasons", label, rendered)


def _append(
    rows: list[TeacherReportRow],
    section: str,
    item: str,
    value: object | None,
) -> None:
    rows.append(
        TeacherReportRow(
            f"row_{len(rows) + 1:03d}",
            (section, item, _display(value)),
        )
    )


def _summary_lines(
    common: Mapping[str, object],
    observation: GradePreviewObservation,
    source_mode: StudentGradeJustificationMode,
    snapshot_reference: ReportingSnapshotReference | None,
) -> tuple[str, ...]:
    if source_mode == "current":
        first = (
            "Current live justification resolved from Meridian's selected Grade "
            "authority with optimistic currentness checks."
        )
    else:
        assert snapshot_reference is not None
        first = (
            "Historical justification bound to frozen ReportingSnapshot "
            f"{snapshot_reference.snapshot_id}; current Grade state was not replayed."
        )
    freshness = f"Selected Grade freshness is {observation.base_freshness_status}."
    if observation.base_freshness_reasons:
        freshness = (
            f"Selected Grade freshness is {observation.base_freshness_status}: "
            + ", ".join(observation.base_freshness_reasons)
        )
    return (
        first,
        "Evidence/proficiency detail summarizes existing Grade explanation provenance; "
        "raw protected student work is not reproduced.",
        f"Grade policy produced base status {common.get('base_result_status')} with "
        f"base Grade {_display(common.get('base_grade')) or 'none'}.",
        f"Teacher override state is {common.get('override_applicability')}; effective "
        f"Grade is {_display(common.get('effective_grade')) or 'none'} from "
        f"{common.get('effective_source')}.",
        freshness,
    )


def _diagnostics(
    common: Mapping[str, object],
    source_mode: StudentGradeJustificationMode,
) -> tuple[TeacherReportDiagnostic, ...]:
    result: list[TeacherReportDiagnostic] = []
    if common.get("base_freshness_status") == "stale":
        result.append(
            TeacherReportDiagnostic(
                "grade.stale",
                "warning",
                "Selected base Grade is stale relative to current Grade basis.",
            )
        )
    if common.get("effective_grade") is None:
        result.append(
            TeacherReportDiagnostic(
                "grade.nonnumeric",
                "info",
                "No numeric effective Grade is available in this exact state.",
            )
        )
    if source_mode == "snapshot":
        result.append(
            TeacherReportDiagnostic(
                "report.historical_snapshot",
                "info",
                "Historical mode uses frozen snapshot authority, not current state.",
            )
        )
    return tuple(result)


def _common_sources(
    observation: GradePreviewObservation,
) -> tuple[TeacherReportSourceReference, ...]:
    source_data = grade_override_source_result_reference_to_dict(
        observation.base_result_reference
    )
    reference = _mapping(source_data.get("reference"), "Grade result reference")
    digest = reference.get("result_sha256")
    if not isinstance(digest, str):
        raise StudentGradeJustificationValidationError(
            "Grade result reference lacks result_sha256."
        )
    target = observation.target
    sources = [
        TeacherReportSourceReference(
            "grade_result",
            f"{target.student_id}:{target.calculation_family}:"
            f"r{reference.get('result_revision')}",
            digest,
        ),
        TeacherReportSourceReference(
            "grade_policy",
            f"{observation.policy_reference.policy_id}:"
            f"r{observation.policy_reference.policy_revision}",
            observation.policy_reference.policy_sha256,
        ),
        TeacherReportSourceReference(
            "grade_policy_activation",
            f"{target.target_period.school_year}:{target.target_period.period_id}:"
            f"r{observation.activation_reference.activation_revision}",
            observation.activation_reference.activation_sha256,
        ),
    ]
    override = observation.selected_override_reference
    if override is not None:
        sources.append(
            TeacherReportSourceReference(
                "grade_override",
                f"{target.student_id}:r{override.override_revision}",
                override.override_sha256,
            )
        )
    return tuple(sources)


def _proficiency_display(standard: Mapping[str, object]) -> str:
    level_id = standard.get("proficiency_level_id")
    if level_id is None:
        return "no current judgment"
    nested = standard.get("nested_proficiency_explanation")
    if isinstance(nested, Mapping):
        scale = nested.get("scale")
        if isinstance(scale, Mapping):
            levels = scale.get("levels")
            if isinstance(levels, list):
                for raw in levels:
                    if (
                        isinstance(raw, Mapping)
                        and raw.get("level_id") == level_id
                        and isinstance(raw.get("label"), str)
                    ):
                        return f"{raw.get('label')} ({level_id})"
    return str(level_id)


def _require_target_matches_observation(
    target: Mapping[str, object],
    observation: GradePreviewObservation,
) -> None:
    period = _mapping(target.get("target_period"), "target period")
    expected = observation.target
    if (
        target.get("class_id") != expected.class_id
        or target.get("student_id") != expected.student_id
        or period.get("school_year") != expected.target_period.school_year
        or period.get("period_id") != expected.target_period.period_id
        or target.get("calendar_revision") != expected.calendar_revision
        or target.get("calculation_family") != expected.calculation_family
    ):
        raise StudentGradeJustificationValidationError(
            "rich explanation target does not match exact Grade observation."
        )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StudentGradeJustificationValidationError(f"{label} must be a mapping.")
    return cast(Mapping[str, object], value)


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise StudentGradeJustificationValidationError(f"{label} must be a list.")
    return cast(list[object], value)


def _display(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _joined(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _canonical_mapping_bytes(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "StudentGradeJustificationAmbiguousError",
    "StudentGradeJustificationError",
    "StudentGradeJustificationEvidenceRequiredError",
    "StudentGradeJustificationMode",
    "StudentGradeJustificationNotFoundError",
    "StudentGradeJustificationValidationError",
    "build_current_student_grade_justification",
    "build_snapshot_student_grade_justification",
    "compose_student_grade_justification",
]
