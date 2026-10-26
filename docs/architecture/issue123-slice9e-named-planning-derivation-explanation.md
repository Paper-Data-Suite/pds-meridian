# Meridian #123 — Slice 9E: Named saved Planning Derivation explanation

## Purpose and route

Add **Explain → 13. Explain a saved Planning Derivation by name** in teacher context. The existing **5. Advanced: Planning derivation** and all other Explain routes remain unchanged, including their explicit-ID CLI behavior. No change to #38 derivation, #37 policy, #35 result, or Core authority.

## Read-only discovery and exact identity

- Start from `TeacherNavigationContext`'s verified class and school year; a remembered class is a hint, not authority.
- Enumerate at most 200 **exact immutable** #38 derivations using `list_grouping_signal_derivation_ids` and `load_grouping_signal_derivation`. Require exact stored class, derivation identity, and content SHA-256.
- Follow each derivation's exact #37 `policy_reference` through `load_grouping_signal_policy_revision`. Verify the **complete** reference including revision and digest. Retrieve the exact Core Academic Period calendar revision to display its authoritative period label. Restrict the ordinary catalog to the currently verified school year.
- Display the verified policy title, school year, academic period, Standard, cohort size, band count and policy-revision timestamp. These are labels, not selectors; `TeacherChoice.identity` binds the immutable derivation ID, and `witness` binds both derivation and policy SHA-256. Distinct records whose visible descriptions collide fail closed under the existing choice service; don't resolve collisions by lexical ID order.
- Do not invent an active/latest derivation: the #38 store exposes no such pointer. Selecting a saved derivation never creates groups or exports a Core signal.

## Explain boundary and currentness

At selection, before the external explanation, afterward, and before every display or provenance action, reverify the class, full bounded catalog choice, exact #38 snapshot and its #37 policy and Core period dependencies. An edit, deletion, changed digest, changed school-year, or ambiguous candidate interrupts with a safe message.

The existing `ExplainMenuDependencies.planning_derivation` service resolves exact #38→#37→#35→Core dependencies and handles evidence permissions. The named controller checks every exact explanatory identity and fingerprint against the selected record before displaying the fixed teacher-readable summary. It never silently substitutes another derivation, policy, period or student. A failure never displays raw file paths or student-level details. `T` exposes technical provenance intentionally.

This is **read-only**. No Grade, proficiency, planning derivation, Core GroupingSignalSet, assignment, or report selection is written. B / M / Q retains Core navigation semantics.

## Qualification and regression

- New targeted tests cover human labels, restricted year, duplicate/oversized inventory, policy digest, wrong scope, cancellation, stale choice, unexpected explanation, mismatched fingerprints, private exception redaction, technical provenance, and menu append compatibility.
- Keep prior #123 Slice 9A–9D focused tests, `test_teacher_menu_explain_issue57`, issue #110 prompt inventory, and frozen 49-route / 9-report audit.
- Ruff lint/format, strict mypy, three pytest regression groups, exact staged-file guards and non-force Git push remain mandatory in the runner.

## Deferred

Slice 9F will add teacher-first Preview / Review explanation using the existing #39/#40 storage. Slice 9G will address named Planning Export provenance. Neither must be mixed into this slice.
