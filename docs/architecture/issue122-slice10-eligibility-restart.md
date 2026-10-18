# Meridian #122 · Slice 10 — Eligibility after-restart recovery

## Decision and authority

A prior Save/Apply may have written one immutable eligibility revision while its current selector remains at the reviewed baseline. This slice adds an *explicit* `RESUME` opportunity to the existing R. Review Interrupted Saves screen, only when the exact prior decision can be reidentified from canonical storage and a newly authorized projection snapshot can be read. **The journal is neither academic truth nor evidence authorization.** This feature never creates a new revision or regenerates a projection.

## Rehydration contract

1. A validated class-local receipt must match the current workspace, original saved actor profile and exact intent basis. Temporary actor overrides cannot be restored.
2. Enumerate bounded canonical Grade Item work relationships and eligibility source histories, requiring exactly one source whose class/work/publication/item fingerprint matches the receipt. Do not show source IDs or student data in the recovery menu.
3. Reopen the exact immutable decision revision and verify checksum, actor, contiguous history without subsequent revisions, membership, current Grade Item revision, current work registration, and the original academic calendar fingerprint.
4. **Before any evidence read or selection**, require a currently configured deployment authorizer, compatible producer/adapter registry, and `load_authorized_projection_snapshot` using the *exact* original publication, cache key, purpose, and empty student scope. Reject unavailable/denied/revoked access, superseded/withdrawn sources, changed snapshot digest, re-projection requirements and all other non-reusable current-use states.
5. Revalidate the canonical eligibility decision against the authorized projection and authored source lifecycle. Build the existing `preview_new_evidence_eligibility_selection` and require its exact digest and expected current revision. Use only `commit_new_evidence_eligibility_selection_preview` and its underlying CAS selector.
6. Reconcile receipt and independently reloaded canonical state. Offer `RESUME` only when the exact target exists, is still valid, and the current pointer still matches the original baseline. `RESUME` is distinct from Save; the immutable authoring method in this restart port always raises.
7. Before committing, re-read the receipt generation, actor profile, authorization, work, policy/sources, and current pointer. After selection, the shared kernel reloads canonical current state before claiming success.

## UI, limitations and testing

The main-menu R route receives the **same active diagnostics/authorizer** configured by A. Set Up Evidence Access. It does not silently load or create an authorization grant. An unconfigured session prints an access-required explanation and does not attempt protected reads. The ordinary single-confirmation eligibility workflow remains unchanged.

Focus regressions cover safe resume, no-writer invariant, cancellation, revoked/changed authorization, revised work/period/membership, later canonical revisions, target digest conflicts, changed attribution, receipt generation changes, and already-current behavior. Synthetic tests do not replace installed-wheel and Windows/Linux qualification. Other recovery families remain inspection-only until exact source authority can be independently reconstructed.
