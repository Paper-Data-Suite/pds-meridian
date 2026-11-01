# Meridian #124 — E2C: persist original #122 action identity before APPLY

**Pinned base:** `0efd3c3bab17a66fb4c8e4d0ad9b06ad1b8bb2b2` (E2B). **Changes:** one opt-in non-menu binder, the E2B atomic cross-intent collision check, isolated action-fence tests, this note, and exact package-inventory updates. No new Grade Item or membership authoring engine, menu entry, academic writer, recovery selector or producer-file reader.

## Execution boundary

`bind_correlated_live_assessment_setup(root, preview, actor=..., dependencies=...)` calls the existing D2 read-only binder, then wraps its two `PreparedGuidedAction` objects with genuine subclasses of the #122 action type. **No correlation is written during binding or cancellation**. The frozen D1 composite continues to own the sole teacher APPLY and its fresh C1 source check. A persistent `reviewed` E2A intent is created only on the first confirmed action, after E1's current canonical/receipt inventory permits a fresh setup. The exact #122 grade action ID and candidate hash are durably CAS-bound **before** calling its original `apply(confirmed=True)`; membership is prepared after canonical grade selection and is durably CAS-bound **before** its original #122 `apply`. A use-existing plan starts directly with the membership binding and does not create a Grade Item. Both stages retain their #122 receipts, immutable revision writers and selection CAS.

In addition to the read-only collision scan, E2B's class-scoped `create_reviewed` lock now checks all existing correlation files for competing intents with the same Grade Item identity or the same producer/work identity. This check is performed *inside the lock* to prevent two separate intent hashes racing past the preliminary scan. An identical reviewed correlation remains an idempotent store read, **not** permission for the E2C action wrapper to replay it. Corruption, incomplete files, absence of the exact verified grade action receipt, changed source, overlapping intent, or failed CAS stops before the next academic step.

After #122 reports both actions complete, D2's independent canonical readiness check is supplemented by rereading the stored correlation, E1 canonical recovery inventory, and the complete #122 receipt inventory. The E2A correlation inspector must return `ready_verified`; no result is derived from the correlation file alone. Unknown outcomes retain the already-persisted stage rather than authorizing a second create. Stage persistence and the independently durable #122 academic writes are **not atomic**.

## Remaining limitations

E2C deliberately does not expose a teacher menu, resume a receipt, reconstruct missing records or automatically execute after restart. After an interruption, re-binding a fresh create action is not a recovery path: the original correlation and #122 receipt must be inspected and any explicit exact-selection recovery must be authorized in E2D/E3. The current binder requires saved teacher attribution for write-bearing setups; a preexisting `already_ready` read-only proposal delegates directly to D2. E2C does not authorize evidence, attempts, proficiency, weighting, policy activation or any producer mutation.

## Qualification

Targeted Ruff lint/format, strict mypy for the new binder and modified store, docs check, and focused E2C/E2B/E2A/E1/D2/D1/C1/#122/package tests. Full repository pytest, release wheels and installed matrices are reserved for integrated final checkpoints. The first 19 E2C isolated synthetic tests and 21 E2B storage scenarios were exercised locally; the Windows repository run is authoritative.
