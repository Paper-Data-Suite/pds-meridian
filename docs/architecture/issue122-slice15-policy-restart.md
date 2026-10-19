# Meridian #122 — Slice 15: attempt-policy restart recovery

**Baseline:** `7622ced3117c0b14816d861551349cd24b52a628`, branch `Paper-Data-Suite/pds-meridian`.

## Contract

- Extend `R. Review Interrupted Saves` to the `attempt_policy` family.
- Discover candidates through a bounded canonical policy-history enumerator. Do not invert hashed paths, use receipt-supplied filesystem paths, fabricate IDs, or trust journal currentness.
- Validate exact class/Grade Item/work/policy identity, contiguous immutable history and SHA-256, actor profile, original `create`/`revise`/`select_existing` intent, academic calendar, included membership, Grade Item, work registration, and original CAS selection pointer.
- For **select-existing**, the saved reviewer may differ from the policy's historical author. Validate the saved actor's current profile and the exact source-intent fingerprint; never rewrite policy history.
- For **create/revise**, require stored author attribution to match the saved reviewer.
- Revalidate current scope again inside canonical policy selection's lock with an optional callback. Legacy policy callers retain their prior behavior.
- Offer **RESUME** only for an interrupted receipt with exact persisted target, an unchanged original baseline and canonical current dependencies. No mutation before confirmation. Selection only; no immutable writer in the restart port.
- If the target is already current, report that status without offering another selection. Corrupt/missing receipts, unknown identities, stale periods/selection/actors, or unsafe files fail closed.

## Tests and release

The focused gate combines the policy restart regression, existing policy Save/Apply, guided attempt, receipt, orchestration, Grade Item, and menu tests. The complete full-suite and installed-wheel acceptance run once after the final qualified commit; none of these tests use real teacher, school, or student records.
