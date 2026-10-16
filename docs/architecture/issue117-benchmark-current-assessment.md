# Issue #117 — Slice 9: current assessment benchmark without a ReportingSnapshot

## Teacher-facing entry

Reports → 9 → choose Class, Marking Period, Assessment. No prior ReportingSnapshot is needed. The existing selector and preview/export UI are unchanged. The Report 9 executor now derives a read-only four-section report from current Grade Item work memberships and each work's canonical current academic-result publications.

## Security and source contract

1. A current, active Grade Item and explicit included work membership in the chosen academic period are required. Work registration revision must agree with the verified publication.
2. Use the current Core academic publication catalog; verify and authorize each producer publication with purpose `teacher_reporting` before reading its manifest. The guided authorization setup from Slice 2 already grants `teacher_reporting` alongside `review_evidence` when the teacher explicitly confirms.
3. Invoke the existing ScoreForm, Quillan or Concord adapter through the contract-first reader registry. This path does not write projection caches or SIS/LMS/Grade records.
4. Preserve roster-identified student evidence; never allocate Concord shared group scores to an individual without a native student subject.
5. Preserve ScoreForm attempts without automatic selection. Only the existing unambiguous single-attempt question analyzer emits difficult-question denominators. Quillan/Concord standards observations are never converted to artificial multiple-choice questions.
6. Reuse exactly one configured proficiency scale, optionally with selected current Grade Item standard proficiency results. No ordinal averaging, missing-as-zero, or fabricated level assignment.
7. Exact current membership, publication digest, Grade Item revision, selected proficiency result digest, and scale identity are reflected in report sources. The existing executor builds twice to reject a changed preview and reauthorizes/rebuilds before local exports or plan writes.
8. An absent publication yields not-assessed participation rather than zero. Missing results are emitted only if a producer supplies explicit missing-result semantics.

## Deliberate limitations

- No automatic determination that instructional interventions caused a change.
- Membership selection remains an explicit teacher operation. A missing membership, incompatible reader, missing authorization, or ambiguous scale blocks the report rather than fabricating a fallback.
- This slice does not claim installed-wheel qualification or physical classroom acceptance. Those are separate release gates.
- The previous snapshot-based private builder is retained for historic tests, but the live Report 9 route no longer calls it. Reports 1–8 continue their existing engines.
