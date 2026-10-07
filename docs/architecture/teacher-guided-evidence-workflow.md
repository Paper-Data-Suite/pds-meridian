# Issue #110 — Teacher-guided evidence workflow contract

Issue #110 replaces Meridian's identifier-driven evidence menu with a guided,
state-aware teacher workflow. Slice 1 freezes that interaction contract before
runtime behavior changes.

## Governing rule

> **Ask teachers for decisions, not identifiers.**

Routine guided evidence workflows present recognizable academic context:
classes, assignment/work titles, roster-backed student labels, Standards,
Grade Items, teacher-relevant status, explicit teacher decisions, and a
mechanically derived recommended next action.

Exact canonical identity remains mandatory internally. Display labels are not
authority.

## Opaque identity is carried, not typed

The ordinary guided route must not require routine free-text entry of:

```text
Publication ID
Projection cache key
Grade Item ID
Authorization purpose ID
Student ID / Student IDs
Evidence item ID
Teacher actor ID
Policy ID / Policy version
Attempt-selection policy ID
Standard ID
Target proficiency scale ID
Target scale revision / SHA-256
decision / association revision identities
```

Those values remain valid in domain models, storage, direct CLI commands,
diagnostics, provenance, tests, and explicit read-only technical details.

Teacher-facing selections carry the exact identity internally. If a display
label cannot safely distinguish canonical objects, Meridian blocks and explains
the ambiguity rather than falling back to a raw identifier prompt.

## Guided route versus direct CLI

Issue #110 changes the ordinary interactive teacher application. Exact,
noninteractive operator commands remain available where their deterministic
contract requires identifiers.

The prohibition is simple: the ordinary guided teacher route must not make
infrastructure identifiers part of the teacher's normal task.

## Existing raw-ID prompts are transitional legacy debt

At the start of #110, the Issue #57 teacher application still contains
identifier-driven prompts across several existing menu controllers, including
Evidence, Grade Items, Proficiency, Grades, Overrides, Snapshots, Export,
Explain, and Planning Signal.

Slice 1 intentionally does not change their behavior. Instead it freezes the
complete existing raw-ID prompt surface as transitional legacy debt. The guard
covers prompts containing opaque IDs, cache keys, SHA-256 identities, revisions,
and explicit version handles.

Any addition, relocation, or wording change to that raw-ID surface fails the
quarantine test until a deliberate #110 slice updates the snapshot. Later
slices must reduce the frozen surface as guided selectors and carried context
replace infrastructure prompts.

Issue #110 is not complete until its ordinary guided journeys no longer hand
the teacher off to these identifier-driven controls.

## Session context is convenience, not authority

Slice 2 adds one bounded process-local `TeacherSessionContext` owned by the
top-level Meridian teacher application. It may carry exact active class, work,
publication, Grade Item, and student identity so later guided workflows do not
force repeated selection.

The context is deliberately not a storage model:

```text
normal child return -> preserve valid context
M. Main Menu        -> preserve valid context
scope switch        -> clear dependent context
Q / EOF / Ctrl+C    -> discard the entire context
```

Selecting a different class clears work/publication/Grade Item/student state.
Selecting a different work clears publication/Grade Item/student state.
Selecting a different publication clears Grade Item/student state. Reselecting
the same exact scope does not destroy still-valid child context.

The session object never validates academic currentness and never guesses
missing parent scope. Later guided workflows must reload canonical state before
consequential actions and explicitly clear stale context when that revalidation
fails. Process-local context remains navigation convenience, not durable
academic authority.

## Recommended next steps are mechanical

Meridian may derive that the teacher can next review evidence, resolve
eligibility, review attempts/reassessment, review Standard associations, link
or create a Grade Item, review proficiency, or finish for now.

It may not derive the academic decision itself. It must not silently choose the
latest attempt, highest score, first Grade Item, first Standard, eligibility
disposition, or proficiency result.

## Publication discovery and compatibility remain separate

Issue #110 preserves the distinction among publication discovery, contract
compatibility, reader readiness, and teacher actionability. A publication may
remain visible but blocked.

The exact Meridian v0.3.1 reader qualification remains unchanged:

```text
ScoreForm == 0.12.1
Quillan   == 0.10.5
Concord   == 0.3.0
```

The follow-up reader-contract issue changes that compatibility mechanism.
The guided UI must consume compatibility through the support/diagnostic
abstraction so that change does not require another teacher-interface redesign.

## No new authority layer

The guided interface orchestrates existing services. It does not create
parallel semantics for publication currentness, authorization, eligibility,
attempt/reassessment decisions, Standard association, proficiency, Grade Item
membership, Grade policy/calculation, overrides, ReportingSnapshots, or export.

The evidence inbox is a derived read model over existing Core and Meridian
state, not a second durable queue and not hidden read/unread authority.

## Migration rule

Every later slice should answer yes to both:

1. Did the teacher make a meaningful academic/workflow choice rather than type
   an infrastructure identifier?
2. Did Meridian preserve exact canonical identity and the existing authority
   boundary behind that teacher-friendly choice?
