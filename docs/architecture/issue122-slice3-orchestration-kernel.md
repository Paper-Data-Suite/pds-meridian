# Issue #122 — Slice 3: exact-action orchestration kernel

**Baseline:** `Paper-Data-Suite/pds-meridian` branch at `fd9c8e0267779fce777236f5e40a610947fb10ca` (Slices 1 and 2 committed).

**Scope:** domain-port contract and synthetic kernel qualification. **Not yet integrated into teacher menus**. The guided-menu adoption belongs to Slices 4–6; installed and cross-producer acceptance belongs to Slice 7.

## Operation contract

`meridian.teacher_action_orchestration` exposes:

- `TeacherActionDomainPort`: one *typed, domain-specific* canonical authority boundary. The caller supplies the selected `ActionKind` and a concrete adapter over existing Meridian authoring, CAS selection, and reloading workflows. This is not an arbitrary command runner; the seven allowed record families are fixed by the Slice 1 contract.
- `apply_reviewed_teacher_action(preview, port, store, confirmation="APPLY")`: exactly one affirmative confirmation, no additional prompt. Non-`APPLY` is side-effect-free. An ordinary action requires `make_current=True`; advanced write-only routes remain separate.
- `resume_exact_teacher_selection(preview, port, store, confirmation="RESUME")`: **separate explicit recovery**. It never calls immutable authoring. It requires an exact durable receipt, a canonical history digest match, still-current basis, and the original expected selector.

A concrete port **must implement**:

1. `revalidate_basis`: independently recheck stable actor identity, one-use actor override binding where applicable, current evidence authorization, publication, class/work registration, grade-item membership, school-year/calendar/period, policy, and source lineage. A profile is attribution, never permission. This method does not assume the target selector remains at its prewrite baseline after a successful selection.
2. `observe`: independently reload immutable exact revision and digest, current selector/digest, and live basis applicability from canonical stores; **never** trust a receipt or callback result as a substitute.
3. `persist_exact`: delegate to existing immutable authoring/locking/CAS validation. Verify the exact reviewed candidate and return its typed revision identity; **never** guess a new revision, read raw producer work, or touch producer storage.
4. `select_exact`: create the existing domain-specific selection preview for the **exact written revision** and invoke the authoritative CAS commit, enforcing every source/currentness precondition. No “select latest” fallback.

Only the seven typed action kinds in #122 are supported. Each domain adapter must carry the actual authoring preview object and relevant authorized snapshot, rather than reconstructing an academic decision from just the action fingerprint. This interface deliberately leaves adapter implementation for domain-integration slices.

## Sequence and durable boundaries

A normal APPLY is:

1. Validate kind/scope and confirmation; run live basis revalidation and canonical observation before any mutation.
2. Compare receipt identity, and refuse blind replay when a canonical target is already present without proven active receipt progress.
3. Prepare the **bounded** Slice 2 receipt; record a second `receipt_prepared` checkpoint via generation CAS to claim execution **before** calling immutable authoring. Competing attempts for the same action ID do not start a second write. A crashed writer's journal must be reconciled instead of automatically replayed.
4. Revalidate the exact basis and prior selector again immediately before authoring.
5. Write exact immutable revision through the domain service. Check returned family, target identity, revision, and digest; record canonical observed identity as a durable `write` checkpoint.
6. Revalidate live authorization/dependencies and exact target/current selector. Record `selection_preview`, then delegate to the authoritative domain preview+CAS selection method for that exact revision.
7. Record `selection_commit`; reload selected canonical state, revision digest, and dependencies, independently. Record `verification` and `receipt_finalized` only when these checks pass; then return `applied`.

**Not cross-record atomic:** Existing canonical stores and selection pointers remain authoritative. Slice 3 handles **one target record family per action**. When Grade Item creation and membership linkage form a larger teacher operation, subsequent domain/menu slices must compose steps with truthful per-family progress and cannot report the composite as applied when only a subset is current.

**Lock scope:** Receipt generation CAS claims an action ID. It does not replace individual canonical domain locks or serialize all class grading. Concurrent writer protection for different action IDs and shared target histories remains the domain authoring and selection services' responsibility.

## Failures and recovery

| Failure window | Guaranteed behavior |
| --- | --- |
| Cancel before APPLY | No journal or academic writes and no background confirmation |
| Preflight/authorization conflict | No immutable write, no new selection; refresh review |
| Unsafe/absent journal path before write | Fail closed before authoring |
| Crash or exception after immutable write | Inspect exact canonical history; never assume absence/rollback; if target verified and selector unchanged, report written-not-current |
| Receipt persistence after write fails | Report recovery required; do not claim selection success or silently continue |
| Selection preview conflict/changed source | Stop; report verified partial state or review-required |
| Selection CAS failure or interrupted commit | Independently observe selector; never infer successful commit from return or journal alone |
| Post-selection verification fails | `current_unverified` or conflict/recovery as appropriate, never fabricated applied |
| Exact already current on restart | Revalidate canonical record/basis and return already applied; no new immutable revision |
| Exact write present, selector still on reviewed baseline | Explicit RESUME may select exact decision after revalidation, with **no rewrite** |
| Different/newer selected revision | Conflict requires new review; never overwrite another teacher's later choice |
| Receipt absent/corrupt or history mismatch | No automatic replay, unsafe deletion, or silent selection |

Both successful and failed steps use machine-readable checkpoints when the journal remains healthy. An audit-write failure after canonical mutation is an indeterminate/recovery result rather than false success. The teacher-facing status copy continues to come from Slice 1's contract; the Slice 4 menus will connect this to meaningful teacher choices.

## Boundaries and follow-ups

- There is **no direct teacher-menu wiring** and no claim that `apply_reviewed_teacher_action` alone completes a real Grade Item, eligibility, attempt, standards, or proficiency workflow; the domain adapters are required and will be qualified individually.
- Do not modify canonical immutable stores, producer publication records, the Core registry auditor, #121 user preferences/profile, or legacy advanced author/select CLI semantics.
- In Slices 4–6, bind actual authoring preview objects, stable actor profile fingerprints, authorised snapshots, typed CAS previews and current selected record reloading. Add fault injection for each real adapter; exercise one-confirm input in actual menus.
- In Slice 7, validate installed wheels against qualified Core, check Windows/Linux release gates, run the full suite **once** at final release candidate and in CI, and document real machine architecture (do not assume ARM64 from x64).

## Focused acceptance

`python -m pytest -q tests/test_issue122_slice3_teacher_action_orchestration.py` uses synthetic class-local workspace fixtures and in-memory simulated canonical domain ports only. It covers 34 assertions/cases spanning the seven families, cancellation, retries, crash/restart, conflicts, actor binding, receipt integrity/error paths, unknown currentness, and independently verified success. The real-workspace installed and cross-repository gates are intentionally deferred.
