# Meridian #126 H1 — operative attempt consumer audit and Report 9 handoff

**Baseline:** `1319c414b9b9e48eab5679349e928287b929a455` (G2 accepted)
**Authority:** Meridian issue #126 §8–11; Report 9 generation issue #133; native multi-attempt statistics issue #134
**Evidence level:** Source audit and focused installed-Core/source-checkout regression only. No official Meridian wheel or mixed Suite composition attested.

## 1. Authority separation

The correction/reassessment workflow writes immutable #30 and #31 decisions only through existing #122 action/CAS controls. Its authoritative current-use reader is `attempt_selection_storage.resolve_current_attempt_selection`; `attempt_decisions_workflow.project_attempt_decisions` retains typed `not_applicable`, `unsupported_attempt_shape`, `no_decision`, `selected_none`, `selected`, and explicit stale distinctions. Historical source observations remain immutable; neither attempted sequence nor ScoreForm value makes an attempt current.

`menu_teacher_verified_continuation.verify_student_current_use` loads a *freshly authorized* publication and assessment roster, verifies exact #30 pointer and historical digest, requires a matching #31 pointer for multiple selected attempts, and filters to #29 **operative included evidence from each selected attempt** before opening the established Standards menu. It is an ephemeral reviewed-menu gate, not a transferable authorization for other consumers or a calculation.

A single selected attempt needs no synthetic reassessment relationship. Multiple selected attempts require an independently current explicit #31 relationship; `retain`, `replace`, `combine`, and `recency` do not themselves supply arithmetic, weights, scales or a Grade.

## 2. Consumer census and exact present behavior

| Consumer | Current boundary on audited baseline | Qualification / gap |
| --- | --- | --- |
| `attempt_decisions_workflow.project_attempt_decisions` | Uses canonical `resolve_current_attempt_selection(..., authorized_snapshot=...)`; typed statuses and candidate identity | Source implementation accepted under earlier #126 slices; not a reporting selection by itself |
| `menu_teacher_verified_continuation.verify_student_current_use` | Fresh authorization + exact current #30, requisite #31, #29 included evidence per selected attempt | F3B1 contract and accepted regression; still revalidate at a future calculation/use |
| `guided_proficiency._selected_evidence_item` | Exact item ID and student identity in the given projection | Does not itself choose a #30 attempt; existing #110 guided item path must not be represented as general multi-attempt consumer qualification |
| `guided_proficiency.build_guided_proficiency_preview` | One explicit `StandardAggregationCandidateBinding` with `attempt=None`, passes to the established #34 preview builder | Do not claim #126 automatically chooses an attempt or computes multi-attempt proficiency; further owner integration when necessary |
| `report_menu_execution.LiveReportMenuExecutor._build` | Routes `benchmark_analysis_instructional_response` to `build_current_benchmark_analysis` and `_benchmark_item_observations` | Report 9 remains separately owned by #133/#134 |
| `benchmark_current_analysis.build_current_benchmark_analysis` | Reads current Grade Item inclusion, publication and authorized producer result inventory; it does **not** filter observations by current #30/#31 selection before the item observer | Valid source inclusion is not identical to resolved operative attempt selection |
| `benchmark_current_analysis._student_results` | For two distinct observed attempt targets, reports no single native score rather than picking first/highest/latest; absent evidence is `not_assessed`, not 0 | Conservative but not a complete #30-derived current score |
| `report_menu_execution._benchmark_item_observations` | Counts question results only for a student/work with exactly one observed native attempt target; two observed attempts produce no item contribution | Intentional fail-safe omission; **#134 still must count exact selected Attempt 2 where authorized**, without counting the invalid original |

No audited consumer was modified in H1. This is an explicit inventory of supported and unsupported behaviors, not a claim that Report 9 or proficiency calculation already uses resolved current attempts.

## 3. Reproducible handoff to #134 — 29 students × six questions

Synthetic one-work/six-question case: 28 students have one native attempt with all six correct. Student 29 has **Attempt 1 = 0/6** (six incorrect historical responses) and **Attempt 2 = 6/6** (six correct responses), with the correction relationship *teacher-reviewed*, not producer-certified. In the complete #126 acceptance scenario, #30 explicitly selects Attempt 2 as operative; Attempt 1 remains immutable but excluded from academic use.

**Current Report 9 observer behavior (H1 test):** each of questions 1–6 reports **28 correct, zero incorrect**. The multi-attempt student's data are omitted entirely because both native targets remain observed. No highest/latest attempt is silently chosen; the selected correction is also not represented.

**Required #134 behavior after separate implementation:** independently resolve exact, authorized and operative #30 selection for this student/work/publication; include only the six eligible current Attempt 2 responses; each question should then count **29 correct, zero incorrect**. Exclude Attempt 1. For absent, stale, disallowed, ambiguous or multiply selected attempts lacking a valid #31 treatment, omit/invalidate with an explicit reason; do not fabricate a score or silently combine records. ScoreForm question facts, Quillan results, Concord Scores and non-score states require producer-specific contract checks.

### Owner/contract input to #134

- Exact `ModuleWorkRef`, class/Grade Item, student, publication, cache/snapshot and authorization purpose.
- Resolved current #30 decision revision/digest plus eligible evidence **per exact selected native attempt**; source and selection currentness checked at report execution time.
- Where multiple attempts are selected, the exact #31 revision/digest and linked #30 digest, plus a supported semantics-specific consumer interpretation (not an assumed average).
- Result classification: current operative single, current operative multi with explicit #31, `selected_none`, no decision, stale/unverifiable, unsupported native shape, or missing publication/authorization.
- Item observations must be deduplicated by source/attempt/question identity, with ambiguous/blank states preserved and counts derived exclusively from selected operative evidence.

## 4. Exact #133 handoff

Report 9's *generation prerequisite and error handling* are separately owned by #133: valid ScoreForm Grade Item, active marking period and authorized publication should yield a usable preview **without a ReportingSnapshot or completed student proficiency decisions**, or give a precise prerequisite-specific blocker. H1 does not change the report builder or claim this installed end-to-end behavior passed. #134 begins after the generation path is independently usable.

## 5. Regression and nonclaim ledger

`tests/test_issue126_sliceh1_report9_attempt_consumer_handoff.py` pins the existing conservative item-observer and student-summary semantics. It includes: one-attempt counts; omission of multi-observed targets; 29×6 corrective counterexample; native blank/ambiguous; duplicate conflicting correctness; separate work identity; two distinct attempts at different **or identical** scores; absent-evidence `not_assessed` without fabricated zero.

These are **bounded tests describing current behavior**, not endorsement of the #134 omission as the end-state. They intentionally fail if the report engine changes without coordinated test/contract review; #134 must update the relevant tests and provide new positive selected-correction acceptance. No production Report 9 engine, writer, policy, Grade or independent producer repository changes are authorized by this H1 slice.

**H1 exit:** Exact source census, executable gap witness and issue-specific acceptance contract delivered. **H2** to address any remaining #126-owned consumer interfaces without entering #133/#134 report implementation. **I/J** remain responsible for installed native 29×6, mixed-wheel and final matrix acceptance.
