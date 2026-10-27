# Meridian #123 — Slice 10D: Named Planning Preview diagnostics

**Scope:** Add one teacher-context, read-only Planning Signal route for saved
Preview/Review diagnostics. Preserve all seven exact-ID legacy operations,
including the existing Advanced diagnostics route, unchanged. This slice does
not author/choose a grouping policy, derivation, preview, teacher review, or
Core/CSV export.

## Teacher journey

1. Reuse the verified selected class, or choose a class using the shared
   bounded choice catalog. There is no second technical class-ID prompt.
2. Select a saved Planning Preview from the existing
   `PlanningPreviewChoiceCatalog` (#123 Slice 9F). Display the exact saved
   policy title, historical academic period, Standard, roster size, and the
   state of the *explicitly selected review*. A saved Preview is not itself
   approval to export or a current grouping decision.
3. The existing `PlanningSignalMenuDependencies.diagnostics_projector`
   receives the selected canonical policy ID, Preview ID, and SHA-256 **only
   internally**. Its existing read-only contract produces live currentness,
   band counts, diagnostics, and selected-review applicability.
4. Before any values are displayed, verify the returned projection binds the
   exact selected Preview, derivation, policy revision/digest, class, academic
   period/calendar, Standard, dimension, band count and total roster; verify
   the selected review pointer and the band/coverage arithmetic.
5. Recheck class, saved Preview and explicitly selected review pointer after
   the read and before each display; a change requires refreshed selection,
   never substitution. Technical IDs/digests are disclosed only by **T**.
   **B / M / Q** retain Core navigation semantics.

## Authority and effects

- The immutable #38 derivation and #39 Preview are separate from a mutable
  explicitly selected teacher-review pointer. The ordinary choice's source
  witness and domain catalog are revalidated at the point of use.
- Live currentness is a **read-time observation**, not a durable assertion or
  an export authorization. Diagnostic messages are summaries; student-level
  data is not exported or copied to preferences.
- Only the canonical service projects current status and exact lineage.
  No UI-created policy/Grade/grouping inference, no file or academic mutation,
  no automatic review acceptance or Core/Concord export.
- Preserve `meridian/menu_planning_signal.py` options 1–10 and the no-context
  1–7 compatibility flow. Append option 11 only with teacher navigation.
- The frozen #123 Slice 1 navigation audit (49 routes, 9 guided reports),
  #110 raw prompt quarantine, #121 preferences and #122 recovery remain gates.

## Acceptance/qualification

Add adverse tests for cancellation, exact-witness changes, wrong class/year,
wrong Preview/policy/derivation/review digests, changing selected review,
malformed coverage/bands, privacy-safe error handling, and terminal navigation.
Run existing preview diagnostics/projection, CLI and planning menu regressions;
strict Ruff/mypy; three regression groups; frozen navigation audit and exact
Git stage/status verification. No change to the underlying service contract.
