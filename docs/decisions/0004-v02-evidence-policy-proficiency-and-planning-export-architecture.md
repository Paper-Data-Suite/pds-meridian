# ADR 0004: Adopt v0.2 Evidence Policy, Proficiency, and Planning Export Architecture

- **Status:** Accepted
- **Date:** 2026-08-25
- **Decision owners:** Paper Data Suite maintainers
- **Related issue:** [#26 — Adopt the v0.2 evidence-policy, proficiency, and planning-export architecture](https://github.com/Paper-Data-Suite/pds-meridian/issues/26)
- **Related milestone issue:** [#25 — v0.2.0 Grade Items, explainable standards proficiency, and planning exports](https://github.com/Paper-Data-Suite/pds-meridian/issues/25)
- **Related decisions:**
  - [ADR 0001](0001-policy-driven-standards-proficiency-and-grade-calculation.md)
  - [ADR 0003](0003-consumer-side-producer-adapters.md)
- **Related Core contract:** [`grouping_signal_set_v1`](https://github.com/Paper-Data-Suite/pds-core/blob/main/docs/grouping_signal_set_v1.md)

## Context

Meridian v0.1.1 deliberately stops at authorized publication ingestion, exact
consumer-side producer adapters, typed evidence projection, immutable projection
snapshots, and read-only diagnostics. That foundation proves that ScoreForm,
Quillan, and Concord evidence can coexist without flattening producer semantics
or accidentally acquiring grading behavior.

The next milestone must turn that typed evidence into teacher-controlled academic
interpretation. The new layer needs Grade Items, explicit evidence eligibility,
attempt and reassessment decisions, native-value mappings, standards evidence
aggregation, standards proficiency, Academic Period proficiency, explanations,
and a teacher-controlled path from a selected academic interpretation to a
temporary planning signal.

The v0.2 architecture therefore has to settle three boundaries before runtime
implementation begins:

1. how Meridian creates reproducible academic interpretation without mutating
   Core or producer authority;
2. how policy, human decisions, calculations, and history remain explicit and
   deterministic; and
3. how Meridian can export a minimal contextual ordinal planning signal through
   Core without becoming a grouping engine or depending on Concord.

ADR 0001 already assigns policy-driven proficiency and Grade interpretation to
Meridian. ADR 0003 already requires exact consumer-side adapters and
producer-owned public readers. This ADR specializes those accepted decisions for
the concrete v0.2 implementation sequence. It does not supersede them.

The governing transition is:

```text
producer publication
        |
        v
Core canonical verification
        |
        v
exact producer adapter / public reader
        |
        v
typed Meridian evidence
        |
        v
explicit teacher and policy decisions
        |
        v
bounded exact calculation inputs
        |
        v
deterministic standards proficiency
        |
        v
explicit teacher-selected planning derivation
        |
        v
Core grouping_signal_set_v1
```

The planning path ends at the neutral Core interchange. Group planning and Group
creation remain outside Meridian.

## Decision

Meridian v0.2 will implement a distinct, versioned **academic interpretation
layer** over the v0.1.1 typed-evidence foundation.

The interpretation layer will use stable logical identities, immutable
revisions, explicit teacher or policy decisions, exact resolved input snapshots,
pure deterministic calculations, immutable persisted results, and structured
provenance.

It will not derive academic meaning from ambient filesystem state, mutate
producer records, redefine Core-owned identities, automatically export planning
signals, form Groups, or act as an official school grading system.

### Authority is split by domain

#### Core owns canonical shared infrastructure

Core remains authoritative for shared suite state and contracts, including as
applicable:

- workspace identity;
- class identity;
- roster and student identity;
- standards and framework identity;
- Academic Period definitions and revisions;
- Academic Work Registrations;
- Publication Records;
- publication series and withdrawal state;
- canonical manifest references and digests;
- module and compatibility profiles; and
- the neutral `grouping_signal_set_v1` interchange.

Meridian consumes those surfaces through public Core APIs.

Meridian may persist exact Core identities, revisions, and digests as provenance,
but those references do not become a competing Meridian registry. Meridian must
not silently copy Core state into a second mutable source of truth.

#### Producers own native evidence

ScoreForm, Quillan, Concord, and future producers retain authority for:

- native record validity;
- native result identity;
- native scoring, rubric, criterion, or observation semantics;
- producer-native scales and dispositions;
- producer correction and supersession relationships;
- producer-owned source provenance; and
- producer-owned public readers.

Meridian treats producer records as immutable source evidence. Meridian decisions
about eligibility, attempts, reassessment, proficiency, or planning do not edit
producer records or change their native meaning.

#### Meridian owns academic interpretation

Meridian owns the v0.2 state that answers how authorized evidence is used
academically, including:

- Grade Item identity and revisions;
- Grade Item membership decisions;
- Meridian Academic Period assignment for calculations;
- evidence-eligibility decisions;
- attempt-selection policy and decisions;
- reassessment and replacement relationships;
- proficiency-scale definitions and revisions;
- native-value mapping profiles and revisions;
- standards-evidence associations used for calculation;
- proficiency calculation policy;
- standards-proficiency results;
- Academic Period proficiency aggregation;
- calculation explanations and trace state;
- planning-signal derivation policy;
- rich immutable planning-derivation snapshots; and
- the explicit teacher decision to export a planning signal.

These records remain Meridian-owned even when they refer to Core or producer
identities.

#### Concord owns grouping

Concord owns:

- GroupPlan identity and lifecycle;
- manual and algorithmic planning strategies;
- random, similar-signal, and mixed-signal planning;
- missing-signal placement decisions;
- proposed groups;
- teacher approval of plans;
- canonical Group creation; and
- canonical GroupMembership creation.

A grouping signal is not a GroupPlan, Group, or GroupMembership.

Meridian must not:

- propose final Groups;
- choose a Concord grouping strategy;
- assign students to Groups;
- create Groups or GroupMemberships;
- launch Concord automatically after export; or
- imply that exporting a signal approves any grouping action.

The planning dependency direction is:

```text
Meridian
   |
   v
Core grouping_signal_set_v1
   |
   v
optional Concord consumer
```

There is no Concord import or runtime dependency in Meridian's planning-signal
derivation or export path.

This does not remove Meridian's existing optional Concord **producer adapter**.
Reading Concord academic publications and exporting a Core planning signal are
separate responsibilities. The producer adapter remains observational and
optional.

#### Official school systems retain official authority

Meridian v0.2 outputs are teacher-controlled Paper Data Suite interpretations.
They are not:

- official district Grades;
- SIS records;
- transcript records;
- report-card issuance;
- authoritative institutional proficiency records; or
- instructions to write into an external gradebook.

The milestone must not present advisory Meridian results as replacements for an
approved school, district, or state system of record.

### Logical identity, revision, selection, and result are distinct

The architecture distinguishes four concepts:

```text
stable logical identity
immutable revision or snapshot
explicit selected revision
derived result
```

They must not collapse into one mutable "current row."

Long-lived concepts such as Grade Items, proficiency scales, mapping profiles,
and policy families use stable logical identities independent of display titles,
filenames, labels, or timestamps.

A material semantic change creates a new immutable revision. Once a revision has
been used by a persisted decision or calculation, its meaning cannot be edited in
place.

Where a policy or profile requires activation or selection, that selection is
explicit. The newest revision is not automatically active.

A derived calculation records the exact revisions and decisions it used. Changing
a policy does not retroactively change historical results.

The following are never sufficient selection rules by themselves:

```text
latest
newest
highest revision found
filesystem mtime
directory enumeration order
```

### Decisions are historical records, not source edits

Teacher and policy decisions that affect academic interpretation become explicit
Meridian state.

Later implementation must preserve prior state when, for example:

- evidence eligibility changes;
- a selected attempt changes;
- reassessment treatment changes;
- Grade Item participation changes;
- an Academic Period assignment changes;
- a mapping profile changes; or
- a planning derivation is replaced.

A newer decision may supersede an earlier one, but the history must remain
explainable. Supersession is not deletion.

Decision records must preserve enough actor, time, scope, source, and
policy/revision context for their later workflows. Individual tickets may decide
whether a rationale is required for a particular decision, but the architecture
must not hide teacher discretion inside nondeterministic control flow.

### Publication validity and evidence eligibility are separate

The v0.1.1 distinction remains normative:

```text
publication validity != evidence eligibility
source lifecycle state != evidence preference
```

A publication may be structurally valid, canonically registered, compatible, and
available while still being ineligible for a specific Meridian calculation.

Newly discovered evidence does not become proficiency evidence merely because it
contains:

- a number;
- a rubric level;
- a standard reference;
- a score-like capability;
- a student subject; or
- a supported producer contract.

Where review or policy resolution is required, unresolved evidence remains
unresolved.

The v0.2 evidence-decision model must preserve semantic dispositions sufficient
to distinguish at least:

```text
included
excluded
pending
superseded
unsupported
withdrawn
```

The exact serialized enum belongs to the implementation ticket. The distinctions
do not.

A Core/producer lifecycle condition such as withdrawal is not the same record as
a Meridian teacher exclusion. Meridian cannot use a teacher decision to
reactivate source state that Core says is withdrawn or invalid.

### Attempts are selected explicitly

Meridian preserves all supported producer-native observations and revisions.
Architecture must not assume:

```text
latest wins
highest wins
first wins
every numeric value counts
```

as universal rules.

The interpretation layer must distinguish producer correction/supersession from
academic concepts such as:

- repeated attempt;
- resubmission;
- reassessment;
- replacement;
- combination; and
- similar-looking evidence that is not actually comparable.

An exact attempt-selection policy may select none, one, or a defined set of
eligible observations.

The exact selected source identities are calculation provenance.

Blank, ambiguous, missing, incomplete, unsupported, or other native non-score
states are never converted to numeric zero merely to make selection easier.

### Reassessment is a Meridian interpretation over preserved history

A later observation does not automatically erase an earlier observation.

The v0.2 architecture supports explicit policy relationships such as:

- replacement;
- retention of earlier evidence;
- combination;
- recency treatment;
- teacher-selected evidence; or
- another versioned bounded strategy.

Reassessment policy never mutates the producer attempt it references.

Producer corrections, revisions, supersession, and withdrawals remain producer
or Core lifecycle facts. Meridian reassessment decisions remain separate
academic interpretation.

### Producer-native values are not Meridian proficiency

The v0.1.1 typed inventory preserves producer semantics and v0.2 must keep that
property.

```text
producer-native result != Meridian proficiency category
```

ScoreForm points or percentages, Quillan rubric/criterion values, Concord native
Scoring Scale values, and future producer values may look numerically similar
while meaning different things.

Meridian does not introduce a universal numeric normalization layer.

Where a source value requires interpretation, it contributes to proficiency only
through an explicit versioned mapping profile that identifies the exact native
source scale/value semantics it supports.

Unsupported or unmapped values remain visible. Meridian must not guess,
interpolate, normalize by percentage, or silently treat them as zero.

### Proficiency scales are explicit Meridian policy

A Meridian proficiency scale has stable identity and immutable revisions.

It defines ordered proficiency categories, labels, interpretation, and the
versioned mappings that are valid for it.

A four-level scale is a supported first-class use case, not a universal constant.

Meridian must not assume that all courses, teachers, or institutions share:

```text
4 = advanced
3 = proficient
2 = developing
1 = beginning
```

or any other fixed set of labels or thresholds.

Scale ordering is configuration. Native producer numbers do not inherit the
meaning of same-looking Meridian level numbers.

### Standards evidence preserves its exact basis

Standards evidence used for a calculation must remain traceable to:

- the exact Core standard/framework identity;
- the student or native target actually represented by the producer;
- the Grade Item/work context;
- the exact producer Publication Record and evidence identity;
- the native result kind, scale, value, or state;
- the mapping profile where one is required; and
- the eligibility and attempt/reassessment decisions that selected it.

Core remains the standards/framework identity authority where Core provides that
identity. Meridian must not create a parallel mutable standards catalog merely
for calculation convenience.

Producer distinctions among question evidence, Focus Standards, criteria,
holistic observations, standards ratings, and producer-local criteria remain
meaningful. A criterion is not automatically a standard.

### Group and non-student evidence is never implicitly individualized

The v0.1.1 subject boundary remains mandatory.

Evidence explicitly targeted to a Core student may be considered for that
student under Meridian policy.

A Group or other non-student result must not be copied to individual students
because they:

- belong to the Group;
- authored an Artifact;
- share a route;
- appear in moderation context; or
- could plausibly be inferred as beneficiaries of the result.

Only actual producer-published student evidence may become student evidence.

This also prevents a circular planning path such as:

```text
Group result
   -> inferred individual proficiency
   -> grouping signal
   -> new Group
```

Student-level evidence legitimately published by Concord is treated under the
same explicit eligibility, mapping, and selection rules as other producer
evidence.

### Core owns Academic Period definitions; Meridian owns calculation membership

Core remains authoritative for Academic Period calendars and revisions.

Meridian owns the academic interpretation that assigns Grade Items/evidence to a
period calculation.

Period membership is not automatically inferred from publication time, file
time, due date, completion date, or whichever Core period is currently active
unless an explicit Meridian policy says to use that basis.

A persisted period-level calculation binds enough exact Core period/calendar
identity to reproduce its historical meaning. A later Core calendar revision
does not silently rewrite an earlier Meridian result.

### Teacher discretion becomes explicit state

When teacher discretion affects a persisted academic result, the discretion is
represented by an explicit decision or selected policy revision.

Examples include:

- Grade Item membership;
- evidence inclusion or exclusion;
- attempt selection;
- reassessment treatment;
- Academic Period assignment;
- mapping/profile choice;
- planning dimension;
- planning evidence window;
- band count;
- boundary and tie handling;
- missing-evidence treatment; and
- confirmation to export a planning signal.

This is different from a v0.3 Grade override.

A v0.2 decision answers how evidence is interpreted or selected before a result
is produced. A future override replaces or supersedes a calculated result under
an override policy. The two concepts must not be represented by one generic
"override" mechanism.

### Proficiency calculation is a pure deterministic domain operation

The calculation core receives exact resolved inputs rather than discovering
ambient current state.

Conceptually:

```text
exact normalized calculation inputs
        +
exact policy/profile revisions
        +
explicit decisions
        +
algorithm version
        |
        v
deterministic proficiency result
```

The calculation operation must not:

- discover the latest publication from disk;
- resolve the newest policy itself;
- consult filesystem order;
- use wall-clock time as evidence-selection meaning;
- mutate producer evidence;
- write teacher decisions as a side effect;
- persist output as part of the calculation function;
- export a grouping signal; or
- silently choose unresolved evidence.

Orchestration resolves and validates dependencies before invoking the pure
calculation layer. Persistence and user-interface workflows remain outside the
calculation function.

Given the same exact normalized inputs, policy revisions, decisions, and
algorithm version, the academic result and explanation basis are the same.

Deterministic policy must cover relevant ordering, equal timestamps, ties,
equivalent evidence, missing optional data, repeated processing, and any rounding
introduced in v0.2.

A `calculated_at` timestamp may record when a snapshot was created; it must not
make identical academic inputs calculate differently.

### Persisted calculations are immutable provenance-bound results

A persisted proficiency result represents one exact calculation.

It must preserve or bind enough structured provenance to identify, as applicable:

- Core class identity;
- student identity;
- standard/framework identity and revision;
- Grade Item identity and revision;
- Publication Record identities;
- exact producer evidence identities;
- source manifest, adapter, and projection identities where required;
- selected evidence;
- material exclusion/decision references;
- eligibility-decision revisions;
- attempt-selection policy and decisions;
- reassessment relationships/policy;
- native-value mapping revision;
- proficiency-scale revision;
- calculation-policy revision;
- Academic Period identity/revision;
- algorithm or calculation-contract version; and
- exact input/snapshot identity or digest.

A human-readable explanation string is not the only provenance. Explanation must
be supported by structured records.

Recalculation after a material dependency changes creates a new result. It does
not mutate the prior result.

### Staleness is a dependency condition, not automatic mutation

A historical result may become stale when a material dependency changes,
including:

- new relevant evidence;
- source withdrawal or correction;
- changed eligibility;
- changed attempt selection;
- changed reassessment treatment;
- changed Grade Item revision or membership;
- changed Academic Period assignment;
- changed mapping profile;
- changed proficiency scale; or
- changed calculation policy.

Staleness does not:

- delete the old result;
- mutate the old result;
- automatically recalculate;
- automatically replace an explanation; or
- automatically generate/export a grouping signal.

A teacher-facing workflow may later offer recalculation, but recalculation
creates a new exact result.

### Absence and unresolved states do not become zero

The architecture freezes the rule:

```text
absence != zero
```

The interpretation layer must be capable of preserving meaningful states such
as:

- not yet assessed;
- missing;
- incomplete;
- excused;
- excluded;
- withdrawn;
- unsupported;
- unmapped;
- invalid;
- unavailable;
- insufficient evidence; and
- not applicable.

The exact set used by each implementation record may be narrower where the
concept does not apply.

None of these states silently means zero or the lowest proficiency level.

An explicit policy may deliberately assign a consequence to a state, but that
policy decision must be visible in provenance.

`insufficient evidence` is a valid calculation outcome distinct from low
demonstrated proficiency.

### Planning-signal derivation is separate from proficiency calculation

A grouping signal is a secondary, explicitly teacher-requested planning artifact.
It is not a proficiency result.

The required boundary is:

```text
exact selected academic interpretation
        |
        v
explicit planning-derivation policy
        |
        v
teacher preview
        |
        v
teacher confirmation
        |
        v
immutable Meridian derivation snapshot
        |
        v
minimal Core grouping_signal_set_v1
```

A proficiency calculation never writes a grouping signal as a side effect.

New evidence, a recalculation, or a changed proficiency result never
automatically generates or exports a new signal.

### Meridian retains rich derivation state; Core receives minimal interchange

Meridian's internal derivation snapshot must eventually explain:

- the exact proficiency/calculation basis selected;
- exact class and roster basis;
- selected dimension;
- evidence/proficiency window;
- band count;
- boundary calculation;
- tie handling;
- missing/insufficient-evidence handling;
- included, excluded, and unrepresented students; and
- derivation-policy revision.

That rich record is Meridian-owned and immutable.

The Core interchange must not duplicate it.

Meridian must not embed the following in `grouping_signal_set_v1`:

- raw Grades;
- percentages;
- proficiency values;
- standards evidence;
- evidence counts;
- Grade Item details;
- calculation formulas;
- mapping profiles;
- teacher rationale;
- rich policy records; or
- Concord planning strategy.

### Core's grouping-signal contract is authoritative

Meridian will consume the public Core grouping-signal contract and APIs rather
than defining a Meridian copy.

The neutral contract is available beginning with Core v0.6.1. The later
Core-adoption implementation issue must require:

```text
pds-core>=0.6.1,<0.7
```

for Meridian's grouping-signal integration.

This ADR does not change the package dependency itself. Until that dedicated
implementation issue, Meridian's executable v0.1.1 package remains on its
existing `pds-core>=0.6,<0.7` dependency declaration.

A Meridian-generated signal uses Core's module-generated source provenance.
Conceptually:

```text
source.kind = module_generated
source.module_id = meridian
source.snapshot_id = <exact immutable Meridian derivation snapshot identity>
source.snapshot_digest_algorithm = sha256
source.snapshot_digest = <SHA-256 of the exact Meridian derivation snapshot>
```

The exact Meridian derivation snapshot serialization belongs to its later
implementation issue.

The invariant is that Core provenance points to one immutable derivation basis,
never to "current proficiency" or another moving target.

The digest of the canonical `grouping_signal_set_v1` bytes is separate Core
exchange-storage integrity metadata. It must not be confused with
`source.snapshot_digest`, which binds the upstream Meridian derivation snapshot.

### Meridian v0.2 exports one explicitly selected planning dimension

Core's neutral contract can represent more than one dimension. Meridian v0.2
does not need to generate multi-dimensional academic planning exports merely
because Core supports them.

One Meridian v0.2 derivation/export uses one explicitly selected academic
planning dimension.

The teacher must choose the academic basis. A dimension identifier is contextual
to the exact signal set and must not be treated as a suite-wide ontology.

A later milestone may add richer derivation choices without changing the
version-1 Core interchange semantics.

### Bands are contextual ordinal values, not learner labels

A planning band is an integer:

```text
1 through N
```

within one exact signal set and dimension.

The Meridian derivation policy owns how the selected academic interpretation is
converted to those bands. Core validates the interchange structure but does not
supply academic meaning.

A band is not:

- a permanent ability label;
- a universal proficiency level;
- a Grade;
- a percentage;
- an IQ-like classification;
- or a cross-course ranking.

Changing the academic basis, calculation snapshot, dimension, evidence window,
band count, boundary handling, tie handling, missing-evidence handling, or
derivation policy creates a new derivation result and, if exported, a new signal
identity.

### Planning export requires explicit preview and confirmation

No automatic signal export is permitted.

Before writing a signal, the later teacher workflow must preview enough state to
understand the derivation, including at least:

- class;
- exact academic/proficiency basis;
- source calculation/derivation snapshot;
- selected dimension;
- evidence/proficiency window;
- band count;
- band boundaries;
- distribution;
- ties;
- students with missing or insufficient evidence;
- excluded or unrepresented students; and
- material limitations.

The teacher must explicitly confirm signal creation.

Cancellation before confirmation writes no signal.

Export does not:

- create Groups;
- create GroupMembership;
- approve a GroupPlan;
- choose a Concord strategy;
- launch Concord; or
- designate the signal as the current or latest grouping input.

### Planning exports are immutable history

Every exported signal is an immutable Core exchange snapshot.

Meridian must not overwrite different contents under the same:

```text
(class_id, signal_set_id)
```

identity.

Meridian must not introduce grouping-signal aliases such as:

```text
latest
current
active
head
```

Teacher choice among historical signals remains explicit.

If academic state changes and the teacher wants a new planning signal, Meridian
creates a new derivation snapshot and a new signal identity.

Optional CSV output must use Core's supported grouping-signal CSV semantics rather
than defining a competing Meridian dialect.

### Privacy and authorization remain restrictive

Meridian academic interpretation and grouping signals are teacher-restricted
educational data.

Removing raw grades from `grouping_signal_set_v1` does not make its student-band
values public metadata.

Student-level proficiency, derivation, or signal data must not leak into
ordinary:

- logs;
- general diagnostic events;
- exception messages intended for broad support;
- package metadata;
- PDS2 route payloads;
- packet metadata;
- Publication Records;
- unrelated producer manifests;
- public fixtures;
- telemetry; or
- troubleshooting bundles.

Tests and documentation use unmistakably synthetic identities only.

Later calculation, explanation, and export services must not widen access to
protected source evidence. A caller who lacks authorization for source evidence
does not gain that evidence through a calculation or explanation surface.

The exact authorization service integration belongs to later implementation
issues, but this no-widening invariant is architectural.

### Dependency direction remains one-way

The v0.2 dependency boundaries are:

```text
pds-meridian -> pds-core

Meridian consumer adapter -> optional producer public reader

producer package -X-> pds-meridian

pds-core -X-> Meridian academic policy
pds-core -X-> Concord grouping policy

Meridian planning export -X-> Concord runtime

Concord grouping-signal consumer -X-> Meridian runtime
```

The Paper Data Suite shell may discover or launch owner-routed workflows, but it
does not calculate proficiency, derive bands, choose signals, or form Groups.

### v0.2 stops before Grade preview and issued reporting

The v0.2 milestone includes:

- Grade Item architecture and state;
- evidence eligibility;
- attempt and reassessment interpretation;
- native-value mappings;
- standards evidence aggregation;
- standards proficiency;
- Academic Period proficiency;
- explanation and trace;
- planning-signal derivation;
- preview; and
- explicit Core planning-signal export.

The following remain for v0.3 or later:

- conventional points/percentage Grade calculation;
- standards-to-letter/percentage conversion;
- hybrid Grade calculation;
- category/assignment weighting execution;
- override of a calculated Grade/result;
- immutable report snapshots;
- official report issuance;
- SIS synchronization; and
- external gradebook writes.

Grade Item records may reserve weighting metadata needed by later Grade policy,
but v0.2 does not execute conventional or hybrid Grade calculations.

## Record and dependency model

Later v0.2 issues should implement records along this authority flow:

```text
Core canonical state
  |
  +-- class / roster
  +-- standards
  +-- Academic Period
  +-- Academic Work Registration
  +-- Publication Record / withdrawal
  |
  v
Meridian typed evidence
  |
  +-- Grade Item revisions
  +-- membership decisions
  +-- eligibility decisions
  +-- attempt decisions
  +-- reassessment relationships
  +-- proficiency-scale revisions
  +-- mapping-profile revisions
  +-- calculation-policy revisions
  |
  v
exact calculation-input snapshot
  |
  v
immutable proficiency result
  |
  +--> explanation / trace
  |
  +--> explicit teacher planning derivation
           |
           v
      immutable Meridian derivation snapshot
           |
           v
      Core grouping_signal_set_v1
```

This diagram is an authority and dependency model. It does not require issue #26
to implement any of the runtime record families shown.

## Implementation invariants for the v0.2 sequence

The remaining v0.2 issues must preserve these invariants:

1. No producer or Core record is modified to express Meridian academic policy.
2. No source publication becomes academically eligible merely by being valid.
3. No implicit latest/highest attempt policy is introduced.
4. No universal numeric normalization is introduced.
5. No non-score or absent state silently becomes zero.
6. No Group/non-student result is copied to students.
7. No policy revision silently changes a historical result.
8. No calculation discovers ambient "current" state after inputs are resolved.
9. No persisted result is overwritten in place by recalculation.
10. No explanation depends only on unstructured text.
11. No planning signal is generated or exported as a calculation side effect.
12. No Core grouping-signal contract is reimplemented in Meridian.
13. No raw academic value or rich derivation record is embedded in the neutral
    interchange.
14. No grouping-signal export forms or approves Groups.
15. No Concord runtime is required for planning-signal derivation or export.
16. No `latest`/`current` grouping-signal alias is introduced.
17. No teacher-restricted student signal is treated as public metadata.
18. No v0.2 output is presented as an official SIS or district Grade record.
19. No v0.3 Grade override is conflated with a v0.2 evidence-selection decision.
20. No dependency direction established by ADR 0003 is reversed.

## Consequences

### Benefits

- Academic interpretation becomes explicit rather than emerging from incidental
  ingestion behavior.
- Standards proficiency remains first-class instead of being reconstructed from
  a conventional gradebook.
- Producer-native meaning and Core canonical authority remain intact.
- Teacher discretion becomes auditable state.
- Historical calculations remain reproducible after policies or evidence change.
- Missing and insufficient evidence remain semantically distinct from low
  proficiency.
- Cross-producer evidence can be combined only through explicit mappings and
  policy.
- Planning signals are useful to downstream workflows without leaking rich
  academic state.
- Meridian and Concord remain independently installable for their respective
  responsibilities.
- Later v0.2 implementation issues can define concrete schemas without reopening
  the domain-ownership questions settled here.

### Costs

- Meridian needs more explicit record families than a mutable gradebook table.
- Policy revisions and calculation snapshots require durable provenance.
- Teacher workflows must expose unresolved and unmapped evidence rather than
  silently normalizing it.
- Recalculation requires staleness tracking and new immutable results.
- Every producer scale used for proficiency may need an explicit mapping profile.
- Planning exports require a distinct derivation/preview step instead of a
  one-click automatic grouping action.
- Explanation and privacy surfaces must be designed around structured,
  authorization-aware provenance.

### Security consequences

- Proficiency and planning-band data remain protected student educational data.
- Authorization must be rechecked at appropriate explanation and export
  boundaries rather than inferred from stored provenance.
- Error handling must not log raw evidence, proficiency values, or student bands.
- Immutable provenance may retain sensitive references for long periods and must
  remain inside teacher-restricted storage.
- The neutral signal's minimal shape reduces accidental academic leakage but does
  not make the signal non-sensitive.

### Testing consequences

Later v0.2 implementation must test:

- explicit eligibility versus valid-but-unselected evidence;
- none/one/many attempt selection;
- producer correction versus Meridian reassessment;
- unmapped and similar-looking-but-different scales;
- missing, incomplete, unsupported, and insufficient-evidence states;
- deterministic calculation replay;
- stale historical calculations without mutation;
- Core Academic Period revision binding;
- student versus Group/non-student evidence;
- no circular individualization of Group evidence;
- exact derivation provenance;
- tie and boundary determinism;
- missing-signal diagnostics;
- explicit preview/confirmation;
- immutable signal export;
- no `latest` alias;
- no Concord installation during Meridian signal-export acceptance; and
- no widening of protected evidence access through explanation/export surfaces.

## Alternatives considered

### Automatically include every valid publication

Rejected because structural validity and academic eligibility are separate
questions. It would make producer publication an implicit grading decision.

### Normalize every producer value to one universal number

Rejected because numeric similarity does not establish semantic equivalence.
Points, percentages, rubric levels, standards ratings, dispositions, and
non-score states must retain their native meaning until explicitly mapped.

### Make the latest or highest attempt universally authoritative

Rejected because recency and highest-evidence strategies are policy choices, not
architectural truths.

### Store mutable gradebook rows

Rejected because changing policy or evidence would erase historical meaning and
make prior results impossible to reproduce reliably.

### Put proficiency calculation in Core

Rejected because Core is module-neutral canonical infrastructure. Proficiency
requires teacher/institution policy, evidence selection, scale mapping, and
academic judgment.

### Let each producer calculate cumulative proficiency

Rejected because no individual producer owns all cross-producer evidence and the
result would fragment policy across modules.

### Individualize Group Scores from Group membership

Rejected because Group membership does not transform a Group-targeted producer
result into actual student evidence and would create a circular grouping risk.

### Let calculation discover whatever is current

Rejected because ambient current state makes replay dependent on timing,
filesystem state, and implicit selection. Calculation receives exact resolved
inputs instead.

### Automatically export a new grouping signal after recalculation

Rejected because a planning signal is a separate contextual teacher decision and
may remain intentionally historical after academic state changes.

### Put grouping algorithms in Meridian

Rejected because Meridian owns academic interpretation, not Group planning.
Concord owns GroupPlan strategy and Group application.

### Put rich academic provenance in `grouping_signal_set_v1`

Rejected because the interchange is intentionally neutral and minimal. Rich
derivation state stays in Meridian.

### Maintain a mutable `latest` grouping signal

Rejected because downstream selection could silently change when academic state
changes. Every signal is immutable and historical selection is explicit.

### Treat v0.2 as the official gradebook/SIS layer

Rejected because this milestone stops before conventional/hybrid Grade previews,
overrides, report snapshots, and official-system synchronization.

## Follow-up work

This ADR governs the remaining v0.2.0 issues under #25.

In particular:

- the next issues define and persist Grade Items, membership, eligibility,
  attempts, reassessment, mappings, standards evidence, and proficiency;
- the Core-adoption issue raises Meridian's required Core floor to
  `pds-core>=0.6.1,<0.7` when the grouping-signal runtime integration is added;
- later planning-export issues define the concrete immutable Meridian derivation
  snapshot, generation, preview, Core write, and optional CSV workflow;
- workflow, explanation, attention, cross-producer, installed acceptance, and
  release-audit issues must preserve the invariants above; and
- v0.3 owns conventional/hybrid Grade previews, result overrides, reporting
  snapshots, and external transfer workflows.

If a later implementation issue discovers that one of these ownership or
immutability rules is internally contradictory, it must amend or supersede this
ADR explicitly rather than silently changing the architecture in code.
