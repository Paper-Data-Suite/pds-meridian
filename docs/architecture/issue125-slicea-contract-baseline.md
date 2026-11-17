# Meridian #125 — Slice A: canonical contract and teacher-interaction baseline

**Audit base:** Meridian `main` after #124 squash merge, `fc05b248139ce0eb8b58aadddc0c04cc96677d07`. The #125 working branch begins at this commit. Reconfirm HEAD/remote before executing future slices.

**Purpose:** Freeze the *existing* evidence-readiness, attribution, authorization, and current-selection rules before adding an assessment-scale batch UI. This slice adds only documentation and synthetic baseline tests; it makes no academic writes and is not an implementation of batch acceptance.

## Verified ownership and current integration seams

| Owner | Existing interface | #125 permitted use |
|---|---|---|
| Core | `pds_core.rosters`, `pds_core.classes`, `ModuleWorkRef`, academic work registration, periods and publication records | Read canonical identities and currentness. Do **not** store eligibility in Core or infer a student attribution from names/titles. |
| Meridian #110/#117 | `guided_projection.py`, `publication_authorization.py`, `teacher_evidence_review.py` | Obtain one exact, purpose- and subject-authorized projection. Preserve shared/group and unmatched evidence separately. |
| Meridian #29 | `EvidenceSourceReference`, `EvidenceEligibilityDecision`, storage/current selection, `resolve_current_evidence_eligibility()` | All resulting decisions remain individually immutable, per-source, and CAS-selected. No assessment-global eligibility flag. |
| Meridian #41/#110 | `NewEvidenceReview`, `NewEvidenceRow`, `guided_eligibility.py` | Reuse the existing read-only item inventory and teacher policy choices. No second reader of producer-private files. |
| Meridian #121/#122 | `TeacherActionActor`, `prepare_eligibility_action()`, individual `PreparedGuidedAction.apply()`, receipts and restart | One *UI* confirmation may coordinate multiple individually verified actions. A receipt is not canonical academic truth; no promise of cross-record atomicity. |
| Meridian #124 | Assessment discovery and one-APPLY Grade Item/work/period setup; Evidence Inbox setup route | Enter batch eligibility with retained and revalidated class/work/publication/Grade Item/period. Never silently create a Grade Item in this batch path. |
| Core #236/#237 | Core contract `pds_core.teacher_experience/1`, `teacher_ui` header, `teacher_commands` opt-in parser | Feature-detect installed capabilities. Core `main` currently advertises `terminal.header.v1` and `terminal.notes_command.v1`; neither implies released-wheel availability or Notes storage/menu. |
| Suite #15/#49 | Teacher home, qualified module launching, privacy-minimized attention | No Suite eligibility API, gradebook authority, student-level telemetry, fixed Suite version, publisher signing/service installation, or Notes-to-academic decision bridge. |

## Exact canonical taxonomy

Canonical `EvidenceEligibilityDisposition` (Meridian): **included, excluded, pending, unsupported, superseded, withdrawn**. Teacher-authorable dispositions (`TeacherEligibilityDisposition`): **included, excluded, pending, unsupported**. Superseded/withdrawn are provenance/lifecycle states requiring their separate domain authority, not teacher batch decisions.

`EvidenceEligibilityResolutionStatus` additionally distinguishes **no_decision**, included-but-source-superseded/withdrawn, membership_stale, source_unverifiable, and operative included/excluded/pending/unsupported. A persisted included decision is not automatically *operative*. A missing result is **not zero**, no decision is **not excluded**, and eligibility is **not** attempt selection, Standard alignment, proficiency, Grade, or evidence-read authorization.

The identity of one decision is the exact `EvidenceSourceReference`: Core `ModuleWorkRef` + exact `publication_id` + `cache_key` + `snapshot_digest` + `item_id`, within the selected Grade Item/membership context. Row numbers, same title, student name, Question 1, or same native value are **not** source identities. Corrections/new attempts remain #126.

## Observed single-item workflow before #125

`menu_teacher_evidence.py` -> `run_guided_eligibility_menu()` -> chosen current-included Grade Item -> one exact `item_id` -> disposition -> existing `GuidedEligibilityPolicyChoice` (default teacher-local v1) -> saved/overridden #121 actor and rationale -> reviewed action -> `prepare_eligibility_action()` -> single-record `apply(confirmed=True)` -> reload selected eligibility.

This is one consequential confirmation **per evidence item**. For a *nominal* synthetic shape of 29 students × six question results, there are 174 separately actionable source items, **if** the real published producer inventory contains exactly one item per student/question. This is a baseline shape rather than a guaranteed ScoreForm manifest count; Slice G must measure actual native result counts, interaction counts and teacher time. The tests in this slice create 174 read-only synthetic `NewEvidenceRow` values, not a producer publication.

## Security, state and failure cases to freeze for Slice B–H

1. Before detail projection or selection: current authorized Core publication, reader compatibility and subject-/purpose-scoped access; class/period/Grade Item currentness and operative `included` membership. Never broaden a student-restricted grant by grouping.
2. Preserve Core roster order/display and exact IDs; ambiguous same-name students, missing/unreturned results, unrostered students, non-student targets, Concord groups, invalid/source-stale items and multiple attempts must enter explicit exception routes. No silent first match.
3. A batch selection must enumerate and seal the exact source refs and individual chosen dispositions, policy/version, actor and basis before any mutation. Student-level exceptions expand to a fixed set of listed items, not a future blanket rule.
4. `APPLY` is one teacher confirmation, not one global record: each individual decision goes through existing #122 immutable write, CAS selection and currentness revalidation. Cancellation before confirmation writes zero academic records **and zero #122 receipts**.
5. If any action reports `written_not_current`, `current_unverified`, `conflict_requires_review`, or `recovery_required`, the batch stops before later writes and reports the exact partial scope. Do not mark it complete, rollback immutable history, allocate a new action ID for an uncertain retry, or auto-select a newer source.
6. No automatic zero/Developing, attempt choice, Standard mapping, policy activation, Grade/proficiency computation, producer publication, source correction or authorization grant. Other issues own these.
7. Navigation reuses `B/M/Q`; Core `:notes` requires explicit menu-choice opt-in and must not intercept free-text rationale, data entry, or `APPLY`. Shared Notes/Tasks is not an academic eligibility decision or canonical module attention event.
8. No Core/Suite changes or release assumptions are required to start the Meridian batch implementation; any missing public producer/reader capability must become a narrow owner-specific follow-up, not a direct private-storage import.

## Slice-A qualified evidence and next step

- `tests/test_issue125_slicea_contract_baseline.py`: canonical/teacher status separation; exact source identity; 29×6 distinct-item read-only fixture; no invented current selection; group/non-student separation; honest status accounting.
- Focused regressions in existing eligibility, currentness, #122 restart, #117 authorization and #124 context modules; full validation deferred to #125-H.
- **Next slice: 125-B.** Implement a bounded, immutable assessment-level roster/readiness view by composing the existing authorized `NewEvidenceReview` and Core roster, without any academic write path.
