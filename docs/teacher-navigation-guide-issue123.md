# Meridian teacher navigation guide — Issue #123

**Applies to:** development branch `123-teacher-first-navigation-existing-menus`, after Slice 11E (`941f268`). **Release status:** candidate, not a published release or district gradebook integration.

## Open Meridian and choose a class

Launch `meridian` or `meridian menu` from a supported PDS installation. The teacher menu offers Review New Evidence (1), Manage Grade Items (2), Review Proficiency (3), Preview Grades (4), Overrides (5), Snapshots (6), Export (7), Explain (8), and Reports (9). `S` opens teacher settings/first-time setup, `A` appears when evidence access setup is available, and `R` appears when interrupted-save recovery is available. `H` displays Help.

Choose a task by its number. On the first supported named workflow, select the correct class by a readable class title. A verified class is retained across compatible tasks during the same process; Meridian rechecks Core state and may request a new selection if the year, class, roster, or a dependent record changed. A stored class preference is only a hint. No class, work, Grade Item, period, student, or authorized publication is silently inferred from a name.

## Keyboard-first selector

In a teacher choice screen, enter a visible **row number** to select the corresponding verified record. `S` searches names, `C` clears the search, `N` and `P` move between pages when available, and `R` refreshes the current list. `T` displays Advanced/exact record details for a visible row; displaying them does not select or mutate that record. `B` returns one logical menu level; `M` returns to Meridian's main menu; `Q` quits. Blank input cancels where offered. A displayed name is a label, not an academic identifier; duplicate names should be distinguished by other visible context. If two candidates cannot be distinguished, do not guess.

Selections are checked against the latest canonical record. If a record changes between listing and selection, the selector requests a fresh choice. Missing roster data, unavailable Core state, stale records, or missing policy/configuration should appear as blockers, not invented grades, policy values, or a silently selected first record.

## Routine tasks by menu

| Main-menu task | Teacher-first choices | Important boundary |
| --- | --- | --- |
| 2. Manage Grade Items | Browse Grade Items by name, inspect relationships, discover registered work, select an existing Grade Item version or existing work-membership decision | Historical author/select operations with exact IDs are retained as Advanced choices |
| 3. Review Proficiency | View current Grade Item or Academic Period proficiency by named Grade Item, student, Standard, and applicable period | Existing scale, policy, mapping, eligibility and evidence authorization are required; direct calculation/author/select is Advanced |
| 4. Preview Grades | Review a current Grade by named student/period or a report for selected roster students | No assessment/Grade is not automatically treated as zero |
| 5. Overrides | Review, author a replacement, select the latest authored override, or withdraw a selected replacement through named student/period context | Writing an override does not silently select it; consequential actions preserve attribution and review/currentness gates |
| 6. Snapshots | Browse frozen reporting checkpoints, select a frozen checkpoint, browse/revise/create reporting definitions | Freeze using manually assembled build-request JSON remains Advanced |
| 7. Export | Browse/select Export Profiles, inspect receipts, preview and deliberately deliver a local report export | Local export **does not** post to an SIS, LMS, or Genesis |
| 8. Explain | Explain current/historical Grades, Grade Item or period proficiency, Planning Signal records, and local ExportReceipts | Explanation remains tied to the exact selected source/provenance |
| 9. Reports | Access the nine existing guided read-only teacher reports | Reports retain the separately qualified #111 selection and execution contract |

### Planning Signal

Within **3. Review Proficiency**, choose **10. Create Planning Signal (named workflows)**. This ordinary, discoverable entry opens the existing nested Planning Signal menu; it is not a separate main-menu item. The nested menu offers seven **named** teacher actions (choices 8–14): readiness; save derivation; save preview; inspect diagnostics; author review; select review; and export the accepted Planning Signal to Core. Choices 1–7 in that submenu remain exact-record Advanced operations. Selecting the gateway makes no academic decision.

An accepted Planning Signal exported to Core is not automatically a Concord group, a Grade, or a student outcome. Core export and optional Core-native CSV remain deliberate actions with exact preview/review/currentness checks.

## Before saving or exporting

Read the review screen. Verify class, period, student, selected source and proposed effect, and follow the existing typed Save/Apply confirmation. If a source is stale, missing or unauthorized, return to the choices; do not use a visually similar row as a replacement. `R` at the main menu can review interrupted Save checkpoints when shown, without replaying an unverified academic write.

Meridian's local outputs are advisory teacher-controlled PDS results. No ordinary menu action here constitutes an official district gradebook, SIS, or LMS update.

## Support and limitations

`T` on a selector is read-only technical detail. For established exact-record CLI commands use `meridian --help`; do not substitute teacher-facing labels for canonical IDs in automation. If current labels or supported public producer metadata are unavailable, use the displayed blocker and consult the Advanced guide rather than guessing. This guide describes the **implemented feature-branch behavior**; full Linux/Python CI, richer installed-domain journey acceptance, and final before/after interaction measurements are tracked separately in `docs/architecture/issue123-slice11f-acceptance-ledger.md`.
