# Issue #117 — Slice 3: Teacher-facing evidence authorization

## Entry point

Normal Meridian main menu:

```text
A. Set Up Evidence Access
```

Existing numbered tasks 1–9 remain unchanged. No publication ID, student ID,
policy ID, digest, or JSON file edit is requested during this workflow.

The teacher selects an existing local Core class, then explicitly chooses one of:

1. All current and future ScoreForm results within that class.
2. All current and future Quillan results within that class.
3. All current and future Concord results within that class.
4. All current and future results within that class from those three supported producers.
5. One canonical, current, uniquely presented publication returned by the Core-backed discovery list.

Producer-wide grants are *not* the default. The teacher must deliberately select
the wider scope and confirm with the exact text `AUTHORIZE`. Publication-specific
grants carry the exact publication identity internally. Changed, withdrawn, or
otherwise no-longer-current publications are rejected after selection, before
policy commit. Exact policy-byte drift is independently prevented by the Slice 2
service. The process never opens a manifest during discovery or preview.

## Class selection

The class list is derived from actual, valid, non-linked directories within the
resolved `classes/` workspace folder. Missing classes produce an actionable
message and do not create a class or an authorization file. This route does not
invent class IDs or take free-text class input. A present but malformed class
root is an error, not an invitation to select an arbitrary path.

## Scope and authority

The teacher-visible confirmation screen states the class, producer(s), optional
selected assignment, current-only vs future-publication scope, both purposes,
and the fact that protected student evidence may be read. A grant permits
`project_evidence` and `read_projection_cache` separately; neither operation is
authenticated by mere discovery. The Slice 1 empty-scope correction remains the
authoritative student filter enforcement.

Existing policies and more restrictive grants are preserved. A configured
alternate policy path remains protected from this guided writer. The writer
rejects malformed policies, symlinked policy destinations, and stale preview
bytes. Neither the menu nor the saved grant performs publication, grading,
reporting, or academic decisions.

## Same-session activation

`run_teacher_evidence_authorization_menu` returns the reloaded workspace-bound
provider only after successful explicit commit. The application recomposes its
normal teacher controller dependencies using `default_diagnostics_dependencies`
with that exact provider, preserving the active session context. Protected
projection and protected cache read independently recheck authorization. The
teacher can immediately use `1. Review New Evidence` in the same process.

A cancellation or rejected save leaves the original dependencies in effect.
Synthetic tests cover all three producers and this provider-refresh mechanism.
Actual installed-wheel and classroom-file acceptance remain for later slices.

## Boundaries and follow-ups

- New or unknown producer reader contracts are never implicitly authorized or
  marked supported; the current menu offers the three installed-adapter kinds.
- A compatible publication can be discovered without authorization. This slice
  makes access setup discoverable; the separate readiness-label correction is
  still required by Issue #117.
- Existing support failure and missing/invalid deployment-policy recovery
  screens will be made more actionable in the subsequent workflow slice.
- No technical identifier is typed; the policy-file structure remains exactly
  the existing version-1 schema.

## Focused acceptance

- Class names derive from the existing workspace, not manual paths.
- Explicit one-producer, all-current/future, and one-publication scopes are kept
  separate; direct class/producers combinations cannot be guessed by discovery.
- No authorization is written on `B`, missing classes, invalid custom policy,
  changed publication, or failed confirmation.
- Exact student-level authorization continues to be checked in Slice 1 tests.
- A newly saved policy is reloaded into the same main-menu session.
- Original teacher menu 1–9 navigation and issue #110 no-opaque-prompt contract
  remain unchanged.
