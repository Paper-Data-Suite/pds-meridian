# ADR 0003: Adopt Consumer-Side Producer Adapters for Core Publications

- **Status:** Accepted
- **Date:** 2026-08-04
- **Decision owners:** Paper Data Suite maintainers
- **Related issue:** [#4 — Reconcile Meridian architecture with Core v0.6 and producer contracts](https://github.com/Paper-Data-Suite/pds-meridian/issues/4)
- **Related architecture:** [`core-v0.6-publication-ingestion.md`](../architecture/core-v0.6-publication-ingestion.md)
- **Related decisions:**
  - [ADR 0001](0001-policy-driven-standards-proficiency-and-grade-calculation.md)
  - [ADR 0002](0002-provenance-bound-report-snapshots-and-subscriptions.md)

## Context

Core v0.6 defines module-neutral academic publication infrastructure. It stores
canonical registration, publication, withdrawal, compatibility, Academic Period,
and catalog records. It verifies exact producer-manifest paths and SHA-256 bytes.
It deliberately does not parse producer manifest bodies or interpret educational
semantics.

Producer modules own different native result models:

- ScoreForm publishes attempts, points, question evidence, response states, and
  scan or manual provenance.
- Quillan owns review states, Focus Standard observations and ratings,
  minimum-requirement outcomes, feedback boundaries, and native rating scales.
- Concord may later publish collaborative Activity evidence and moderated
  scoring.
- Portia may later publish intervention history, status, and outcomes that are
  reportable but nonacademic.

Those values cannot be consumed safely through one generic numeric schema.
Likewise, Core's `PublicationProducerProfile` cannot contain a parser callback
without coupling Core to every producer implementation and turning compatibility
discovery into executable producer logic.

Meridian must consume exact producer contracts while remaining the owner of
cross-producer evidence projection, grading policy, and reporting policy. That
requires an explicit dependency direction.

## Decision

Meridian will use **consumer-side producer adapters** selected by exact Core and
producer contract compatibility.

The dependency direction is:

```text
pds-meridian -> pds-core

Meridian adapter -> producer-owned public reader/contract

producer package -> pds-core
producer package -X-> pds-meridian

pds-core -X-> producer parser
pds-core -X-> Meridian grading policy
producer package A -X-> producer package B
```

### Meridian owns the adapter layer

Meridian owns:

- the adapter interface;
- the adapter registry;
- exact adapter selection;
- adapter availability diagnostics;
- translation from validated producer public models into Meridian's typed
  evidence inventory; and
- the adapter/projection identity recorded in provenance.

The adapter is part of the consumer. It is not a callback registered by the
producer into Core.

### Producers own public readers and semantic validation

A producer owns:

- its manifest schema and version identifiers;
- canonical serializer and decoder;
- whole-value validation;
- public reader API;
- source-record interpretation;
- native scale and state semantics;
- record-set and revision policy; and
- privacy projection.

A Meridian adapter may import and call that documented public API. It must not
copy the producer validator or reconstruct the contract from documentation.

Producer public APIs must remain consumer-neutral. They do not import Meridian
or return Meridian inventory models.

### Core profiles remain metadata-only

`PublicationProducerProfile` remains compatibility metadata. It declares:

- producer module ID;
- supported Core publication schemas;
- supported Academic Work producer contracts;
- publication kinds;
- manifest contracts;
- capabilities; and
- source-record contracts.

It contains no parser, callback, path resolver, authorization decision, or
Meridian adapter.

A compatible profile is necessary but not sufficient for Meridian ingestion.

### Adapter selection uses exact compatibility

Adapter selection must use exact supported values, including:

- producer module ID;
- publication kind;
- manifest contract version; and
- producer contract version where applicable.

Source-record kind/version and required capabilities may further constrain the
selection.

Versions are independent. Numeric similarity between Core, producer package,
manifest, registration, source-record, or adapter versions does not imply
compatibility.

Meridian must not choose:

- the newest adapter;
- the nearest version;
- an adapter based only on module ID;
- an adapter based only on capabilities; or
- a generic JSON fallback.

### Unsupported states fail closed

The following are explicit, distinct outcomes:

- producer profile missing;
- producer profile incompatible;
- Meridian adapter missing;
- producer public reader unavailable;
- manifest contract unsupported;
- producer contract unsupported;
- source-record contract unsupported; and
- producer manifest decode or validation failure.

Meridian must not continue with guessed semantics.

### Base and optional dependencies

The Meridian base package requires `pds-core>=0.6,<0.7`.

It does not unconditionally require every producer package. Producer readers are
installed by the deployment or through adapter-specific optional dependencies.
They are imported only when their adapter is selected.

The package-foundation and adapter-registry issues will define exact optional
extra names, discovery mechanics, and error surfaces. They must preserve this
one-way dependency decision.

### Canonical verification precedes producer parsing

The adapter does not receive an unverified catalog row. Before producer parsing,
Meridian orchestration must:

1. reload the canonical Publication Record;
2. reload the exact referenced Academic Work Registration where applicable;
3. reload canonical withdrawal and series state;
4. evaluate the producer profile;
5. select the exact adapter;
6. enforce authorization for the requested use; and
7. verify the exact manifest path and SHA-256 bytes through Core.

The adapter then invokes the producer public reader and projects validated native
values.

### Projection preserves native meaning

An adapter must preserve:

- all represented attempts or observations;
- native result kind;
- native scale identity;
- non-score states and dispositions;
- standards alignment versus standards rating distinctions;
- contract-significant ordering;
- native provenance; and
- exact Core publication and manifest identity.

Projection must not choose a Grade-bearing attempt, convert missing states to
zero, or map a producer scale into a Meridian proficiency scale. Those are later
explicit policies.

### Academic and intervention adapters remain distinct

An adapter for `academic_result_set` projects academic producer evidence.

An adapter for `intervention_record_set` projects intervention context. It does
not create an Academic Work Registration, standards evidence, assessment
attempt, proficiency observation, or Grade component.

Shared inventory infrastructure may use tagged unions or common provenance
envelopes, but it must not erase the semantic distinction.

### Discovery is not authorization

An installed producer package, profile, adapter, or readable file does not grant
access. Authorization is supplied by the deployment and enforced before
student-level manifest access for the requested use.

Adapters do not make authorization decisions from producer identifiers or
filesystem readability alone.

## Consequences

### Benefits

- Core remains module-neutral and does not execute producer parsers.
- Producers retain authority over native validation and semantics.
- Meridian can support exact producer contracts without guessing arbitrary
  files.
- Unsupported versions fail explicitly.
- Producer packages remain reusable by consumers other than Meridian.
- The base Meridian installation does not require every producer package.
- Cross-producer grading policy remains centralized without creating producer
  dependencies on Meridian.
- Native scales, attempts, and non-score states remain auditable.

### Costs

- Each supported producer contract requires an adapter.
- Deployments must install the matching producer reader.
- Adapter and producer-reader versions require explicit compatibility testing.
- Similar-looking producer values cannot be combined without a deliberate
  mapping policy.
- Diagnostics must distinguish profile, adapter, reader, integrity,
  authorization, and policy failures.

### Security consequences

- Loading producer code is a trust decision made by the deployment.
- Adapter import must be side-effect controlled and occur only when required.
- Manifest contents must not be logged on validation failure.
- Authorization must precede sensitive producer-manifest access.
- Optional dependencies must not silently enable all installed producers.

### Testing consequences

Later implementation must test:

- profile-compatible and adapter-supported ingestion;
- profile-compatible but adapter-missing failure;
- adapter-present but profile-incompatible failure;
- producer reader missing;
- unsupported manifest and producer versions;
- manifest digest mismatch before parsing;
- producer validation failure without data leakage;
- all native attempts or observations preserved;
- non-score states preserved;
- intervention data remaining nonacademic; and
- installed-wheel dependency direction with no producer import of Meridian.

## Alternatives considered

### Put parsers in Core producer profiles

Rejected because it couples Core discovery to producer execution, expands Core's
trust and failure surface, and makes Core responsible for producer semantics.

### Require producers to implement Meridian adapters

Rejected because it reverses the dependency direction and makes producers depend
on one consumer's internal model and release cadence.

### Copy producer validators into Meridian

Rejected because validation would drift, producer corrections would require
synchronized copies, and Meridian could misrepresent native semantics.

### Parse arbitrary JSON by capability names

Rejected because capabilities do not define manifest shape or educational
meaning. `points`, `standards_ratings`, or `criterion_scores` are not universal
schemas.

### Create one universal normalized score

Rejected because it collapses points, ratings, observations, missing states,
review outcomes, and intervention context into a misleading value.

### Make every producer a required dependency

Rejected because most deployments use only a subset of producers and the base
package should not import unrelated producer code.

### Let the deployment write custom unversioned mappings

Rejected as the default because unversioned mappings are not reproducible and
could silently change Grades. Future custom adapters or mapping policies must be
explicitly identified and versioned.

## Follow-up work

- Issue #5 establishes packaging, dependency, typing, and CI foundations.
- Issue #6 defines the internal evidence inventory.
- Issue #7 defines the adapter protocol and registry.
- Issue #8 implements Core discovery and canonical verification.
- Issues #9 and #10 implement ScoreForm and Quillan adapters against accepted
  public contracts.
- Later issues add diagnostics, cache identity, cross-producer scenarios, and
  release audit.
