# Versioned Grade policies and Academic Period activation

Issue #49 implements the first executable v0.3 Grade-policy state while
preserving ADR 0005's separation between producer evidence, Meridian
interpretation, proficiency, Grade policy, Grade calculation, preview,
ReportingSnapshot, export, and official school-system records.

This issue stops before Grade calculation. Issues #50 through #52 consume the
exact policy and activation state defined here.

## Authority boundary

Meridian owns Grade-policy revisions and Grade-policy activation decisions.

Core remains authoritative for class identity, Academic Period Calendars,
Academic Period identity, standards, and the neutral shared contracts already
used by Meridian. Grade Items and v0.2 interpretation state remain Meridian
state with their existing authorities. Producer modules remain authoritative for
producer-native evidence.

The controlling distinctions are:

```text
GradeItemRevision.weighting metadata != executable Grade policy

GradePolicy family
    != GradePolicy revision
    != selected revision within that family
    != activated GradePolicy for an Academic Period

Grade policy
    != Grade calculation
    != Grade preview
    != ReportingSnapshot
    != official Grade
```

A Grade Item's `category_id` or `relative_weight` may help a future authoring
surface construct a policy, but calculation must consume the exact materialized
Grade-policy revision rather than dynamically interpreting Grade Item metadata.

## Released dependency baseline

Issue #49 is implemented against the reviewed v0.3 baseline:

```text
Python >=3.11
pds-meridian 0.2.0
pds-core 0.6.3
scoreform 0.11.0
quillan 0.10.0
pds-concord 0.3.0
```

The issue adds no unconditional producer dependency. Before later substantive
implementation and release qualification, ADR 0005 still requires a fresh check
of the latest non-prerelease relevant PDS releases and exact supported
distribution identities.

## Grade-policy model

`meridian.grade_policy` defines immutable, frozen, slotted policy records.

A logical policy family is identified by:

```text
class_id
policy_id
```

One exact immutable revision is identified by:

```text
class_id
policy_id
policy_revision
```

and `GradePolicyReference` adds the canonical-byte SHA-256:

```text
class_id
policy_id
policy_revision
policy_sha256
```

Revision history is linear:

```text
revision 1 -> supersedes_revision = null
revision N -> supersedes_revision = N - 1
```

No revision is mutated in place.

### Exact Grade Item participation

`GradePolicyItemReference` binds:

```text
class_id
grade_item_id
grade_item_revision
grade_item_revision_sha256
```

`GradePolicyItemParticipation` represents Grade Item -> Grade policy
participation. It is deliberately not `GradeItemMembershipDecision`, which is
the existing v0.2 work -> Grade Item relationship.

```text
registered Core work -> Grade Item
    !=
Grade Item -> Grade policy
```

A `reporting_only` Grade Item cannot silently become Grade-bearing merely
because it appears in policy input.

### Conventional configuration

`ConventionalGradeConfiguration` supports exactly three v1 modes:

```text
total_points
weighted_items
weighted_categories
```

`total_points` lists exact participating Grade Item revisions and stores no item
or category weights.

`weighted_items` requires one explicit positive finite Decimal weight for every
participating Grade Item. The complete weight set must sum exactly to `1`.
Malformed input is rejected rather than normalized.

`weighted_categories` defines exact category records and category weights that
sum exactly to `1`. Each participating Grade Item explicitly names its category.
Within-category calculation remains the bounded points-based calculation owned
by issue #50; issue #49 stores configuration only.

All weights are exact `Decimal` values. Binary floating-point values are not
accepted as Grade-policy weights.

### Standards-based configuration

`StandardsBasedGradeConfiguration` binds:

- one exact `ProficiencyScaleReference`;
- explicit durable Core standard IDs;
- one positive finite Decimal weight per participating standard;
- an explicit proficiency-level -> Grade-value conversion;
- the bounded v1 aggregation strategy; and
- a minimum calculated-result requirement.

Standard weights form a complete weighting scheme and must sum exactly to `1`.

A proficiency label has no universal numeric meaning:

```text
"proficient" != 85
```

unless the exact policy revision explicitly maps that level to that value.

The model stores the conversion; issue #51 performs the calculation.

### Bounded hybrid configuration

`HybridGradeConfiguration` combines only:

```text
one conventional configuration
+
one standards-based configuration
```

with explicit positive Decimal component weights summing exactly to `1`.

v0.3 does not introduce arbitrary formulas, scripts, recursive component graphs,
or plugin-defined Grade expressions. Issue #52 performs the bounded hybrid
calculation.

## Explicit non-Grade state treatment

Every Grade-policy revision materializes treatment for all required states:

```text
missing
pending
incomplete
excused
excluded
not_applicable
insufficient_evidence
unavailable
withdrawn
invalid
unresolved
```

The v1 closed consequences are deliberately constrained.

`missing` and `incomplete` may be configured as `exclude`, `blocking`, or
explicit `zero`.

`pending` may be only `exclude` or `blocking`.

`excused`, `excluded`, and `not_applicable` are `exclude` only.

`insufficient_evidence`, `unavailable`, `withdrawn`, `invalid`, and `unresolved`
may be `exclude` or `blocking`.

Therefore:

```text
missing or unresolved state != numeric zero
```

A numeric zero exists only when the exact policy explicitly assigns the
supported consequence. Nulls, absent keys, failed lookups, empty collections,
invalid records, or unresolved state never coerce to zero.

## Reassessment authority

`GradeReassessmentHandling` preserves the v0.2 attempt/reassessment decision
chain as selection authority.

Issue #49 does not add:

```text
latest_attempt
highest_attempt
best_attempt
```

or any other competing re-selection rule.

The policy may state whether unresolved reassessment state is `exclude` or
`blocking`, but it cannot re-decide which attempt contributes.

```text
v0.2 attempt/reassessment decision
    -> Grade-policy consequence

not

Grade policy
    -> attempt reselection
```

## Rounding

`GradeRoundingPolicy` stores exact Decimal rounding semantics:

```text
quantum
mode
application_stage
```

Schema version 1 supports final-result rounding only. Intermediate item,
category, standard, or component state is not rounded merely because the final
Grade display is rounded.

The rounding mode is explicit rather than inherited from Python defaults.

## Canonical Grade-policy storage

`meridian.grade_policy_storage` stores policy families beneath the existing Core
class Meridian subtree:

```text
classes/
  <class_id>/
    modules/
      meridian/
        grade_policies/
          <policy_id>/
            current.json
            revisions/
              1.json
              1.json.sha256
              2.json
              2.json.sha256
```

Immutable revision JSON uses canonical UTF-8 bytes. Each sidecar is the lowercase
SHA-256 of the exact JSON bytes.

Storage provides:

- immutable exclusive revision creation;
- exact replay returning `existing`;
- same-identity/different-content conflict detection;
- contiguous history validation;
- bounded reads;
- canonical JSON and sidecar validation;
- path containment and identifier validation;
- symlink rejection;
- unexpected-entry rejection;
- scoped write locks;
- explicit compare-and-swap current selection; and
- deliberate historical revision reselection.

Writing revision 2 does not select revision 2.

No reader infers current state from the highest revision, newest timestamp,
filesystem order, or directory modification time.

### Exact dependency validation

Before a policy revision is persisted or selected, storage revalidates its exact
dependencies as applicable:

- Core class existence;
- exact Grade Item revision and SHA-256;
- Grade Item purpose compatibility;
- exact proficiency-scale revision and SHA-256;
- explicit durable Core standard identities;
- complete weighting and conversion constraints; and
- class-scope consistency.

Historical policy records remain immutable. Dependency validation controls
whether a revision can be used now; it does not rewrite historical bytes.

## Grade-policy activation model

`meridian.grade_policy_activation` defines a separate immutable decision family.

Its record type is:

```text
meridian_grade_policy_activation
```

Each decision binds:

```text
class_id
target_period = AcademicPeriodRef
calendar_revision
activation_revision
supersedes_revision
decision
policy_reference
actor
rationale
decided_at
```

Supported decisions are:

```text
activate
deactivate
```

`activate` requires an exact `GradePolicyReference`.

`deactivate` requires `policy_reference = null`.

Activation history is linear and immutable in the same manner as policy
revision history.

### Exact Core calendar binding

Activation binds a school-year-qualified `AcademicPeriodRef` plus one exact
Academic Period Calendar revision. It does not store a copied period label as
authority and does not infer the target period from dates.

A later Core calendar revision does not silently alter an existing activation.

A teacher may create a later activation revision that intentionally binds a
different calendar revision.

There is no automatic parent/child Academic Period inheritance.

## Canonical activation storage

`meridian.grade_policy_activation_storage` stores one logical activation history
per exact class and Academic Period identity:

```text
classes/
  <class_id>/
    modules/
      meridian/
        grade_policy_activations/
          <school-year-qualified-period-identity>/
            current.json
            revisions/
              1.json
              1.json.sha256
              2.json
              2.json.sha256
```

The path uses canonical validated period identity rather than the display label.

Activation persistence preserves the same immutable revision, canonical JSON,
SHA-256, bounded-read, path/symlink, locking, and compare-and-swap protections
used by Grade-policy storage.

Writing an activation revision does not select it.

## Activation currentness

The selected activation decision is separate from the policy family's selected
revision.

```text
policy family's current revision changes
    != active period policy changes
```

For example:

```text
Policy A family current -> revision 4

MP1 activation -> Policy A revision 2
MP2 activation -> Policy A revision 4
```

is valid simultaneous state.

A new Policy A revision 5 also does not change either activation.

`resolve_grade_policy_activation` preserves three distinct outcomes:

```text
unconfigured
deactivated
activated
```

`unconfigured` means there is no explicit activation current selection for that
period.

`deactivated` means the explicitly selected activation decision is
`deactivate`.

`activated` means the explicitly selected decision is `activate` and its exact
policy revision/digest remains verifiable.

These states are not interchangeable.

No activation currentness is inferred from the greatest activation revision or
the newest timestamp.

## Activation dependency validation

Before an activation revision is persisted or selected, Meridian validates:

- the Core class;
- the exact Academic Period Calendar revision;
- the exact target `AcademicPeriodRef` inside that revision;
- for `activate`, the exact Grade-policy family/revision/digest;
- policy/class scope; and
- the policy's own exact dependencies.

This gives downstream calculation an immutable provenance chain:

```text
exact Core Academic Period/calendar revision
+
exact selected GradePolicyActivationDecision
+
exact GradePolicyReference
    ->
#50 / #51 / #52 calculation
```

Changing policy-family `current.json` is not part of this resolution.

## Issue boundary

Issue #49 deliberately does not implement:

- conventional Grade calculation;
- standards-based Grade calculation;
- hybrid Grade calculation;
- Grade previews;
- teacher Grade/proficiency overrides;
- ReportingSnapshots;
- Grade/report exports;
- direct SIS/LMS/district-gradebook writes; or
- official Grade/report-card authority.

The downstream sequence remains:

```text
#49 policy + activation state
-> #50 conventional Grade calculation
-> #51 standards-based Grade calculation
-> #52 bounded hybrid Grade calculation
-> #53 overrides
-> #54 explanations
-> #55 ReportingSnapshots
-> #56 exports
```
