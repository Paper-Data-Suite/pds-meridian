# Core v0.6 publication-ingestion architecture

## Status

This is the active Meridian architecture for consuming Paper Data Suite academic
registry publications through `pds-core` v0.6.

It implements the dependency and ownership direction accepted by
[ADR 0003](../decisions/0003-consumer-side-producer-adapters.md) and reconciles
[ADR 0001](../decisions/0001-policy-driven-standards-proficiency-and-grade-calculation.md)
and
[ADR 0002](../decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md)
with the released Core contract.

Meridian now implements the installable foundation, typed evidence inventory,
exact consumer adapter registry, bounded Core catalog discovery, canonical
publication/registration/series/withdrawal verification, candidate drift
rejection, Core compatibility evaluation, authorization-before-access, bounded
manifest-byte preparation, and final canonical-state rechecking.

Real producer parsing, evidence projection, cache policy, grading, and reporting
remain unimplemented.

## Goals

The ingestion foundation must let Meridian:

- discover candidate publications efficiently without trusting derived state;
- reload and verify canonical Core state;
- enforce authorization before student-level manifest access;
- select a consumer adapter by exact supported contracts;
- parse only through producer-owned public readers;
- preserve native attempts, observations, scales, dispositions, and provenance;
- project evidence without prematurely selecting or grading it;
- distinguish integrity, compatibility, historical, authorization, and policy
  outcomes; and
- bind all imported projections to exact source identity.

## Non-goals

This architecture does not:

- make the Core catalog authoritative;
- put producer parsers into Core profiles;
- create a universal producer manifest schema;
- authorize access based on package discovery;
- define Grade-item membership;
- select an official attempt;
- map producer scales into a Meridian proficiency scale;
- calculate standards proficiency or Grades;
- make intervention information academic evidence;
- define Quillan's future publication contract; or
- require producer packages to depend on Meridian.

## Dependency baseline

The executable package will target:

```toml
dependencies = ["pds-core>=0.6,<0.7"]
```

Core is a required base dependency. Producer packages are not unconditional base
dependencies. A deployment installs the producer readers needed for enabled
adapters, or Meridian exposes adapter-specific optional dependencies after the
package and adapter-registry issues decide their exact names.

The dependency direction is one way:

```text
pds-meridian -> pds-core

pds-meridian adapter -> producer public reader

producer -> pds-core
producer -X-> pds-meridian

pds-core -X-> producer parser
pds-core -X-> grading policy
producer A -X-> producer B
```

## Separate integration surfaces

PDS2 routing and reportable-data publication are independent.

Core discovers routing profiles through:

```text
paper_data_suite.modules
```

Core discovers publication producer profiles through:

```text
paper_data_suite.publication_producers
```

A routing `ModuleProfile` may include a route handler and registration
validator. A `PublicationProducerProfile` contains compatibility metadata only.
Neither implies the other.

Meridian publication ingestion uses the academic registry and publication
producer profile. It does not require a routing handler and must not invoke a
routing callback to parse an academic-result manifest.

## Authority model

### Core authority

Core owns:

- `ModuleWorkRef` and shared record-reference envelopes;
- Academic Period Calendar identity, revisions, hierarchy, and current pointers;
- Academic Work Registration envelopes, revisions, and current pointers;
- Publication Record and Publication Withdrawal envelopes;
- publication kinds and shared capability vocabulary;
- publication-series identity and explicit predecessor relationships;
- manifest path containment and exact SHA-256 binding;
- canonical registry storage and retrieval;
- metadata-only producer compatibility profiles;
- the disposable academic catalog; and
- bounded audit, validation, and recovery services.

Core validates its envelopes and exact manifest bytes. It does not parse the
producer manifest body or determine educational semantics.

### Producer authority

A producer owns:

- authoritative native records;
- assignment, attempt, review, rating, criterion, intervention, and outcome
  semantics;
- producer manifest schema and contract versions;
- canonical producer serialization and validation;
- source-record contracts and resolution;
- stable record-set identity and producer revision policy;
- correction, supersession, and withdrawal intent;
- privacy projection decisions; and
- a consumer-neutral public reader when consumption is supported.

The producer must not call Meridian to interpret its own records or publish to
Core.

### Meridian authority

Meridian owns:

- candidate-selection requests;
- consumer adapter interface and registry;
- adapter selection and diagnostics;
- projection into Meridian's internal evidence inventory;
- evidence eligibility and exclusion policy;
- Grade-item membership;
- attempt and reassessment selection;
- standards-proficiency and Grade policy;
- Academic Period membership of Grade items;
- report composition and snapshots; and
- consumer-side provenance.

Meridian does not become authoritative for producer-native validation merely
because an adapter invokes the producer reader.

### Deployment authority

The application or deployment layer owns:

- trusted package installation;
- enabled-producer and enabled-adapter configuration;
- identity and authorization integration;
- filesystem permissions;
- secrets;
- backup, retention, and deletion policy; and
- the decision that an installed package is trusted for a deployment.

Discovery is not authorization.

## Canonical and derived state

### Canonical Core state

Canonical Core state includes:

- Academic Period Calendar revisions and explicit current pointers;
- Academic Work Registration revisions and explicit current pointers;
- Publication Records; and
- Publication Withdrawals.

### Canonical producer state

Canonical producer state includes:

- native records and history;
- immutable producer manifest revisions; and
- producer-owned source evidence referenced by the public contract.

### Derived state

Derived state includes:

- `registry/catalog.sqlite`;
- catalog rows and snapshots;
- Meridian evidence projections;
- Meridian caches and indexes;
- audit summaries; and
- rendered report artifacts.

Derived state must not silently replace canonical authority.

### Transient state

Locks, temporary files, SQLite journals, WAL/SHM files, in-memory parse results,
and incomplete writes are transient.

## Canonical verification precedes producer parsing

A producer adapter never receives an unverified catalog row. Meridian reloads
canonical Core records, evaluates compatibility, enforces authorization, and
verifies exact manifest bytes before producer parsing begins.

## Ingestion state machine

The later implementation should model ingestion as ordered stages rather than a
single `load()` operation.

### Stage 1: candidate discovery

Query Core's disposable catalog with bounded typed filters. Capabilities may be
used to narrow candidates.

Possible outcomes include:

- candidate rows returned;
- no candidate rows;
- catalog absent;
- catalog incompatible;
- catalog locked;
- catalog malformed or corrupt; or
- catalog known to be stale.

A catalog failure is not proof that canonical publications are invalid.
Meridian may report that discovery cannot proceed or may use a separately
defined bounded canonical fallback in a later issue. This architecture does not
require automatic catalog rebuild or repair.

### Stage 2: canonical publication reload

For each candidate, reload the canonical Publication Record by exact
`publication_id`.

Do not trust catalog copies of:

- work identity;
- publication kind;
- record-set identity or revision;
- capabilities;
- manifest contract, path, or digest;
- source-record reference;
- registration revision;
- predecessor; or
- publication time.

If the candidate no longer exists canonically, report candidate drift rather
than fabricating a publication from the row.

### Stage 3: registration reload

For `academic_result_set`, reload the exact Academic Work Registration revision
referenced by the Publication Record. Validate exact work agreement and producer
contract compatibility.

Current registration state may also be loaded for eligibility and diagnostics,
but it must not replace the historical referenced revision. A current metadata
update does not rewrite the registration revision used by a historical
publication.

`intervention_record_set` supplies no Academic Work Registration. Meridian must
not fabricate one.

### Stage 4: series and withdrawal state

Reload canonical withdrawal state and enough canonical series state to identify:

- current selectable head;
- withdrawn head;
- historical predecessor;
- explicit supersession chain; and
- contradictory or cyclic state.

Core never selects a head from greatest revision, newest timestamp, identifier,
filename, or directory order. Meridian must use explicit canonical relationships.

Historical and withdrawn are states, not generic validation errors. A historical
publication may remain required to explain an earlier imported projection or
issued report.

### Stage 5: producer compatibility

Load the installed `PublicationProducerProfile` for the publication's producer
module and evaluate compatibility against the canonical Publication Record and
referenced registration.

Compatibility evaluation covers:

- Core publication schema;
- producer module;
- Academic Work producer contract where applicable;
- publication kind;
- manifest contract version;
- claimed capabilities; and
- source-record kind and contract version.

A missing profile differs from an incompatible profile. Neither authorizes
manifest access.

### Stage 6: Meridian adapter selection

Select an adapter by an exact compatibility key that includes, at minimum:

- producer module ID;
- publication kind;
- manifest contract version; and
- producer contract version where applicable.

Source-record kind/version and required capabilities may further constrain
selection.

Adapter selection is separate from the Core profile registry:

- profile-compatible, adapter-missing is unsupported by Meridian;
- adapter-present, profile-incompatible is not ingestible;
- adapter-present, reader-missing is unavailable in the deployment; and
- unknown versions never fall back to the nearest, latest, or generic adapter.

The adapter identity and projection-contract version must be recordable in the
resulting evidence inventory.

### Stage 7: authorization

Before opening or exposing student-level producer-manifest contents, enforce the
deployment's authorization decision for:

- the source publication;
- the student or target scope;
- the requested operation;
- the requested report or calculation purpose; and
- any referenced producer artifacts.

Package discovery, profile compatibility, filesystem readability, and adapter
availability do not grant authorization.

The implementation may inspect privacy-minimized canonical envelope metadata to
determine what authorization is needed. It must not parse the sensitive manifest
first and ask for authorization afterward.

### Stage 8: manifest verification

Use Core's canonical path and manifest verification surfaces to require:

- a workspace-relative POSIX path;
- containment below the exact producer work root;
- a regular nonsymlink file;
- exact recorded digest algorithm;
- exact SHA-256 bytes; and
- agreement with the canonical Publication Record.

Never bind ingestion to `latest.json`, `current.json`, a directory scan, or a
producer-generated convenience symlink.

A missing or altered manifest is an integrity problem. Meridian must not
reconstruct different bytes under the historical publication identity.

### Stage 9: producer parsing

Invoke the producer-owned public reader or pure contract API for the exact
manifest version.

The adapter may translate validated public model values into Meridian's internal
inventory. It must not:

- duplicate producer validation;
- parse arbitrary JSON before the producer reader;
- import private implementation models;
- open native source files as a substitute for the manifest;
- reinterpret a field based on its name alone; or
- suppress producer validation failures and continue with partial values.

A producer parse failure must avoid logging student data or dumping the manifest.

### Stage 10: evidence projection

Project producer-native values into a typed inventory without applying Grade or
proficiency policy.

The projection must preserve:

- exact source provenance;
- producer and contract identity;
- native result kind;
- native scale identity and descriptors where supplied;
- all represented attempts, observations, and evidence links;
- contract-significant order;
- non-score response states and dispositions;
- source record references; and
- eligibility diagnostics separate from native meaning.

Projection may normalize storage representation, such as using immutable tuples
or tagged unions. It must not normalize educational meaning into a universal
number.

### Stage 11: later policy

Only after verified projection may later Meridian policy determine:

- whether the evidence is eligible;
- whether registered work is a Grade item;
- which attempts or observations are selected;
- how reassessment is handled;
- how native evidence maps to a Meridian proficiency scale;
- Academic Period membership;
- conventional or hybrid Grade calculation; and
- report inclusion.

## Adapter contract boundaries

A future adapter interface should separate:

1. support declaration;
2. public-reader availability check;
3. exact parse and validation;
4. projection; and
5. privacy-safe diagnostics.

It should not combine canonical Core reload, authorization, manifest file
verification, producer parse, evidence selection, and Grade calculation into one
callback.

Adapters are consumers, not producer plugins. A producer package exposes a
consumer-neutral reader. It does not register a Meridian callback or import a
Meridian protocol.

## Producer readiness matrix

### ScoreForm

| Concern | Current architectural fact |
| --- | --- |
| Producer module | `scoreform` |
| Target publication kind | `academic_result_set` |
| Manifest contract | `scoreform_academic_result_manifest_v1` |
| Production record-set ID | `academic_results` |
| Native values | all attempts, points, responses, correctness, response states, question alignments, provenance |
| Expected capabilities | `points`, `question_evidence`, `multiple_attempts` |
| Not a native capability | `standards_ratings` |
| Public pure reader | implemented |
| Workspace generation/profile/publication/installed acceptance | report from producer default-branch reality; do not infer from pure contract existence |

ScoreForm question-to-standard alignment identifies what a question addresses.
It is not a producer rating of proficiency on that standard.

The adapter must preserve every published attempt. Attempt selection belongs to
later Meridian policy.

### Quillan

| Concern | Current architectural fact |
| --- | --- |
| Producer module | `quillan` |
| Native assignment contract | schema v2 |
| Native review contract | schema v2 |
| Native values | Focus Standards, native rating scale, review states, minimum-requirement outcomes, observations, overall ratings, feedback boundaries |
| Academic-result manifest | `quillan_academic_result_manifest_v1` |
| Academic Work producer contract | `quillan_academic_work_v1` |
| Publication record set/capability | `academic_results`; `standards_ratings` only |
| Public consumer reader | released in exact `quillan==0.9.0` |
| Meridian adapter | explicit, lazy `quillan.academic_result`, projection contract `1` |

The adapter preserves the exact Quillan scale and distinguishes a native
rating from a Meridian-derived proficiency level. `returned_without_full_review`
and other non-score states must not become zero or the lowest rating.

### Concord and future academic producers

A future academic producer is ingestible only after it supplies:

- a Core-compatible publication profile;
- an accepted immutable manifest contract;
- a public reader;
- producer-owned privacy and revision rules; and
- an exact Meridian adapter.

### Portia and intervention producers

An intervention producer may publish `intervention_record_set` without Academic
Work Registration and with only intervention capabilities.

Meridian may include authorized intervention context in reports. The adapter and
inventory must tag it as intervention information. It does not become standards
evidence, an assessment attempt, proficiency, or a Grade component by proximity
to academic data.

## Evidence provenance requirements

A projection must be capable of preserving:

- canonical `publication_id`;
- complete `ModuleWorkRef`;
- publication kind;
- record-set ID and revision;
- Core publication schema version;
- manifest contract version;
- exact manifest path;
- digest algorithm and digest;
- publication time;
- exact referenced Academic Work Registration revision;
- producer contract version;
- source-record reference and contract version when present;
- predecessor publication ID;
- observed withdrawal and series state;
- producer reader/contract identity;
- Meridian adapter identity and projection-contract version;
- native evidence identity and provenance; and
- import time and authorization/purpose context where required by later
  security design.

Later calculations add policy versions, selected and excluded evidence, exact
Academic Period Calendar revision, overrides, and calculation time.

## Cache and snapshot rules

A cached projection is derived state. Its cache key and stored provenance must
bind to exact canonical publication and manifest identity.

At minimum, a cache must not be considered reusable when any of these differ:

- publication ID;
- manifest digest;
- manifest contract version;
- referenced registration revision;
- producer contract version;
- adapter/projection-contract version; or
- authorization scope that materially governs retained contents.

Supersession or withdrawal may make a cached projection stale for current use,
but it does not mutate the historical projection. A current refresh creates a
new verification observation.

An issued report snapshot keeps the exact historical source publication even if
that publication is later superseded or withdrawn. Current views repeat
canonical verification and current source selection.

## Failure taxonomy

Later typed implementation must distinguish the following classes.

### Discovery and catalog

- catalog missing;
- catalog stale;
- catalog application/schema incompatible;
- catalog locked;
- catalog read failure;
- catalog malformed or corrupt; and
- candidate drift between catalog and canonical state.

### Canonical Core integrity

- Publication Record missing;
- Publication Record malformed;
- contradictory publication series;
- referenced registration missing;
- referenced registration malformed or mismatched;
- withdrawal relationship invalid; and
- canonical state changed during verification.

### Historical state

- current selectable;
- series head but withdrawn;
- historical predecessor;
- superseded; and
- withdrawn.

Historical state is not equivalent to malformed state.

### Compatibility and support

- producer profile missing;
- producer profile incompatible;
- Meridian adapter missing;
- producer public reader unavailable;
- publication kind unsupported;
- manifest contract unsupported;
- producer contract unsupported;
- capability incompatible; and
- source-record contract incompatible.

### Manifest integrity

- manifest path invalid;
- manifest outside work root;
- manifest missing;
- manifest not a regular file;
- symlink or path-race rejection;
- digest mismatch; and
- producer decode or validation failure.

### Authorization

- source access denied;
- student/target scope denied;
- requested use denied;
- referenced artifact access denied; and
- disclosure/report audience denied.

### Meridian policy

- valid evidence ineligible under active policy;
- Grade-item membership absent;
- attempt excluded;
- insufficient evidence;
- Academic Period exclusion; and
- report-definition exclusion.

Policy exclusion must not be reported as producer invalidity.

## Determinism

Candidate ordering, adapter selection, projection ordering, and diagnostics must
not depend on filesystem order, SQLite row order without explicit ordering,
Python hash iteration, package discovery order, or timestamps used as implicit
series selection.

Exact ties and duplicate candidates require deterministic handling defined by a
later implementation contract.

## Privacy and logging

Catalog and envelope diagnostics should remain privacy-minimized. Producer
manifests contain student-level educational information and must not be dumped to
logs, exception messages, test snapshots, CI output, or issue comments.

Public tests use synthetic identifiers and content. Adapter errors identify the
failed contract or invariant without reproducing student records.

## Implementation sequence

This architecture guides the remaining v0.1.1 issues:

1. package, typing, test, and CI foundation;
2. internal typed evidence inventory;
3. adapter interface and registry;
4. Core catalog discovery and canonical verification;
5. ScoreForm adapter;
6. Quillan adapter â€” implemented against the accepted v0.9.0 contract;
7. inventory and diagnostics commands;
8. exact cache and snapshot rules;
9. cross-producer synthetic scenarios; and
10. foundation audit and release.

No producer adapter should be implemented by copying a planned issue description
when the producer's accepted public contract is not yet available.

## Validation expectations

Documentation and later code reviews must verify:

- exact Core v0.6 API and contract names;
- no catalog-as-authority claims;
- no profile callback or parser claims;
- no producer dependency on Meridian;
- no generic fallback parser;
- no automatic Grade inclusion;
- no silent native-scale conversion;
- no intervention-to-academic conversion;
- exact source provenance; and
- synthetic-data-only public fixtures.

## Projection snapshots are derived state

Meridian may persist a validated producer projection only after exact canonical
verification, adapter projection, and a second canonical and authorization
check. The cache is Meridian-derived state outside Core registry and producer
work roots. It does not modify Publication Records, registrations, withdrawals,
producer manifests, or the disposable catalog.
