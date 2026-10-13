# Evidence Coverage and Grade Checkpoint Comparison — Issue #111 Slice 10

Slice 10 adds the fifth and sixth teacher-report families.

## Evidence Coverage / Missing & Incomplete Evidence

This report is intentionally an attention report, not a submission-verdict
engine. Meridian reports only what its existing authority can prove.

Important distinctions:

- **No current judgment** means no Academic Period proficiency result is
  currently selected for that student/standard.
- **No represented Grade Item result** means the selected Academic Period
  calculation expected that Grade Item but carried no Grade Item proficiency
  result.
- Neither state, by itself, proves that a student never submitted work.
- **Returned before full review** is surfaced only when an already-projected
  evidence/native state is exactly `returned_without_full_review`.
- **Producer-reported missing state** is surfaced only for an explicit projected
  missing-state code; it is not inferred from manifest/result absence.
- Pending, excluded, unmapped, unresolved-attempt, and unresolved-reassessment
  states come from exact stored proficiency provenance.
- Configured minimum evidence/result counts come from the exact stored
  proficiency policies. Thin evidence is not relabeled "insufficient" merely
  because a teacher might prefer more evidence.

The report uses current selected Academic Period proficiency explanations and
their nested Grade Item provenance. It does not request or reproduce raw
protected student work.

Useful filters include student, standard, Grade Item, producer, attention state,
and attention-only mode.

## Grade Checkpoint Comparison

Checkpoint comparison does not implement Grade-difference semantics. It reuses:

- `GradePreviewObservation`;
- `ReportingSnapshot`;
- `reporting_snapshot_comparison`; and
- the closed `GradePreviewComparison` taxonomy.

Supported comparisons:

1. exact ReportingSnapshot -> exact ReportingSnapshot;
2. exact ReportingSnapshot -> live/current Grade report.

Snapshot-to-current uses the existing ReportingSnapshot freeze-preview workflow
to reconstruct the exact live report request, including authorization-gated
projection inputs for conventional/hybrid Grades. The live report is observed
twice; digest movement fails with a currentness conflict.

Teacher-facing states are presentation only:

- `INCREASED` and `DECREASED` require a meaningful numeric delta from the
  existing comparison engine;
- `UNCHANGED` means the existing engine reports no material reasons;
- `NEEDS_REVIEW` means material reasons exist without a meaningful numeric
  direction;
- `NEW_OR_NEWLY_AVAILABLE` and `REMOVED_OR_UNAVAILABLE` correspond to the
  existing `new` / `removed` relationships;
- unavailable-to-unavailable rows are preserved as status without manufacturing
  a synthetic Grade comparison.

All underlying material reason codes remain exactly the existing closed
comparison taxonomy.

## Authority and privacy

Both reports are read-only derived artifacts. They do not create or select
Grades, proficiency results, evidence decisions, ReportingSnapshots, Core
records, producer records, or external SIS/LMS state.
