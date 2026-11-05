# Meridian #124 — D2: canonical live action binder (not yet a menu entry)

**Pinned base:** `44808c484582bc2bf7d2f924946990885ffb5810` (D1). D2 adds one additive, UI-independent adapter, synthetic tests, and the required one-module package inventory increment. It does **not** introduce a second data authority, a producer reader, or a generic workflow engine.

## Exact binding and authority

`bind_live_assessment_setup(root, preview, actor=..., dependencies=...)` takes an immutable C1 proposal and #121 attribution. It reloads the fresh C1 review (which itself invokes bounded B1/B2 registration, publication and Grade Item readers) **before preparing any actions**. The binder checks exact class/work, title, registration revision/lifecycle, school year, marking period/calendar revision, publication reference, selected Grade Item identity, purpose/title and required selected revision. Changed source or attribution prevents binding or stops the D1 coordinator before any write. The frozen C1 SHA is a review witness, **not** permission to modify records.

For `create_and_link`, D2 uses the existing `guided_grade_items.preview_new_grade_item` and #122 `prepare_grade_item_action`; it verifies the candidate was neither retargeted nor silently assigned a different title/purpose/revision. D1 invokes that action after **one** user APPLY. After canonical selected-state reread, D2 uses `preview_membership_link` and #122 `prepare_membership_action` for the exact `included` decision and selected academic-period assignment. For `use_existing`, no Grade Item authoring occurs. For `already_ready`, no write action is prepared. There is no second teacher prompt. Every #122 action retains its own persisted receipt, compare-and-swap, selection and currentness checks; D2 never writes those objects directly.

The binder's `after_grade_read` checks exact current Grade Item selection and source conditions before the membership step. `verify_ready` independently reopens B2/B1-derived registered work/publication/Grade Item state and requires **ready** plus the exact selected Grade Item/revision before D1 returns readiness. An applied #122 result alone does not establish composite ready. If a producer publication changes, setup must be reviewed again; no protected manifest bytes, student answers or producer work are opened.

## Deliberate nonclaims

D2 is **not wired into menus** and is not installed-producer qualification. A cancelled D1 APPLY does not execute any academic action, although the D2 *binder itself* performs read-only preparation. The two #122 operations are independently durable, **not atomic**. D2 is a one-shot in-process binding, **not a restartable composite**; if a stage may have written, it is unsafe to construct a new create-and-link plan and replay it. #124 E must add exact cross-process partial-state identification, receipt correlation and resume, and #124 F must wire a single visible confirmation and return-to-origin navigation. No Grade policy activation, proficiency, evidence authorization, attempt selection, weighting or producer mutation is included.

## Qualification cadence

Targeted D2 unit tests verify no-write preparation, one confirmation, exact source rereads, registered-publication drift, both stage failures and selected-state verification. Run changed-file Ruff/mypy, docs, and focused D1/C1/#122/package tests for this slice. Full repository pytest, wheel builds and installed producer matrices are reserved for integration/release checkpoints.
