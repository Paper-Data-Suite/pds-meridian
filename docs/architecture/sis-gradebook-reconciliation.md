# SIS Gradebook Reconciliation — Issue #111 Slice 7

Slice 7 adds the first report-specific teacher workflow on top of the common
Issue #111 report foundation.

The report is vendor-neutral. A teacher-owned immutable external-gradebook
mapping revision binds one class/reporting period and one exact proficiency
scale revision to explicit proficiency-level -> external-value representations.
A system label such as `Genesis`, `Skyward`, or another gradebook name is display
metadata only; Meridian has no vendor-specific runtime dependency and performs
no SIS/LMS write.

Current reconciliation state is derived only from explicitly selected Academic
Period proficiency results. A standard with no selected result is absent from
ordinary current output. Meridian never converts absence into Developing or a
low numeric value.

A selected calculated result maps through the exact external-gradebook profile.
A selected insufficient result has no safe external value and is
`REVIEW_REQUIRED`.

Change states are:

- `NEW` — current selected proficiency has no prior checkpoint value;
- `CHANGED` — current proficiency or external representation differs;
- `UNCHANGED` — current proficiency and representation match exactly;
- `REVIEW_REQUIRED` — a safe current representation is unavailable, including a
  prior checkpoint judgment with no current selected judgment.

The canonical full reconciliation `TeacherReportPreview` is itself the exact
standards checkpoint for the next run. Changed-only output is a display view and
is never accepted as a prior checkpoint. This avoids misusing the existing
`ReportingSnapshot` Grade-row contract for standards judgments it does not
contain.

CLI surfaces:

```text
meridian reports reconciliation profile ...
meridian reports reconciliation preview ...
```

`preview --view auto` shows the full current view when no prior checkpoint is
provided and defaults to changed-only when one is supplied. JSON checkpoint
output remains complete even when the teacher display is changed-only.

CSV, TSV, Markdown, and canonical JSON are local representations only. A local
artifact does not prove that an external gradebook received or accepted it.
