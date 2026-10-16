# Issue #117 — Slice 4: Truthful evidence readiness and access recovery

## Defect corrected

The current teacher inbox labels an academic-result publication **Ready to review**
if canonical state, display identity, installed reader, and adapter compatibility
are acceptable. Those conditions do **not** prove that the active Meridian process
has authority to project protected student evidence. A teacher can select that
"ready" publication only to encounter missing or denied authorization.

## Installed teacher behavior

After compatibility succeeds, the normal `load_teacher_evidence_inbox()` path
preflights the *same exact whole-assignment* `project_evidence` / `review_evidence`
scope used by the guided projection flow. If authorization is absent, denied,
or impossible to verify, the evidence stays visible but **blocked**:

- **Evidence access not configured**: no provider in this process; use Main Menu
  **A. Set Up Evidence Access**.
- **Evidence access not granted**: provider denied the exact whole-assignment
  request; review the existing policy and deliberately grant appropriate scope.
- **Evidence access could not be checked**: unexpected provider behavior;
  inspect the deployment configuration rather than assuming approval.

A blocked compatible publication is not removed from discovery. The status
explains how to return to the already implemented explicit-confirmation
setup menu. The teacher does not type Publication IDs, student IDs, cache keys,
or policy IDs during routine recovery.

Reader unavailable/incompatible, canonical drift, unsupported contracts,
withdrawal, and invalid/ambiguous presentation statuses retain priority over
access setup. This avoids suggesting that additional authorization can fix a
missing reader or a withdrawn publication.

## Security and authority

A preflight uses canonical publication and referenced Academic Work Registration,
no private manifest content, and no caches. Its allowed result is **not** an
authorization token and does not bypass either protected boundary. During
actual evidence projection and protected cache loading, the existing providers
MUST independently reauthorize using newly verified canonical state; TOCTOU
changes can still revoke access after a positive preflight. `read_projection_cache`
remains an independently protected operation. Missing or invalid provider output
must fail closed. No user or group identity is inferred from filesystem location.

Legacy direct `project_teacher_evidence_inbox(diagnostic)` callers retain
compatibility-only diagnostics; the installed loader always passes the deployment
provider explicitly. A later slice may unify direct diagnostic read models with
these states without destabilizing existing synthetic support tests.

## Cross-repository viewer audit (#134, conditional)

A targeted source audit of Meridian `menu_reports.py`, `teacher_report_output.py`,
`report_export_cli.py`, and `report_export_commit.py` did not identify a
programmatic local-viewer launch. This is **not** evidence of a Meridian launch
defect or proof that all manual external exports open on deep Windows paths.
If Issue #117 adds report/PDF/HTML Open actions, use Core's subsequently
qualified viewer handoff and exercise actual deep-workspace opening on Windows,
without changing protected evidence access or teacher-selected export destination
constraints. Do not delay this slice for speculative viewer work.

## Qualification

Only focused tests for inbox readiness, guided menu, provider authorization,
and representative teacher-menu composition, then Ruff, targeted strict mypy,
and Git whitespace checks. No repeated dirty-tree full-suite run.
