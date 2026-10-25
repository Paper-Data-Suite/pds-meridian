# Meridian #123 — Slice 7C: named reporting definition browsing

**Base:** `01a42b2` on `123-teacher-first-navigation-existing-menus`.

## Change

Adds **9. Browse reporting definitions by name** to the teacher-context
Snapshots menu. Existing choices 1–8 and the no-context legacy menu retain
their numbers and routes. The new screen is read-only.

A report definition can exist without any frozen ReportingSnapshot. Therefore,
this route uses Meridian's canonical reporting-definition family listing,
validated contiguous revision histories, and exact latest stored revision. It
does **not** derive the definition inventory from frozen snapshot references.

The teacher selects a verified class and then a bounded searchable definition
choice identified by its actual title, purpose, academic period, update time,
and latest revision. Canonical IDs and SHA-256 witnesses stay internal, with
technical identities available through the existing opt-in choice details.
Duplicate indistinguishable labels fail closed rather than selecting by order.

The selection is re-enumerated and revalidated before display. It does not
create or revise a reporting definition, freeze or select a snapshot, read
protected student evidence, calculate a Grade, or communicate with any SIS.

## Compatibility and boundary

- Only the `menu_snapshots.py` controller receives a narrow additive route.
- Existing Advanced exact-ID operations and direct CLI remain untouched.
- The current class is revalidated via Meridian's Core-backed navigation layer.
- The storage APIs own integrity, revision-chain and digest validation. No
  additional mutable cache or unverified path traversal is introduced.
- At most 200 definition families and 500 revisions per family may be browsed;
  larger workspaces are directed to Advanced diagnostics.
- The frozen Issue #110 raw prompt inventory is unchanged.
- Core #237 public terminal components are not adopted here; Notes & Tasks
  and Core #238+ private-storage ownership are outside this slice.

## Deferred follow-on

A later slice can use the verified definition catalog to support deliberately
reviewed revision authoring. A newly created definition needs its own explicit
canonical-ID generation policy and separate acceptance checks. Manual JSON
snapshot freeze requests remain Advanced until a complete authorized builder
is qualified.

## Qualification

Focused adversarial tests cover canonical definition listing independent of
snapshots, class scope, title/purpose/period display, opaque identity, missing
history, inventory bounds, duplicate names, stale revision/digest, cancellation,
Core M/Q propagation, and sanitized errors. Runner adds Ruff, strict mypy,
Issue #123 frozen inventory, and the existing regression groups before any
commit/push.
