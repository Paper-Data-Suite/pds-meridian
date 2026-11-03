# Issue #124 - E2G3J: Canonical Grade Item Restart Reconciliation

This test-only slice extends the E2G3I persisted-receipt safety gate with real Core class metadata, real immutable Meridian Grade Item revision and digest files, a real unselected/current pointer, and a real #122 receipt reopened through a fresh store. It proves that the canonical reader detects the pending selection without changing disk, that canceling does not select anything, and that explicit `RESUME` selects **only** the exact existing revision. The post-selection inspection must refuse a second resume, and the original revision JSON and digest sidecar remain byte-identical.

Additional cases cover a later immutable revision, a corrupted SHA-256 sidecar, and an interrupted-save menu reentry against persisted data. The menu harness replaces only the saved-profile actor-check callback so synthetic identity can be used without a real teacher profile; it does not mock canonical Grade Item history, canonical selection, Core class metadata, or the receipt store.

Scope: test and architecture files only; no production code, producer data, student records, or default permissions. This exercises the existing #122 Grade Item restart selector in the real recovery menu, not the entire #124 composite membership/correlation workflow. Further composite-fixture qualification remains required before release.
