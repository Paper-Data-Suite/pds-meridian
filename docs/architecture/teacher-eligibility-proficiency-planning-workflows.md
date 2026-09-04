# Teacher eligibility, proficiency, and planning-export workflows

Issue #41 composes Meridian's existing v0.2 academic-interpretation and
planning-export capabilities into seven independently invocable teacher tasks.
It is an application/workflow layer over the canonical #27-#40 domain,
persistence, calculation, review, and export services. It does not create a
parallel academic model.

The installed CLI tasks are:

```text
meridian workflow new-evidence
meridian workflow grade-items
meridian workflow attempt-decisions
meridian workflow exclusions
meridian workflow standards-review
meridian workflow calculation-preview
meridian workflow create-planning-signal
```

## Governing boundaries

The workflow layer preserves the existing distinctions:

```text
publication validity != Grade Item membership
Grade Item membership != evidence eligibility
evidence eligibility != attempt selection
attempt selection != reassessment
producer-native value != Meridian proficiency
mapped value != standards proficiency
Grade Item proficiency != Academic Period proficiency
proficiency != grouping band
calculation != export
grouping signal != GroupPlan
write immutable revision != select revision as current
```

Core remains authoritative for shared class, roster, standards, Academic
Period, Academic Work Registration, Publication Record, and neutral
`grouping_signal_set_v1` exchange state. Producer modules remain authoritative
for producer-native records and semantics. Meridian remains authoritative for
its academic interpretation. Concord remains authoritative for GroupPlans,
Groups, GroupMembership, and grouping strategy.

## Application-layer structure

The implemented dependency direction is:

```text
canonical Meridian/Core services
        |
        v
workflow/application controller
        |
        v
teacher-facing projection/view model
        |
        v
CLI renderer/input adapter
```

Workflow controllers assemble bounded canonical state, produce deterministic
teacher-facing projections, accept explicit teacher actions, and invoke the
existing write/select/calculate/export APIs. Terminal rendering does not own
academic policy.

Generic workflow modules remain producer-neutral. They do not import ScoreForm,
Quillan, Concord, Portia, Vitrine, or the suite shell to reinterpret producer
records. Protected evidence continues through the existing authorized
projection and reader boundaries.

## Teacher identity and authorization

Teacher-authored records require an explicit teacher actor identifier.

The workflow layer does not infer teacher identity from:

```text
OS username
Git configuration
filesystem ownership
environment-variable accidents
student identity
```

The actor identifier is provenance, not authentication.

Possession of a publication ID, cache key, item ID, student ID, digest, or
filesystem path is not authorization. A workflow that needs protected
persisted evidence must use the existing deployment-provided authorization
capability. Without that capability, protected evidence access fails closed.

## Workflow 1 — New Evidence

New Evidence presents bounded evidence that requires attention while preserving:

```text
publication exists
    !=
work belongs to a Grade Item
    !=
evidence is eligible
    !=
evidence is selected
```

It distinguishes unresolved, pending, unsupported, stale/nonoperative,
superseded, withdrawn, and already-resolved state without auto-creating Grade
Item membership or eligibility.

Eligibility revision authoring and current selection remain separate actions.

## Workflow 2 — Grade Items

Grade Items exposes current and historical Grade Item revisions, explicit work
membership, and exact Academic Period assignment.

The workflow preserves:

```text
no membership decision != excluded
new revision written != new revision selected
```

It does not infer membership from publication presence, evidence, dates, or the
current Academic Period. Conventional Grade weighting remains outside #41.

## Workflow 3 — Attempt Decisions

Attempt Decisions uses the canonical applicability and candidate derivation from
#30. It preserves:

```text
not_applicable
unsupported_attempt_shape
no_decision
selected_none
selected
stale decision
```

No workflow path silently implements latest-wins, highest-wins, best-score,
highest-attempt-number, percentage ranking, or filesystem ordering.

Where multiple selected attempts require #31 reassessment, the existing
`retain`, `replace`, `combine`, and `recency` meanings remain unchanged.

## Workflow 4 — Exclusions

Exclusions preserves all six canonical eligibility dispositions:

```text
included
excluded
pending
unsupported
superseded
withdrawn
```

Academic exclusion remains distinct from source lifecycle. A teacher cannot
reactivate Core-withdrawn source state, and pending, unsupported, blank,
ambiguous, absent, excluded, superseded, or withdrawn evidence never becomes
zero merely because it does not contribute.

Eligibility revision write and current selection remain separate operations.

## Workflow 5 — Standards Review

Standards Review keeps the interpretation chain explicit:

```text
producer-declared alignment
    !=
Meridian standards association
    !=
mapped native value
    !=
aggregation input
    !=
calculated proficiency
```

Standard association is explicit. Mapping-profile selection is explicit.
Compatible or newer profiles are not selected automatically. Native non-score
states remain native states rather than being normalized to zero.

## Workflow 6 — Calculation Preview

Calculation Preview supports both Grade Item standards proficiency and Academic
Period proficiency.

Preview is read-only.

The workflow shows the exact calculation policy, proficiency scale, bounded
inputs, exclusions/blockers, sufficiency state, calculation strategy, and
resulting proficiency when calculable.

For Academic Period aggregation it preserves exact calendar revision and
direct/descendant scope. Dates do not infer Academic Period membership.

The consequential sequence remains:

```text
preview exact calculation
    ->
explicitly confirm immutable result write
    ->
result exists as history
    ->
explicitly preview current selection
    ->
explicitly confirm selection
```

Persisting a result never silently selects it as current.

## Current-selection semantics

Across all revisioned #41 tasks:

```text
write immutable revision
    !=
select revision as current
```

Current state is not inferred from highest revision number, newest timestamp,
filesystem mtime, directory order, lexical filename order, or the revision most
recently created by the workflow.

Where canonical selectors use compare-and-swap semantics, stale CAS state is
reported and the teacher must review fresh state. The workflow does not silently
retry selection against a replacement current revision.

## Cancellation semantics

Cancellation is a first-class boundary.

Before a canonical write:

```text
Cancel -> no persisted change
```

After an immutable revision has already been written but before selection:

```text
Cancel -> written historical revision remains
          current selection remains unchanged
```

The workflow does not delete immutable history merely because a teacher exits a
later step.

After a Core grouping signal is durably written, later receipt or CSV failure
does not trigger rollback of Core state.

## Staleness and revalidation

Consequential operations preserve the exact state the teacher reviewed.

The general pattern is:

```text
teacher reviews A
    ->
revalidate exact basis
    ->
commit A only if still valid
```

It is never:

```text
teacher reviews A
    ->
B becomes current
    ->
system silently commits B
```

Changed basis, stale selection, currentness drift, or dependency drift fails
closed and requires a fresh preview/review.

Storage, integrity, canonical-JSON, digest, lineage, or impossible-state
failures remain errors. They are not downgraded to ordinary academic states
such as `pending`, `no_data`, or `not_applicable`.

## Workflow 7 — Create Planning Signal

Create Planning Signal composes #37-#40 without collapsing their deliberate
boundaries:

```text
selected/current Academic Period proficiency
        |
        v
selected #37 grouping-signal derivation policy
        |
        v
read-only #38 derivation candidate
        |
        v
explicit #38 immutable derivation write
        |
        v
read-only #39 preview-write intent
        |
        v
explicit #39 preview write
        |
        v
teacher-facing #39 diagnostics
        |
        v
explicit warning acknowledgment
        |
        v
accepted_for_export review write
        |
        v
explicit review selection
        |
        v
read-only #40 Core export preview
        |
        v
final #40 live revalidation
        |
        v
Core grouping_signal_set_v1
        |
        v
privacy-minimal Meridian export receipt
        |
        +--> optional Core-native grouping_signal_csv_v1
```

Generation does not write Core state.

Previewing does not accept a review.

Acceptance does not select the review.

Review selection does not export.

The final export requires separate confirmation and final #40 live
revalidation.

Before final confirmation, the teacher-facing plan states that Core signal
state and a Meridian receipt may be written and that an optional Core-native
CSV may be emitted afterward. It also states that no Concord operation occurs.

## Optional CSV and partial success

CSV is a secondary convenience representation, not the authoritative shared
signal.

For the one-dimension Meridian export:

```text
stored Core signal
    ->
Core grouping_signal_csv_v1 bytes
    ->
Core parser
    ->
Core signal conversion
    ->
exact same runtime signal
    ->
exact same canonical Core JSON bytes
```

CSV requires an explicit destination. Existing identical bytes reconcile as
`existing`; different existing bytes conflict and are not overwritten.

Core signal persistence, Meridian receipt persistence, and CSV emission are
separate stores. If Core and receipt are durable but CSV fails, the workflow
reports partial success and does not roll back Core or the receipt.

## Privacy

Issue #41 does not create a broad workflow-log persistence surface.

Teacher-facing projections may join mutable display metadata such as student
names transiently from Core. Canonical Meridian derivation, review, receipt,
and export records do not duplicate those display names merely for UI
convenience.

The privacy-minimal export receipt contains exact export/provenance references
and digests, not student names, student bands, raw responses, essays, guardian
data, accommodations, protected traits, or Portia support/behavior records.

## Concord boundary

There is no Concord runtime dependency in the generic planning workflow.

The valid relationship remains:

```text
Meridian
    ->
Core grouping_signal_set_v1
    ->
optional independent downstream consumer
```

Issue #41 does not choose `similar_signal` or `mixed_signal`, choose Group size
or count, place noncontributors, create or approve a GroupPlan, create Groups,
or create GroupMembership.

No Concord runtime dependency is required for the installed issue #41
teacher-workflow smoke.

## Boundary with #42

#42 owns deeper proficiency and planning-export explanation/trace views.

Issue #41 answers:

```text
What do I need to decide or do next to complete this task?
```

Issue #42 answers:

```text
Why exactly did Meridian reach this academic/provenance result,
and what contributed at every stage?
```

The #41 projections retain exact identities and references so #42 can build
deeper trace views without rewriting workflow behavior.

## Boundary with #43

#43 owns Meridian-wide attention summaries across classes and Grade Items.

Issue #41 may show unresolved or stale state inside the task the teacher opened,
but it does not build the global attention dashboard.

## Boundary with later v0.2 acceptance

The next v0.2 sequence is:

```text
#42 proficiency and planning-export explanation/trace views
#43 Meridian proficiency attention summaries
#44 ScoreForm/Quillan/Concord cross-producer proficiency scenarios
#45 installed proficiency and signal-export acceptance without Concord
#46 v0.2.0 policy, fairness, privacy, interoperability, and release audit
```

The focused #41 smoke is intentionally narrower than #44 and #45.

## Boundary with future v0.3

Issue #41 does not implement the future v0.3 main menu, conventional Grade
calculation, category-weighted Grade calculation, hybrid Grade calculation,
final course Grades, teacher Grade overrides, report snapshots, report cards,
report delivery, SIS synchronization, or external gradebook synchronization.

The workflow/application controllers are reusable so later presentation
surfaces can invoke them without moving academic policy into a menu layer.

## Installed issue #41 teacher-workflow smoke

The release guard includes:

```text
scripts/smoke_test_teacher_workflows_wheel.py
scripts/smoke_program_teacher_workflows.py
```

The smoke installs only exact authenticated Core plus the candidate Meridian
wheel into an isolated environment, executes from outside the source checkout,
keeps Concord and producer packages absent, and exercises the packaged #41
workflow/application layer over exact synthetic canonical state.

The smoke proves:

```text
workflow catalog
Grade Item inspection
planning readiness
explicit #38 persistence boundary
explicit #39 preview boundary
teacher-facing diagnostics
accepted selected review
read-only final Core export preview
final Core + receipt + optional CSV export/reconciliation
```

The existing #40 installed export smoke remains a prerequisite baseline rather
than being replaced.

## Release baseline

Issue #41 is qualified against:

```text
pds-core 0.6.3
scoreform 0.11.0
quillan 0.10.0
pds-concord 0.3.0
```

The generic workflow runtime depends only on Core/Meridian contracts and remains
producer-neutral. Optional producer packages are present in the full
repository-validation environment for existing adapter qualification, not
because the #41 workflow layer imports them.
