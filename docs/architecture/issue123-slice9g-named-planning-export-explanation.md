# Issue #123 · Slice 9G — Named Planning Export Explanation

## Scope

Append teacher-context Explain menu option **15. Explain a saved Planning Export by name**. The legacy `7. Advanced: Planning export` exact-ID path and non-teacher legacy route are unchanged. The additional menu controller is read-only. It never exports, computes grouping bands, changes Core state, selects reviews, or infers a latest historical export.

## Verified discovery

1. Verify the current Core class, roster, and active school year through the established #123 navigation context.
2. List Core's strictly verified class-local grouping signals (bounded to 200). Exclude signals created by other producers. Do not claim that every Core signal has a Meridian export receipt.
3. For each Meridian-produced Core signal, load its exact immutable Meridian #40 export receipt. Bind `class_id`, signal identity and digest, source derivation digest, and receipt digest. Fail closed on absent or inconsistent receipts.
4. Inspect the exact #38 derivation with the existing #123 named derivation catalog to obtain its verified policy title, Core historical period label, and Standard. Resolve the exact #39 preview and **the historical review revision recorded by the export receipt**, not the currently selected review pointer. Verify preview, derivation, policy and review provenance. Verify cohort counts.
5. Render the human-facing choice using policy title, period, Standard, exported/omitted counts and export creation date. The exact signal identity and digests remain opaque `TeacherChoice.identity` and `witness`, excluded from ordinary labels.

## Explanation and anti-staleness

The selected class, exact Core grouping signal, immutable receipt and all underlying named-choice witnesses are reloaded before read, after the existing `ExplainMenuDependencies.planning_export` explanation provider returns, before ordinary display, and before technical detail display. The explanation's seven teacher and ten technical lines must match the exact stored export, Core digest, receipt, derivation, preview and historical review identity. Any scope or witness divergence fails closed and prints no academic result.

The ordinary screen displays human-readable policy title, period, Standard, dimensions and participation counts; it explicitly distinguishes this historical export from a current grouping decision. Exact signal IDs and checksums only appear under **T. Technical details**. Errors do not expose protected paths, student-level source data or raw storage exceptions.

## Qualification contract

The guarded runner pins baseline `e28a6ae77eca5dac1f6f66465cb64e76255c1be6` and the exact Explain menu base Git blob; allows three additive files and only four reviewed Explain-menu anchors; verifies payload SHA-256 and sanitized paths; runs Ruff, strict mypy and frozen Slice 1 navigation audit; executes focused and previously established regression groups, including Planning Export explanation, grouping export workflow, receipt workflow and teacher Explain-menu tests. Commit/push is not attempted if any gate fails. No destructive Git operations or security bypasses occur.
