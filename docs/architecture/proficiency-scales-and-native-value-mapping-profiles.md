# Proficiency scales and native-value mapping profiles

## Purpose

Issue #32 adds Meridian's canonical v0.2 proficiency-scale and native-value
mapping layer after explicit reassessment (#31) and before standards-evidence
association (#33).

It answers one bounded question:

```text
Given this exact producer/result semantic and this exact native value,
what category on this exact teacher-defined proficiency scale does one
explicit mapping-profile revision assign?
```

The boundary is:

```text
producer-native result
!=
Meridian proficiency category
!=
standards evidence association
!=
calculated standard proficiency
```

The interpretation layers also remain separate:

```text
reassessment != native-value mapping
native-value mapping != standards evidence association
```

Mapping interprets one native value. It does not decide whether the evidence is
eligible, selected, associated with a standard, aggregated, or sufficient to
establish student proficiency.

## Criterion-referenced proficiency scales

`ProficiencyScale` is Meridian-owned policy. It has stable logical identity
`(class_id, scale_id)` and immutable contiguous revisions.

One scale revision contains ordered `ProficiencyLevel` values with:

```text
level_id
position
label
description
```

Positions are contiguous positive ordinal positions. They express lower/higher
placement on this exact configured continuum. They are not interval-scale
numbers, percentages, points, or values safe to average.

Every scale revision also identifies one explicit
`proficiency_threshold_level_id`, the minimum category this policy regards as
meeting its proficiency criterion. The threshold is not inferred from a label
such as `Proficient`.

A four-level scale is a first-class use case, not a universal constant. Meridian
hard-codes no number of levels, category labels, threshold, or conventional
`1-4` meaning.

## Exact revisions and activation

Revision 1 has `supersedes_revision = null`; later revisions are contiguous and
preserve the same logical identity. Material changes to labels, descriptions,
order, level set, or threshold require a new revision.

Writing a revision never makes it active. Each scale family has an independent
SHA-256-bound `current.json` selector with compare-and-swap semantics.

Never infer current policy from:

```text
highest revision
latest timestamp
filesystem mtime
directory order
```

Historical revisions remain immutable and loadable.

## Exact scale references

`ProficiencyScaleReference` binds:

```text
class_id
scale_id
scale_revision
scale_sha256
```

A mapping profile always binds one exact scale revision/digest. A later scale
revision does not rewrite an older profile or historical mapping outcome.

## Native-value source signature

A mapping profile supports one exact producer/result semantic family through
`NativeValueSourceSignature`:

```text
producer_module_id
publication_kind
manifest_contract_version
producer_contract_version
projection_id
projection_contract_version
producer_reader_distribution
producer_reader_version
result_kind
target_kind
```

This deliberately prevents accidental cross-producer or cross-contract reuse.
`result_kind` alone is insufficient. A Python value type alone is insufficient.
A future producer/reader/projection revision does not silently inherit an older
profile merely because its output looks similar.

## Mapping profile identity and revisions

`NativeValueMappingProfile` has stable logical identity:

```text
class_id
scale_id
profile_id
```

Each immutable revision binds:

- one exact `ProficiencyScaleReference`;
- one exact `NativeValueSourceSignature`;
- one mapping kind;
- exact native-scale or point-scale semantics where required;
- explicit mapping rules;
- actor/rationale/time provenance.

New revisions never auto-activate. Each family has an independent CAS-protected
`current.json` selector.

Selecting a revision within one profile family does not automatically choose
that profile for any evidence. Profile application remains explicit.

## v1 mapping kinds

Version 1 supports exactly:

```text
exact_scalar
exact_native_scale
raw_points
```

There is no generic expression language, executable policy callback, universal
percentage transform, or interpolation mechanism.

## Exact scalar mapping

`exact_scalar` maps `NativeScalarValue` through explicit
`ScalarMappingRule` values.

Native scalar identity includes type as well as value:

```text
True != 1
1 != 1.0
```

Several native values may deliberately map to one proficiency category. A value
with no explicit rule returns `unmapped`. No scalar ordering is inferred.

## Exact native-scale mapping

`exact_native_scale` maps `NativeScaledValue`. The profile binds the complete
exact `NativeScale` snapshot represented by Meridian, including all available
identity, level, ordering, lineage, revision, type, status, and supersession
metadata.

Binding only `scale_id` is insufficient.

A mapping rule identifies one exact native level value and one target
`proficiency_level_id`. Partial mappings are valid. An unlisted native level is
`unmapped`; Meridian does not interpolate.

When the producer scale declares `order_is_meaningful = true`, mapped target
positions must be nondecreasing as native scale order increases. Adjacent native
levels may collapse to one target category, but the mapping cannot invert an
explicitly ordered native scale.

When native order is not meaningful, Meridian invents none.

### Quillan

Quillan v0.9.0 explicitly owns an assignment-local native rating scale. Values
need not be consecutive or start at one. Its normative public contract includes
a `0, 2, 4` scale specifically to prevent downstream assumptions about native
numeric meaning.

An explicit profile may map that scale to Meridian categories, but same-looking
numbers do not carry Meridian meaning automatically. `NativeStateValue("unrated")`
remains a non-score state.

### Concord

Concord v0.2.0 publishes rich native Scoring Scale semantics. Meridian preserves
native ordering, level meaning/position, lineage, revision, scale type, status,
and supersession where present.

Profiles therefore bind the exact scale snapshot. Similar-looking values from a
different Concord scale, lineage, revision, producer, result kind, or target kind
do not silently reuse a mapping.

## Raw-points mapping

`raw_points` maps `NativePointValue` using explicit earned-point ranges. The
profile binds one exact `points_possible` value with exact numeric type/value
semantics.

Therefore:

```text
8 / 10
```

and:

```text
9.6 / 12
```

are not automatically equivalent even though both could be described as 80%.

Point ranges have explicit inclusive/exclusive lower and upper boundaries. They
must be deterministic, ordered, and nonoverlapping. Gaps are permitted and
produce `unmapped`.

Because `earned` is explicitly a points-achieved semantic, higher ranges may not
map to lower target proficiency positions within one valid v1 profile.

## No percentage normalization

Issue #32 does not add:

```text
earned / possible
percentage
ratio
0-100 normalization
```

as a mapping kind or hidden helper.

The architecture explicitly rejects a universal numeric bridge across producer
semantics. If a future concrete requirement justifies ratio-based profiles, it
requires a later explicit schema/design decision.

## ScoreForm

ScoreForm v0.10.0 currently projects:

```text
attempt_points             -> NativePointValue
question_correctness       -> NativeScalarValue(bool)
selected_response          -> NativeScalarValue(...)
selected_response_state    -> NativeStateValue(...)
result_origin              -> NativeScalarValue(...)
```

ScoreForm publishes no native proficiency scale. Attempt points are raw points,
not implicit percentage/proficiency. Question correctness is an exact Boolean
native result, not calculated standard proficiency.

A profile for `question_correctness` does not apply to `selected_response` merely
because both use `NativeScalarValue`.

## Native non-score states

`NativeStateValue` is never mapped to a proficiency category in v1.

Examples include:

```text
unrated
blank
ambiguous
absent
excused
not_applicable
deferred
```

When the source semantic family otherwise matches the profile, the pure mapping
operation returns `native_state` and preserves the exact native state object.

It is never coerced to zero, false, the lowest category, or `unmapped` numeric
performance.

## Mapping outcomes

`NativeValueMappingOutcome` has a closed status vocabulary:

```text
mapped
unmapped
unsupported
native_state
```

### mapped

The exact source signature and value semantics are supported and exactly one
explicit rule identifies a target level.

### unmapped

The profile supports the source semantic family, but no explicit rule maps this
exact value. This is a normal visible domain state, not an exception or zero.

### unsupported

The profile does not support the actual source semantics, including source
signature mismatch, value-kind mismatch, exact native-scale mismatch, or raw
points denominator mismatch.

There is no automatic fallback to another profile.

### native_state

The supported source semantic is represented by an exact producer-native
non-score state. The state remains visible and unconverted.

## Pure mapping operation

`map_native_value(...)` receives:

```text
exact EvidenceValue
exact NativeValueSourceSignature
exact NativeValueMappingProfile revision
exact ProficiencyScale revision
```

and returns one deterministic `NativeValueMappingOutcome`.

`map_evidence_item(...)` derives the exact generic source signature from one
already-projected `EvidenceItem` and invokes the same pure operation.

Neither operation:

- opens producer files;
- discovers profiles from disk;
- chooses newest/current policy;
- changes evidence eligibility;
- changes attempt selection;
- changes reassessment state;
- creates standards associations;
- calculates student proficiency;
- persists output;
- uses wall-clock time.

## Mapping is not evidence selection

The runtime boundary is:

```text
mappable != eligible
eligible != selected
selected != mapped
mapped != standards evidence
mapped standards evidence != calculated proficiency
```

A successful mapping does not make evidence academically usable by itself.

## Mapping is not standards association

Issue #32 does not infer standards membership from:

- producer `standard_ids`;
- a successful mapping;
- a criterion identifier;
- a producer result called a standards rating.

Issue #33 owns bounded standards-evidence association and aggregation inputs.

## Mapping is not calculated proficiency

One mapped value is only an interpretation of one source value. It is not a
student's current standard proficiency, Grade Item result, Academic Period
proficiency, course result, or Grade.

Pure standards-proficiency calculation remains later work.

## Group and non-student evidence

Mapping never changes source target identity. A group/non-student source may be
mapped as a source value, but that does not individualize it or copy its meaning
to group members.

The no-individualization boundary remains intact for #33 and later calculation.

## Storage

`meridian.proficiency_mapping_storage` persists class-local policy under:

```text
classes/
  <class_id>/
    modules/
      meridian/
        proficiency_scales/
          <scale_id>/
            current.json
            revisions/
              1.json
              1.json.sha256
            mapping_profiles/
              <profile_id>/
                current.json
                revisions/
                  1.json
                  1.json.sha256
```

Scale/profile revisions use canonical UTF-8 JSON with one LF and SHA-256
sidecars. Histories are contiguous and immutable. Exact replay is idempotent;
same-identity/different-content writes conflict.

Current selectors are explicit, atomic, digest-bound, and compare-and-swap
protected. New revisions do not auto-select.

Profile writes verify that the exact referenced target scale revision/digest is
already persisted and that the profile's target-level/order rules remain valid
against that exact scale.

## Filesystem safety

Storage follows the hardened v0.2 persistence pattern:

- existing Core class required before policy creation;
- lexical containment;
- path-safe IDs;
- bounded reads;
- canonical byte verification;
- SHA-256 verification;
- symlink rejection;
- unexpected-entry rejection;
- narrow per-family write locks;
- atomic current-pointer replacement.

No `latest` alias is created.

## Privacy

Scale/profile state is policy data and stores no student evidence. It does not
copy answers, scores from real students, feedback, accommodations, demographics,
or producer artifacts.

Tests and installed smoke use synthetic values only.

## Producer neutrality

`meridian.proficiency_mapping` and
`meridian.proficiency_mapping_storage` import no producer package. They operate
on generic Meridian evidence contracts and public Core class/routing paths.

ScoreForm, Quillan, Concord, Portia, and Vitrine remain optional producer
integrations rather than runtime dependencies of the generic mapping layer.

## Compatibility

Issue #32 retains:

```text
Python >=3.11
pds-core>=0.6,<0.7
```

The package version remains unchanged during the v0.2 implementation sequence.

## Boundary to #33

After #32 Meridian can explain how one exact producer-native value maps, or why
it is unmapped/unsupported/non-score.

It still does not answer:

```text
Should this evidence count for this standard?
Which standard/criterion association is academically valid?
How should multiple mapped observations become bounded calculation inputs?
What is the student's calculated standard proficiency?
```

Issue #33 owns standards-evidence association and aggregation inputs.
