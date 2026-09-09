# ADR 0005: Adopt v0.3 Grade Preview and Reporting Snapshot Architecture

- **Status:** Accepted
- **Date:** 2026-09-09
- **Decision owners:** Paper Data Suite maintainers
- **Related issue:** #48
- **Related milestone issue:** #47
- **Builds on:** ADR 0001, ADR 0002, ADR 0003, ADR 0004

## Context

Meridian v0.2.0 is released and verified. It implements the teacher-controlled
academic-interpretation chain from exact released producer evidence through
Grade Item membership, evidence eligibility, attempt/reassessment decisions,
source mapping, Grade Item proficiency, Academic Period proficiency,
explanation, and contextual planning-signal export.

v0.2 deliberately does not execute conventional, standards-based, or hybrid
Grade policy. It also does not implement teacher Grade overrides, immutable
reporting snapshots, Grade/report exports, subscriptions, delivery, or official
school-system writes.

v0.3 adds the Grade and reporting layer over that released foundation. This ADR
specializes ADR 0001's Grade authority, ADR 0002's broader reporting model,
ADR 0003's adapter boundary, and ADR 0004's released v0.2 interpretation model.

## Decision

The governing separation is:

```text
producer evidence
    != Meridian interpretation
    != proficiency
    != Grade calculation
    != teacher override
    != Grade preview
    != ReportingSnapshot
    != export artifact
    != official school-system record
```

Meridian owns Grade policy, Grade calculations, teacher override decisions,
ReportingSnapshots, Export Profiles, and Meridian export provenance. Core and
producers retain their existing authority.

## Current released compatibility baseline

This decision was reviewed against the latest stable relevant PDS releases
available on 2026-09-09:

```text
Python >=3.11

pds-meridian 0.2.0
pds-core 0.6.3
scoreform 0.11.0
quillan 0.10.0
pds-concord 0.3.0
```

Authenticated upstream wheel SHA-256 values:

```text
pds_core-0.6.3-py3-none-any.whl
98d7596ce0eed26e4d56a17bbbbd644db3014259b56a45783a173fe8237af5e5

scoreform-0.11.0-py3-none-any.whl
8248c6a1cc8254b5f9df46440131d524f80da8662a0dc7864fdc982e501b4c44

quillan-0.10.0-py3-none-any.whl
5dd4ed62b8bf39f7e11e6538d1c094929c6428dba81b254fe80d03c60d5114e9

pds_concord-0.3.0-py3-none-any.whl
dd827f7059c91c79bd69b6190b3c673d6b3bbc02bc25fa666286bbf5883c5e12
```

These versions are a review baseline, not permission to remain on stale sibling
releases. Before substantive downstream implementation begins, and again during
installed/release qualification, Meridian must:

1. check the latest non-prerelease GitHub Release for each relevant PDS
   dependency;
2. use the newest compatible released contract unless a reviewed incompatibility
   requires otherwise;
3. record any deliberate compatibility exception;
4. never silently substitute a sibling checkout, editable sibling install,
   unreleased branch, or older wheel for a released dependency; and
5. qualify exact supported distribution identities.

A newer producer distribution that preserves an existing public contract still
requires explicit Meridian qualification before support is claimed.

## Authority boundaries

Core remains authoritative for neutral shared state such as workspace/class/
student identity, standards, Academic Period revisions, Academic Work
Registrations, Publication Records, publication lifecycle, manifest identity,
and compatibility metadata.

Producers remain authoritative for native evidence, native result identity,
native scales/dispositions, correction/supersession history, and public reader
semantics.

Meridian remains authoritative for v0.2 interpretation state and additionally
owns v0.3 Grade policy/revisions, Grade calculations, overrides, previews,
ReportingSnapshots, Export Profiles, and local export receipts.

External SIS/gradebook/LMS systems remain authoritative for records they own.

## Grade policy

Every v0.3 Grade calculation must identify an exact, versioned Meridian Grade
policy revision. No material behavior may arise from an undocumented default.

Grade policy may govern calculation family, Grade Item participation,
categories, weights, point/percentage treatment, standards conversion, hybrid
weights, missing/pending/incomplete treatment, reassessment consequences,
minimum evidence, rounding, and display thresholds.

Existing v0.2 Grade Item metadata does not gain stronger authority merely because
v0.3 exists:

```text
GradeItemRevision.weighting metadata != executable Grade policy
```

A v0.3 policy must explicitly interpret any Grade Item property that affects a
Grade.

## Missing and non-Grade states

v0.3 preserves:

```text
missing or unresolved state != numeric zero
```

Missing, pending, incomplete, excused, excluded, not-applicable,
insufficient-evidence, unavailable, withdrawn, invalid, and unresolved states
remain distinct unless an explicit Grade policy assigns a supported consequence.

A policy may explicitly assign zero where intended, but that consequence must be
policy-owned, visible, deterministic, and explainable. It must never arise from
null coercion, empty collections, missing keys, or fallback numeric defaults.

## Grade calculation and Grade preview

A Grade calculation is a deterministic Meridian-derived result over exact Core
state, exact released producer projections, exact v0.2 decisions/results, an
exact Academic Period revision, an exact Grade policy revision, and exact
applicable override state.

A Grade preview is the teacher-facing advisory observation of that result. It is
read-only with respect to producer/Core state, may become stale, exposes
unresolved states, and does not create a snapshot or export by being displayed.

```text
Grade calculation != Grade preview
Grade preview != ReportingSnapshot
Grade preview != official Grade
```

## Teacher overrides

Overrides are immutable Meridian decisions layered over an exact target/source
result. They never edit producer evidence, Core state, v0.2 history, or the
pre-override calculation.

The precedence model is:

```text
source facts
-> base Meridian calculation for the target
-> explicit active override for that exact target, if any
-> downstream use only where policy explicitly consumes that effective result
```

Conflicting active overrides at the same target/scope must fail closed or
require explicit teacher resolution. "Newest timestamp wins" is not valid
precedence unless explicit supersession/current selection makes that
relationship authoritative.

## ReportingSnapshot ownership

For v0.3, a `ReportingSnapshot` is a Meridian-owned immutable canonical record
of one explicitly frozen reporting observation.

It is not a Core Publication Record.

```text
producer work
-> Core work-scoped Publication Records
-> Meridian interpretation / proficiency
-> Meridian Grade calculation
-> teacher review
-> Meridian ReportingSnapshot
```

No new Core publication kind, cross-work Publication Record, or reporting
registry contract is required by v0.3. Any future Core-level discovery of
Meridian reporting snapshots requires a separate Core architecture and
compatibility decision.

## Snapshot provenance and coherence

Issue #55 owns the exact schema. It must bind enough immutable provenance to
explain the observation, including as applicable:

- snapshot identity/schema;
- purpose and subject scope;
- Academic Period identity and exact calendar revision;
- Core Publication Record identities and relevant lifecycle observation;
- Grade Item and v0.2 decision identities;
- selected proficiency result identities;
- Grade policy family/revision;
- Grade calculation/result identity;
- applicable override identities/state;
- generation request/time/actor;
- structured result content; and
- integrity algorithm and canonical digest.

Snapshot generation must use one coherent observation:

```text
resolve exact inputs
-> validate currentness/eligibility
-> resolve base/effective results
-> compose structured snapshot
-> calculate integrity metadata
-> validate complete snapshot
-> commit immutable snapshot
```

If material source state changes during construction, generation must restart
against a coherent observation or fail with an explainable conflict.

## Snapshot immutability and currentness

A frozen snapshot never silently changes because evidence, publications,
membership, eligibility, attempts, reassessment, proficiency, Grade policy,
overrides, Academic Period calendars, Export Profiles, or later snapshots
change.

A later observation creates a new snapshot. Supersedes/corrects/current-use
relationships may be stored separately, but they do not mutate prior content.
Currentness must not be inferred from greatest ID, filesystem order, or newest
timestamp.

A refreshable/current report view remains distinct from a frozen snapshot.

## Snapshot versus export artifact

```text
ReportingSnapshot != rendered/export artifact
```

Issue #56 must not reopen a frozen snapshot merely to add metadata for a later
file. Later export follows:

```text
immutable ReportingSnapshot
+ exact ExportProfile revision
-> preview exact outgoing data
-> explicit teacher export action
-> local artifact or copyable payload
-> immutable/auditable export receipt
```

The receipt may bind snapshot ID/digest, Export Profile revision, format, field
order, creation time, and artifact/payload digest.

## Transferability and official-system non-authority

"Transferable" in v0.3 means teacher-controlled local output such as CSV or
copy-friendly data after preview and explicit action.

The invariant is:

```text
export != external-system write
```

v0.3 does not directly write to SIS platforms, official district gradebooks,
LMS gradebooks, vendor APIs, or other external school systems.

Meridian must not claim:

```text
Meridian calculated Grade == district Grade of record
Meridian ReportingSnapshot == official report card
export file generated == data successfully imported
external import attempted == external system accepted the record
```

A future direct integration requires separate authorization, interchange,
failure, reconciliation, and acknowledgement architecture.

## Vitrine boundary

```text
ReportingSnapshot != Vitrine Portfolio Snapshot / Edition
```

Meridian gains no runtime dependency on Vitrine. Vitrine is not required for
Grade calculation, snapshot creation, or export. Future Vitrine consumption of a
Meridian report requires a reviewed public contract/adapter and must not crawl
Meridian private storage.

At adoption, the latest stable Vitrine release is v0.2.0; it is interoperability
context only.

## Dependency direction

Allowed:

```text
pds-core -> neutral shared contracts
released producer public contracts -> consumer-side Meridian adapters
Meridian -> Meridian interpretation/calculation/reporting state
```

Forbidden:

```text
ScoreForm -> Meridian runtime
Quillan -> Meridian runtime
Concord -> Meridian runtime
Core -> Meridian Grade policy
Vitrine -> Meridian runtime
Meridian -> producer private implementation
```

Producer "Share Results with Meridian" workflows publish through Core. They do
not invoke Meridian calculation/reporting behavior.

## v0.3 scope relative to ADR 0002

ADR 0002 defines a broader eventual reporting architecture. The required v0.3
subset is narrower:

```text
teacher-driven Grade/report review
-> explicit snapshot creation
-> immutable Meridian ReportingSnapshot
-> explicit teacher-controlled local export
```

Automatic subscriptions, scheduled/event-driven delivery, email delivery,
direct SIS/gradebook writes, external receipt/reconciliation, and
institution-wide distribution remain outside required v0.3 scope.

## Privacy and authorization

Grade previews, snapshots, and exports can contain sensitive academic
information. Rich provenance remains Meridian-local unless explicitly needed in
an authorized output. Core does not become a general store for snapshot bodies.
Source discoverability does not imply report-generation authorization. Export
must be explicit, previewed, and data-minimized.

This ADR does not invent institutional authentication, consent, or authorization
infrastructure that does not yet exist.

## Required v0.3 flow

```text
released producer evidence
-> Core publication
-> Meridian v0.2 evidence decisions
-> Meridian v0.2 proficiency
-> versioned Grade policy
-> deterministic Grade calculation
-> applicable explicit override
-> teacher Grade preview/explanation
-> explicit snapshot build
-> immutable ReportingSnapshot
-> optional export preview
-> explicit export
-> local transferable representation
```

## Issue #48 boundary

Issue #48 is architecture only. Runtime remains assigned to #49-#56 and later
v0.3 issues. This issue must not add Grade engines, override persistence,
ReportingSnapshot persistence, ExportProfile persistence, subscription runtime,
direct external-system integration, a new Core publication kind, a Core
reporting-snapshot schema, or a Vitrine runtime dependency.

## Rejected alternatives

- **Core-publish ReportingSnapshots:** rejected for v0.3 because current Core
  publication is producer/work scoped and a Meridian report is a cross-work
  aggregate plus Meridian-owned policy/calculation state.
- **One mutable current Grade/report:** rejected because historical source,
  policy, calendar, and override provenance would be lost.
- **Mutate snapshots during later exports:** rejected; exports have separate
  receipts/provenance.
- **Newest override/snapshot automatically wins:** rejected; authority requires
  explicit selection/supersession.
- **Treat CSV export as permission for direct external writes:** rejected; those
  workflows have materially different authorization/reconciliation semantics.

## Verification requirements

Focused architecture tests/documentation validation must freeze at least:

```text
GradeItemRevision.weighting metadata != executable Grade policy
missing or unresolved state != numeric zero
Grade preview != ReportingSnapshot
Grade preview != official Grade
ReportingSnapshot != Core Publication Record
ReportingSnapshot != Vitrine Portfolio Snapshot / Edition
ReportingSnapshot != rendered/export artifact
export != external-system write
```

The repository must also retain the latest-release re-check rule.

## Final invariant

```text
These were the exact released source records.
These were the exact Meridian evidence/proficiency decisions.
This was the exact Grade policy.
This was the exact calculated result.
This was the exact applicable override.
This was what the teacher previewed.
This was the exact immutable snapshot the teacher chose to freeze.
This was the exact local representation the teacher explicitly exported.
None of those facts, by themselves, claims that an external official
school system accepted or recorded the Grade.
```
