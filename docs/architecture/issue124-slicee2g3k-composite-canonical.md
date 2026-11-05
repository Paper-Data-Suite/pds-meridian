# Issue #124 — E2G3K: Composite Canonical State Reconciliation

## Scope

Tests only: fixture builds a synthetic, isolated Core class, marking-period calendar,
registered ScoreForm work, canonical Grade Item and included membership. It calls
existing read-only #124 E1/E2D services against *real persisted files*. No
production files or package inventory are changed. No user or student records.

## Qualification evidence sought

1. Exact five-state progression: pristine, immutable Grade Item written but not
   selected, Grade Item selected without membership, included membership written
   but unselected, and fully verified ready relationship.
2. Duplicate read-only inspection of a completed setup changes zero bytes and
   does not append academic history or create additional pointers.
3. Exact E2B correlation survives process-style reopen but grants no replay,
   academic selection or implied teacher confirmation.
4. A durable correlation without an original #122 action receipt does not
   make a separately written Grade Item restart-resumable.
5. Registration revision drift invalidates a formerly ready review.
6. Corrupt membership revision digest cannot be reported as ready.

This increment deliberately does **not** assert complete #122 receipt-bound
Grade Item-and-membership RESUME: no original action binding is synthesized
from a correlation or a canonical file. A subsequent slice must exercise the
exact original #122 actions and their durable witnesses.
