# Concord v0.3.0 adapter qualification

## Status

Meridian issue #23 originally added the exact consumer-side adapter for the
released Concord v0.2.0 Academic Result publication contract. That remains a
historical Meridian v0.1.1 release fact. The current unreleased v0.2 development
tree requalifies the same bounded adapter against released Concord v0.3.0.

The adapter is intentionally observational. It projects validated producer
results into Meridian's typed evidence inventory. It does not select Scores,
individualize Group Scores, calculate eligibility, calculate proficiency,
calculate Grades, read separately protected Artifact bytes, consume GroupPlans,
consume grouping signals, or infer Group membership.

## Current exact release boundary

The active qualification targets the authenticated Concord release:

```text
release tag: v0.3.0
release commit: fe37f9fca3dd7894a86f5a5c4e74bbe09c1e84ed

wheel:
  pds_concord-0.3.0-py3-none-any.whl
  SHA-256:
  dd827f7059c91c79bd69b6190b3c673d6b3bbc02bc25fa666286bbf5883c5e12

sdist:
  pds_concord-0.3.0.tar.gz
  SHA-256:
  454ecb87bee50ec6a54b6e17c0d38ea14c3c7fb417a8926e2b32090dba0dc3db
```

The public academic-result contract used by Meridian did not change between the
qualified v0.2.0 and v0.3.0 tags. Git identifies the exact same blobs for:

```text
concord/academic_result_manifest.py
  0d82054ba2d72700871d6e9756bb1973fa1396d0
concord/academic_result_reader.py
  4d6b0b2a46717debe45eac3838a8182171bd9814
concord/pds_publication.py
  b1e36b3b70217b9cdf5a785e60da4984abc93df2
```

Therefore the qualification change rebases exact reader distribution identity
without changing Meridian projection semantics. Concord v0.3.0's new GroupPlan
and grouping-signal workflows remain downstream Concord-owned planning state and
do not expand this academic-result adapter's authority.

Meridian's `scripts/verify_concord_wheel.py` freezes the wheel filename,
distribution metadata, exact version, SHA-256, public contract members, exact
Core requirement, and active installation identity.

## Exact adapter key

The adapter identity is:

```text
adapter_id: concord.academic_result
projection_contract_version: 1
producer_reader_distribution: pds-concord
producer_reader_version: 0.3.0
```

The exact `AdapterKey` is:

```text
producer_module_id: concord
publication_kind: academic_result_set
manifest_contract_version: concord_academic_result_manifest_v1
producer_contract_version: concord_academic_work_v1
source_record_kind: activity
source_record_contract_version: concord_activity_v1
```

There is no version range, producer-only fallback, publication-kind-only
fallback, or adapter entry-point discovery.

## Required Activity source record

A Concord academic publication must carry the exact versioned source record:

```text
module_id: concord
record_kind: activity
contract_version: concord_activity_v1
```

The referenced Academic Work Registration must use:

```text
producer_contract_version: concord_academic_work_v1
work_kind: collaborative_activity
```

After the released reader validates the immutable manifest bytes, Meridian
requires exact agreement among Core publication identity, the referenced
registration, the manifest work/activity context, the record-set identity and
revision, the source Activity, and the released capability derivation.

These are consumer handoff invariants. Meridian does not duplicate Concord's
manifest semantic validator.

## Dynamic capability derivation

The adapter descriptor supports at most:

```text
criterion_scores
moderated_scores
standards_ratings
```

A concrete Concord publication may claim only the subset represented by its
content. Meridian calls Concord's released `derive_manifest_capabilities()` and
requires exact set equality with `PublicationRecord.capabilities`.

Meridian does not derive Concord capabilities from field names or require all
three capabilities on every publication.

## Public-reader boundary

Runtime Concord imports are lazy and occur only during actual projection.

The manifest authority is:

```text
concord.academic_result_reader
read_academic_result_manifest(request.manifest_bytes)
```

Meridian does not parse Concord JSON itself, open a Concord workspace, scan
directories, load current native records, regenerate a manifest, or infer a
manifest from filenames.

Importing `meridian.concord_adapter`, constructing the built-in Meridian adapter
registry, and running metadata-only CLI/help diagnostics do not import the
Concord runtime.

## Group versus student evidence

Concord Score targets are preserved exactly.

A Score whose target is `core_student` receives a `StudentSubject`. A Group or
other non-student Score carries:

```text
subject = None
```

while retaining its exact producer-native target kind, target ID, owning system,
and contract version.

`None` means only that Meridian asserts no individual student subject for the
item. It does not mean missing evidence.

A nonempty requested student scope excludes non-student evidence. Meridian does
not copy one Group Score to Group members and does not infer Group membership
from evidence subject context, Artifact authorship, or route metadata.

## Local and standard-backed Scores

Each represented Concord Score revision becomes one `EvidenceItem`.

Local Scores and standard-backed Scores use distinct result kinds. Standard
alignment is retained only when the producer Score is standard-backed. Meridian
does not reinterpret a local Criterion as a Standard or a standard-backed Score
as calculated proficiency.

No current/preferred Score is selected. Superseded Score revisions remain in the
inventory with their explicit supersession/current-state provenance.

## Native Scoring Scales

Concord Scoring Scale semantics are retained without normalization.

`NativeScale` preserves:

- exact scale ID;
- lineage ID;
- name;
- revision;
- scale type;
- status;
- superseded scale identity;
- producer order semantics; and
- every ordered level.

Each `NativeScaleLevel` may preserve value, label, description, meaning, and
position. Nonconsecutive values and nonconsecutive positions remain exact.

A Concord native scale is not a Meridian proficiency scale.

## Non-score semantics

A Score with disposition `scored` becomes a `NativeScaledValue`.

A non-score disposition becomes `NativeStateValue`. Native zero remains numeric
zero. Absence, missingness, or another non-score disposition is never converted
to zero.

Producer-native status-reason identity, recording actor, recording timestamp,
and related-record identity are retained in provenance when present.

## Score history

Every represented Score revision is preserved. Producer supersession identity,
current/superseded state, scorer identity, score timestamp, basis, moderation
completion, Activity/session identity, and manifest generation context remain
native provenance.

Score history is evidence history. It is not Meridian attempt selection,
reassessment policy, Grade-item membership, or Grade calculation.

## Score Evidence Links

Public Score Evidence Link identities remain provenance attached to the
corresponding Score. Link status, significance, relevance description,
supersession, public evidence-reference identity, locator metadata, and subject
context are preserved where represented.

An evidence reference is not a Score and does not authorize Artifact access.

## Moderation

Public Moderation relationships remain provenance. Meridian retains explicit
Moderation record identity, status, permitted use, qualification, current state,
supersession, and target-subject context.

Moderation does not become proficiency, eligibility, Score selection, or Grade
policy. A student appearing in Moderation subject context does not transform a
Group Score into an individual Score.

## Artifact-reader separation

The Concord Academic Result Manifest may contain public Artifact references.
The adapter never calls or imports the separately authorization-gated Concord
Artifact reader.

Preserve:

```text
manifest authorization != Artifact authorization
evidence reference != permission to read Artifact bytes
```

A later feature that requires Artifact content must use Concord's separately
authorized Artifact boundary.

## Privacy boundary

Deterministic Meridian item IDs are hashes over contract-significant identities
and do not embed Group IDs, student IDs, feedback text, or Artifact content.

Controlled adapter failures identify the adapter/publication boundary without
dumping manifest bytes or producer content.

## Eligibility boundary

All projected Concord evidence enters Meridian with existing
`EvidenceEligibility(status="unevaluated")`.

The adapter does not evaluate eligibility, infer Moderation acceptance as
eligibility, select evidence, or assign a numeric consequence to a non-score
state.

## Cache and diagnostic integration

The producer-neutral evidence changes introduced for Concord are part of the
same exact serialization/cache boundary used by the other adapters.

Legacy ScoreForm and Quillan target/scale mapping shapes remain readable. The
extended representation is emitted when target ownership/version or richer scale
metadata is present.

Student-scoped projection snapshots never individualize non-student evidence.
An empty authorized student scope may retain complete authorized inventories
under the deployment authorization decision.

Diagnostics render non-student evidence with a null/none student identity and
retain target ownership/version and rich scale metadata. Student filters exclude
non-student items rather than associating them with a requested student.

## Packaging

Concord remains optional:

```text
pds-core>=0.6.3,<0.7
```

remains Meridian's only unconditional runtime dependency.

Exact Concord support is exposed as:

```text
pds-concord==0.3.0; extra == "concord"
```

The built-in registry explicitly composes ScoreForm, Quillan, and Concord
adapters. Installing a producer package does not auto-register an adapter.

## Non-goals

Issue #23 does not implement:

- Score selection;
- Group membership inference;
- eligibility policy;
- standards-proficiency calculation;
- Grade-item membership;
- Grade calculation;
- report or portfolio policy;
- Concord Artifact authorization; or
- changes to Concord, Core, ScoreForm, Quillan, or another producer repository.
