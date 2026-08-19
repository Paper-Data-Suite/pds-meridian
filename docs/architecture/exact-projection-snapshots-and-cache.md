# Exact projection snapshots and cache

ScoreForm v0.10.0 inventories use this unchanged generic boundary. Their cache
execution identity records adapter `scoreform.academic_result`, projection
contract `1`, distribution `scoreform`, and reader version `0.10.0`. The
adapter itself never reads or writes cache state.

Quillan v0.9.0 inventories use the same boundary. Their execution identity is
adapter `quillan.academic_result`, projection contract `1`, distribution
`quillan`, and reader version `0.9.0`; there is no producer-specific cache.

Concord v0.2.0 inventories use the same boundary with adapter
`concord.academic_result`, projection contract `1`, distribution `pds-concord`,
and reader version `0.2.0`. Group/non-student evidence remains non-student; no
Concord-specific cache path or ownership inference exists.

## Status

Meridian defines immutable, digest-bound projection snapshots for the
`0.1.1.dev0` publication-ingestion foundation.

A projection snapshot persists one exact authorized producer projection. It is
not a producer record, Core registry record, eligibility decision, selected
attempt, proficiency result, Grade, report snapshot, rendered report, or mutable
current view.

## Placement

```text
bounded Core catalog discovery
    -> canonical publication verification
    -> exact adapter selection and authorization
    -> exact manifest verification
    -> producer-owned reader and Meridian adapter projection
    -> validated EvidenceInventory
    -> canonical projection snapshot
    -> later eligibility, selection, grading, and reporting policy
```

The cache writer accepts an already projected `EvidenceInventory`. It validates
that inventory against the exact prepared request and adapter identity but does
not invoke the adapter or parse producer bytes.

## Exact source observation

Each `ProjectionSourceObservation` retains:

- the exact Core `PublicationRecord`;
- the exact referenced Academic Work Registration for academic evidence;
- the separately observed current registration;
- the exact target withdrawal;
- complete ordered publication-series IDs;
- target position;
- explicit series head and successor; and
- canonical state.

Canonical states remain `current_selectable`, `withdrawn_head`, `historical`,
and `withdrawn_historical`. No state is inferred from timestamps, greatest
revisions, filenames, cache order, or catalog order.

## Projection execution identity

`ProjectionExecutionIdentity` records the exact `AdapterKey`, adapter ID,
adapter-interface version, projection-contract version, producer-reader
distribution, and producer-reader version.

Every persisted evidence item must carry the corresponding
`ProjectionIdentity`. Adapter implementations, callbacks, registries, and import
paths are not serialized.

## Authorization observation and minimization

The snapshot records the exact successful `project_evidence` purpose, requested
student scope, authorization policy ID, and authorization policy version.

A nonempty scope filters the inventory before persistence while preserving item
order. Only evidence with an exact matching `StudentSubject` is retained.
Non-student Group/context evidence is excluded rather than individualized merely
because a requested student appears in producer context. Students with no
evidence receive no manufactured placeholder. An empty scope preserves the
complete authorized inventory, including non-student evidence, under the
deployment's exact decision; Meridian does not reinterpret it as universal
access.

The historical authorization observation does not authorize later cache reads.
Every public cache load requires a fresh `read_projection_cache` decision before
the snapshot file is opened and a fresh `project_evidence` decision before
current reuse is assessed.

## Exact evidence serialization

`meridian.evidence_serialization` converts every evidence model through exact,
closed mapping contracts. Unknown and missing fields fail. The evidence-value
union uses explicit `scalar`, `points`, `scaled`, and `state` tags.

Native scalar type is preserved. Boolean `true`, integer `1`, floating-point
`1.0`, and string `"1"` remain different values. NaN, infinities, bytes,
arbitrary mappings, pickle-like references, and unsupported variants are
invalid.

Core Publication Records, registrations, withdrawals, and routing identities use
Core's public conversion and validation APIs.

## Cache identity

`ProjectionCacheIdentity` contains only:

- snapshot schema version;
- exact source observation;
- exact projection execution identity; and
- exact projection authorization observation.

The cache key is lowercase SHA-256 of canonical UTF-8 JSON bytes for that
identity. Capture time, filesystem location, content digest, filesystem metadata,
and inventory content are excluded.

Inventory is excluded deliberately. Two different inventories produced from the
same declared projection inputs are a `cache.projection_nondeterministic`
conflict rather than two unrelated cache identities.

## Snapshot contract

The schema constants are:

```text
schema_version = 1
record_type = meridian_projection_snapshot
```

The exact top-level fields are:

```text
schema_version
record_type
cache_key
captured_at
source
projection
authorization
inventory
```

Canonical JSON is UTF-8, sorted by object key, indented by two spaces, finite,
and terminated by exactly one newline. Service-created capture time is normalized
to UTC. Duplicate object keys and noncanonical equivalent byte encodings fail.

## Cache location

```text
cache/meridian/projections/
  <publication_id>/
    <cache_key>/
      <snapshot_digest>.json
```

`snapshot_digest` is SHA-256 of exact canonical snapshot bytes. The cache-key
write lock is `.write.lock` in the same directory.

There is no `latest.json`, `current.json`, mutable pointer, SQLite index, or
selection by timestamp, modification time, lexical digest, revision, or directory
order.

Paths are workspace-relative and use forward slashes. Absolute, drive-qualified,
backslash, empty, dot, traversal, symlink, and nonregular storage components are
rejected.

## Creation, replay, and durability

Creation repeats canonical verification and the exact projection authorization
after adapter work. Changed canonical state or authorization blocks persistence.

A cache-key lock covers directory inspection, replay validation, and exclusive
creation. Exact replay returns the existing bytes and original capture time,
does not call the clock, and does not touch the file.

A difference in canonical serialized inventory bytes under the same identity
fails as projection nondeterminism. Replay comparison deliberately uses the
canonical persistence encoding rather than Python object equality, so
serialization-significant distinctions such as `0.0` versus `-0.0` or differing
timezone-offset representations cannot silently collapse. Meridian does not
overwrite, add a second snapshot, or choose a newer result.

Before confirmed durability, only an incomplete file created by the current
operation may be removed. After durability, the immutable snapshot is preserved.
Later reload or lock-cleanup failures produce privacy-safe partial-success state.

Reads are bounded by
`DEFAULT_MAXIMUM_PROJECTION_SNAPSHOT_BYTES`, currently 64 MiB, and read at most
one byte beyond the configured limit before rejecting oversized content.

## Current-state assessment

Assessment is read-only and separates source state from reuse state.

Source statuses are:

```text
current
superseded
withdrawn
withdrawn_superseded
unverifiable
```

Reuse statuses are:

```text
reusable
reprojection_required
historical_only
unverifiable
```

Current reuse requires an exact current, unwithdrawn source; unchanged current
registration observation; exact manifest verification; compatible producer
profile; unchanged adapter identity; unchanged reader version; and current
projection authorization under the same policy identity and version.

Supersession and withdrawal make a snapshot historical; they do not corrupt it.
Registration, profile, adapter, reader, or authorization changes require
reprojection when the source remains current. Missing or contradictory canonical
or manifest state is unverifiable.

Reason codes have one documented deterministic order. Assessment never writes a
`stale`, `current`, `last_checked_at`, withdrawal, or supersession field into the
snapshot.

## Historical immutability

Fresh assessment never rewrites the stored source observation, projection
identity, authorization observation, inventory, capture time, cache key,
snapshot digest, path, or bytes. Current reuse status exists only in the
returned assessment.

## Projection snapshots versus report snapshots

A projection snapshot preserves one producer-to-inventory transformation. A
future report snapshot will preserve selected sources, policy versions, derived
results, audience, issuance, and report composition.

A report may eventually reference an exact projection cache key and snapshot
digest. It must not reference a mutable current-cache alias or treat the
projection snapshot as an issued report.

## Privacy and security

Snapshot and stored-byte fields are hidden from ordinary representations.
Student IDs, evidence values, native provenance, manifest bytes, cache bytes, and
absolute paths do not appear in cache paths or routine errors.

Filesystem readability is not authorization. Public cache reads require a fresh
deployment decision before opening student-level snapshot bytes.

Imports, package help, and version output do not resolve a workspace, create
cache state, discover producers, import producer packages, invoke adapters,
configure logging, or write files.

## Non-goals

This foundation does not implement evidence eligibility, attempt or Score
selection, Academic Period assignment, proficiency or Grade calculation, report
snapshots, rendering, subscriptions, delivery, cache retention, deletion,
eviction, repair, migration, encryption, automatic refresh, background
monitoring, or Core publication of Meridian-derived state.
