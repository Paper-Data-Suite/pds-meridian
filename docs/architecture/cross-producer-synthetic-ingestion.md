# Cross-producer synthetic ingestion acceptance

This document records the v0.1.1 cross-producer acceptance boundary exercised by
Meridian issue #13. It describes what the synthetic scenarios prove about the
completed publication-ingestion foundation and, equally importantly, what they
do not prove about later grading policy.

The acceptance suite uses only synthetic educational records and the exact
released public contracts/readers for:

```text
ScoreForm v0.10.0
Quillan v0.9.0
Concord v0.2.0
Core v0.6.0
```

The governing rule is:

```text
producer-neutral != producer-semantic flattening
```

Meridian shares evidence containers, provenance, cache, diagnostics, and
authorization machinery across producers. It does not treat superficially
similar native values or relationships as interchangeable.

## Relationship to the ingestion foundation

The scenarios exercise the production boundaries already defined in:

- [Core v0.6 publication ingestion](core-v0.6-publication-ingestion.md);
- [typed evidence inventory](typed-evidence-inventory.md);
- [adapter interface and registry](adapter-interface-and-registry.md);
- [catalog discovery and canonical verification](catalog-discovery-and-canonical-verification.md);
- [exact projection snapshots and cache](exact-projection-snapshots-and-cache.md);
- [evidence inventory and diagnostics](evidence-inventory-and-diagnostics.md);
- [ScoreForm adapter](scoreform-adapter.md);
- [Quillan adapter](quillan-adapter.md); and
- [Concord adapter](concord-adapter.md).

The tests orchestrate several ordinary single-publication operations in one Core
workspace. They do not create a production combined-inventory API or a batch
ingestion contract.

For each publication the path remains:

```text
Core catalog candidate
-> canonical Core reload
-> producer compatibility
-> exact Meridian adapter selection
-> reader version check
-> deployment authorization
-> Core manifest path/digest verification
-> producer public reader
-> EvidenceInventory projection
-> immutable projection cache
-> fresh authorized cache assessment
```

Catalog rows remain observations. Canonical Core JSON remains authoritative.

## Real mixed Core workspace

The primary scenario creates one synthetic Core class:

```text
synthetic_class_2026
```

with independent registered works and publications for ScoreForm, Quillan, and
Concord.

All three publications coexist in one Core Academic Catalog and are rediscovered
through bounded catalog queries. Each candidate is then canonically reloaded
before projection.

The scenario uses:

- released ScoreForm, Quillan, and Concord producer profiles;
- Meridian's explicit built-in adapter registry;
- the exact public producer readers;
- a synthetic deployment authorizer;
- Core registry services for first publication, supersession, and withdrawal;
- Meridian projection-cache creation and authorized reload.

No sibling producer checkout is used as an alternate parsing authority.

## Same Standard, different semantics

The same synthetic Standard identifier is deliberately reused across producers:

```text
standard_ela_1
```

That shared identifier does not erase producer meaning.

The suite proves:

```text
ScoreForm question alignment
!= Quillan standard observation
!= Quillan overall standard rating
!= Concord standard-backed Score
```

ScoreForm question alignment remains alignment metadata attached to
question/response evidence. It is not promoted into a producer standards rating.

Quillan review-unit observation and overall rating remain different result
kinds even when they concern the same Standard.

Concord's standard-backed Score remains a Concord Score with its own target,
Criterion, Scoring Scale, Score history, and public provenance.

Issue #13 therefore establishes no generic "one Standard result" abstraction.

## Similar-looking numeric values and scales

The scenarios deliberately arrange an apparent native value of `2` across the
three producers.

The value remains:

```text
ScoreForm: NativePointValue
Quillan:   NativeScaledValue on a Quillan-owned scale
Concord:   NativeScaledValue on a Concord-owned scale
```

The two scaled values preserve different scale identities and metadata.
ScoreForm points remain earned/possible points.

The acceptance rule is:

```text
native Scale A value 2 != native Scale B value 2
points != native Scale rating
```

No percentage, normalization, common scale, average, or proficiency is
calculated during ingestion.

## Repeated attempts versus Score history

ScoreForm and Concord expose different kinds of repetition.

The ScoreForm scenario preserves multiple attempts for one registered work.

The Concord scenario preserves both a superseded Score predecessor and its
current successor, including the explicit supersession relationship.

The invariant is:

```text
ScoreForm attempt != Concord Score history
```

Neither relationship is treated as reassessment policy. Meridian does not
choose latest, highest, best, current, or preferred evidence in this milestone.

## Native zero versus non-score state

The mixed scenarios retain legitimate numeric zero separately from explicit
producer-native non-score states.

Representative states include:

```text
ScoreForm: blank / ambiguous
Quillan:   unrated / returned_without_full_review
Concord:   absent
```

A valid native Scale value of `0` remains numeric zero.

The invariant is:

```text
native zero != non-score state
```

No producer-native non-score code becomes `0`, `False`, a minimum scale level,
or a generic `missing` sentinel.

Every adapter-created item remains:

```text
EvidenceEligibility(status="unevaluated")
```

Non-score state therefore does not itself create a Meridian eligibility
decision.

## Exact source-record asymmetry

The producer contracts do not share one source-record shape.

At the frozen releases:

```text
ScoreForm Publication Record source record: absent
Quillan Publication Record source record:   absent
Concord Publication Record source record:   required Activity
```

Concord still requires:

```text
module:   concord
kind:     activity
contract: concord_activity_v1
```

The mixed workspace proves that generic orchestration does not normalize these
differences into a weaker nullable source-record convention.

## Group evidence and student scope

Concord can publish a Group Score that is not an individual student Score.

With an empty requested-student scope, an authorized full projection can retain
subjectless Group/context evidence.

With a nonempty scope for the shared synthetic student, the generic cache layer
retains only exact matching `StudentSubject` evidence and excludes
`subject=None` items.

The invariant is:

```text
Group Score != individual Score
Group context mentioning a student != student ownership
```

No Group Score is copied or individualized merely because public subject
context mentions that student.

This behavior is implemented by the producer-neutral cache scope, not by a
Concord-specific cache branch.

## Deterministic replay and cache separation

For each producer, identical canonical source, exact adapter/reader,
authorization identity, manifest bytes, and projected inventory produce the
same cache key and immutable stored snapshot.

An exact second cache operation returns the existing snapshot and does not
capture a new time.

Across the three producers, cache keys remain distinct even when fixtures reuse
similar identifiers such as:

```text
student_synthetic_001
standard_ela_1
native value 2
```

Cross-producer identity is therefore bound to exact Core source and projection
identity rather than local value resemblance.

## Supersession and withdrawal isolation

The canonical-state scenario first caches all three current publications, then
changes only selected producer state:

```text
ScoreForm: superseded by record-set revision 2
Quillan:   current publication withdrawn
Concord:   unchanged
```

Assessment of the original snapshots then yields the existing cache semantics:

```text
old ScoreForm snapshot -> superseded / historical_only
Quillan snapshot       -> withdrawn / historical_only
Concord snapshot       -> current / reusable
```

The old snapshot bytes remain unchanged.

This proves that supersession or withdrawal for one producer does not create a
global workspace-stale state and does not rewrite another producer's cache.

Canonical source status and evidence eligibility remain separate concepts.

## Unsupported reader version versus unsupported contract

Two failure classes are exercised separately.

An installed reader version outside one adapter's exact frozen version is a
producer-local reader-version failure. A synthetic Quillan `0.9.1` resolution
does not make exact ScoreForm `0.10.0` or Concord `0.2.0` support unavailable.

An unsupported future contract fails exact adapter selection. Meridian does not
fall through by producer name, publication kind, capability similarity, or
another producer's adapter.

The distinction is:

```text
unsupported installed reader version
!= unsupported publication/producer/source contract
```

No closest-version or generic-parser fallback is introduced.

## Multiple Academic Periods

The primary boundary scenario also persists a real Core
`AcademicPeriodCalendar` for school year `2026-2027` with two periods:

```text
period_q1
period_q2
```

The three producer publications ingest successfully while that calendar exists.

The calendar is then advanced from revision 1 to revision 2 and the disposable
Core Academic Catalog is rebuilt.

Existing raw projection snapshots remain current and reusable because Academic
Period configuration is not part of producer-to-evidence projection identity.

The architectural rule is:

```text
Academic Period definition != ingestion-time Grade-period assignment
```

No `EvidenceItem` receives a fabricated period field. Ingestion does not infer
period membership from score time, review time, publication time, manifest
generation time, registration time, or filesystem placement.

Future Grade/proficiency calculations may bind an exact Academic Period calendar
revision. That later policy does not belong in the raw ingestion cache.

## Mixed diagnostics

One bounded publication diagnostic listing can contain all three producers at
once.

A synthetic reader-version failure for Quillan remains local to the Quillan
observation:

```text
ScoreForm -> support_ready
Quillan   -> support_unsupported / version_unsupported
Concord   -> support_ready
```

Diagnostics therefore retain per-publication support state rather than
manufacturing one global support status.

Metadata-only diagnostics do not open producer manifests or inspect persisted
student evidence.

## Authorization isolation

Authorization remains per publication, operation, purpose, and student scope.

A selective synthetic authorizer can deny Quillan projection while allowing
ScoreForm and Concord.

The denial test removes the Quillan manifest before preparation. Meridian still
returns the authorization-denied error, proving the denied manifest is not
opened or verified first.

The invariant is:

```text
authorization for one publication != authorization for the workspace
```

No allow-all production authorizer is introduced by these tests.

## Failure privacy

Cross-producer acceptance includes explicit assertions that routine
unsupported-version and unsupported-contract exceptions do not embed manifest
bytes or the shared synthetic student identifier in their messages.

This complements the repository-wide
[synthetic-data policy](../development/synthetic-data.md), which requires stable
error categories and prohibits educational-record dumps.

A failure in one producer does not include evidence from another producer merely
because both live in the same synthetic workspace.

## No grading leakage

The adversarial fixture intentionally contains several facts that later grading
policy could use:

- repeated ScoreForm attempts;
- Concord Score history;
- Quillan and Concord evidence on the same Standard;
- a withdrawn publication;
- multiple Academic Periods;
- native numeric zero;
- explicit non-score states.

Issue #13 proves that raw ingestion does not turn those facts into policy.

The suite does not:

- select an attempt or reassessment winner;
- choose latest, highest, best, or current evidence;
- average values across producers;
- normalize native scales;
- calculate proficiency;
- infer Grade-item membership;
- assign evidence to Academic Periods;
- calculate assignment, period, or course Grades;
- create report snapshots.

Those remain governed by later Meridian policy architecture.

## Acceptance outcome

The cross-producer scenarios did not expose a production runtime defect in the
post-Concord v0.1.1 ingestion foundation.

No Meridian runtime, cache schema, adapter interface, package dependency, or
producer contract change was required.

The implementation changes for issue #13 are therefore limited to:

- parameterized synthetic producer fixture support;
- additive cross-producer scenario support/tests;
- this architecture/acceptance record;
- documentation validation protecting the record.

This is the intended result:

```text
verified producer-neutral ingestion foundation
```

It is not:

```text
completed proficiency or Grade engine
```

The next milestone step is the v0.1.1 foundation audit and release.
