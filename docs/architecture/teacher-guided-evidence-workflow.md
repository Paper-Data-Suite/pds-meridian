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

## Teacher evidence inbox read model

Slice 3 adds a read-only `TeacherEvidenceInbox` projection over the existing
Core publication discovery and Meridian support diagnostics. The default inbox
query is finite, current-state-only, and limited to `academic_result_set`
publications.

The inbox retains exact hidden publication/work identity while presenting:

```text
teacher-created class_id
canonical Academic Work Registration title
producer label
teacher-facing readiness / blocker status
```

For Issue #110, `class_id` is treated as practical teacher-facing class identity.
It is chosen at class creation and is acceptable for normal selection even when
its formatting is compact, such as `english_12_pd2`. Improving class display
labels is a later presentation refinement, not a prerequisite for a usable
grading workflow.

This exception does not extend to infrastructure identity such as Publication
IDs, cache keys, hashes, policy IDs, revision handles, or student IDs. Those
remain hidden from the ordinary guided workflow.

The projection does not open manifests, create projection caches, authorize
evidence, persist read/unread state, or write an inbox database.

The canonical referenced Academic Work Registration supplies the assignment
title. If canonical state is unavailable, Meridian does not expose `work_id` as
the assignment name.

If two otherwise-ready publications would have the same class label, work
title, and producer label, both are blocked as presentation-ambiguous rather
than forcing the teacher to distinguish them by Publication ID.

## Class-first guided inbox menu

Slice 4 makes the normal `Review New Evidence` task open the teacher evidence
inbox rather than the Issue #57 identifier-driven evidence submenu.

The first screen is class-scoped rather than a workspace-wide evidence dump:

```text
1. english_12_pd2
   2 evidence sets · 2 ready

2. english_10_pd4
   1 evidence set · 0 ready · 1 needs attention
```

Choosing a class updates only the process-local class scope and opens a second
screen containing evidence for that class:

```text
Class: english_12_pd2

1. Memory Snapshot
   ScoreForm · Ready to review

2. Locke Personal Identity
   Quillan · Ready to review
```

`B` from the evidence screen returns to class selection. `B` from class
selection returns to Meridian's main menu. `M` and `Q` retain their standard
navigation semantics.

Selecting a ready evidence source carries its exact `ModuleWorkRef` and
Publication ID into the process-local teacher session without displaying or
prompting for the Publication ID. No protected student evidence is opened in
Slice 4. Selecting a blocked evidence source explains the blocker in
teacher-facing language and does not replace any already-selected work or
publication in the same class.

The Issue #57 evidence controllers remain in the package as transitional legacy
infrastructure for later #110 replacement slices, but the normal top-level
teacher route no longer enters that raw-ID submenu.

## Guided projection preparation

Slice 5 adds one orchestration service over the existing publication-ingestion,
adapter, and projection-cache boundaries. The teacher-guided route owns the
stable review purpose `review_evidence` and uses whole-assignment scope
(`requested_student_ids=()`) for initial evidence preparation.

For one selected work/publication, Meridian internally:

```text
rediscover exact current work candidate
-> prepare_publication_invocation(...)
-> AdapterRegistry.invoke(...)
-> cache_projected_inventory(...)
-> load_authorized_projection_snapshot(...)
-> require reusable current-use assessment
```

The guided layer does not parse manifests, derive cache keys, or implement a
private projector. Manifest integrity, adapter selection, reader qualification,
canonical-state rechecks, repeated authorization, deterministic cache identity,
and authorized cache loading remain owned by the existing services.

The returned `GuidedProjectionResult` intentionally exposes the authorized
context and teacher-useful evidence count but no cache-key field.

The ordinary teacher route never asks for Publication ID, cache key,
authorization-purpose ID, or student-ID scope. Selection supplies publication
identity internally; the guided contract supplies the purpose; whole-assignment
review supplies the empty requested-student tuple.

Authorization remains deployment-owned. Meridian does not add a permissive
default authorizer. If the process has no configured authorizer, or policy
denies access, the teacher receives a bounded blocker and the selected
work/publication is not installed into session context.

## Teacher-friendly evidence review

Slice 6 projects an authorized evidence inventory into a read-only teacher view
before any Grade Item or eligibility decision is required.

The normal review hierarchy is:

```text
assignment summary
-> roster-backed student
-> teacher-readable evidence rows
```

Individualized evidence is joined to the canonical Core class roster. Student
presentation uses Core's `student_display_name` helper, including
`preferred_name` when present. If two represented students share the same
display name, roster period is added when that safely distinguishes them. If
name plus period is still ambiguous, review blocks rather than exposing a raw
student ID.

Evidence rows carry exact hidden `item_id` and `student_id`, but render
recognizable context such as target kind/sequence, native point value or scale
label, result kind, and producer-declared Standard identities. Native values are
not converted to percentages or a Meridian scale.

Nonstudent/shared producer evidence remains reviewable without fabricating a
student identity or requiring a roster.

This slice is read-only. It does not create Grade Item membership, eligibility,
attempt/reassessment, Standard-association, proficiency, Grade, or override
state. Attention routing that depends on those states remains for later guided
continuation slices.

## Guided eligibility continuation

Slice 7 makes an evidence detail capable of continuing into the existing
eligibility authority without asking the teacher for evidence, Grade Item,
actor, policy, or revision identifiers.

Eligibility first discovers active Grade Items whose current membership
explicitly includes the selected work and whose membership basis matches the
current selected Grade Item revision. The teacher still chooses the Grade Item
by title; Meridian never infers that academic relationship merely because only
one candidate exists. Duplicate titles use purpose as additional presentation
context and block if that remains ambiguous.

The teacher then chooses the academic disposition explicitly:

```text
Included
Excluded
Pending
Unsupported
```

Meridian does not choose the disposition. The teacher supplies a readable name
for attribution rather than an opaque actor-ID prompt. The guided policy
presentation currently exposes `Teacher review`, which carries the existing
`teacher_local_eligibility` / `1` policy identity internally. Non-included
decisions use the existing generic `eligibility.manual` reason code while any
teacher explanation remains explicit rationale text.

Consequential behavior preserves the established two-step authority boundary:

```text
preview exact eligibility write
-> teacher explicitly writes immutable decision
-> preview exact newly written selection
-> teacher explicitly makes it current
-> reload current eligibility state
```

No free-text decision revision is requested. The exact newly written revision is
carried internally into the existing CAS-protected selection workflow.

When no current included Grade Item relationship exists, eligibility enters the
Slice 10 teacher-facing Grade Item bridge. The teacher explicitly links an
existing Grade Item or creates one; Meridian does not infer membership.

## Guided attempt/reassessment continuation

Slice 8 adds teacher-guided attempt/reassessment continuation for
student-specific evidence. The route carries the roster student, active work,
authorized projection, and Grade Item identity internally.

A current Grade Item selected earlier in the teacher session is reused when it
still matches an explicit included work relationship. If there is exactly one
valid Grade Item and no meaningful choice, Meridian carries it forward. Multiple
valid Grade Items are presented by teacher-facing label.

Attempt policy is also teacher-facing rather than an ID prompt. The guided
presets are explicit academic choices:

```text
Select exactly one attempt
Select one or more attempts
Allow no selected attempt
```

Each preset carries a stable internal policy identity and explicit cardinality.
After the teacher chooses a preset, Meridian mechanically determines whether the
existing policy is ready, must be created, must be revised, or has a matching
unselected revision. Any required policy write/selection is performed only
after teacher confirmation and through the existing immutable policy authoring
and CAS-selection workflows.

Current candidate attempts are re-derived from operative included evidence. The
teacher chooses displayed attempt menu numbers; exact producer-native attempt
references are carried internally. Meridian does not choose the newest, highest,
first, or otherwise preferred attempt.

The decision itself retains the established two-step authority boundary:

```text
preview exact attempt decision
-> explicitly write immutable decision
-> preview exact newly written selection
-> explicitly make it current
-> reload current attempt state
```

Student IDs, Grade Item IDs, attempt-policy IDs, and decision revisions are not
entered in the ordinary route.

## Guided Standard association continuation

Slice 9 adds teacher-guided evidence/Standard association for student-specific
evidence. The routine route uses teacher-facing Standard metadata from Core and
current proficiency-scale presentation rather than infrastructure identity.

Standard selection has two layers:

```text
producer-declared Standards
or
Browse all active Standards
```

Producer-declared alignment is presented first, but it remains only a candidate
relationship. Meridian never turns producer declaration into an association
without an explicit teacher decision. The teacher chooses `Associated` or
`Not associated`. When the chosen Standard was producer-declared, the teacher
also chooses whether the decision basis is `Producer-declared alignment` or
`Explicit teacher judgment`. A non-declared Standard uses explicit teacher
judgment.

Core `standard_id` remains the durable identity, but the routine menu presents
Core's standard code, short label, and source. Missing producer-declared
references remain visible as an unresolved count and are not silently
substituted.

The #33 review projection requires an exact proficiency-scale context. Slice 9
lists only current class scales and presents scale title plus ordered level
context; exact scale ID, revision, and digest remain internal. If no current
scale exists, the route blocks with `Proficiency Scale Needed` rather than
asking the teacher for scale infrastructure values.

Association authoring preserves the existing authority sequence:

```text
build current Standards Review projection
-> preview create/revise association
-> explicitly write immutable decision
-> preview exact newly written selection
-> explicitly make it current
-> reload current association state
```

No Standard, Grade Item, scale, evidence, student, revision, or digest identity
is typed in the ordinary guided route.

## Grade Item bridge

Slice 10 replaces the `Grade Item Relationship Needed` dead end with an explicit
teacher bridge. When eligibility, attempt/reassessment, or Standard association
needs an included Grade Item relationship, the teacher can:

```text
link this work to an existing active Grade Item
or
create a new Grade Item, make it current, then link the work
```

The teacher chooses Grade Items by title, a new Grade Item's title and purpose,
and an Academic Period by label/type/date range. Meridian derives a bounded
internal Grade Item identity from the title and resolves the exact current
Academic Work Registration revision and current Academic Period Calendar
revision internally.

Creating a Grade Item does not invent weighting. Weighting remains unset in this
bridge and can be managed separately.

Both authority boundaries remain explicit:

```text
new Grade Item:
preview -> write immutable revision -> explicitly make current

work membership:
preview included relationship -> write immutable revision
-> explicitly make relationship current -> reload and verify
```

Existing membership history is revised rather than overwritten. A current
included relationship binds the selected Grade Item revision, current Academic
Work Registration revision, and the teacher-selected Academic Period assignment.

No Grade Item ID, registration revision, membership revision, calendar revision,
or storage digest is entered in the ordinary bridge.

## Proficiency bridge and contextual continuation

Slice 11 carries the selected Grade Item, roster student, Standard, evidence,
and exact current proficiency-scale context forward after a current
`Associated` Standard decision. The teacher does not reconstruct class, Grade
Item, student, or Standard identity.

The bridge discovers only already-current proficiency configuration. It presents
current calculation policies by title, strategy, and minimum observation count,
and presents current mapping profiles by readable mapping semantics. Exact
policy/profile IDs, revisions, and digests remain internal. If no current policy
targets the selected scale, the teacher receives `Proficiency Policy Needed`.
If no current mapping profile matches the exact producer/result signature and
selected scale, the teacher receives `Evidence Mapping Needed`.

The teacher explicitly chooses both configured policy and mapping. Meridian does
not choose a proficiency policy, mapping, or result on the teacher's behalf.

Slice 11 keeps the calculation basis deliberately bounded: the contextual
preview binds only the exact evidence row the teacher just reviewed. It does not
discover, add, or silently aggregate other evidence. The existing #33/#34
resolver therefore remains responsible for membership, eligibility,
attempt/reassessment, Standard-association, mapping, and calculation semantics.

The consequential sequence remains explicit:

```text
choose current policy
-> choose current exact-signature mapping
-> build read-only proficiency preview for this evidence row
-> optionally preview/write immutable calculated result
-> optionally make that exact result current
-> reload current proficiency result
```

A preview never writes. Writing never selects. The calculated level is produced
only by the existing deterministic proficiency policy; Slice 11 adds no new
proficiency semantics and no automatic academic judgment.

## Navigation, empty states, recovery, and continuation

Slice 12 qualifies the routine guided route around state changes and failure
recovery rather than adding academic authority.

Evidence detail now recomputes a mechanical continuation projection every time
a child workflow returns. The projection can recommend:

```text
C. Set up Grade Item and review eligibility
C. Review eligibility
C. Review attempts / reassessment
C. Review Standard association
C. Refresh current evidence state
C. Finish for now
```

`C` means continue to the mechanically appropriate teacher-controlled stage. It
never writes, selects, associates, calculates, or otherwise makes an academic
decision by itself. Numbered alternate actions remain available.

The evidence inbox now supports `R. Refresh evidence list`. Each refresh rebuilds
the read model from current Core/Meridian state and reconciles process-local
session context conservatively. The inbox is not an authoritative registry of
every valid class or work, so absence alone does not clear class/work context.
When the active work is present in the refreshed inbox but its previously
selected publication is no longer current there, Meridian clears only the
publication and its descendants. No replacement is guessed.

Missing or unreadable derived catalog state receives a bounded recovery screen.
The teacher may retry or explicitly rebuild Core's disposable Academic Catalog.
The rebuild uses Core's canonical rebuild service and does not modify Publication
Records, producer manifests, or academic judgments. Stale/drifted publication
rows also offer this recovery path.

Empty and blocked states remain informative:

- no current publications explicitly says there is nothing currently indexed;
- an all-blocked inbox says nothing is ready while keeping blocked work visible;
- withdrawn/superseded/drifted work remains fail-closed;
- authorization denial and reader unavailability remain teacher-readable;
- ambiguous roster labels still block rather than exposing student IDs;
- blank teacher attribution now explains that attribution is required and makes
  no change.

`B`, `M`, and `Q` continue to use Core navigation primitives. `T. Technical
details` is read-only and may expose exact diagnostic identity only after the
teacher explicitly requests it. Opening technical details does not refresh,
reproject, authorize, write, or select anything.

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
