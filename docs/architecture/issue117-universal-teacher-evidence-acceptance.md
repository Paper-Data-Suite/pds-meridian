# Issue #117 — Slice 5: dual-operation readiness and cross-producer teacher acceptance

**Scope:** Meridian v0.4.2; after Slices 1–4, before benchmark/report completion.

## Problem and invariant

A guided evidence session first projects evidence (`project_evidence`) and later
loads an authorized projection-cache snapshot (`read_projection_cache`). Slice 4
preflight could label an assignment **Ready to review** when only the first
operation was authorized. The protected cache service would still deny access,
so this was not an authorization bypass, but the readiness label was untruthful.

Production preflight now requires *both* explicit, exact-scope decisions before
advertising readiness. The preflight remains a read-only, advisory diagnostic:
actual preparation, caching, and loading each recheck authorization at their
existing protected boundaries. Student-restricted grants cannot satisfy the
empty tuple representing the whole assignment. Invalid/throwing providers fail
closed without returning their error strings to ordinary teacher menus.

## Cross-producer acceptance

The synthetic Core publication tests exercise the actual installed ScoreForm,
Quillan, and Concord reader modules via Meridian's built-in producer adapters,
including registration, publication, catalog discovery, status projection,
protected preparation, cache loading, roster-backed review, and the ordinary
`Review New Evidence` menu. They assert that teacher navigation shows assignment
and producer labels but does **not** expose publication identifiers. Each producer
also has a project-only denial test to ensure the menu does not offer an unusable
review entry.

Fixtures and student names are entirely synthetic. The tests create only
isolated `tmp_path` workspaces. They do not write to school OneDrive or to a
real user workspace. A missing producer installation is an acceptance failure,
not an implicit success or skipped producer.

## Qualification strategy

Run the new acceptance tests with the existing Slice 4 readiness and guided
projection regressions, then Ruff, targeted strict mypy, and `git diff --check`.
Do not run the full repository suite immediately after a focused gate. Installed
wheel matrices and actual work-PC acceptance remain release qualification for a
later slice. The Concord #134 viewer assessment remains conditional: this slice
introduces no programmatic PDF/HTML `Open` action, so it does not change or
weaken local-file viewing/export policy.
