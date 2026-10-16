# Meridian #117 — Slice 12: installed Report 9 teacher journey

## Requirement

The previous installed smoke for ScoreForm 0.13.0 and Quillan 0.10.6 validated the guided evidence inbox but did **not** demonstrate that current assessment evidence could reach a teacher-authored benchmark plan. Core 0.6.6 must be qualified through the same installed-wheel boundaries.

## Design

Extend the already-wired `scripts/smoke_program_guided_evidence_issue110.py` used in the existing `scoreform` and `quillan` prepared matrices. Do not create another matrix or venv. After the original guided evidence acceptance, create synthetic, canonical academic metadata, calendar, Grade Item and selected membership in that same producer's fresh workspace; rebuild the disposable Core catalog; navigate Reports → 9 using the actual `LiveReportMenuExecutor`, choose class/period/assessment, open planner (`P`), explicitly `SAVE PLAN`, and verify immutable stored plan and losslessly saved teacher annotations. The plan must carry a publication source but **not** a ReportingSnapshot source. The saved four-section Markdown must render.

The acceptance uses real released producer manifest codecs, real Core publication storage, and live Meridian APIs. It grants only the two read-purpose operations required for the demonstration (`review_evidence`, `teacher_reporting`) through a synthetic acceptance-only authorizer. It does not authorize academic writes, and no production authorization policy changes.

The synthetic CLI journey does not count as physical user acceptance. Actual test execution under installed packages is pending until the six dependency-matrix gate; focused tests only verify its wiring and source contracts.

## Remaining work

1. Equivalent installed Concord academic publication and Report 9 journey (Concord has distinct student/shared semantics).
2. Source-currentness/revocation and end-to-end plan revision/reassessment scenarios.
3. Final clean pytest, package/sdist, six installed matrices, CI, physical work-PC, and v0.4.2 release verification. Do not claim completed checks before their outputs exist.
