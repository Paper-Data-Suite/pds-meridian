# Grade Item standards-proficiency calculation

Issue #34 implements Meridian's first executable standards-proficiency
calculation over the exact bounded aggregation inputs established by issue #33.

The governing boundary is:

```text
producer-native evidence
    -> Grade Item membership
    -> evidence eligibility
    -> attempt selection
    -> reassessment/replacement
    -> native-value mapping
    -> standards-evidence association
    -> StandardAggregationInputs
    -> Grade Item standards-proficiency calculation
```

The calculation remains distinct from later Academic Period aggregation and
conventional/hybrid Grade calculation:

```text
mapped performance observation
!= Grade Item standards proficiency
!= Academic Period standards proficiency
!= Grade
```

This architecture follows ADR 0001 and ADR 0004. The pure calculation core does
not read the filesystem, discover current state, mutate decisions, select
revisions, or persist results.

## Runtime modules

Issue #34 adds:

```text
meridian.standards_proficiency
meridian.standards_proficiency_storage
```

`meridian.standards_proficiency` owns immutable policy, calculation outcome,
result snapshot/reference, serialization, transition validation, calculation
fingerprints, and pure freshness diagnostics.

`meridian.standards_proficiency_storage` owns immutable policy/result revision
persistence, SHA-256 sidecars, explicit current selectors, compare-and-swap
selection, bounded reads, and path/integrity hardening.

No producer package is imported by either generic module.

## Exact input boundary

The calculation accepts one exact:

```text
StandardAggregationInputs
```

from issue #33. It already contains:

- one exact `GradeItemAggregationBasis`;
- one `student_id`;
- one durable Core `standard_id`;
- one exact `ProficiencyScaleReference`; and
- deterministically ordered `StandardAggregationInputEntry` values.

Every input entry is already classified as exactly one of:

```text
performance
native_state
excluded
```

Issue #34 does not revisit membership, eligibility, attempt selection,
reassessment, mapping, or association decisions. It interprets the exact
resolved input body it receives.

The exact input digest is:

```text
standard_aggregation_inputs_sha256(inputs)
```

and becomes part of the calculation fingerprint and persisted result
provenance.

## Calculation-policy family

`StandardProficiencyCalculationPolicy` is a frozen/slotted immutable revisioned
policy owned by Meridian. Its logical family is:

```text
class_id + policy_id
```

Each revision contains:

```text
schema_version
record_type
class_id
policy_id
policy_revision
supersedes_revision
title
target_scale
strategy
minimum_performance_observations
mode_tie_rule
median_even_rule
blocking_exclusion_reasons
native_state_handling
actor
rationale
revised_at
```

The exact policy schema/algorithm constants are:

```text
STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION = "1"
STANDARD_PROFICIENCY_ALGORITHM_VERSION = "1"
```

Revision 1 supersedes nothing. Revision N must supersede N-1. A pure transition
validator requires stable class/policy identity, contiguous revisions, and
nondecreasing revision time.

Policy actor kind is explicitly:

```text
teacher
policy
```

There is no producer calculation-policy actor.

## Exact policy reference

Every calculation binds an exact
`StandardProficiencyCalculationPolicyReference`:

```text
class_id
policy_id
policy_revision
policy_sha256
```

A result never persists only a `policy_id` or ambient "current policy" label.

## Supported v1 strategies

Version 1 supports exactly four ordinal strategies:

```text
highest
lowest
median
mode
```

They operate only on configured `ProficiencyLevel.position` values from the
exact target `ProficiencyScale`.

They do not operate on:

- numeric-looking level IDs;
- labels;
- producer-native points;
- percentages;
- filesystem order; or
- evidence timestamps.

### `highest`

Select the contributing performance observation at the highest configured scale
position.

This is an explicit calculation policy, not an attempt-selection rule.

### `lowest`

Select the contributing performance observation at the lowest configured scale
position.

### `median`

Sort contributing performance observations by exact target-scale position.

For odd counts, select the middle observation.

For even counts, explicit `median_even_rule` is required:

```text
lower
higher
insufficient
```

`lower` and `higher` select the corresponding central observation.
`insufficient` yields `unresolved_even_median`.

No arithmetic midpoint or synthetic level is created.

### `mode`

Count exact target-scale levels among contributing observations.

A unique most-frequent level is selected directly. A tie requires explicit
`mode_tie_rule`:

```text
lower
higher
insufficient
```

`lower`/`higher` select by target-scale position among tied modal levels.
`insufficient` yields `unresolved_mode_tie`.

## Minimum evidence and native states

`minimum_performance_observations` is a positive bounded policy value.

Zero performance observations produce:

```text
status = insufficient_evidence
reason = no_performance_evidence
```

They never become:

```text
zero
lowest proficiency
failure
missing Grade
```

A positive observation count below the policy minimum produces:

```text
below_minimum_performance_observations
```

This preserves forward compatibility with valid producer workflows that may
contain no scored/performance observations.

Native states remain non-score states. Policy chooses exactly:

```text
native_state_handling = noncontributing
native_state_handling = blocking
```

`noncontributing` preserves the state in explanation while omitting it from
performance reduction. `blocking` produces `blocking_native_state`.

## Blocking exclusions

The policy may configure only unresolved/problem exclusion reasons as blockers:

```text
association_unresolved
eligibility_unresolved
attempt_selection_unresolved
reassessment_unresolved
mapping_not_supplied
mapping_unmapped
mapping_unsupported
scale_mismatch
source_unverifiable
standard_unresolved
```

Deliberate, already-resolved noncontributing workflow outcomes are not
configurable blockers:

```text
not_associated
eligibility_not_included
attempt_not_selected
reassessment_noncontributing
nonstudent_target
student_mismatch
```

This keeps "explicitly does not contribute" distinct from "calculation basis is
unresolved or unsupported."

## Pure calculation API

The pure entry point is:

```python
calculate_standard_proficiency(
    inputs: StandardAggregationInputs,
    policy: StandardProficiencyCalculationPolicy,
    scale: ProficiencyScale,
) -> StandardProficiencyCalculationOutcome
```

Before calculation, Meridian requires exact agreement among:

```text
inputs.target_scale
policy.target_scale
proficiency_scale_reference(scale)
```

and requires policy class identity to match the Grade Item class.

No current scale/policy lookup occurs inside the function.

## Calculation outcome

`StandardProficiencyCalculationOutcome` has status:

```text
calculated
insufficient_evidence
```

A calculated outcome carries exactly one `proficiency_level_id`.

An insufficient outcome carries no proficiency level and one or more structured
reasons drawn from:

```text
no_performance_evidence
below_minimum_performance_observations
blocking_exclusion
blocking_native_state
unresolved_mode_tie
unresolved_even_median
```

The outcome also retains bounded deterministic explanation metadata:

- exact algorithm version;
- exact aggregation-input SHA-256;
- exact policy reference;
- exact target-scale reference;
- calculation fingerprint;
- contributing performance count;
- native-state count;
- excluded count;
- per-level counts;
- tie-resolution metadata where applicable;
- structured insufficiency reasons; and
- privacy-minimal per-source explanation entries.

Explanation source identities are deterministic source keys rather than copied
student answers or producer payloads.

## Calculation fingerprint

`standard_proficiency_calculation_fingerprint(...)` hashes canonical JSON over:

```text
algorithm_version
aggregation_inputs_sha256
exact policy reference
exact target scale reference
```

The same exact academic basis therefore produces the same fingerprint.

`calculated_at` is not part of the academic fingerprint. It is audit metadata on
a persisted result snapshot.

## Policy persistence and selection

Calculation-policy storage is class-local:

```text
classes/<class_id>/modules/meridian/standards_proficiency/
  policies/<policy_id>/
    current.json
    revisions/<N>.json
    revisions/<N>.json.sha256
```

Policy revisions are immutable canonical JSON with exact SHA-256 sidecars.

Writing a policy revision does not select it.

`current.json` is a separate SHA-bound identity pointer changed only through
explicit compare-and-swap selection. Historical revisions may be deliberately
reselected. Current state is never inferred from:

```text
highest revision
newest revised_at
filesystem mtime
directory order
```

A new policy write verifies the exact persisted target-scale revision and digest.

## Persisted result snapshot

`StandardProficiencyResultSnapshot` is the immutable persistence wrapper over one
already-pure outcome. It contains:

```text
schema_version
record_type
class_id
grade_item_id
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

The entire exact `StandardAggregationInputs` object is embedded so historical
reproduction does not require reconstructing the old #33 input body from
mutable/current state.

The snapshot validates that:

- top-level scope matches the embedded inputs;
- `inputs_sha256` matches the exact embedded inputs;
- target scale matches the embedded inputs;
- policy reference matches class scope;
- outcome algorithm/fingerprint/input/policy/scale bindings match the snapshot;
  and
- `calculated_at` is timezone-aware audit metadata.

Result logical identity is:

```text
class_id
+ grade_item_id
+ student_id
+ standard_id
```

Result revisions are contiguous immutable history. A result reference binds:

```text
class_id
grade_item_id
student_id
standard_id
result_revision
result_sha256
```

## Result persistence and selection

Result families are stored below:

```text
classes/<class_id>/modules/meridian/standards_proficiency/
  results/grade_items/<grade_item_id>/
    students/<student_id>/
      standards/<standard_key>/
        current.json
        revisions/<N>.json
        revisions/<N>.json.sha256
```

`standard_key` is a deterministic SHA-256 derived from canonical durable
`standard_id` text. Raw standard IDs never become path components.

New result writes verify exact persisted dependencies:

- Grade Item revision/digest;
- calculation-policy revision/digest; and
- proficiency-scale revision/digest.

Exact historical result reload does not resolve ambient current selectors or
substitute newer dependencies. Persisted historical bytes remain replayable.

Writing a result does not select it.

Result `current.json` uses the same explicit SHA-bound compare-and-swap model as
policy selection. Historical result revisions may be reselected.

## Freshness and staleness

Staleness is a pure diagnostic comparison, not mutation.

The API is:

```python
assess_standard_proficiency_result_freshness(
    result,
    current_inputs,
    current_policy_reference,
    current_scale_reference,
    algorithm_version,
)
```

The supplied comparison must preserve the same result logical family.

Status is:

```text
current
stale
```

Structured reasons are deterministic and independent:

```text
inputs_changed
policy_changed
scale_changed
algorithm_changed
```

Identical dependencies return `current` with no reasons.

A stale result remains immutable. Freshness assessment does not:

- create a new result;
- recalculate;
- change `current.json`;
- delete history; or
- modify upstream decisions.

## Canonical serialization and integrity

Policy and result records use:

- UTF-8;
- closed exact JSON schemas;
- duplicate-key rejection;
- unknown/missing-key rejection;
- nonfinite-value rejection;
- deterministic sorted-key output;
- canonical timezone-aware UTC timestamps;
- one trailing LF;
- byte-for-byte canonical reload checks; and
- lowercase SHA-256 sidecars.

Storage uses bounded reads, lexical containment checks, real-directory and
regular-file validation, narrow per-family locks, atomic pointer replacement,
and fail-closed unexpected-entry/symlink handling.

## Privacy and producer neutrality

The generic calculation layer imports no ScoreForm, Quillan, Concord, or other
producer package.

Producer-native evidence remains behind exact #33 provenance references. Result
records do not copy:

- student names;
- answers or essay text;
- feedback;
- accommodations;
- roster data;
- scans/images;
- producer manifests; or
- full Core standard descriptions.

Student ID is present because one result family is explicitly student-scoped;
the persisted explanation remains privacy-minimal and source-key based.

Current active release qualification is ScoreForm v0.11.0, Quillan v0.10.0, and
Concord v0.2.0. Producer-reader qualification does not change the generic
calculation contract.

## Integration acceptance

Focused integration acceptance proves:

```text
#33 bounded inputs
    -> pure calculation
    -> immutable result persistence
    -> no automatic result selection
    -> explicit result selection
    -> exact reload
    -> deterministic reproduction
    -> freshness comparison
    -> stale-input detection
```

It also proves that a legitimate zero-performance input body persists as
`insufficient_evidence` rather than zero or the lowest proficiency level.

## Boundary to issue #35

Issue #34 stops at one exact:

```text
Grade Item + student + standard
```

result.

It does not aggregate multiple Grade Item results into an Academic Period,
execute weighting, calculate a course Grade, generate grouping signals, or
export planning state.

Issue #35 owns Academic Period proficiency aggregation under explicit period
membership and policy, with missing-data and insufficient-evidence states kept
distinct from low proficiency.
