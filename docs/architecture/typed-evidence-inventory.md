# Typed evidence inventory

The first production population of this model is the exact ScoreForm v0.10.0
adapter. It preserves every native attempt, point pair, response/state,
correctness boolean, ordered standards alignment, Core provenance, and
producer-native provenance without introducing attempt selection or policy.
Quillan v0.9.0 is the second production population, preserving workflow states,
minimum-requirement outcomes, observation missingness, Boolean applicability and
evidence presence, native ratings, and teacher-entered overall ratings without
grading inference. Concord v0.2.0 is the third production population, adding
truthful non-student Score targets, richer native Scoring Scale metadata, Score
history, and Moderation/evidence-link provenance. See
[ScoreForm v0.10.0 adapter](scoreform-adapter.md),
[Quillan v0.9.0 adapter](quillan-adapter.md), and
[Concord v0.2.0 adapter](concord-adapter.md).

## Status

Meridian defines an immutable, producer-neutral evidence inventory for the
`0.1.1.dev0` publication-ingestion foundation.

The inventory is a typed projection boundary. It does not discover publications,
open manifests, load producer readers, evaluate eligibility policy, select
attempts, calculate proficiency, calculate Grades, or compose reports.

## Placement in the ingestion sequence

Later ingestion work follows this boundary:

```text
Core canonical verification
    -> exact consumer-side producer adapter
    -> validated producer public reader
    -> Meridian typed evidence inventory
    -> later eligibility and selection policy
    -> later proficiency, Grade, or reporting policy
```

Adapters project producer-native results into the inventory. They do not flatten
those results into one universal number.

## Exact Core provenance

Each `EvidenceProvenance` retains validated Core objects directly:

- one exact `PublicationRecord`;
- the exact referenced `AcademicWorkRegistration` for academic evidence;
- an optional matching `PublicationWithdrawal` for historical provenance;
- one explicit projection identity; and
- ordered producer-native provenance.

Meridian does not copy selected Publication Record fields into a competing
publication model. Convenience properties derive producer, work, publication,
record-set, manifest, source-record, and producer-contract identity from the
retained Core objects.

Academic evidence requires the exact registration revision referenced by the
Publication Record. Intervention evidence must not carry an Academic Work
Registration.

A withdrawal retained in provenance must identify the same Publication Record.
This model does not decide whether a withdrawn publication is currently
selectable.

## Projection identity

`ProjectionIdentity` records:

- the Meridian projection or adapter identifier;
- its projection contract version;
- the producer-reader distribution name; and
- the producer-reader version.

These values are recorded, not discovered, by this module. Version strings are
opaque identities. Meridian does not choose a nearest or numerically similar
version.

## Student subject

`StudentSubject` contains only `student_id`.

An `EvidenceItem` may instead carry `subject=None` when the producer result does
not assert an individual student subject. This is required for exact Group and
other non-student academic evidence and must not be interpreted as missing
evidence or copied to students.

The identifier follows Core's shared identifier policy and remains a string so
leading zeros are preserved. The inventory does not copy names, email addresses,
accommodations, roster rows, or other student display fields.

## Evidence target

`EvidenceTarget` preserves producer-native target meaning. It records:

- a target kind;
- an optional target identifier;
- an optional parent-target identity;
- ordered, duplicate-free aligned standard IDs;
- an optional positive sequence;
- optional exact producer owning-system identity; and
- optional exact producer target contract version.

Target examples include a whole work, attempt, question, standard, review unit,
criterion, requirement, submission, or intervention goal. The model does not
claim that those target kinds are interchangeable.

Alignment and rating remain distinct. A question aligned to a standard is not
therefore a standards rating. A review-unit observation is not an overall
standard rating. A whole-work point result is not retargeted to every Focus
Standard on an assignment.

### Producer-native identity and display text

Meridian-owned contract identifiers remain under their strict Meridian/Core
grammars. Producer-native identities carried by targets, standard alignment,
native references, and native scale IDs are different: they are opaque data
whose syntax and bounds belong to the validated producer contract.

Meridian requires producer-native text to be a string with non-whitespace
content and no NUL, then preserves the original string exactly. It performs no
trimming, case conversion, slash replacement, whitespace collapse, Unicode
normalization, or narrower consumer-side length restriction. Spaces, `/`, `\`,
punctuation, Unicode, embedded formatting, and meaningful leading or trailing
whitespace therefore remain intact when the producer contract permits them.

A native target or reference identity containing `/` is not a filesystem path.
It grants no artifact access and is never passed to a path resolver. Only
`NativeArtifact.path` uses Meridian's strict workspace-relative path contract.
Producer validation remains responsible for producer-specific identity grammar
and bounds before projection.

## Native result kind

Every `EvidenceItem` has an explicit producer-native `result_kind` independent
of its storage type.

For example, these boolean values have different meanings:

```text
standard_applicability = false
standard_evidence_presence = false
question_correctness = false
```

Their shared Python type does not make them equivalent.

## Typed native values

The evidence value is a closed union:

```text
NativeScalarValue
NativePointValue
NativeScaledValue
NativeStateValue
```

There is no arbitrary JSON mapping, `Any` payload, or generic normalized score.
Future shapes require explicit model changes.

### Scalar values

A native scalar is exactly one of:

```text
str | int | finite float | bool
```

Scalar equality preserves the exact Python scalar type. Integer `1`, floating
point `1.0`, string `"1"`, and boolean `true` are different native values.

`None`, bytes, collections, NaN, and infinity are invalid. An explicit absence or
non-score condition uses `NativeStateValue`.

### Point values

`NativePointValue` retains exact `earned` and `possible` numbers. `possible` must
be greater than zero.

The model does not calculate or store a percentage, clamp extra credit, round,
map points to proficiency, or declare the points to be a Grade.

### Native scales

`NativeScale` retains:

- exact scale ID;
- optional scale contract version;
- whether producer order is meaningful;
- optional lineage ID, name, revision, scale type, status, and superseded scale
  identity; and
- ordered native levels.

Each `NativeScaleLevel` retains an exact scalar value and optional producer label,
description, meaning, and position. Scale IDs, labels, descriptions, and meanings
use the same exact producer-native text boundary and are not normalized. Exact
level values must be unique.

A `NativeScaledValue` must match one declared level by both scalar type and
value. Numeric `1` does not match string `"1"`.

Scale equivalence is not inferred from equal level counts, numeric values,
labels, or descriptions.

For example, these remain distinct:

```text
Scale A
  id: quillan_standards_4_level
  contract: 2
  levels: 1 Developing, 2 Approaching, 3 Meeting, 4 Exceeding

Scale B
  id: district_performance_4_level
  contract: 1
  levels: 1 Beginning, 2 Developing, 3 Proficient, 4 Advanced
```

A later explicit mapping policy may relate them. The inventory does not.

### Native non-score states

`NativeStateValue` preserves an exact producer-owned state or disposition,
including an optional label and description.

Examples include:

```text
blank
ambiguous
unrated
not_checked
returned_without_full_review
```

No state automatically becomes zero.

## Native provenance

`NativeProvenance` preserves contract-significant order across three typed
collections.

### Native references

A `NativeReference` records a reference kind plus an exact identifier, positive
sequence, or both. A producer adapter may retain a hierarchy such as:

```text
attempt -> issuance -> page -> route -> scan -> source page
```

Other adapters may retain submission, review, review-unit, observation,
requirement, or intervention references.

The reference kind remains a strict Meridian contract code. Its optional
identifier is exact producer-native data, not an artifact path or authorization
to inspect an underlying producer record.

### Native artifacts

A `NativeArtifact` records an artifact kind and an optional workspace-relative
path or digest identity.

Paths must:

- be lexical and workspace-relative;
- use forward slashes;
- contain no drive or absolute prefix;
- contain no empty, dot, or traversal components; and
- avoid absolute private paths.

An artifact is optional because a valid producer result may represent
plain-paper or otherwise nondigital evidence.

### Native timestamps

A `NativeTimestamp` pairs a semantic timestamp kind with a timezone-aware
`datetime`.

Publication time, scan time, review-update time, and projection time remain
separate meanings rather than one ambiguous timestamp.

## Evidence eligibility

`EvidenceEligibility` has exactly three statuses:

```text
unevaluated
eligible
ineligible
```

`unevaluated` carries no policy claim. `eligible` identifies the exact policy and
version. `ineligible` additionally carries ordered, explicit reason codes.

Eligibility does not:

- validate a publication or manifest;
- represent authorization;
- represent withdrawal or compatibility failure;
- select an attempt;
- remove an item from the inventory;
- alter a native value; or
- assign a numeric consequence.

Validity, eligibility, and selection are separate questions.

## Evidence item and inventory

An `EvidenceItem` combines:

- one opaque inventory item ID;
- an optional privacy-minimal student subject;
- one native target;
- one native result kind;
- one typed native value;
- complete provenance; and
- one eligibility decision.

The item does not contain normalized score, percentage, proficiency, Grade,
selection, category weighting, Academic Period assignment, or teacher override.

`EvidenceInventory` preserves an ordered tuple of items. Item IDs must be unique;
duplicates fail instead of overwriting. Pure filter helpers can return items for
one student, work, publication, target kind, standard, or eligibility status.
They preserve relative order and perform no aggregation or selection.

## Synthetic examples

### ScoreForm-shaped attempt points

```python
EvidenceItem(
    item_id="attempt_1_points",
    subject=StudentSubject("00001"),
    target=EvidenceTarget("attempt", "attempt_1", sequence=1),
    result_kind="attempt_points",
    value=NativePointValue(earned=18, possible=20),
    provenance=verified_projection_provenance,
)
```

This item is not automatically a percentage, Grade, selected attempt, or
standards-proficiency observation.

### ScoreForm-shaped ambiguous response

```python
EvidenceItem(
    item_id="question_7_response_state",
    subject=StudentSubject("00001"),
    target=EvidenceTarget(
        "question",
        "question_7",
        parent_target=EvidenceTargetIdentity("attempt", "attempt_1"),
        sequence=7,
    ),
    result_kind="selected_response_state",
    value=NativeStateValue("ambiguous"),
    provenance=verified_projection_provenance,
)
```

`ambiguous` is not zero and is not the same as `blank`.

### Quillan-shaped Focus Standard rating

```python
EvidenceItem(
    item_id="overall_rating_rl_cr",
    subject=StudentSubject("00001"),
    target=EvidenceTarget(
        "standard",
        "njsls-ela:RL.CR.9-10.1",
        standard_ids=("njsls-ela:RL.CR.9-10.1",),
    ),
    result_kind="overall_standard_rating",
    value=NativeScaledValue(value=3, scale=quillan_native_scale),
    provenance=verified_projection_provenance,
)
```

The native Quillan scale is retained. Meridian does not reinterpret `3` as a
universal proficiency level.

### Quillan-shaped return disposition

```python
EvidenceItem(
    item_id="review_return_disposition",
    subject=StudentSubject("00001"),
    target=EvidenceTarget("submission", "submission_1"),
    result_kind="review_disposition",
    value=NativeStateValue("returned_without_full_review"),
    provenance=verified_projection_provenance,
)
```

The disposition is not a score, zero, completed review, or Grade.

## Academic and intervention separation

The retained Core `publication_kind` distinguishes `academic_result_set` from
`intervention_record_set`.

Shared provenance infrastructure does not transform intervention context into an
assessment attempt, standards rating, proficiency observation, or Grade
component. Producer-specific intervention value variants remain future adapter
work.

## Immutability and side effects

All inventory models are frozen and slotted. Ordered collections are immutable
tuples. Equality is deterministic and preserves exact scalar types.

Importing `meridian.evidence` or constructing inventory values does not:

- resolve a workspace;
- inspect the current directory;
- open manifests or artifacts;
- discover entry points;
- import ScoreForm, Quillan, Concord, Portia, or Vitrine;
- configure logging; or
- write files.

## Privacy

The inventory intentionally stores student IDs rather than copied roster display
fields. Artifact paths are workspace-relative. Tests and examples use synthetic
identifiers and records.

Representations and validation errors must not include artifact bytes, student
writing, full producer records, absolute local paths, or sensitive metadata
collections.

## Non-goals

This foundation does not implement:

- adapter interfaces or discovery;
- producer-reader loading;
- Core catalog discovery;
- canonical workspace retrieval;
- authorization;
- manifest verification or decoding;
- Portia, Vitrine, or other future intervention adapters;
- eligibility evaluation;
- attempt or evidence selection;
- proficiency or Grade calculation;
- Academic Period assignment;
- teacher overrides;
- persistence, caches, or snapshots;
- diagnostics commands; or
- report composition.

Those behaviors remain later reviewed issues.

## Exact persistence conversion

`meridian.evidence_serialization` now provides exact closed mapping conversion
for every inventory model. Persisting an inventory in a projection snapshot does
not normalize native values, evaluate eligibility, select evidence, or make an
item Grade-bearing.
