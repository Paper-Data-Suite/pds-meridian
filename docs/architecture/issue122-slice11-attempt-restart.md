# #122 Slice 11 — exact attempt-decision recovery after restart

## Scope

Extend `R. Review Interrupted Saves` to **attempt decisions**. Do not change the
separate attempt-policy workflow, academic authoring, advanced CLI, producer
files, evidence authorization configuration, or existing immutable revisions.

A journal is not an authorization grant. The exact student is resolved only
from the currently validated Core class roster, and the exact work is resolved
from canonical Grade Item memberships. Neither the student nor the work is
chosen from a journal-supplied plaintext identifier. Both are verified against
original action identity and work-scope fingerprints. The search is bounded
and must yield exactly one pair; changed or removed roster identity fails closed.

## Recovery barriers

Before exposing **RESUME**, recheck:

1. Exact class/workspace, `attempt_decision` family and `make_current` intent.
2. Original **saved** actor profile, attribution and all receipt basis digests.
3. Exact history from revision one through target, immutable target digest and
   original actor; no newer saved decision or divergent target is accepted.
4. Included, currently selected Grade Item relationship and canonical Grade Item.
5. Current Core work registration and exact school-year/period/calendar digest.
6. Current selected attempt policy revision and digest.
7. Fresh access to the *existing exact* projection cache via the configured
   authorizer, producer registry and adapter support; publication must still be
   current/reusable. Never project or write the cache as recovery side effect.
8. Derive currently eligible attempt candidates and require an exact match to
   the stored decision; no inference or automatic choice of the preferred attempt.
9. CAS selector must still match the *original* prior selected revision, then
   post-selection canonical state must independently verify exactly the target.

The port's immutable writer always raises. The only academic mutation is
`commit_attempt_decision_selection_preview` after explicit `RESUME`, routed
through the common #122 orchestrator. Cancellation, absent authorization,
changed roster/policy/eligibility/publication, unknown journal truth, corrupted
journal, selection races, unexpected filesystem entries, or missing target
never authorize a new write or automatic selection.

## Limitations / later work

The action receipt remains privacy-minimal: no student name or attempt content.
This recovery requires the exact student to remain in the current Core roster.
If roster identity was removed or replaced, the teacher must review the source
manually and may not use automatic restart recovery.

Remaining post-restart families: standards association and proficiency result.
Final #122 gate: exact-commit package boundary, sdist, installed wheel with a
qualified Core release, synthetic multi-process recovery/fault injection, full
suite once at qualified final commit, and Linux/Windows CI.
