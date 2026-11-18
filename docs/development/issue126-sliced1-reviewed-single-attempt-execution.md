# Meridian #126 — Slice D1: reviewed single-attempt execution

**Baseline:** #126 Slice C `afcf4061f71dbd578cace99e50555c9290cd2a60` accepted on Windows. **Branch:** `126-verified-correction-attempt-reassessment-management`.

## Scope and authority

`meridian/attempt_resolution_execution.py` binds a **typed, exact Slice C teacher interpretation** to the existing #30 immutable authoring/current-selection workflow through #122's `prepare_attempt_decision_action` and `PreparedGuidedAction.apply`. It is an orchestration layer; it owns no academic persistence, journal, source revision, producer correction classification, new policy, or current pointer.

D1 supports an already-qualified, **single selected attempt** for a teacher-reviewed correction or a separate performance. It covers the synthetic 0/6 original -> 6/6 manual-correction case only when the corrected observation is **already operative eligible** under #29. Earlier excluded evidence remains historical. A producer `scan_review_manual` origin remains a producer-origin fact, not producer-certified causation. The typed teacher testimony becomes an attributable, explicitly described **free-text** rationale in the immutable #30 decision, not a new certified relation field. The teacher's chosen policy must already be current and exactly match the explicitly chosen preset; D1 never sets it up silently.

The same #122 port, receipt, CAS and canonical author/select services already used by the older guided attempts UI remain the *sole* write path. An actor's saved profile does not grant publication authorization.

## Execution stages (no hidden academic action)

1. **Prepare (read-only):** require the exact authorized current publication/work, authorized roster student, typed interpretation, one current eligible selected candidate, original evidence from that same source, and a #30 current/policy basis consistent with the teacher's review.
2. **Policy gate (read-only):** use `plan_guided_attempt_policy`; only `ready` is accepted. Creation, revision or selection of a policy is a separate consequential decision, never bundled secretly.
3. **#30 preview (read-only):** use existing `preview_guided_attempt_decision` with exact selected observation and the Slice C rationale. Compare its student/work/snapshot, policy, actor, selected observations, current revision and rationale to the teacher review.
4. **#122 bind (read-only):** `prepare_attempt_decision_action` verifies membership, academic-period/policy/source dependencies, CAS and actor; its candidate digest, revision and prior pointer must match the #30 preview.
5. **One confirmation:** `apply(confirmed=False)` runs canonical #122 cancel with zero academic writes; `apply(confirmed=True)` rereads current roster/source/eligibility/selection before delegating to #122's single confirmed author/select. Precommit divergence blocks before calling the writer.
6. **Post-write independent observation:** only after #122 reports `applied` or `already_applied` with a verified current target, independently reload the canonical #30 selection. Check exact revision/digest, projection snapshot, operative status, and selected observation(s), not merely count or success text. Only then report `applied_current` / `already_current` and permit continuation toward Standards review.

`written_not_current`, `current_unverified`, `recovery_required`, CAS/source conflicts and indeterminate exceptions must never be presented as applied or retried blindly. The #122 journal is an auxiliary recovery record, not academic authority. Multiple internal author/select stages are not an atomic cross-record transaction. A failed post-write canonical read is **uncertain**, not a rollback.

## Explicitly unsupported by D1

- **Two or more selected current attempts:** require an explicit #31 `retain`, `replace`, `combine` or `recency` relationship. D1 raises `AttemptResolutionNeedsReassessment` *before* any action binding or writing. D2 will implement reviewed #30/#31 composition and conditional recovery. Do not let an incomplete pair appear resolved merely because #30 was selected.
- **New policy:** no implicit creation, selection or revision. The teacher first resolves policy in the established service.
- **Full interactive menu:** Slice F owns the exception queue, single-task teacher prompts, and navigation. A CLI/window entry is not claimed by this service alone.
- **End-to-end classroom acceptance:** D1 tests use synthetic 29×6 read-only data with controlled service seams and the existing canonical regressions. They do not establish actual installed native ScoreForm/Quillan/Concord D4, eight CI jobs or final A1–A18 closure.
- **Typed historical correction link:** #30 rationale preserves attributed words but cannot be reparsed as a structured producer-certified or historical teacher relationship. Any new schema requires a separate demonstrated necessity and exact-source authorization/transition audit.

## Focused tests and no-collateral-change claim

`tests/test_issue126_sliced1_reviewed_single_decision.py` verifies cancellation, one confirmation, current canonical exact-match, already-applied identity, wrong digest, changed selected revision, roster/source drift, policy not ready, foreign source/actor, incomplete writer outcome, unresolved intent and missing #31 relation. The tests use a fake port for **write-outcome branching**; actual authoritative #30/#122 storage and concurrency behavior is covered by the existing repository suites, not reinvented here.

No source data, Grades, Standards associations, proficiency, reports, SIS or Notes records are written by this bridge. Slice E will extend recovery/idempotency composition and native interruption qualification; this document does not claim that work complete.

## Progress/ledger

- A1 assessment entry: pending F.
- A2 separation of source and teacher facts: source-level B/C and D1 rationale path; D4 native release not yet qualified.
- A3 correction: D1 single-attempt orchestration composed; actual installed teacher journey pending F/I.
- A4 genuine retake: single selected supported; multi-selected needs D2.
- A5 multi-selected #31: **not yet implemented in D1; blocked without writes**.
- A6–A12: targeted source coverage only; full gates open.
- A13 cancel: #122 canonical cancel delegated and controlled unit test; native storage check pending.
- A14–A15 interruption/idempotency: source-level truth statuses; extended E pending.
- A16–A18 shared UI, downstream, official wheels and final CI: pending G–J.

**Next:** D2 — explicit multi-selected #30/#31 staged composition, reviewed treatment and honest partial state. No claim of a complete Slice D until D2 is independently qualified.
