# Meridian #123 Slice 8A — Named Export Profile Browsing

**Base:** `3f2e646c029a41215bfe5ef35f3411c41311eb09`
**Branch:** `123-teacher-first-navigation-existing-menus`

## Scope

Add the teacher-context route **7. Browse Export Profiles by name** to the existing Export menu. Routes 1–6 remain reachable with their original numbers and are explicitly labeled Advanced when a teacher navigation context is present. The legacy no-context menu remains unchanged. No CLI behavior, Core public API, export storage schema, or report-export service changes.

A teacher chooses a verified class and an existing Export Profile by its saved name and latest/selected revision status. `NamedExportProfileCatalog` uses the existing `ExportMenuDependencies.profile_lister` and the bounded, Unicode-safe `TeacherChoice` selector. Canonical profile IDs and revision witnesses are retained internally, never requested or printed as ordinary input. Duplicate indistinguishable choices fail closed rather than guess by list order. The catalog is limited to 200 class-scoped records and is reloaded before inspection.

The selected/current Export Profile is loaded using the existing `profile_loader`. Its class, opaque family identity, and current revision are verified against the latest authoritative listing. Another catalog and selected-profile read must agree before display. The browser deliberately distinguishes the latest authored title from the possibly older **selected** version's title, purpose, output format and column headings. A profile with no selected version reports that no output format is ready for export; it does not choose one by itself.

## Safety boundaries

- Browsing is **read-only**. It does not select a profile version, build an outgoing payload, create a local file, write a receipt or contact the SIS.
- Class hints are revalidated against current Core context. Every candidate is an ephemeral choice, not a permission or authority token.
- A changed title, revision, selected pointer or class between reads reports a stale choice. Unknown errors are redacted rather than printing internal paths or protected data.
- Preserve exact-ID source compatibility through the Advanced routes and noninteractive APIs. No change to Issue #110's frozen raw-identifier prompt inventory.
- B/M/Q from Core propagate as before. Empty and canceled choices have no side effects.

## Qualification

The focused synthetic suite exercises named discovery, current versus latest revisions, absent selected state, Unicode-disambiguation via the shared selector, bounded discovery, wrong class/profile/selected version, changed title/status, errors, cancellation and navigation unwind. The Windows runner pins the baseline SHA and reviewed Export menu blob, validates exact file scope and archive hashes, runs Ruff/import sorting, strict mypy, frozen Issue #123 navigation audit, the focused suite, prior #123 regressions and core export/profile integration tests. Only a fully qualified exact-scope commit is pushed normally.

## Deferred

Later Export slices will guide explicit selection of an existing profile version, exact named ReportingSnapshot/profiles into read-only export preview, reviewed local-file or copyable-text delivery, and named receipt inspection. Destination selection, export IDs, preview digests, selected profile authority and consent must be revalidated against the existing domain services. No district/SIS import is implied.
