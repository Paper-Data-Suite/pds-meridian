# Evidence inventory and diagnostics

## Purpose

`meridian.diagnostics` is Meridian's read-only observation surface for Core
publication state and already-persisted Meridian evidence projections. It makes
the ingestion foundation inspectable without turning diagnostics into ingestion,
eligibility, selection, proficiency, Grade, or report policy.

The command surface is:

```text
meridian publications list ...
meridian publications verify <publication_id> ...
meridian evidence inspect <publication_id> <cache_key> ...
meridian evidence explain <publication_id> <cache_key> ...
```

All commands support deterministic text output. Data commands also support
`--format json` with diagnostic output version `1`.

## Authority boundaries

Catalog rows remain observations rather than canonical authority.

`publications list` performs one finite Core `PublicationCatalogQuery`, retains
the returned rows as candidate observations, and reloads canonical state before
reporting canonical status. Candidate drift and disappearance are diagnostic
findings; the command does not rebuild the disposable catalog.

`publications verify` starts from one exact canonical `publication_id` and does
not require the catalog. It reports canonical publication, registration, series,
withdrawal, producer-profile compatibility, exact Meridian adapter support, and
producer-reader distribution/version readiness.

Metadata diagnostics do not read producer manifests and do not invoke
`ProducerAdapter.project()`.

A successful metadata readiness result means only that the observed canonical
contracts can be understood by the installed compatibility surface. It does not
mean that manifest bytes were checked, access was authorized, evidence was
eligible, an attempt was selected, or a Grade can be calculated.

## Explicit adapter composition

The built-in diagnostic registry is ordinary explicit Meridian composition. At
this milestone it contains the exact ScoreForm v0.10.0 and Quillan v0.9.0
adapters. Installing a producer package does not register a Meridian adapter,
and Meridian does not discover its adapters through entry points.

Producer-reader readiness uses installed distribution metadata. Metadata-only
publication diagnostics therefore do not import producer runtime packages.

The command model is producer-neutral so a later Concord adapter can join the
same explicit registry without redesigning diagnostics.

## Support stages

Publication support is reported as separate stages rather than one generic
valid/invalid flag:

```text
producer profile
Core contract compatibility
Meridian adapter support
producer-reader readiness
```

The diagnostic model preserves existing `contracts.*`, `ingestion.*`, and
`adapters.*` identities where those codes already describe a failure.

Unsupported is distinct from unavailable. Historical and withdrawn are distinct
from malformed. An intervention publication is not malformed merely because
Meridian has no intervention adapter.

## Evidence inspection boundary

For issue #11, imported evidence means an existing immutable
`meridian_projection_snapshot` created through `meridian.projection_cache`.
Diagnostics do not create a second evidence store and do not reconstruct evidence
from producer workspaces or manifests.

`evidence inspect` and `evidence explain` require the caller to identify the
exact publication and cache key together with the exact projection purpose and
student scope.

The diagnostic service delegates the read to:

```python
load_authorized_projection_snapshot(...)
```

That existing cache boundary reloads current canonical state, requests a fresh
`read_projection_cache` authorization decision before cache-file access, checks
exact purpose and student-scope agreement, validates the immutable snapshot, and
assesses current source/cache reuse.

Possession of a cache key is not authorization. A matching student ID is not
authorization. Filesystem access is not authorization.

The stock console application deliberately has no production authorizer. If an
application or deployment has not injected a `PublicationAuthorizer`, sensitive
evidence commands fail closed with:

```text
diagnostics.authorization_provider_required
```

There is no command-line allow-all, skip-authorization, or unsafe bypass.
Synthetic authorizers are test-only.

## Evidence inspection

After successful authorization, `evidence inspect` exposes only the already
persisted typed `EvidenceInventory`.

Exact filters include:

```text
item ID
student ID
target kind
standard ID
result kind
EvidenceEligibility status
```

Different dimensions combine with logical AND. Repeated values within one
dimension use exact-match OR semantics. Filtering preserves original inventory
order and never mutates eligibility or selection state.

Typed values remain distinct:

```text
boolean
integer
float
string
points
scaled
state
```

Therefore `true`, `1`, `1.0`, and `"1"` remain different values. Native zero
remains zero. A producer non-score state remains a state rather than a numeric
sentinel. A native scale remains producer-owned rather than a Meridian
proficiency scale.

## Explaining current use

`evidence explain` reports the existing `ProjectionCacheAssessment` without
creating new policy. Its source states remain:

```text
current
superseded
withdrawn
withdrawn_superseded
unverifiable
```

Its reuse states remain:

```text
reusable
reprojection_required
historical_only
unverifiable
```

Existing ordered `cache.*` reason codes remain authoritative. Diagnostics do not
rename them or collapse them into a generic exclusion reason.

Source/current-use status is independent of `EvidenceEligibility`.

## EvidenceEligibility

Diagnostics expose only an item's already-recorded `EvidenceEligibility`:

```text
unevaluated
eligible
ineligible
```

`unevaluated` means no Meridian evidence-eligibility policy has evaluated the
item. Diagnostics invent no reason.

For an existing eligible decision, exact policy identity/version is retained.
For an existing ineligible decision, exact policy identity/version and reason
codes are retained.

Diagnostics do not infer ineligibility from withdrawal, historical state,
attempt number, review state, low value, missing response, producer disposition,
or adapter type.

## Output and process behavior

Text output is bounded and does not depend on terminal color for meaning. JSON
output is an ephemeral command result, not a persistent Meridian schema or
record.

Handled diagnostic findings such as historical, withdrawn, unsupported,
profile-incompatible, reader-unavailable, or existing ineligible evidence are
successful observations and do not automatically imply process failure.

Unsafe or incomplete operations, including canonical integrity failure, cache
integrity failure, denied evidence access, or missing authorization provider,
return failure without dumping manifests, cache bytes, arbitrary Python reprs,
or tracebacks.

Argument-parsing errors retain the normal argparse usage status.

## Privacy

Publication metadata commands expose privacy-minimized Core/publication identity
and compatibility metadata only.

Evidence commands may expose already-projected student evidence only after the
existing cache-read authorization boundary succeeds. Routine and failure output
must not disclose raw producer manifests, private producer-native records,
authorization secrets, workstation paths, or complete snapshot bytes.

Metadata access and student-evidence access are intentionally separate security
surfaces.

## Read-only guarantees

Diagnostics do not:

- rebuild the Core catalog;
- repair canonical Core state;
- write registrations or Publication Records;
- create withdrawals;
- invoke producer adapters to create evidence;
- create or modify projection snapshots;
- change evidence eligibility;
- select attempts or Scores;
- calculate proficiency or Grades;
- create reports.

Help and version operations retain the stronger baseline guarantee: they do not
discover a workspace, discover producer profiles, access the catalog, access a
cache, or import producer packages.

## Future producer shapes

The diagnostics model does not assume that every source record is absent, every
producer has the same evidence kinds, or every future publication is an academic
result. This is required for the planned Concord adapter and for Core's existing
`intervention_record_set` publication kind.

Issue #11 does not preemptively widen Meridian evidence subjects or native scale
metadata for Concord. Those changes, if genuinely required by Concord's released
contract, belong to the Concord adapter issue.

## Non-goals

This diagnostic layer does not implement:

- producer ingestion commands;
- evidence-eligibility policy;
- attempt or reassessment selection;
- standards-proficiency calculation;
- Grade-item membership;
- Grade calculation;
- Academic Period policy;
- report generation or delivery;
- production authentication or institutional authorization policy.
