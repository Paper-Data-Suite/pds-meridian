# Catalog discovery and canonical verification

## Status

Meridian implements a typed, read-only preparation layer for Core v0.6
publications. The layer discovers bounded candidates through Core's disposable
Academic Catalog, reloads exact canonical Core state, evaluates producer
compatibility, selects an exact Meridian adapter, checks reader readiness,
enforces deployment authorization, verifies and reads bounded manifest bytes,
and constructs an immutable `AdapterProjectionRequest`.

Catalog rows are candidate observations only. They never become canonical
Publication Records, registration records, withdrawal records, evidence, Grade
items, or report sources.

The generic preparation service still stops before parsing and invocation. A
caller may pass its verified request to an explicitly composed ScoreForm v0.10.0
or Quillan v0.9.0 adapter.

## Implemented sequence

The executable sequence is:

```text
bounded PublicationCatalogQuery
    -> Core CatalogPublication candidates
    -> canonical Publication Record reload by publication_id
    -> exact referenced registration reload when academic
    -> separate current registration reload when academic
    -> complete canonical series and withdrawal reload
    -> candidate-to-canonical drift comparison
    -> exact Core producer profile lookup
    -> Core compatibility evaluation
    -> exact Meridian adapter selection
    -> non-importing producer-reader version check
    -> deployment authorization decision
    -> Core manifest path and digest verification
    -> bounded immutable byte read
    -> AdapterProjectionRequest digest handoff check
    -> canonical context reload
    -> PreparedPublicationInvocation
```

Authorization precedes manifest access. The preparation service does not open or
read the producer manifest before the deployment returns an explicit allowed
decision.

## Catalog authority boundary

Core's `registry/catalog.sqlite` is derived, disposable state. Meridian queries
it only through:

```python
PublicationCatalogQuery
query_publication_catalog(...)
```

Meridian does not:

- connect to SQLite directly;
- issue SQL;
- rebuild or repair the catalog;
- infer a catalog lock from exception text;
- create a missing catalog;
- or fall back automatically to an unbounded canonical scan.

Every Meridian discovery request requires a positive finite Core query limit.
Core's deterministic result order and explicit pagination are retained.
Capabilities may narrow candidates, but they do not establish educational
meaning, producer compatibility, adapter support, authorization, or Grade
membership.

Catalog failures remain distinct:

```text
ingestion.catalog_missing
ingestion.catalog_incompatible
ingestion.catalog_invalid
ingestion.catalog_read_failed
```

A catalog failure does not prove canonical Core records are invalid.

## Candidate observations

`PublicationCandidate` retains one exact Core `CatalogPublication` and its
zero-based ordinal in the bounded result. Meridian keeps the complete row only
for drift diagnostics.

The candidate's `publication_id` is the sole value used to begin canonical
reload. Meridian never constructs a `PublicationRecord` from catalog fields and
never allows a catalog path, digest, capability set, registration state, or
series flag to override canonical state.

Duplicate publication IDs in one result are treated as catalog integrity
failure rather than silently deduplicated.

## Canonical publication reload

For every candidate, Meridian calls Core's stable canonical retrieval surface by
exact publication ID. A missing canonical record is reported as:

```text
ingestion.candidate_missing
```

Malformed or contradictory publication state and operational read failure remain
separate:

```text
ingestion.publication_invalid
ingestion.publication_read_failed
```

The Core exception remains available as the cause, while Meridian's outer error
message avoids absolute paths and sensitive producer content.

## Referenced and current registration state

For an `academic_result_set`, Meridian loads two deliberately separate values:

1. the exact immutable registration revision referenced by the Publication
   Record; and
2. the registration selected by Core's explicit current pointer.

The referenced registration supplies the historical producer contract used for
Core compatibility and adapter selection. A later current registration update
does not rewrite that historical contract.

The current registration is retained for drift and later diagnostics. Its
lifecycle may differ from the historical referenced lifecycle without making the
Publication Record malformed.

Registration failures remain explicit:

```text
ingestion.registration_missing
ingestion.registration_invalid
ingestion.registration_mismatch
ingestion.registration_current_invalid
```

An `intervention_record_set` carries no referenced or current Academic Work
Registration in Meridian's canonical context. Meridian does not fabricate a
producer contract or attach an unrelated academic registration merely because
the same work identity has one.

## Canonical series and withdrawal observation

Meridian reloads the complete exact series identified by:

```text
ModuleWorkRef + publication_kind + record_set_id
```

It delegates chain validation to Core's `list_publication_record_set(...)`.
Core's validated order is retained. Meridian does not select a head using the
largest record-set revision, newest timestamp, filename, publication ID, or
filesystem order.

Each `PublicationSeriesMember` preserves the exact Publication Record and its
optional exact Publication Withdrawal. The target publication receives one of
four nonoverlapping observations:

```text
current_selectable
withdrawn_head
historical
withdrawn_historical
```

Historical and withdrawn states are not generic corruption. They may remain
necessary for audit, provenance, prior projections, or issued reports. Later
policy decides whether they may be used for a current calculation.

Contradictory series and withdrawal state use:

```text
ingestion.series_invalid
ingestion.withdrawal_invalid
ingestion.withdrawal_read_failed
```

## Candidate drift

After canonical reload, Meridian compares every supported catalog observation
against canonical authority, including:

- work and source-record identity;
- publication kind and capabilities;
- record-set identity and revision;
- manifest contract, path, algorithm, and digest;
- publication time;
- referenced registration revision and lifecycle;
- current registration revision and lifecycle for academic publications;
- predecessor identity;
- series-head state;
- withdrawal state and time; and
- current-selectable state.

The catalog's derived school-year value is retained as discovery metadata but is
not claimed as canonically verified by this implementation.

Any disagreement raises:

```text
ingestion.candidate_drift
```

The error carries a deterministic tuple of privacy-safe field codes. Meridian
does not silently substitute canonical values and continue under a candidate
that may no longer satisfy the original query. The caller must rediscover or use
an explicitly reviewed maintenance workflow.

Typical drift scenarios include:

- a publication superseded after catalog rebuild;
- a publication withdrawn after catalog rebuild;
- a current registration pointer advanced after catalog rebuild;
- changed registration lifecycle;
- changed capabilities or contract metadata; and
- a canonical Publication Record removed while a stale row remains.

## Producer compatibility and adapter support

The deployment supplies an explicit Core `PublicationProducerRegistry`.
Meridian does not discover producer profiles at module import.

The exact canonical producer module selects one profile. Meridian then delegates
all shared contract evaluation to Core's
`evaluate_publication_compatibility(...)` and preserves Core's exact
`contracts.*` result codes.

Profile outcomes include:

```text
ingestion.profile_missing
ingestion.profile_registry_invalid
ingestion.profile_evaluation_failed
ingestion.profile_incompatible
```

Core compatibility and Meridian support remain separate:

- a compatible profile may have no Meridian adapter;
- an adapter may exist while the profile is incompatible;
- a selected adapter may have no installed reader; and
- an installed reader version may be unsupported.

After compatibility succeeds, Meridian calls `AdapterRegistry.select(...)` with
canonical objects only. Adapter failures retain their existing `adapters.*`
codes.

Reader readiness uses `resolve_producer_reader_version(...)` and an injectable
distribution-version resolver. It inspects distribution metadata without
importing the producer package. Later adapter invocation rechecks readiness.

## Authorization boundary

`PublicationAuthorizer` is a narrow deployment protocol. Meridian supplies a
privacy-minimized `PublicationAuthorizationRequest` containing:

- the canonical Publication Record;
- exact referenced registration or `None`;
- target withdrawal or `None`;
- canonical series state;
- the closed `project_evidence` operation;
- an explicit purpose ID; and
- an optional deterministic tuple of requested student IDs.

The request contains no roster names, email addresses, credentials, tokens,
workspace path, manifest bytes, or arbitrary claims mapping.

A `PublicationAuthorizationDecision` always identifies an exact policy ID and
version. Allowed decisions contain no denial reasons. Denied decisions contain
at least one stable dotted reason code.

There is no permissive default authorizer. A denied decision raises:

```text
ingestion.authorization_denied
```

and performs no Core manifest verification or byte read.

This foundation defines the protocol and enforcement point only. It does not
implement a district identity system, role model, legal policy, or audience
policy.

## Manifest verification and bounded bytes

After authorization, Meridian calls Core's
`verify_publication_manifest(...)` with the canonical Publication Record.
Catalog path and digest values are never used for filesystem access.

Core remains responsible for canonical path validation, workspace/work-root
containment, regular-file inspection, and exact SHA-256 agreement.

Meridian then reads the exact Core-returned path in binary read-only mode with a
positive explicit bound. The package default is 16 MiB:

```text
DEFAULT_MAXIMUM_MANIFEST_BYTES = 16 * 1024 * 1024
```

A deployment may choose a smaller or larger positive bound explicitly.
Meridian reads at most `maximum_manifest_bytes + 1` bytes so oversized content
fails without an unbounded read.

Manifest outcomes remain distinct:

```text
ingestion.manifest_missing
ingestion.manifest_invalid
ingestion.manifest_read_failed
ingestion.manifest_too_large
```

Meridian does not decode, normalize, parse, rewrite, or canonicalize the bytes.
It retains immutable `bytes` only inside `AdapterProjectionRequest`, whose
representation excludes them.

`AdapterProjectionRequest` recomputes SHA-256 over the in-memory bytes. This
handoff invariant detects a path race or mutation between Core verification and
the bounded read. It supplements rather than replaces Core's filesystem
verification.

## Final canonical-state recheck

After the request is constructed, Meridian reloads the complete canonical
context again. If the second observation differs—or cannot be reverified—the
prepared result is discarded and Meridian raises:

```text
ingestion.canonical_state_changed
```

This catches events such as:

- a withdrawal added during verification;
- a successor published during verification;
- a current registration pointer change;
- target disappearance; or
- newly contradictory series state.

Meridian never merges fields from two observations.

## Prepared invocation

`PreparedPublicationInvocation` retains:

- the catalog candidate observation;
- one coherent canonical context;
- exact producer profile;
- exact Core compatibility result;
- exact adapter match;
- resolved producer-reader version;
- allowed authorization decision; and
- hidden `AdapterProjectionRequest`.

It retains no absolute path, open file, writable buffer, parsed producer model,
evidence inventory, Grade policy, credential, or arbitrary context mapping.

The production preparation function does not call `adapter.project(...)` or
`AdapterRegistry.invoke(...)`. The ScoreForm v0.10.0 and Quillan v0.9.0 adapters
use this prepared handoff; other producers remain follow-up work.

## Determinism

Discovery preserves Core's explicit catalog order. Series observations preserve
Core's validated chain order. Student IDs, authorization reasons, compatibility
codes, and drift fields are deterministic.

The implementation does not use filesystem order, Python hash iteration,
entry-point order, timestamps as implicit selection, or largest revisions as
current-state authority.

## Privacy and side effects

Public tests and documentation use only synthetic identifiers and bytes.
Manifest bytes never appear in representations, errors, logs, snapshots, CI
output, or issue examples.

Importing `meridian.ingestion` does not:

- resolve a workspace;
- query a catalog;
- discover profiles;
- construct adapters;
- import producer packages;
- open manifests;
- configure logging;
- read secrets;
- access the network; or
- write files.

Discovery and verification are explicit calls. They read Core and producer
state but do not mutate, rebuild, repair, cache, or persist it.

## Synthetic scenarios

### Current candidate remains current

A bounded `state="current"` row is reloaded, matches the canonical head, has no
withdrawal, passes compatibility and authorization, and produces a prepared
request.

### Candidate superseded after catalog build

The catalog row still says current, but canonical series reconstruction finds a
successor. Drift includes `series_head` and `current_selectable`; preparation
stops.

### Candidate withdrawn after catalog build

Canonical withdrawal state disagrees with the catalog row. Drift includes
`withdrawal` and `current_selectable`; no manifest is opened.

### Current registration changed

The publication still references registration revision 1, while Core's current
pointer now selects revision 2. Meridian preserves both. A stale catalog row
fails with `current_registration` drift.

### Intervention publication

The context includes no Academic Work Registration. Compatibility and adapter
selection use `None` for the producer contract.

### Compatible profile, missing adapter

Core compatibility succeeds, then exact Meridian selection raises
`adapters.not_found`. The failure is not renamed as profile incompatibility.

### Selected adapter, unavailable reader

Exact adapter selection succeeds, but the distribution resolver raises
`adapters.reader_unavailable` before authorization or manifest access.

### Authorization denied

The deployment returns a denied policy decision. Meridian raises
`ingestion.authorization_denied`; manifest verification and byte reading are
not called.

### Altered manifest

Core rejects the digest, or the in-memory handoff digest rejects bytes changed
after Core verification. No adapter is invoked.

### Withdrawal during verification

Initial state is current and unwithdrawn. After byte preparation, the final
reload observes a withdrawal and raises `ingestion.canonical_state_changed`.

## Non-goals

This implementation does not provide:

- catalog rebuild or repair;
- automatic canonical fallback;
- direct SQLite access;
- Core JSON parsing;
- registry mutation;
- institutional authorization policy;
- producer manifest decoding;
- producer semantic validation;
- adapter invocation;
- ScoreForm or Quillan projection;
- evidence eligibility or selection;
- Grade-item membership;
- proficiency or Grade calculation;
- diagnostics CLI commands;
- persistent ingestion records;
- cache or snapshot policy;
- report generation; or
- release-version changes.

## Post-projection snapshot preparation

`PreparedPublicationInvocation` retains the exact authorization request and
decision. After adapter projection, cache creation reloads canonical context and
repeats the exact projection authorization before persisting derived evidence.
Cache reuse never substitutes for current canonical verification.
