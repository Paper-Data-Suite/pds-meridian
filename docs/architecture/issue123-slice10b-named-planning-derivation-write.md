# Meridian #123 Slice 10B — Save Planning Derivation by policy name

## Adoption contract

Adds teacher-context Planning Signal menu option **9. Save Planning Derivation by policy name**. Option 8 remains a read-only readiness check. Options 1–7 remain separate **Advanced** routes and retain their pre-existing raw exact-record command semantics for direct/legacy callers. No new main-menu entry or Core service is introduced.

The teacher chooses an already verified class and an **explicitly selected**, existing #37 policy by policy title, historical Core calendar label, Standard, dimension, band configuration and revision date. The opaque identity and exact selected policy revision and digest remain transient, not a teacher-input requirement.

The controller:

1. Rechecks class, year, current policy revision/digest, calendar-derived label, and chosen identity before readiness and after candidate preview.
2. Invokes the existing `project_planning_signal_readiness` service. If blocked, it displays the existing codes and does **not** invoke the previewer or committer.
3. Uses the existing `preview_planning_signal_derivation_persistence` to prepare one exact #38 candidate without writing. It checks the candidate's policy reference, identity, fingerprint, and contributing/noncontributing counts against the reviewed readiness projection.
4. Displays named policy, Standard, academic period and student counts. Technical policy and candidate IDs/hashes are opt-in via `T`.
5. Requires the exact, case-sensitive `WRITE` confirmation. All other responses cancel safely; `B`, `M`, `Q` obey existing navigation semantics. Before committing, the class and exact policy are revalidated again.
6. Calls **only** the existing `commit_planning_signal_derivation_persistence_preview`, which independently reprojects current readiness and checks the complete originally reviewed candidate against the current source before writing an immutable derivation. The controller does not implement a second write mechanism or weaken compare-and-swap checks.
7. Explains the saved or already-existing disposition. No #39 preview, teacher review or selection, Core signal, CSV file, or Concord grouping is generated.

## Safety and adverse checks

Tests cover every non-WRITE cancellation, blocked readiness, changed active class and academic year, stale selected policy revision, mismatched candidate ID/fingerprint/source reference, impossible counts, hidden technical identifiers, confirmation-time witness drift, existing committed disposition, redacted errors, and `M`/`Q` propagation. The previous Slice 10A test's exact menu-range assertion is made append-safe without weakening its named-route and Advanced invariants.

## Acceptance limits

Slice 10B implements one narrow ordinary derivation-write route. It does not implement named preview creation, diagnostic review, teacher review authoring/selection or Core export; these remain Advanced until later slices. Installed multi-menu journeys and whole-project acceptance are still required before closing #123.
