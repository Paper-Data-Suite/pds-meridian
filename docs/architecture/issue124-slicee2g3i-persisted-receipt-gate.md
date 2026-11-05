# Issue #124 — E2G3I: Persisted Receipt Restart Gate

This slice adds three tests using real durable #122 Grade Item receipt files in a temporary registered class workspace. It exercises menu reopening and verifies unchanged receipt bytes, no legacy fall-through after invalid composite contexts, and no composite prompt without exact durable correlation evidence.

Scope is intentionally read-only: this is a persisted-receipt integration test, **not** a complete canonical Grade Item history/selection test or proof of restart replay safety. E2G3J will build the exact canonical Grade Item fixture and verify pending-selection CAS behavior independently. No production files are modified.
