# Issue #125 A4 acceptance matrix

Status: **A4 satisfied within supported boundaries.** This closure is limited
to Review Exceptions First. It does not qualify A16, the final PR SHA, the
full repository validator, or merge readiness.

The required baseline was commit
`dcedf36a8552b8019cfa3a683149ca3911ee34cc`. Its PR #144 CI run
`43735571387` completed successfully with all eight Ubuntu/Windows jobs for
Python 3.11, 3.12, 3.13, and 3.14. All changes and qualification were performed
in a separate worktree.

All classroom data are synthetic. The isolated installed run used released
official Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6, Concord 0.3.2, and the
rebuilt Meridian 0.4.2 candidate. It loaded Meridian from the installed wheel,
not the source tree, and completed **77 passed, 0 failed, 0 skipped**.

## Exception matrix

| Condition | Authoritative boundary | Observed teacher-facing outcome | Executable evidence | Result |
| --- | --- | --- | --- | --- |
| Unreadable or invalid ScoreForm scan | ScoreForm 0.13.0 `RoutedScoringOperationResult` and guided scan summary | `Failed safely`, zero complete/recorded attempts, and no result targets. The failure occurs before an academic-result publication, so Meridian does not invent an evidence row, score, or eligibility state. | Installed `test_installed_unreadable_scoreform_scan_fails_before_result_publication` | Qualified at the producer boundary. |
| Conflicting original/corrected attempts | ScoreForm public result exporter, manifest generator, publication supersession service, and Meridian authorized projection | The real successor publication presents the competing native targets as `multiple items same native target` and routes to **Review attempts (#126)**. No first/newest attempt is selected. | Installed `test_installed_scoreform_corrected_attempt_teacher_walkthrough_is_exception_first` | Qualified. |
| Missing or unknown roster subject | Core roster plus the authorized projection | Unknown attribution is shown as unmatched evidence and routed to **Review Core roster** without exposing or fabricating a student identity. Safe unrelated evidence remains selectable. | `test_unknown_roster_evidence_is_exposed_without_fake_attribution`; `test_unknown_student_source_identity_is_not_printed` | Qualified. |
| Duplicate exact source identity | Exact publication/cache/snapshot/item identity invariant | Projection raises a scope-integrity error before a review model exists. The menu now says source integrity could not be verified, directs source/publication and roster review, and never enters batch selection or prints the raw identifier. | `test_duplicate_exact_source_identity_stops_before_teacher_selection` | Qualified; one minimal menu correction. |
| Multiple ambiguous native targets | Exact `(subject, target, result kind, standards)` grouping | Every competing item is unsafe and routes to #126; unrelated exact targets remain safe. | Installed ScoreForm corrected-attempt walkthrough; `test_competing_attempts_are_not_silently_chosen`; `test_repeated_result_kind_on_same_target_blocks_every_competing_item` | Qualified. |
| Concord evidence-only work | Concord 0.3.2 activity orientation and academic-result publication service | Concord refuses academic-result publication. The teacher inbox says no current academic evidence publication was found; no fictional publication, setup correlation, action receipt, or eligibility row is created. | Installed `test_installed_concord_evidence_only_cannot_fabricate_result_publication` | Qualified at the availability boundary. |
| Concord local criterion | Concord score kind and target reference | `local_score` remains local. A `core_student` target is associated only with that authoritative student target; no Standard is invented. | Installed student case of `test_installed_concord_group_is_not_student_attributed` | Qualified. |
| Concord group/shared evidence | Concord `concord_group` target reference | The item remains `local_score`, `concord_group`, has no student subject, is excluded from individual batch candidates, and routes to **Review individual evidence** as shared/non-student evidence. | Installed group case of `test_installed_concord_group_is_not_student_attributed` | Qualified. |
| Withdrawn publication | Current publication lifecycle and canonical eligibility resolution | Source/eligibility withdrawal stays distinct, routes to **Review source/publication**, and is neither a candidate nor an implicit Exclude. | `test_withdrawn_source_never_becomes_batch_eligible`; `test_source_lifecycle_statuses_are_faithful_and_never_batch_safe` | Qualified. |
| Stale Grade Item membership | Canonical membership and selected eligibility history | Routes to **Review Grade Item setup** while the existing decision history remains unchanged and unavailable for silent replacement. | `test_uncertain_current_state_is_named_and_fails_closed`; `test_membership_not_included_routes_to_grade_item_setup` | Qualified. |
| Conflicting or unverifiable selection | Canonical selected pointer, disposition, and source currentness | Routes to exact-integrity stop or Advanced individual-action recovery. It never silently replaces a prior decision. | `test_conflicting_selection_history_is_stop_not_replacement`; `test_uncertain_current_state_is_named_and_fails_closed`; `test_advanced_and_individual_recovery_routes_remain_explicit` | Qualified. |
| Denied or restricted authorization | Publication authorization before protected projection/cache access | The three installed producer cases remain blocked as **Evidence Not Ready** with an access reason. Publication identifiers and protected evidence details are absent, and the active publication is not selected. | Installed ScoreForm/Quillan/Concord `test_missing_cache_permission_never_claims_ready`; H3D9 denial/redaction checks | Qualified. |

## Installed teacher walkthrough

The installed ScoreForm walkthrough uses the producer's public exporter to add
a corrected manual attempt, public manifest generation, and the public
supersession service. Meridian then enters through the existing selected
assessment/Grade Item context and uses its normal discovery, authorization,
projection, and assessment menu.

Observed results:

1. The Grade Item is selected through the existing teacher context.
2. **Assessment Exceptions — Read-Only Queue** appears before any exact batch
   selection screen.
3. Competing attempts show a readable reason and **Review attempts (#126)**.
4. All competing source IDs are disjoint from the safe candidate IDs.
5. Safe evidence from unrelated native targets remains available.
6. Existing H3D3/H3D5 tests preserve pagination and B/M/Q unwinding.
7. Choosing `B` at exception review leaves the complete workspace byte-for-byte
   unchanged, including eligibility pointers and action receipts.
8. Publication IDs and producer source markers are absent from the transcript;
   the installed denied cases likewise remain redacted.
9. **Review individual evidence** and the **Advanced individual-action recovery
   screen** remain explicit exits.
10. No test path changes source attempts, roster identity, Standards mapping,
    grades, publication state, or eligibility state implicitly. The only
    publication supersession in the walkthrough is an explicit producer setup
    operation completed before Meridian review begins.

## Minimal production correction

The exact-source invariant already rejected duplicate item identities, but the
assessment menu collapsed that integrity failure into the same generic message
used for an unavailable/expired authorization. The menu now catches
`AssessmentEligibilityReviewScopeError` separately, gives a redacted
source-integrity explanation and source/publication/roster next action, and
states that no evidence entered batch selection. No projection classification,
authorization, storage, or recovery mechanism changed.

## Supported-contract limitations

1. An unreadable ScoreForm scan has no result target and no academic-result
   publication. Its authoritative teacher explanation is ScoreForm's guided
   scan summary, not a manufactured Meridian exception row.
2. Concord evidence-only work cannot publish an academic-result set. Its
   authoritative teacher state is source/publication unavailability in the
   inbox, not a fabricated scored item.
3. A Concord local criterion can be student-targeted or group-targeted. Meridian
   preserves the released target reference; it does not infer an individual
   from group membership or convert the local criterion into a Standard.
4. Whole-assessment authorization denial precedes protected projection. There
   are therefore no per-student denial rows or protected aggregates to display.

## Qualification record

Source-only focused command (native gates intentionally disabled):

```text
python -m pytest -q \
  tests/test_issue125_a4_acceptance_closure.py \
  tests/test_issue125_h3d3_exception_queue_navigation.py \
  tests/test_issue125_h3d5_status_route_terminal_matrix.py \
  tests/test_issue125_h3d9_teacher_acceptance.py \
  tests/test_issue125_sliceg1_native_source_acceptance.py
59 passed, 12 skipped in 0.97s
```

Installed command used all three native gates and the five focused modules above
plus `tests/test_issue117_producer_teacher_acceptance.py`:

```text
PDS_ISSUE125_A4_NATIVE_TEST=1
PDS_ISSUE125_NATIVE_TEST=1
PDS_ISSUE125_H3D9_NATIVE_TEST=1
python -m pytest -q <six focused installed modules>
77 passed in 34.12s
```

Focused static checks:

```text
ruff check meridian/menu_teacher_assessment_eligibility.py \
  tests/test_issue125_a4_acceptance_closure.py \
  tests/test_issue125_sliceg1_native_source_acceptance.py
All checks passed!

python -m mypy meridian/menu_teacher_assessment_eligibility.py
Success: no issues found in 1 source file
```

## Artifact identities

| Distribution | Version | SHA-256 |
| --- | --- | --- |
| `pds-core` | 0.6.6 | `d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301` |
| `scoreform` | 0.13.0 | `4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7` |
| `quillan` | 0.10.6 | `7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb` |
| `pds-concord` | 0.3.2 | `825b27bc6142cc8bce8c3b9381a3337c4a55e983f6f3f2e7e4b1a10f980e83ce` |
| `pds-meridian` candidate | 0.4.2 | `02d4e30c5e6e93fdcc47427e985aa8fb492dbf0e82e8f17c5c89e19130fa6dc8` |

The full repository validator was deliberately not repeated; it remains the
final PR gate. No Core, Suite, ScoreForm, Quillan, or Concord source was changed.
