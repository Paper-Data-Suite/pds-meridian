# Grade and report attention summaries

Issue #58 extends Meridian's issue #43 read-only attention boundary into the
v0.3 Grade and ReportingSnapshot surfaces. The implementation remains a
teacher-work routing projection, not another academic-authority layer.

## Native categories

The native schema is version 2 and retains all issue #43 categories while
adding four bounded Grade/report categories:

- `meridian_grade_result_stale` counts exact selected Grade-result targets and
  routes to `preview-grades` / `open_preview_grades`.
- `meridian_reporting_publication_changed` counts exact selected current-use
  ReportingSnapshot scopes whose frozen Core publication-series authority can
  be proven to have changed, and routes to `snapshots` / `open_snapshots`.
- `meridian_reporting_snapshot_refresh_needed` counts exact selected current-use
  ReportingSnapshot scopes with a safely provable material Grade/report basis
  change, and routes to `snapshots` / `open_snapshots`.
- `meridian_reporting_snapshot_selection_pending` counts exact reporting scopes
  where an immutable `replaces_for_current_use` successor exists while the
  predecessor remains the explicit current-use selection, and routes to
  `snapshots` / `open_snapshots`.

Counts never determine priority. Existing evidence, Grade Item, proficiency,
and calculation attention precedes Grade currentness; ReportingSnapshot
currentness/selection follows Grade currentness; planning remains later.

## Explicit authority only

Issue #58 does not infer current state from filenames, directory order,
timestamps, snapshot age, or "latest" records.

ReportingSnapshots never become attention merely because they are old.

`meridian_reporting_snapshot_selection_pending` depends on the explicit
`replaces_for_current_use` relationship plus the exact current-use selector.
A newer snapshot without that relationship is not selection-pending.

`meridian_grade_result_stale` uses canonical standards-based Grade assembly and
freshness APIs. At the neutral Core v1 operations boundary, conventional and
hybrid Grade freshness is not inferred because those families require
caller-supplied protected work evidence.

`meridian_reporting_snapshot_refresh_needed` reuses issue #54 semantic Grade
comparison and issue #55 frozen ReportingSnapshot bases. The neutral Core v1
request can safely reconstruct standards-based rows. Conventional and hybrid
rows remain outside that authorization boundary. A material standards-row
change can prove that the selected reporting scope needs review; an unchanged
standards subset does not prove that a mixed snapshot is fully current.

`meridian_reporting_publication_changed` compares only Core-owned
publication-series/current-registration authority already frozen into the
selected ReportingSnapshot with current canonical Core state. It does not open
producer-private evidence and does not recompute deployment authorization or
projection reuse policy.

## Privacy and failure semantics

Core v1 receives only privacy-minimal category, label, count, class scope, and
opaque module-owned action routing. Student identifiers, Grades, proficiency
levels, evidence bodies, rationale, digests, and ReportingSnapshot contents are
not projected into the Core attention report.

Successful empty evaluation remains distinct from unavailable evaluation.

Malformed, unreadable, cross-scope, moving-selector, or otherwise unverifiable
canonical state fails closed through the existing issue #43 provider semantics.
Workspace aggregation preserves the existing partial-evaluation contract; an
exact-class integrity failure is never silently converted to empty attention.

Export readiness is intentionally not attention.

Issue #58 defines no `meridian_export_pending`, `meridian_export_ready`,
export-age, or missing-export category. Absence of an ExportReceipt is not
teacher intent. Local transfer remains deliberate teacher-controlled issue #56
work.

## Installed qualification

Final issue #58 qualification runs in the issue #96 prepared Core-only matrix
with exact `pds-core 0.6.3` plus the candidate Meridian wheel.

ScoreForm, Quillan, and Concord remain absent.

The installed smoke persists a real ReportingDefinition, two immutable
ReportingSnapshots, an explicit `replaces_for_current_use` relationship, and an
explicit predecessor current-use selection. It then verifies
`meridian_reporting_snapshot_selection_pending` through both the installed Core
provider and installed `meridian attention` CLI. It also verifies all four new
category/count-unit/destination/action contracts, native schema version 2,
privacy-minimal projection, successful-empty exact-class behavior, partial and
unavailable distinctions, deterministic CLI output, attention behavior
independent of the Issue #59 readiness capability, producer/suite-package
absence, and zero inspection writes.

The current Issue #58 smoke invokes Core's attention capability directly. Issue
#59 separately qualifies Meridian readiness, so this historical attention
acceptance does not constrain whether readiness is present.

Source-level issue #58 tests remain responsible for the other canonical
derivation semantics: standards Grade staleness, standards-safe snapshot
refresh, Core publication-state changes, selector revalidation, and fail-closed
integrity behavior.

## Ownership boundaries

Issue #58 owns Meridian's Grade/report attention facts and stable Core v1
attention-provider behavior. Issue #59 may consume that provider for suite
doctor, launcher, backup, or future readiness integration, but must not redefine
Grade/report attention semantics.

Paper Data Suite issues #20, #22, and #23 remain downstream owners of shared
privacy-minimized attention models, provider aggregation, and the cross-module
Attention Needed presentation. Meridian does not import the suite shell, rank
cross-module work, or expose private storage for shell-side interpretation.

The intended path remains:

```text
Meridian canonical state
-> Meridian native attention
-> Core ModuleAttentionReport
-> Suite provider aggregation
-> owner-routed Meridian action
```

Issue #58 Grade/report attention summaries — implemented and qualified.
