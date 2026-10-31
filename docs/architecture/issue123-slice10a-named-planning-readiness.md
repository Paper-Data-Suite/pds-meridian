# Issue #123 — Slice 10A: Named Planning Signal Readiness

**Baseline:** `60c1c14b1c934e09c157feb5204a34725701c3a1` on `123-teacher-first-navigation-existing-menus`.

## Verified teacher route and reason for this slice

The nine-task Meridian menu reaches **Proficiency → Create Planning Signal** (Proficiency option 10). Unlike the completed Explain 9A–9H flows, the original `menu_planning_signal.py` options 1–7 all still require technical scope, policy, derivation, preview or review references. This slice starts the still-open #123 Planning Signal adoption work; it does not close it.

In a teacher-context session, legacy options 1–7 are now explicitly labeled **Advanced**. Their existing handlers, confirmation and write semantics remain unchanged; direct/injected callers without teacher context retain the unchanged seven-option menu. A new option 8 provides the first routine, name-based, read-only operation: **Review Planning Signal readiness by policy name**.

## Canonical ownership and navigation

- Reuse the verified class/year/workspace scope from `TeacherNavigationContext`. The user's existing selected class is a validated hint, never academic authority.
- Enumerate only bounded, verified #37 policy families with `list_grouping_signal_policy_ids`; look up **only explicitly selected current revisions** with `load_current_grouping_signal_policy`. Do not implicitly select the latest authored revision or create missing policies. No policy selected means the name-based list is empty and no academic action runs.
- Resolve labels from the selected policy's `title`, Standard, dimension, band count and **exact Core historical calendar**. Wrong school year, ambiguous display, missing dependencies and duplicate identity fail closed.
- Use `TeacherChoice` with opaque policy ID and `revision:digest` witness; never render the ID or SHA-256 in the normal selection text.
- Re-read class, choice, exact selected policy revision and digest before and after the existing `project_planning_signal_readiness` service, and before each displayed screen. A changed selection requires an explicit fresh choice, not silent replacement.
- Keep generation/status/blockers and source-of-truth academic interpretation owned by existing #37/#38 readiness service. Display teacher-readable readiness state, bounded blocker codes and consistent cohort counts. Never infer a grouping assignment or turn a missing/insufficient result into a zero.
- **T** is opt-in technical provenance; **B/M/Q** preserve standard navigation and propagated exceptions. No data writes, selection commits, #39 preview, review, #40 Core signal or CSV export are reachable via the named controller.
- Keep the original Advanced policy-ID readiness, derivation, preview, review, selection and Core export routes functional and untouched for CLI/expert compatibility.

## Operation-by-operation remaining Planning Signal inventory

| Legacy route | Teacher-context status after 10A | Remaining #123 adoption work |
| --- | --- | --- |
| 1. Review readiness | Advanced exact-ID fallback | **Named equivalent option 8 complete** |
| 2. Write exact derivation | Advanced | Named policy → exact preview → deliberate immutable write and revalidation |
| 3. Write planning preview | Advanced | Named saved derivation/policy → exact #39 preview write |
| 4. Review preview and diagnostics | Advanced | Named preview and verified review diagnostic summary |
| 5. Write teacher review | Advanced | Named preview → deliberate teacher decision and warning acknowledgments |
| 6. Select teacher review | Advanced | Named review revision → explicit CAS selection and revalidation |
| 7. Export accepted signal to Core | Advanced | Named reviewed preview → deliberate Core/optional CSV destination and export commit |
| 8. Review readiness by policy name | Routine named read-only | **Added by Slice 10A** |

No acceptance claim is made for the remaining Advanced-only write operations. Later slices must preserve the #110 raw-prompt baseline and #121/#122 teacher attribution and one-reviewed-action safety boundaries. Full synthetic cross-module teacher journeys, installed-wheel qualification and prompt-count measurements are still required before closing issue #123.
