# Academic Period standards-proficiency aggregation

Issue #35 implements Meridian's Academic Period standards-proficiency aggregation
layer over the exact immutable Grade Item-level results established by issue #34.

The governing boundary is:

```text
exact #34 Grade Item standards-proficiency results
    -> explicit Academic Period scope resolution
    -> bounded Academic Period aggregation inputs
    -> pure deterministic Academic Period proficiency calculation
    -> immutable Academic Period proficiency result
```

The academic meanings remain distinct:

```text
mapped evidence
!= Grade Item standards proficiency
!= Academic Period standards proficiency
!= Grade
```

Issue #35 does not calculate a conventional, standards-based, or hybrid Grade. It
does not execute Grade Item weighting, generate grouping signals, form Groups,
produce reports, or synchronize with an SIS.

This architecture follows ADR 0001 and ADR 0004 and builds directly on
[Grade Item membership and Academic Period assignment](grade-item-membership-and-academic-period-assignment.md)
and [Grade Item standards-proficiency calculation](standards-proficiency-calculation.md).

## Runtime modules

Issue #35 adds:

```text
meridian.academic_period_proficiency
meridian.academic_period_proficiency_storage
```

`meridian.academic_period_proficiency` owns immutable policy, exact target and
membership-basis models, pure period-scope resolution, bounded aggregation
inputs, pure ordinal calculation, result snapshots/references, canonical
serialization, calculation fingerprints, transition validation, and pure
freshness diagnostics.

`meridian.academic_period_proficiency_storage` owns immutable policy/result
revision persistence, SHA-256 sidecars, dependency verification, explicit
current selectors, compare-and-swap selection, bounded reads, and path/integrity
hardening.

Neither generic module imports ScoreForm, Quillan, Concord, or another producer
package.

## #34 results are atomic

One persisted #34 result is one atomic Grade Item/student/standard academic
judgment. Issue #35 never reopens that result to split, filter, move, or
recalculate its underlying evidence.

The required relationship is:

```text
exact #34 result
    -> evaluate its complete recorded membership basis
    -> decide whether that whole result fits the requested period scope
    -> aggregate the result as one value or preserve an explicit mismatch
```

The prohibited relationship is:

```text
#35
    -> open #34 evidence
    -> choose a period-specific subset
    -> recalculate Grade Item proficiency
```

This matters when one Grade Item result was calculated over work whose exact #28
membership basis spans different Academic Periods. That historical state is
valid, but the combined #34 result cannot be silently attributed to one sibling
period.

## Exact membership provenance

`AcademicPeriodProficiencyMembershipBasis` captures the minimal exact #28 basis
needed for period interpretation:

```text
grade_item_id
grade_item_revision
grade_item_revision_sha256
work_reference
membership_revision
membership_sha256
academic_period
```

When a #34 input entry records membership provenance for a represented work,
the supplied #35 membership snapshot must match that exact revision and digest.
Current membership cannot reinterpret an older #34 result.

Teacher-controlled membership revision remains the reconciliation mechanism. If
work is explicitly reassigned from MP2 to MP1, the old membership and old #34
result stay immutable; a later #34 result must be built from the revised exact
basis before it can become eligible for MP1.

## Exact Academic Period target

`AcademicPeriodProficiencyTarget` binds:

```text
AcademicPeriodRef
+ calendar_revision
```

Therefore every calculation targets exactly:

```text
school_year
+ calendar_revision
+ period_id
```

The target period must exist in that exact Core `AcademicPeriodCalendar`
revision. Period IDs are not treated as globally timeless identities across
calendar revisions.

A membership from another school year or calendar revision is an explicit scope
mismatch even when its `period_id`, label, dates, or apparent hierarchy happen
to look identical.

## Period-membership scope

`AcademicPeriodMembershipScope` supports exactly:

```text
direct
descendants
```

### `direct`

Every included membership in the exact Grade Item basis must be assigned directly
to the target school year, calendar revision, and period ID.

For example:

```text
Quiz    -> MP1
Writing -> MP1
target  -> MP1
scope   -> direct

eligible
```

But:

```text
Quiz    -> MP1
Writing -> MP2
target  -> MP1
scope   -> direct

period_scope_mismatch
```

### `descendants`

Every included membership must be assigned either to the exact target period or
to one of its descendants in the same exact Core calendar revision.

For example:

```text
Semester 1
├── MP1
└── MP2
```

Two separate atomic #34 results whose complete bases belong to MP1 and MP2 may
both contribute to `Semester 1` when the policy uses `descendants`.

That does not create Core membership inheritance. Under `direct`, child-period
membership is not treated as direct Semester 1 membership.

## No date or lifecycle inference

Scope resolution uses only exact Academic Period identity, exact calendar
revision, and explicit Core hierarchy. It never infers period eligibility from:

- overlapping or identical dates;
- period labels or period type;
- current lifecycle;
- current date;
- publication date;
- assignment or due date;
- submission or result date;
- filesystem location; or
- whichever calendar revision is current now.

Parallel roots remain unrelated even when their date ranges overlap exactly.

## Scope-resolution outcomes

Pure scope resolution returns either:

```text
eligible
period_scope_mismatch
```

A mismatch carries one stable reason drawn from the schema-v1 vocabulary,
including:

```text
mixed_sibling_periods
outside_target_period
calendar_revision_mismatch
school_year_mismatch
```

`mixed_sibling_periods` is used when one atomic candidate itself spans sibling
periods. A separate Grade Item wholly assigned to a child period but evaluated
against its parent under `direct` is instead `outside_target_period`.

`period_scope_mismatch` is always blocking in schema version 1. It is never
silently dropped from the calculation.

## Bounded aggregation inputs

`AcademicPeriodProficiencyAggregationInputs` represents one exact:

```text
class_id
+ target Academic Period/calendar revision
+ student_id
+ standard_id
+ target proficiency scale
+ period-membership scope
```

It contains deterministic, bounded
`AcademicPeriodProficiencyAggregationInputEntry` values ordered by stable Grade
Item identity. Duplicate logical Grade Item candidates are rejected.

Each entry is exactly one of:

```text
calculated
insufficient_evidence
missing_result
period_scope_mismatch
```

### `calculated`

An exact #34 result exists, its logical Grade Item/student/standard/scale basis
matches, its outcome is calculated, and the complete exact membership basis fits
the requested period scope.

The entry preserves the exact #34 result reference, algorithm version,
calculation fingerprint, and proficiency level.

### `insufficient_evidence`

An exact #34 result exists and its outcome is `insufficient_evidence`. Its exact
#34 insufficiency reasons remain attached to the #35 input. It is not converted
to a proficiency level.

### `missing_result`

The Grade Item basis is an intended, period-eligible candidate, but no exact #34
result was supplied. This means no result exists in the bounded candidate set;
it does not mean zero, lowest proficiency, failure, or #34 insufficiency.

### `period_scope_mismatch`

The candidate's complete exact membership basis does not fit the requested scope.
If an exact #34 result exists, its immutable reference and calculated level may
remain visible for provenance even though the entry cannot contribute.

## Missing and insufficient result policy

`PeriodResultHandling` is exactly:

```text
noncontributing
blocking
```

`AcademicPeriodProficiencyAggregationPolicy` configures missing and insufficient
results separately through:

```text
missing_result_handling
insufficient_result_handling
```

With `noncontributing`, the entry remains in inputs and explanation but supplies
no ordinal value.

With `blocking`, at least one such entry prevents a calculated period result and
produces `insufficient_evidence` with an explicit reason:

```text
blocking_missing_result
blocking_insufficient_result
```

A genuine low proficiency result remains a real calculated result. Missing and
insufficient states are never fabricated as the lowest scale level.

## Calculation-policy family

`AcademicPeriodProficiencyAggregationPolicy` is a frozen/slotted immutable
revisioned policy. Logical identity is:

```text
class_id + policy_id
```

A revision binds an exact `ProficiencyScaleReference` plus:

```text
strategy
period_membership_scope
minimum_calculated_results
mode_tie_rule
median_even_rule
missing_result_handling
insufficient_result_handling
actor
rationale
revised_at
```

Policy revisions are contiguous immutable history. Writing a new revision does
not automatically select it.

## Supported ordinal strategies

Schema version 1 supports exactly:

```text
highest
lowest
median
mode
```

The implementation reuses #34 ordinal scale-position and tie semantics. It does
not average labels, percentages, points, dates, weights, or producer-native
values.

Median-even and mode ties use the established rules:

```text
lower
higher
insufficient
```

An `insufficient` tie rule yields a structured insufficient result rather than a
synthetic midpoint or arbitrary winner.

## Pure calculation

The pure entry point is:

```python
calculate_academic_period_proficiency(
    inputs: AcademicPeriodProficiencyAggregationInputs,
    policy: AcademicPeriodProficiencyAggregationPolicy,
    scale: ProficiencyScale,
) -> AcademicPeriodProficiencyCalculationOutcome
```

Before reduction, the exact input scale, policy scale, and supplied target scale
must agree. Scope was already resolved into the immutable input entries; the
calculator does not load Core state or revisit membership history.

`AcademicPeriodProficiencyCalculationOutcome` is exactly:

```text
calculated
insufficient_evidence
```

A calculated result has one proficiency level. An insufficient result has no
proficiency level and deterministic structured reasons drawn from:

```text
period_scope_mismatch
blocking_missing_result
blocking_insufficient_result
no_calculated_results
below_minimum_calculated_results
unresolved_mode_tie
unresolved_even_median
```

The outcome also records deterministic candidate/status counts, per-level counts,
tie resolution when relevant, and privacy-minimal per-Grade-Item explanations.

## Calculation fingerprint

The exact algorithm constant is:

```text
ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION = "1"
```

`academic_period_proficiency_calculation_fingerprint(...)` binds canonical
calculation provenance over:

```text
algorithm version
aggregation-input digest
exact policy reference
exact Academic Period target/calendar revision
exact target scale reference
```

Audit time is not part of the academic fingerprint.

## Immutable result snapshots

`AcademicPeriodProficiencyResultSnapshot` embeds the exact #35 aggregation inputs
and binds:

```text
class_id
target_period
student_id
standard_id
result_revision
supersedes_revision
algorithm_version
calculation_fingerprint
inputs
inputs_sha256
policy_reference
target_scale
outcome
calculated_at
```

Logical result identity is:

```text
class_id
+ school_year
+ period_id
+ student_id
+ standard_id
```

The exact calendar revision remains part of the embedded target/calculation
basis. Result revisions are immutable, contiguous history; a result reference is
SHA-256 bound to one exact persisted revision.

## Policy and result storage

Policy history is class-local:

```text
classes/<class_id>/modules/meridian/academic_period_proficiency/
  policies/<policy_id>/
    current.json
    revisions/<N>.json
    revisions/<N>.json.sha256
```

Result history is period/student/standard-local:

```text
classes/<class_id>/modules/meridian/academic_period_proficiency/
  results/school_years/<school_year>/periods/<period_id>/
    students/<student_id>/standards/<standard_key>/
      current.json
      revisions/<N>.json
      revisions/<N>.json.sha256
```

`standard_key` is derived from the durable standard ID so raw standard IDs never
become path components.

Writes use canonical JSON and SHA-256 sidecars. Exact duplicate writes are
idempotent; conflicting bytes at an existing revision fail closed.

Writing either a policy revision or result revision does not select it.
`current.json` changes only through explicit SHA-bound compare-and-swap
selection, and historical revisions may be deliberately reselected.

Result writes verify exact persisted dependencies, including the policy/scale
basis and exact referenced #34 result revisions. Historical #35 reload does not
substitute ambient current state.

## Freshness and staleness

`assess_academic_period_proficiency_result_freshness(...)` is pure diagnostic
comparison only. Status is:

```text
current
stale
```

Reasons are deterministic and independent:

```text
inputs_changed
policy_changed
scale_changed
calendar_changed
algorithm_changed
```

Staleness never mutates a persisted result, recalculates it, or changes a current
selector. A historical result remains valid history even when a newer membership,
calendar, policy, scale, algorithm, or bounded candidate set would produce a
new calculation basis.

## Canonical serialization and integrity

Policy, input, outcome, and result records use strict closed schemas and canonical
UTF-8 JSON. The runtime rejects duplicate keys, unknown/missing keys, nonfinite
values, malformed timestamps, invalid digests, invalid revision transitions, and
noncanonical reload bytes.

Storage uses bounded regular-file reads, lexical containment checks, safe
identifier/path construction, narrow locks, atomic pointer replacement, and
fail-closed unexpected-entry/symlink handling.

## Privacy and producer neutrality

The #35 layer carries only the bounded identities and academic interpretation
needed to reproduce a period proficiency judgment. It does not copy:

- student names;
- answers or essay text;
- rubric prose;
- feedback or intervention narratives;
- private teacher notes;
- roster records;
- producer manifests; or
- source-document contents.

Exact #34 references/digests and normalized bounded values are preferred over
copying #34's embedded evidence again.

## Acceptance coverage

Focused source and installed-wheel acceptance prove:

```text
direct MP1 aggregation
parent Semester 1 descendants aggregation over separate MP1/MP2 results
mixed sibling MP1/MP2 atomic result -> period_scope_mismatch
explicit membership reconciliation without historical reinterpretation
calendar-revision mismatch
parallel overlapping root rejection without date inference
low calculated proficiency != missing_result != insufficient_evidence
noncontributing missing/insufficient policy
blocking missing/insufficient policy
immutable #35 result persistence
no automatic result selection
explicit current selection
deterministic replay
current/stale freshness diagnostics
```

Package and source-distribution guards require the #35 runtime and focused tests.
The authoritative repository validator executes the dedicated #35 installed-wheel
smoke against the exact supported Core wheel.

## Boundary to issue #36

Issue #35 stops at explainable Academic Period standards proficiency. It does not
create or export a planning signal.

Issue #36 formally adopts the neutral Core grouping-signal contract. That
contract first shipped in Core 0.6.1, while Meridian's authoritative
qualification baseline is Core 0.6.3 and the active runtime floor remains
`pds-core>=0.6.3,<0.7` because issue #33 required later Core standards support.
The grouping-signal contract does not change #35's academic result semantics.
