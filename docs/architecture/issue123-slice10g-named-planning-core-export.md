# Meridian #123 Slice 10G — Core export by saved Planning Preview name

**Baseline:** Slice 10F `911e83f…` on `123-teacher-first-navigation-existing-menus`.

## Adoption

Teacher-context Create Planning Signal adds **14. Export accepted Planning Signal to Core by name**. Existing direct `7. Advanced: Export accepted signal to Core` and uncontextualized seven-operation legacy menus remain unchanged. This completes the *named route* inventory for the seven legacy Planning Signal operations; final cross-menu, prompt, installed-wheel, and adversarial acceptance for #123 remains separate.

The teacher chooses a verified class and an exact saved Planning Preview from bounded, historical, class/year-scoped canonical catalogs. The choice lists policy title, marking period, Standard and cohort counts; it is not authority. Before preview and before commit, the controller reloads the class, preview, derivation, policy and explicitly selected review witnesses. The canonical #40 export preview independently verifies selected **accepted_for_export** review, live derivation currentness, source eligibility and the proposed immutable Core signal. An unselected, rejected, stale or mismatched review is not exported.

The controller generates an opaque `meridian_signal_` UUID-based Core identity internally and assigns the export timestamp using the existing injected clock. Teachers do **not** type canonical IDs or SHA-256 digests. They may opt into `T` to see exact identifiers (including the generated signal ID and created-at time) before confirming, which is important for reconciliation in partial-success cases. There is no new persistent ID cache or authority source.

The teacher chooses **Core + Meridian receipt** or **Core + receipt + optional local CSV**. For CSV, a `.csv` file destination is deliberately entered and shown again in the confirmation; the canonical exporter checks paths, no-overwrite semantics, exact bytes and Core/receipt correspondence. `EXPORT` is required. A blank answer, `B`, or a different confirmation has no write effect; `M`/`Q` unwind according to Core menu semantics. The controller never itself writes Core state, receipts, CSV or Concord state.

## Mutation and failure boundaries

- `deps.export_previewer` (`preview_planning_signal_core_export`) is pure and produces an exact candidate.
- `deps.export_committer` delegates to `commit_planning_signal_core_export` without CSV or `commit_planning_signal_export` with CSV. Core final eligibility revalidation and immutable write belong to these services; the Meridian receipt is separately reconciled.
- Local CSV is a separate, later, nontransactional write. Core and receipt can be durable even if CSV fails. Errors after commit is attempted never claim rollback, absence of a write or unqualified success; the teacher is directed to inspect saved exports and reconcile **the exact same export** rather than generate an unrelated replacement.
- Success requires matching candidate provenance and verified Core/receipt dispositions and hashes; optional CSV must match the generated signal and canonical destination. No external SIS/LMS or Concord grouping acceptance is implied.

## Qualification

The slice adds source-isolated tests for confirmation, destinations, exact scope and review authority, race/stale failures, allowed technical diagnostics, partial-success ambiguity, result validation and old-menu preservation. The guarded runner pins the prior HEAD, remote, source blob, four reviewed anchors and three newly added paths, verifies a checksummed data-only payload, runs Ruff, strict mypy, the frozen 49-route/9-report navigation audit and three regression groups (including #40/#41 export/CSV services). Only after all tests pass does it stage the exact file inventory, commit and push without force. End-to-end installed acceptance remains outstanding under #123.
