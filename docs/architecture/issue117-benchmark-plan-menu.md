# Issue #117 Slice 7 — Report 9 teacher plan authoring and history

## Integration

The existing **Reports → 9. Benchmark Analysis & Instructional Response** preview has a new `P` option. Unlike Save local copy, it opens a teacher-only planning controller. It derives its source preview from the existing authorized `LiveReportMenuExecutor` and retains the original Report 1–8 menu routes and reporting/export implementation.

### Teacher workflow

1. Select the class, marking period, and assessment through the existing guided selectors.
2. Review the four-section, read-only native assessment report.
3. Press **P** to create or revisit a local benchmark plan. The controller checks current selection and protected-report authority before displaying saved history or accepting a new draft.
4. Enter interpretation, optional explicitly supported standard judgment, student groups, instructional responses, and follow-up observations. Student choices are made using roster names and numbers, never raw subject IDs.
5. See the unsaved teacher-authored summary, then type exactly **SAVE PLAN**. This invokes Slice 6's source-bound append-only revision writer and revalidates source authority immediately before commit.
6. View the latest authorized saved plan and browse historical revisions. Previous versions are never overwritten.

**Scope limitation:** The Slice 6 persisted report rows preserve teacher-visible interpretations but not all roster membership IDs needed for lossless reopening into typed authoring dataclasses. For **editing**, this slice therefore deliberately requires a *complete replacement teacher draft* with clear notice to re-enter groups, responses, and reassessment notes the teacher intends to retain. It never guesses historic student identities, silently drops notes without notice, or overwrites old revisions. A later schema-compatible typed-draft persistence enhancement can enable prefilling all fields.

## Data, authorization and privacy

- History is not listed or displayed when the current report fails `revalidate`; historical source rows must still match the selected authorized report.
- Core class roster is loaded from canonical workspace context. No manual typed student identifiers, inferred students, external rosters, or unverified PDF paths.
- Report generation and `revalidate` already enforce the existing publication authorization and projection-cache policies. This controller does not introduce producer-data access, a local-opener call, PDF/HTML launch, shell command, or external export.
- All plan saves are explicit and local, source-bound with `report.source_references`, checked against the exact most recent revision digest by the Slice 6 storage engine.
- Saved plan currentness remains `unverified` until a separate authority check; it is not a claim of district or SIS approval. New instructional observations are teacher-authored, not inferred causal improvement.
- A failed date, scope, policy, roster, or storage validation leaves no plan revision created.

## #134 opening audit

The new controller remains text-only: its operations are in-terminal preview and canonical JSON plan-revision storage. No programmatic Open action or native viewer is introduced. Teacher-selected external export destinations remain governed by their existing commit constraints. The opening audit remains **conditional, not a confirmed Meridian defect**.

## Qualification

Run `test_issue117_benchmark_plan_menu.py`, the Slice 6 authoring regression, and the historical Report menu end-to-end regression; then Ruff, targeted strict mypy and whitespace. No full-suite repetition in this slice. Reserve real installed-wheel/deep-workspace acceptance for the final qualification slice.
