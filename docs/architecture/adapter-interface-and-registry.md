# Adapter interface and registry

## Status

Meridian defines an immutable, deterministic consumer-side producer adapter
interface and exact-match registry for the `0.1.1.dev0` publication-ingestion
foundation.

The registry selects synthetic or later real Meridian-owned adapters from
already validated Core publication context. It does not query the Core catalog,
load canonical records, evaluate Core producer-profile compatibility, authorize
access, open workspace files, or implement a real producer reader.

## Placement in the ingestion sequence

The executable boundary is:

```text
Core candidate discovery and canonical reload
    -> Core producer-profile compatibility evaluation
    -> exact Meridian adapter selection
    -> deployment authorization
    -> Core manifest path and digest verification
    -> AdapterProjectionRequest with verified immutable bytes
    -> selected producer public reader
    -> Meridian EvidenceInventory
```

Issue #8 owns the orchestration before the projection request. Issues #9 and #10
will provide the first real ScoreForm and Quillan adapters.

## Dependency direction

Adapters are consumer-side Meridian integrations:

```text
pds-meridian -> pds-core

Meridian adapter -> producer-owned public reader or contract

producer package -> pds-core
producer package -X-> pds-meridian

pds-core -X-> producer parser
pds-core -X-> Meridian grading policy
producer package A -X-> producer package B
```

Core's `PublicationProducerProfile` remains metadata-only. It does not contain a
Meridian callback, parser, path resolver, authorization decision, or grading
policy.

The base Meridian distribution still requires only:

```text
pds-core>=0.6,<0.7
```

No producer package, adapter entry-point group, or automatic plugin discovery is
introduced by this foundation.

## Core compatibility versus Meridian support

Core compatibility and Meridian adapter availability are separate questions.

Core's compatibility evaluator checks shared metadata including:

- producer module identity;
- Core publication schema;
- Academic Work producer contract;
- publication kind;
- manifest contract;
- publication capabilities; and
- source-record kind and contract version.

The Meridian registry does not copy or replace that evaluator. Later
orchestration must preserve Core compatibility failures separately.

A publication may therefore be:

- Core-compatible and supported by a Meridian adapter;
- Core-compatible but adapter-missing;
- adapter-present but Core-incompatible;
- adapter-selected but producer-reader unavailable;
- adapter-selected but reader-version unsupported; or
- adapter-invoked but projection-invalid.

Those states must not collapse into one generic parse error.

## Adapter interface version

`MERIDIAN_ADAPTER_INTERFACE_VERSION` identifies the callable contract between
Meridian orchestration and adapters.

It is independent from:

- the Core package version;
- Publication Record schema version;
- Core publication compatibility contract version;
- Academic Work producer contract version;
- manifest contract version;
- source-record contract version;
- adapter projection contract version; and
- producer-reader distribution version.

Numeric resemblance among those versions is not compatibility.

## Exact adapter key

`AdapterKey` contains:

```text
producer_module_id
publication_kind
manifest_contract_version
producer_contract_version
source_record_kind
source_record_contract_version
```

`adapter_key_from_core(...)` derives the key from validated
`PublicationRecord` and `AcademicWorkRegistration` values.

For `academic_result_set`, the exact referenced registration is required and its
producer contract version enters the key.

For `intervention_record_set`, no registration or producer contract version is
allowed.

Source-record states remain distinct:

```text
missing source record
    source_record_kind = None
    source_record_contract_version = None

unversioned source record
    source_record_kind = "assignment"
    source_record_contract_version = None
```

The registry uses exact typed equality only. It performs no semantic-version
ordering, prefix matching, nearest-version selection, newest-version selection,
or wildcard fallback.

## Examples of exact separation

### Same producer, different manifest contract

```text
synthetic_producer / academic_result_set / manifest_1
synthetic_producer / academic_result_set / manifest_2
```

These require separate keys. Registering `manifest_2` does not make
`manifest_1` compatible.

### Same manifest, different producer contract

```text
manifest_1 + producer_contract_1
manifest_1 + producer_contract_2
```

These also require separate keys. A later producer contract does not supersede
an earlier contract by numeric or chronological inference.

### Missing versus unversioned source record

```text
(None, None)
("assignment", None)
```

These are different keys and never fall back to one another.

## Adapter descriptor

`AdapterDescriptor` records:

- stable adapter ID;
- exact adapter key;
- adapter-interface version;
- projection contract version;
- supported Core publication capabilities;
- producer-reader distribution name; and
- exact supported producer-reader distribution versions.

The adapter ID becomes the evidence `ProjectionIdentity.projection_id`.

The projection contract version identifies Meridian's projection semantics. It
is not the producer manifest version or reader package version.

Reader versions are an explicit nonempty set of exact tested distribution
versions. The registry does not use version ranges and does not add a runtime
version-parsing dependency.

## Capability semantics

Capabilities constrain an already exact key match:

```text
Publication Record capabilities
    must be a subset of
AdapterDescriptor.supported_capabilities
```

Capabilities do not select an adapter by themselves and do not define manifest
shape or educational meaning.

For example, an exact key may exist for an adapter declaring only `points` while
the canonical publication claims both `points` and `question_evidence`. That is
reported as `adapters.capability_unsupported`, not adapter-missing.

## Producer adapter protocol

`ProducerAdapter` exposes:

```python
@property
def descriptor(self) -> AdapterDescriptor: ...

def project(self, request: AdapterProjectionRequest) -> EvidenceInventory: ...
```

The protocol contains no ScoreForm-, Quillan-, Concord-, Portia-, or
Vitrine-specific type.

A producer package does not implement this protocol for Meridian. Meridian owns
the adapter and calls the producer's consumer-neutral public reader.

## Projection request

`AdapterProjectionRequest` carries:

- exact validated `PublicationRecord`;
- exact referenced `AcademicWorkRegistration` or `None`;
- optional matching `PublicationWithdrawal` for historical provenance; and
- verified immutable manifest bytes.

The bytes are excluded from `repr`.

The request contains no catalog row, workspace root, absolute path, writable
file object, authorization token, roster row, student display name, or arbitrary
context mapping.

Issue #8 is responsible for loading and verifying the bytes through Core. Request
construction recomputes the declared SHA-256 digest as a pure handoff invariant;
it does not reopen the filesystem or replace Core's canonical verification.

## Immutable explicit registry

`AdapterRegistry` is constructed explicitly from trusted adapter objects.

Construction:

- captures immutable descriptor bindings;
- copies the caller's iterable;
- orders entries deterministically by the complete exact key;
- rejects duplicate keys;
- rejects one adapter ID with conflicting projection, reader, capability, or
  interface identity; and
- supports an empty base-package registry.

There are no mutable `register`, `replace`, `remove`, or `clear` operations and
no process-global registry.

Inspection through bindings, adapters, keys, and exact lookup does not import a
producer reader.

## Selection has no fallback

Selection derives one exact key and performs one exact lookup.

These do not match:

- same producer with another publication kind;
- same producer and kind with another manifest contract;
- same manifest with another producer contract;
- same source kind with another source contract;
- versioned versus unversioned source record;
- equal capabilities under different contracts; or
- a numerically nearby version.

A missing exact key raises `adapters.not_found`.

## Lazy reader availability

Reader availability uses an injectable distribution-version resolver.

The production resolver calls `importlib.metadata.version(...)`. It does not
import the producer package.

Reader resolution occurs only during explicit invocation, after adapter
selection. Outcomes remain distinct:

```text
adapters.reader_unavailable
adapters.reader_version_unsupported
```

The registry does not install packages, query package indexes, or accept an
untested reader version.

## Invocation and projection enforcement

Explicit invocation performs:

1. exact adapter selection;
2. capability validation;
3. exact producer-reader version resolution;
4. adapter projection;
5. `EvidenceInventory` return-type validation; and
6. provenance and projection-identity validation for every item.

Every projected item must retain the request's exact:

- Publication Record;
- registration or `None`;
- withdrawal or `None`; and
- therefore producer, work, manifest, and source-record identity.

Every projection identity must equal:

```text
projection_id = AdapterDescriptor.adapter_id
projection_contract_version = descriptor projection contract
producer_reader_distribution = descriptor reader distribution
producer_reader_version = resolved installed version
```

An empty inventory is valid. Meridian does not fabricate placeholder evidence.

## Projection violation example

Suppose the selected adapter is bound to publication
`pub_11111111111111111111111111111111`, but it returns evidence whose provenance
contains `pub_22222222222222222222222222222222`.

The registry rejects the result with
`adapters.projection_contract_violation`. It does not silently rewrite the
provenance or accept the producer's result.

The same failure applies to a wrong registration revision, withdrawal, adapter
ID, projection contract, reader distribution, or reader version.

## Error taxonomy

Stable adapter codes include:

```text
adapters.duplicate_key
adapters.duplicate_identity
adapters.not_found
adapters.capability_unsupported
adapters.reader_unavailable
adapters.reader_version_unsupported
adapters.projection_failed
adapters.projection_contract_violation
```

Core compatibility codes such as `contracts.manifest_version_incompatible`
remain Core-owned and are not renamed by this module.

Controlled adapter projection errors remain distinct from contract violations.
Unexpected exceptions are wrapped with a privacy-safe message and cause chain.
Manifest bytes and native student content are not included in messages.

## Security and side effects

Importing `meridian.adapters`, constructing a registry, inspecting it, and
selecting an adapter do not:

- resolve a workspace;
- inspect the current directory;
- open files;
- read secrets;
- configure logging;
- access the network;
- discover entry points;
- import producer packages; or
- write files.

Loading and executing producer code is a later explicit trust decision.
Discovery is not authorization.

## Non-goals

This foundation does not implement:

- Core catalog discovery or canonical retrieval;
- producer-profile discovery or compatibility orchestration;
- authorization;
- filesystem manifest verification;
- a real producer public reader;
- ScoreForm, Quillan, Concord, Portia, or Vitrine projection;
- automatic adapter discovery or adapter entry points;
- optional producer dependency extras;
- evidence eligibility or attempt selection;
- proficiency or Grade calculation;
- diagnostics commands;
- persistence, caches, snapshots, or reports; or
- a release-version change.
