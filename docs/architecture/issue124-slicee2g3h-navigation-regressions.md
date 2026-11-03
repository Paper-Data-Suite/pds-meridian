# #124 E2G3H — Recovery navigation regression gate

This increment adds **tests only** for the newly activated teacher recovery menu. It does not change production code or authorize academic writes.

The synthetic class-local inbox tests exercise B cancellation, malformed and unavailable fresh-review sources, changed canonical review, original-action identity mismatches, and exactly one guarded composite prompt per selected entry. They assert that a handled composite entry does not fall through to a separate #122 selector.

These tests mock canonical persistence and journal dependencies and are therefore an integration/navigation regression gate, **not proof of actual crash-safe recovery on production workspaces**. A later end-to-end fixture should include original persisted receipts, canonical academic selections, and interrupted-process restart transitions.
