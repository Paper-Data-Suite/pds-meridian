# Meridian #117 — Slice 6: teacher-authored benchmark plan revisions

## Acceptance boundary

This slice supplies the **planning authoring/persistence service**, not the
interactive Report 9 editor. The Reports menu integration and label-based
student/group selection follow in the next slice. The current Report 9
preview continues to be built from an explicitly selected reporting checkpoint.

`benchmark_plan_authoring.py` consumes a **verified**
`TeacherReportPreview` from that reader path and a canonical Core class-roster
identity set supplied by its caller. It does **not** select evidence, authorize
students, guess proficiency, read producer manifests, open external documents,
or contact an SIS. The caller must reauthorize the protected evidence and
revalidate the selected checkpoint before inviting the teacher to save.

The supported teacher-authored decisions are:

- Interpretation notes for the benchmark and teacher-selected strong/challenging
  standard judgments, requiring an explicit basis and affirmation that results
  are comparable. These judgments never replace native standard observations.
- Optional planning/bubble groups with verified class-roster membership; they
  are **not** calculated proficiency categories.
- Explicit reteach/revisit/small-group/enrichment/extension strategies, target
  selection, planned and reevaluation dates, rework/retest items, status, and
  teacher reflection.
- Follow-up/reassessment date, instrument, observations, continued support,
  and comparison basis. No causal improvement assertion is inferred.

The four-section report preserves original native evidence rows, selected
proficiency, all original report source digests, diagnostics, and period
identity. Teacher text goes into separate `zz_plan_*` rows; revised plans
replace those rows rather than appending duplicate responses. When teacher
responses are removed, the relevant section explicitly reports no response or
follow-up recorded. When the source benchmark lacks per-standard/item data,
the planner displays an honest unavailable-information placeholder instead
of fabricating the missing section.

## Immutable revision persistence

`save_teacher_benchmark_plan` requires the exact `SAVE PLAN` confirmation.
An absent predecessor digest authorizes **creation only**; an existing plan can
only be updated with the exact SHA-256 of its latest stored revision. A revision
cannot change teacher, assessment, class, target period, calendar revision,
source references, original evidence rows, report summary, columns, or
source diagnostics. Revision writes delegate to the existing protected,
append-only plan store and retain predecessor digest lineage.

The saved `currentness` is `unverified` until actual current authority is
requalified. Saving a plan does not mark it implemented, approved, submitted,
complete, or reflected in Genesis or another SIS.

## #134 conditional viewer audit

The current `menu_reports.py`, `teacher_report_output.py`,
`report_export_cli.py`, and `report_export_commit.py` did not expose a default
Open/viewer-launch call during targeted inspection. This authoring slice does
not introduce one. Teacher-selected external export destinations retain their
own existing controls. A future Open action must use a Core-qualified handoff
and deep-workspace installed acceptance; do not mistake launch acceptance for
a verified viewer display.

## Focused qualification

- One pytest pass over new authoring/revision tests and existing benchmark
  engine/storage tests.
- Ruff for the new module/tests; strict mypy on the new module.
- `git diff --check`; no clean/dirty duplicate suite or installed matrix.
- All fixtures are synthetic and use a temporary workspace; no classroom or
  OneDrive data is used.
