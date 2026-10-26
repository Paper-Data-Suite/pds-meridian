# Meridian #123 — Slice 9F: Explain a Saved Planning Preview / Selected Review by Name

## Goal

Add an ordinary teacher-context **Explain** menu option 14 that replaces manual preview IDs with a bounded, verifiable, human-readable choice. Preserve Advanced option 6, the existing CLI, and the authoritative `planning_signal_preview_review_explanation` service.

## Teacher path

1. Reuse or select a verified Core class. A class selection is only a navigation hint, never an evidence authorization.
2. Browse saved #39 previews with the exact historical #38 derivation, #37 policy title, Core marking-period label, Standard, roster count, and band count. An immutable preview has **no latest/current pointer**. Similar names must not be resolved by guessing.
3. Choose the intended preview by its opaque option identity; internally keep the exact preview digest and the explicitly selected review revision/digest for that derivation (if any).
4. Revalidate class, preview, derivation, historical policy and calendar provenance, and selected review pointer before and after the existing explanation read and before displaying technical detail. Any missing or changed witness fails closed.
5. Display the authoritative service's path status, live currentness, selected review decision, coverage, and export eligibility. Technical IDs, digests, and policy revision are shown only after `T`.

## Authority and safety boundaries

- All previews are read using `list_grouping_signal_preview_ids` and `load_grouping_signal_preview`, not filesystem enumeration by the UI.
- Exact #38 source lineage is loaded through `load_grouping_signal_derivation_reference` and verified against the existing #123 9E derivation catalog, which itself checks the policy and Core academic calendar.
- Selected review state is obtained using `load_current_grouping_signal_review`; its revision and SHA-256 are included in the navigation witness. The selected review may belong to a different saved preview of the same derivation; the existing read-only Explain service determines applicability and export eligibility.
- The existing `ExplainMenuDependencies.planning_preview_review` reader remains authoritative for currentness, review applicability, and eligibility. This slice adds no independent grading/grouping logic or review-selection operation.
- Preview title and status are presentation labels, not canonical authority. Duplicate indistinguishable descriptions are blocked by the shared choice service; there is no silent selection by list ordering.
- A missing review is normal and must not be represented as approval. A stale preview, changed selected review pointer, unverifiable calendar or missing source fails closed with a teacher-readable refresh message.
- Live currentness and eligibility are **point-in-time**, not ongoing attestations. No review, export, grouping, academic result, or external SIS/Concord state is written.

## Regression contract

Focused tests cover ordinary/technical displays, absent review, cancellations, stale scope and witness, error redaction, B/M/Q propagation, bounded catalogs, source-digest binding, and append-only Explain menu integration. The legacy Advanced path remains unchanged. The only change to the established `_planning_preview` adapter is the addition of two *technical-only* selected-review pointer fields, used to validate its output against the selected record.

## Qualification

Runner requires exact feature-branch HEAD `9b1a36562db725bc8f03406c3e50b01d5f9e1a00`, original Explain menu Git blob, payload SHA-256, clean working tree, and unchanged remote. It runs Ruff, strict mypy, frozen #123 navigation audit, focused tests, and three regression groups. It commits/pushes without force only upon successful qualification; no reset or rebase is performed.
