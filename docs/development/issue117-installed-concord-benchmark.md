# Meridian #117 — Slice 13: Concord installed Report 9 acceptance

**Branch:** `117-universal-evidence-workflow-and-benchmark-completion`
**Target:** Meridian v0.4.2; exact Core v0.6.6 and Concord v0.3.2 wheels.

This slice adds a synthetic installed Concord benchmark journey **inside the existing Concord-only installed qualification matrix**, with no seventh dependency environment. It deliberately does not add ScoreForm or Quillan to the Concord matrix. The compiled candidate Meridian wheel is imported from the prepared venv.

The smoke builds a canonical Concord v1 Academic Result Manifest with one student-backed standards score and one shared-group local score. It uses Concord's published model/serializer, semantic digest, public reader, and capability derivation to validate the native input. Core owns the work registration, publication and disposable catalog. Meridian owns the selected Grade Item/membership, current four-level class scale, report generation, confirmed teacher plan revision and notes restoration.

The shared group score has **no Core student subject**, and must not be counted as the named student's academic evidence. The student-backed standard score remains student evidence. The menu and report must not print the opaque Core publication ID or turn native scaled values into fabricated academic judgments.

## Acceptance boundary

- Fast focused local tests verify runner placement, isolation, explicit `teacher_reporting` grant, native score kinds and wrapper behavior; these do **not** establish installed Concord success.
- The existing six-matrix installed gate executes the new program in a fresh process, fresh synthetic workspace, and prepared **Concord-only** environment with exact released Core and Concord wheels.
- The actual classroom Windows ARM64/OneDrive application check remains a separate manual acceptance step.
- No student submissions or private teacher data are used in CI; all generated data is synthetic.
- The smoke does not create external SIS/LMS updates or assume that an accepted default-app launch guarantees the viewer displayed a file. Core 0.6.6 alias behavior is qualified independently where an actual local opener is exercised.

No historical released artifacts are altered by this slice. Source remains uncommitted until integration qualification.
