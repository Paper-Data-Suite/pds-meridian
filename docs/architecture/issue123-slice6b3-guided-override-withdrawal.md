# Meridian #123 · Slice 6B3 — Guided withdrawal decision authoring

## Purpose

Provide a low-density, named teacher route for **recording** an immutable withdrawal of a currently selected, active Grade replacement. This is a **Meridian-owned domain** workflow, not a Core shared terminal, Notes, or classroom management implementation. Core #237's reusable terminal primitives are deliberately not duplicated or integrated by this slice; their adoption is a separately qualified producer step.

## Teacher journey

1. Choose the current Core-verified class, marking period, roster student, and exact Grade calculation family using existing teacher choice catalogs. Retained period hints are revalidated, not treated as academic authority.
2. Enter a **withdrawal rationale** and resolve teacher attribution using the existing saved-identity adapter's exact `Teacher actor ID: ` input contract. No student or academic canonical identifier is typed.
3. Preview one immutable `withdraw` candidate created by the current `withdrawal_previewer`. This requires an **already-selected active override**; a selected withdrawal, absent selection, invalid source, stale dependency, and an inconsistent candidate fail closed.
4. Reverify class/period/student witnesses and the exact preview before any consequential action. Require uppercase `WITHDRAW` to record the candidate.
5. Commit **only** through the existing `withdrawal_committer`, which invokes Meridian's canonical write workflow. No selection committer is called.
6. On a confirmed write, explain that the **prior selected replacement remains current** until the teacher visits **option 6** and explicitly selects the newest authored withdrawal decision with `USE`. No implied automatic activation, retry, rollback, or base Grade recalculation.

## Ownership and invariants

- `meridian/menu_teacher_named_override_withdrawal.py` adds a presentation/controller adapter. Domain source integrity, selected-reference validation, CAS and immutable storage remain the responsibility of established Meridian services.
- Teacher attribution is carried through the existing explicit prompt string (read from a named constant to preserve the Issue #110 AST-frozen raw-ID surface); there is no parallel identity service or bypass of a one-action override.
- A reviewed candidate is correlated to class, student, academic period, calendar revision, calculation family, selected active reference and digest, source result, author, rationale, and candidate digest before `WITHDRAW`.
- A changed second preview aborts before committing; the domain committer independently verifies its canonical state.
- A pre-write failure says **no write was attempted**. A failure or unknown outcome after invoking the committer says a decision **may have been stored** and directs the teacher to inspect history. These outcomes are not conflated.
- Never display canonical student IDs, actor IDs, storage paths, or hashes in the routine screen; keep existing Advanced routes for exact technical details.
- Preserve direct CLI and all existing menu choices 1–7 unchanged. New teacher-context option **8** is the only route addition; legacy no-context menu remains untouched.
- Preserve B/M/Q exception propagation and the frozen 49-route / 9-report audit.

## Qualification

18 isolated focused tests cover accepted and rejected flows, selected override and withdrawal semantics, zero-grade prior values, currentness, source/actor/candidate binding, exact confirmation, uncertainty, and Advanced continuity. Ruff, mypy and installed-repository regression checks execute in the guarded delivery runner and must succeed before commit or push.

**Dependencies:** existing Core marking-period/roster catalogs, Meridian teacher navigation and existing Override authoring/selection domain services. No capability requirement beyond those already installed for #123. Core #237 is implemented but downstream UI migration is outside this slice.
