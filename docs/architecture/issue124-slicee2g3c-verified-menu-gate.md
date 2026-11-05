# Issue #124 E2G3C — Verified menu handoff

Provide a separate opt-in `reconstructed_context_loader` to the existing
interrupted-save menu. Its callback must return a reviewed preview, saved
actor and zero-argument fresh canonical review loader. This is **not** a
storage deserializer. The E2G3B read-only gate verifies the reviewed intent
and original receipt before E2G2's exact action binding and E2G1's literal
`RESUME` confirmation. An invalid tuple or failed check consumes the
composite request without falling back to another selector in that turn.

Without the new callback the existing #122 and E2G2 behavior is unchanged.
No caller is registered automatically. No automatic resume, new action or
immutable academic writer is introduced.
