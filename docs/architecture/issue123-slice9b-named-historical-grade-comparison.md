# Meridian #123 — Slice 9B: Compare a current Grade with a named frozen report

**Baseline:** `2e8d63212426d13dd2504779a315618c6b8ab71b` on `123-teacher-first-navigation-existing-menus`.

## Teacher-facing route

In the verified teacher-context Explain menu, choose **10. Compare a current Grade to a saved checkpoint by name**. The existing Advanced comparison remains option 2; the no-context Explain menu remains options 1–8. Choose a verified Core class, marking period, roster student, calculation family, and a named frozen ReportingSnapshot (report definition title, frozen timestamp, row count). Technical identifiers are not requested. The frozen list is bounded and filtered to the exact verified school year, period and calendar revision; an incompatible snapshot is not substituted.

The controller uses the existing frozen-snapshot catalog and exact digest witness, then delegates the request to `ExplainMenuDependencies.snapshot_comparison`, which already uses the protected current Grade explanation, exact `ReportingSnapshotReference`, frozen prior-grade basis, and issue #54 comparison semantics. Missing/unavailable Grades are not interpreted as zeros. The presentation reports relationship, whether changed, canonical reason labels and effective Grade delta; exact identifiers and calculation fingerprint appear only after selecting `T. Technical details / provenance`.

## Safety and contracts

* No Grade recomputation outside the existing comparison provider, no snapshot mutation, no implicit snapshot selection, no academic or SIS writes, and no protected producer reads initiated by the catalog.
* Core-backed class, student and period selection are revalidated before and after comparison and before displaying Technical Details. The historical snapshot's class, period, calendar revision, digest and catalog choice witness are reloaded and checked repeatedly, including after the protected comparison call. Source changes fail closed, with a safe request to refresh.
* Exact `ExplanationPresentation` identity and schema are checked before displaying comparison output; private paths/details are not echoed on operational errors. Existing authorization semantics are enforced by the established comparison provider.
* Technical route 2 and legacy Explain routes 1–8 remain available. The Slice 9A test is corrected to check option 9 is retained without assuming it remains the last menu entry.
* Missing historical target rows remain an explicit comparison-provider error, not a synthesized zero or unrelated row. A historical report built under an earlier calendar revision is intentionally not passed as the same exact Grade scope.

## Qualification

Run Ruff and strict mypy on the changed Explain controller, new named controller and 9A/9B tests, then run the frozen #123 navigation audit, focused 9B and 9A tests and all designated regression groups, including the #110 prompt inventory, legacy Explain, snapshot selection/storage and issue #54 comparison tests. Commit/push only after those workstation gates pass. Runner must require the exact branch, baseline commit, remote SHA, a clean checkout and verified payload archive before modifying anything.
