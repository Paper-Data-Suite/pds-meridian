# Conventional Grade calculation

Status: issue #50 pure conventional calculation, bounded storage-aware input
assembly, immutable conventional-result persistence, explicit current selection,
and pure freshness diagnostics are implemented. Installed producer acceptance and
final package qualification remain later slices of issue #50.

## Boundary

`meridian.conventional_grade` calculates an advisory conventional Academic
Period Grade only from an already-resolved immutable basis. It does not discover
or authorize evidence and it does not choose Grade Items, work membership,
eligibility, attempts, reassessment outcomes, Grade policies, or activations.

The required separation remains:

```text
producer evidence
    != Meridian interpretation
    != Grade Item conventional input
    != conventional Grade calculation
    != teacher override
    != Grade preview
    != ReportingSnapshot
    != official Grade
```

The calculation layer therefore consumes the exact v0.2 interpretation result
rather than rebuilding it:

```text
v0.2 attempt/reassessment state
    != conventional Grade arithmetic
```

Likewise:

```text
GradeItemRevision.weighting metadata
    != executable GradePolicy configuration

GradePolicy family current
    != GradePolicy activation
```

Only the exact conventional configuration materialized into the supplied
Grade-policy revision is executable.

## Exact calculation scope

`create_conventional_grade_calculation_input()` binds:

```text
class_id
student_id
exact AcademicPeriodRef
calendar_revision
exact activated GradePolicyActivationDecision
exact conventional GradePolicyRevision
exact policy-participating Grade Item inputs
```

The builder verifies that the activation is an `activate` decision, that it
matches the exact class/period/calendar scope, and that it references the exact
canonical digest of the supplied conventional Grade-policy revision. A family
`current.json`, newer policy revision, another period, or another calendar
revision is not substituted.

Every `ConventionalGradeCalculationInput` must contain exactly one input for
every policy-participating Grade Item and no additional item. The embedded
`GradePolicyItemParticipation` must exactly equal the immutable policy authority,
including category, item weight, and policy-owned `possible_points`.

## Exact point-input resolution

`resolve_conventional_grade_item_input()` enforces the version-1 one-observation
rule after an upstream assembly layer has already determined which point
observations are academically operative:

```text
0 operative NativePointValue values
    -> explicit non-Grade state supplied by assembly

1 operative NativePointValue
    -> exact Decimal point input

2+ operative NativePointValue values
    -> unresolved / multiple_point_observations
```

There is deliberately no reducer for multiple operative observations. `retain`,
`combine`, multiple contributing attempts, timestamps, attempt numbers, or score
magnitude do not imply sum, average, latest, highest, or best arithmetic.

Only `NativePointValue` enters this resolver. Numeric-looking scalar or scaled
values are not accepted as conventional points.

`NativePointValue` is producer-native and may carry an integer or finite float.
The resolver converts that already-authorized native number to the exact Decimal
meaning of its textual numeric value before Grade arithmetic. Policy values
remain Decimal-only. For points-based modes:

```text
producer possible points != policy possible points
    -> unresolved / possible_points_mismatch
```

No rescaling or tolerance is applied.

## Source state and policy consequence remain separate

An item input carries either exact points or one source state from the Grade
policy vocabulary:

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

The calculation result then records a separate action:

```text
contribute
exclude
blocking
zero
```

Thus:

```text
source state: missing
policy consequence: zero
```

never becomes a fabricated source state named `zero`.

The governing invariant is:

```text
missing or unresolved state != numeric zero
```

A numeric zero exists only when the exact activated policy explicitly assigns a
supported `zero` consequence. For `total_points` and `weighted_categories`, the
zero denominator is the exact policy-owned `possible_points`; absent evidence is
never asked to invent its own denominator. For `weighted_items`, the explicit
policy item weight supplies the zero contribution.

## Arithmetic

All Grade arithmetic uses `Decimal`. Intermediate item percentages, category
fractions, category contributions, weighted-item contributions, and numerator /
denominator accumulations are not rounded.

### Total points

For numerically contributing items:

```text
total_earned   = sum(earned)
total_possible = sum(possible)
Grade          = total_earned / total_possible * 100
```

An excluded item contributes neither numerator nor denominator. An explicit
zero contributes `0 / policy possible_points`. A blocking item prevents a
numeric final Grade. If no positive denominator remains, the outcome is
`insufficient` with `no_calculable_items`; it is not `0%`.

### Weighted items

For each contributing item:

```text
item_fraction     = earned / possible
item_contribution = item_fraction * policy_item_weight
```

The final fraction is the sum of exact item contributions. An excluded item does
not contribute, and its configured weight is not redistributed.
There is no silent renormalization of the remaining weights.

### Weighted categories

Within each category:

```text
category_earned   = sum(contributing earned)
category_possible = sum(contributing possible)
category_fraction = category_earned / category_possible
category_contribution = category_fraction * configured_category_weight
```

A category with no calculable denominator is explicitly `noncalculable`; it is
not automatically zero. A noncontributing category does not cause other
category weights to expand. If at least one category contributes and none is
blocking, the final fraction is the sum of the configured category
contributions. If no category contributes, the overall outcome is
`insufficient`.

## No universal clamp

The pure calculator does not assume `earned <= possible`. If otherwise-valid
producer-native evidence and exact policy authority yield extra credit above
100%, the advisory Grade may exceed 100%. No hidden 0-100 clamp exists in
algorithm version 1.

## Final-only rounding

`GradeRoundingPolicy.application_stage` remains `final`. The unrounded Grade is
calculated first and then rounded explicitly with the policy's Decimal quantum
and named Decimal rounding mode. Python's implicit/default rounding is not used.

## Result and provenance

`ConventionalGradeCalculationOutcome` distinguishes:

```text
calculated
blocked
insufficient
```

Every policy-participating Grade Item remains present in `item_results`, including
excluded, missing, blocked, and unresolved items. Weighted-category calculations
also preserve deterministic category results.

Per-item results retain:

- exact `GradePolicyItemReference`;
- resolved source state;
- separate calculation action/policy consequence;
- exact earned/possible/percentage values when numeric;
- exact item/category policy facts;
- exact numeric contribution where applicable;
- deterministic reason codes; and
- privacy-minimal exact upstream provenance references.

The generic provenance reference identifies its authority kind, a bounded exact
reference key, and a lowercase SHA-256 digest. The later assembly layer is
responsible for producing those references from canonical membership, source,
eligibility, attempt-selection, and reassessment state. The pure calculator does
not reopen those sources.

## Algorithm version and fingerprint

Version 1 is frozen as:

```text
CONVENTIONAL_GRADE_ALGORITHM_VERSION = "1"
```

`conventional_grade_calculation_fingerprint()` hashes canonical structured input
over:

```text
algorithm version
class_id
student_id
exact AcademicPeriodRef
calendar_revision
exact GradePolicyActivationReference
exact GradePolicyReference
exact conventional Grade-policy configuration/state treatment/rounding
exact resolved Grade Item input body and provenance
```

Input and provenance collections are canonicalized before hashing. The same
academic basis therefore yields the same fingerprint independent of caller
iteration order; changing a material point value, policy fact, activation,
period/calendar scope, or exact upstream provenance changes the fingerprint.

Wall-clock calculation time, filesystem path, mtime, discovery order, and Python
object identity are not fingerprint inputs.

## Storage-aware exact input assembly

`meridian.conventional_grade_assembly` is the read-only bridge from canonical
workspace state to the pure calculator. It resolves the exact selected #49
Grade-policy activation first, reloads the exact digest-bound policy revision,
and verifies every policy-participating Grade Item revision before opening any
academic evidence. A Grade-policy family `current.json` is never substituted for
the exact activated revision.

For each participating Grade Item, assembly enumerates canonical #28 logical
work relationships and admits only explicitly selected `included` memberships
whose exact `AcademicPeriodRef` and `calendar_revision` match the calculation
target. Another period, another calendar revision, an excluded relationship, or
an unselected membership cannot silently contribute. If no selected included
work belongs to the exact target scope, the Grade Item resolves to
`not_applicable`, not zero.

Student-bearing evidence remains behind `AuthorizedProjectionSnapshot`. The
caller supplies one bounded `ConventionalGradeWorkEvidenceSpec` for each exact
in-scope work observation:

```text
available   -> exact authorized snapshots are supplied
missing     -> the caller established no student-bearing source/projection
unavailable -> the work relationship exists, but required authorized/source
               material cannot presently be supplied
```

An `available` snapshot is never accepted for a different work. Evidence is read
only from those supplied authorized snapshots; #50 does not crawl producer
workspaces, reopen producer-private files, or turn publication/cache identifiers
into an authorization bypass.

Each exact student `EvidenceItem` is converted to its exact #29
`EvidenceSourceReference`, and `resolve_current_evidence_eligibility()` remains
the canonical eligibility authority. Projection-time `EvidenceEligibility` is
not used as a substitute. Only `operative_included` evidence can become a point
candidate. Pending/no-decision, withdrawn, stale-membership, unsupported, and
unverifiable states remain structured nonnumeric observations.

Attempt/reassessment filtering delegates to
`resolve_current_reassessment()`, which already consumes the canonical #30
resolver. Therefore:

```text
#29 operative evidence
    -> #30 exact attempt selection
    -> #31 exact contributing_attempts
    -> conventional point candidates
```

`single_selected` and `resolved` use only the exact `eligible_evidence` sources
bound to the #31 contributing attempt set. `not_applicable` does not fabricate an
attempt layer and may pass otherwise-operative exact evidence directly.
`selected_none` remains nonnumeric, and unresolved/stale #30/#31 state becomes
`unresolved`; the Grade layer never repairs it by choosing latest, highest, or
best.
If more than one supplied snapshot somehow resolves as simultaneously operative
for reassessment, assembly fails closed as `unresolved` with
`multiple_operative_reassessment_snapshots`; it never merges those authorities.

Only `NativePointValue` survives as a conventional point observation. Scalar,
scaled, rubric/rating, correctness, selected-response, and other non-point
values remain non-point evidence. This distinction also prevents normal
ScoreForm question detail from eclipsing a valid selected `attempt_points`
observation: non-point detail is ignored for point arithmetic when one exact
point observation is operative, but it still classifies a no-point Grade Item as
`insufficient_evidence` when appropriate. Nonstudent evidence remains
nonstudent evidence and is never individualized.

When no numeric observation survives, assembly uses the deterministic fail-closed
precedence:

```text
unresolved
> invalid
> unavailable
> withdrawn
> pending
> incomplete
> insufficient_evidence
> excluded
> excused
> not_applicable
> missing
```

The precedence is semantic rather than temporal: it never uses timestamps,
filesystem order, attempt number, or score magnitude. A stronger problem state
therefore cannot collapse to `missing` merely because the Grade policy happens
to configure `missing -> zero`. Structural corruption, digest disagreement,
invalid canonical references, and authorization-boundary violations remain hard
errors instead of academic `missing` states.

The assembly returns the exact stored activation and policy, the immutable pure
`ConventionalGradeCalculationInput`, and the resulting advisory
`ConventionalGradeCalculationOutcome`. It performs no writes.

## Immutable conventional result persistence and freshness

`ConventionalGradeResultSnapshot` is Meridian's immutable persisted wrapper over
one exact conventional calculation input and its reproduced pure outcome. It is
not a Grade preview, teacher override, ReportingSnapshot, export artifact, or
official Grade. The result embeds the exact input body and binds:

```text
schema_version / record_type
class_id / student_id
target AcademicPeriodRef / calendar_revision
result_revision / supersedes_revision
algorithm_version / calculation_fingerprint
activation_reference / policy_reference
exact conventional calculation inputs
exact pure calculation outcome
calculated_at
```

Deserialization validates the closed canonical schema and then reruns the pure
calculator over the embedded inputs. The stored outcome must reproduce exactly.
This means a self-consistent-looking but arithmetically altered result cannot be
accepted merely because its JSON parses. `calculated_at` remains persistence
metadata and is not part of the academic calculation fingerprint.

The canonical result family is scoped by exact class, student, period, and
calendar revision. Its filesystem path uses a deterministic lowercase SHA-256
`subject_key` over that complete scope instead of exposing the raw student ID:

```text
classes/<class_id>/modules/meridian/conventional_grades/
  periods/<school_year>/<period_id>/students/<subject_key>/
    current.json
    revisions/
      1.json
      1.json.sha256
```

The immutable result retains the exact `student_id`; the subject key is only a
path-safe privacy boundary. Canonical result storage uses bounded reads, closed
JSON, one trailing LF, lowercase SHA-256 sidecars, path/model identity checks,
symlink rejection, unexpected-entry rejection, contiguous history, exact retry
idempotence, and a narrow per-result-family write lock.

The selector preserves the repository invariant:

```text
writing result revision != selecting result revision
```

Writing revision 2 does not make revision 2 current. `current.json` is an exact
SHA-bound selector and selection uses compare-and-swap against the caller's
expected current revision. Historical revisions may be explicitly reselected
when their immutable structural dependencies still validate. Current is never
inferred from the highest revision, latest `calculated_at`, filesystem mtime,
directory order, or Grade value.

Before a genuinely new result revision is committed, storage reassembles the
same caller-bounded authorized evidence scope and requires the exact current
inputs and pure outcome still to match the candidate. It repeats that check while
holding the result-family lock. If activation, membership, eligibility, attempt
selection, reassessment, or point inputs changed during the observation window,
the write fails with an explicit conflict rather than mixing old and new current
state. Exact retry of an already-existing immutable revision remains idempotent.

Freshness is diagnostic and does not mutate or recalculate history.
`assess_conventional_grade_result_freshness()` compares one immutable result with
one explicitly supplied current input basis and reports `current` or `stale` with
deterministically ordered independent reasons:

```text
calendar_scope_changed
activation_changed
policy_changed
inputs_changed
algorithm_changed
```

The reasons are independent flags: more than one may be present when the supplied
current basis differs in more than one material way. A stale result is not
rewritten, automatically recalculated, or reselected. A later calculation
creates another immutable result revision.

The exact `ConventionalGradeResultReference` carries class, student, school year,
period, calendar revision, result revision, and result SHA-256 so downstream
features do not need to identify a historical calculation as merely "the latest
Grade."

## Final issue #50 acceptance

The calculation, assembly, and persistence contracts above are qualified by a
representative released-producer path rather than only synthetic point objects.
Installed ScoreForm acceptance uses released ScoreForm v0.11.0 through Core
v0.6.3 publication state and Meridian's real adapter/authorization boundary:

```text
released ScoreForm v0.11.0 publication
-> AuthorizedProjectionSnapshot
-> exact #28 Grade Item membership
-> exact #29 evidence eligibility
-> explicit #30 attempt selection
-> explicit #31 reassessment
-> exact activated conventional Grade policy
-> ConventionalGradeCalculationInput
-> pure conventional calculation
-> immutable result revision
-> explicit result selection
-> fresh-process reload and deterministic reproduction
```

The acceptance preserves the write/selection boundary. In exact terms,
writing a result does not select it. A fresh process reloads the exact selected
revision and reproduces the persisted outcome from the embedded exact inputs. The ScoreForm producer-owned
assignment/result files and immutable publication manifest are hashed before the
Meridian Grade workflow and verified unchanged afterward. In the source-level
cross-producer scenario, producer-owned source bytes remain unchanged for
ScoreForm, Quillan, and Concord module trees.

The producer semantic boundary is also frozen by released-contract regressions:

- ScoreForm v0.11.0 `NativePointValue` attempt totals are eligible point inputs;
  response/correctness detail and native states are not coerced into points.
- Quillan v0.10.0 scaled ratings are not conventional points.
- Concord v0.3.0 scaled results are not conventional points, and nonstudent
  group-level evidence is never individualized into a student Grade.

The installed smoke intentionally installs only exact released Core v0.6.3,
ScoreForm v0.11.0, and the candidate Meridian wheel. Quillan and Concord remain
absent there; their released-contract semantics are exercised by the full
repository cross-producer qualification. Wheel/sdist guards require all #50
runtime, architecture, source-level acceptance, and installed-smoke surfaces.

Issue #50 therefore ends at an advisory conventional Grade calculation result.
It still does not implement a teacher Grade override, Grade preview,
ReportingSnapshot, report export, official-system Grade write, or any implicit
selection of a persisted result.
