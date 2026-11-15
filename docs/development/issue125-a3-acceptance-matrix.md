# Issue #125 A3 acceptance matrix

Status: **A3 satisfied within documented supported boundaries.** This matrix is
limited to faithful status and coverage presentation. It does not qualify A4,
A16, the final PR SHA, or merge readiness.

Qualification used synthetic identities and the released official wheels:
Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6, Concord 0.3.2, and the Meridian
0.4.2 candidate. The installed focused run loaded Meridian from the candidate
wheel and completed **46 passed, 0 failed, 0 skipped**. The broader affected
source run completed **148 passed, 0 failed, 4 skipped**; those four tests are
the explicit official-wheel gates that executed without skips in the installed
run.

## Matrix

| Scenario | Authoritative available source | Expected teacher-facing behavior | Executable evidence | Result |
| --- | --- | --- | --- | --- |
| Roster student with no returned result | Core roster plus the authorized producer projection | The released readers identify represented results but do not attest why an unrepresented roster student is absent. Show **Projection coverage unavailable (never zero)** and do not make the student batch-safe. | `test_absent_roster_projection_is_unknown_never_zero_or_inferred`; installed Quillan `test_installed_quillan_absent_roster_coverage_remains_unknown_not_zero` | Qualified within producer boundary; no-result is not invented. |
| Evidence outside teacher authorization | Publication authorization decision before projection/cache access | Show a redacted access blocker. Do not open protected evidence or show student identities, evidence labels, or protected aggregates. A student-scoped grant cannot satisfy the whole-assignment request. | `test_authorization_or_projection_unavailable_fails_closed`; `test_denied_roster_scope_never_exposes_student_or_source_labels`; Issue #115 authorization tests | Qualified; there is no per-item unauthorized row because authorization precedes protected projection. |
| Evidence not projected by producer | Authorized projection inventory and inbox support status | An empty inventory is **no projected evidence**. For an individual absent roster student, the installed contracts cannot distinguish no returned result from not projected, so show coverage unavailable instead of choosing either explanation. Unsupported/unavailable readers remain blocked in the inbox. | `test_empty_projection_is_not_relabelled_as_no_returned_result`; Issue #110 reader support tests | Qualified within producer boundary. |
| No eligibility decision | Canonical eligibility resolver: `no_decision`, with no selected pointer | Count and label `eligibility no decision`; it is a candidate only when source, membership, roster attribution, and pointer state are otherwise safe. | `test_distinct_current_statuses_are_neither_missing_nor_grades` | Qualified. |
| Currently included | Canonical selected decision and operative resolution | Count and label `eligibility included`; do not call it a grade. Existing decisions require explicit reviewed replacement. | `test_distinct_current_statuses_are_neither_missing_nor_grades` | Qualified. |
| Currently excluded | Canonical selected decision | Count and label `eligibility excluded`; route to existing-eligibility review and never silently include it. | `test_distinct_current_statuses_are_neither_missing_nor_grades` | Qualified. |
| Currently pending | Canonical selected decision | Count and label `eligibility pending`; route to existing-eligibility review and never silently include it. | `test_distinct_current_statuses_are_neither_missing_nor_grades` | Qualified. |
| Explicitly unsupported | Canonical selected decision | Count and label `eligibility unsupported`; keep distinct from missing projection and source lifecycle. | `test_distinct_current_statuses_are_neither_missing_nor_grades`; `test_absent_projection_is_not_unsupported_result_or_zero` | Qualified. |
| Stale or superseded source evidence | Current publication state plus canonical resolution statuses `included_source_superseded`, `superseded`, and `membership_stale` | Preserve the exact lifecycle or stale-membership label, route to source or Grade Item review, and exclude it from safe batch candidates. A valid `included_source_superseded` resolution is not misreported as pointer inconsistency. | `test_withdrawn_source_never_becomes_batch_eligible`; `test_source_lifecycle_statuses_are_faithful_and_never_batch_safe`; `test_uncertain_current_state_is_named_and_fails_closed` | Qualified. |
| Withdrawn publication or source evidence | Current publication state plus canonical resolution statuses `included_source_withdrawn` and `withdrawn` | Preserve the withdrawal label, route to source review, and never convert withdrawal into teacher Exclude or a safe candidate. | `test_withdrawn_source_never_becomes_batch_eligible`; `test_source_lifecycle_statuses_are_faithful_and_never_batch_safe` | Qualified. |
| Uncertain/inconsistent eligibility or current pointer | Canonical resolver and selected revision/disposition pointer | Label `source unverifiable`, `membership stale`, `selection unverifiable`, or `resolution inconsistent` as applicable; route to stop/setup review and fail closed for selection and replacement. | `test_conflicting_selection_history_is_stop_not_replacement`; `test_uncertain_current_state_is_named_and_fails_closed` | Qualified. |

All coverage/status counts are observations, not scores. No code path in this
matrix converts missing or unavailable evidence into numeric zero.

## Supported-contract limitations

1. ScoreForm 0.13.0, Quillan 0.10.6, and Concord 0.3.2 publish represented
   result records. Their installed public reader contracts do not provide a
   complete Core-roster coverage assertion or an absence-reason field saying
   that an unrepresented student has either "no returned result" or "not
   projected." Meridian therefore reports that distinction as unavailable.
2. Concord `evidence_only` work has no academic-result publication to project.
   It remains an inbox/source-availability boundary and is not manufactured as
   an assessment eligibility row.
3. The current assessment entry requests whole-assignment evidence. A
   student-restricted authorization grant cannot authorize that empty-student-
   tuple request. Authorization denial is therefore a redacted assessment-
   level blocker, not a count of unauthorized student evidence.
4. A future producer may make no-result versus not-projected distinguishable
   only through a released authoritative coverage contract. Meridian must not
   infer that distinction from Core roster subtraction alone.

## Focused artifact identity

The local Meridian 0.4.2 candidate wheel used for the installed run had SHA-256
`debacdda66e26072bb3ac6989a447cc6897ba83bb67bee1ec7586879ca58588d`.
The official dependency hashes remain the release-audit identities recorded in
the Issue #125 acceptance ledger.
