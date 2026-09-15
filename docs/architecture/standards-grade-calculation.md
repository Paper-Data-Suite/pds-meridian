# Standards-based Grade calculation

Issue #51 adds Meridian's bounded v0.3 standards-based Grade calculation over
already-interpreted, explicitly selected Academic Period proficiency. The result
is advisory Meridian calculation history. It is not a teacher override.
Grade preview presentation, ReportingSnapshot, export artifact, SIS write, or
official school-system Grade are also outside this calculation boundary.

## Authority boundary

The exact calculation scope is one class, one student, one exact
`AcademicPeriodRef`, one exact Academic Period calendar revision, and one exact
explicitly selected Grade-policy activation. The activation must identify an
exact digest-bound `GradePolicyRevision` with `calculation_family =
"standards_based"`.

Grade-policy family `current` is not activation. A newer policy revision is not
substituted for the exact activated revision, and policy authority does not
inherit across Academic Periods.

The standards Grade layer consumes one explicitly selected Academic Period
proficiency result for each policy-participating standard. It does not reopen
producer evidence, re-run eligibility, select attempts, reinterpret
reassessment, rebuild Grade Item proficiency, or recalculate Academic Period
proficiency.

The authority chain is therefore:

```text
producer evidence
  -> Meridian v0.2 interpretation and selection
  -> selected Academic Period proficiency
  -> exact standards Grade-policy conversion
  -> standards-based Grade calculation
```

not a producer-specific Grade shortcut.

## Selected does not automatically mean current

A selected Academic Period proficiency result contributes numerically only when
its canonical v0.2 basis is still current. Issue #51 reuses the same upstream
currentness definition used by Academic Period proficiency attention. Changes
to the selected result, algorithm, calendar, Academic Period proficiency policy,
target proficiency scale, Grade Item revisions, memberships, or selected Grade
Item proficiency basis can make the upstream result stale.

A stale selected result becomes an unresolved standards Grade input. Meridian
does not silently choose a newer result, recalculate proficiency, trust stale
numeric output, or convert staleness to zero.

## Exact proficiency scale and conversion

The activated standards policy owns one exact `ProficiencyScaleReference`. A
selected Academic Period proficiency result must use that exact scale revision
and SHA-256 digest. A matching level label from another scale or revision is not
equivalent.

Proficiency levels have no universal percentage meaning. Numeric Grade values
come only from the policy's exact `ProficiencyGradeConversion` table. Meridian
does not map a label such as `proficient` to a built-in percentage and does not
convert by ordinal position.

An otherwise-valid explicit conversion may exceed 100. Version 1 has no hidden
0-100 clamp.

## Weighted-mean calculation

Version 1 supports only `weighted_mean`. Every participating standard has an
explicit positive Decimal weight, and the complete configured weights sum to
exactly 1.

For a calculated standard:

```text
converted_value = exact policy conversion for the selected proficiency level
weighted_value  = converted_value * configured standard weight
```

After policy state treatment, the active numerator and denominator are:

```text
weighted_numerator = sum(active calculation value * configured weight)
active_weight       = sum(active configured weight)
unrounded Grade     = weighted_numerator / active_weight
```

`exclude` removes both the value and its weight, so the remaining active
standards are renormalized through `active_weight`. `zero` contributes numeric
zero while retaining its configured weight. A blocking standard prevents a
numeric Grade.

If no active weight remains, the outcome is `insufficient`, never numeric zero.

## Minimum actual proficiency evidence

`minimum_calculated_results` counts actual selected, current, calculated
Academic Period proficiency results.
A policy-created zero does not manufacture a proficiency result and therefore does
not satisfy this minimum.

For example, with `minimum_calculated_results = 3`, two actual calculated
proficiency results plus three missing standards treated as zero still fail the
minimum-evidence requirement.

## Missing and unresolved state

Missing or unresolved proficiency is not numeric zero. Each participating
standard preserves its source state separately from the Grade-policy
consequence. Supported consequences remain `contribute`, `exclude`, `blocking`,
and explicit policy-owned `zero` where the Grade-policy schema permits it.

An upstream `insufficient_evidence` result remains nonnumeric and follows the
exact policy treatment. Scale mismatch, stale result, unavailable dependency,
invalid state, and absent selection also remain explicit non-Grade states.

## Exact Decimal arithmetic and rounding

All conversion values, weights, weighted products, numerator totals, active
weight totals, and division use exact `Decimal` arithmetic. Version 1 Grade
policy permits final-stage rounding only. Intermediate values are not rounded.
The final Grade is quantized once with the activated policy's exact quantum and
rounding mode.

## Pure result and explanation basis

The pure calculation outcome is `calculated`, `blocked`, or `insufficient` and
preserves the exact activation, Grade policy, target proficiency scale,
calculation fingerprint, minimum/actual evidence counts, active weight,
weighted numerator, unrounded/rounded Grade, structured reasons, and one result
entry for every participating standard.

Per-standard results retain the configured weight, source state, policy action,
exact selected Academic Period proficiency result reference, upstream
calculation fingerprint and algorithm version, target scale, proficiency level,
converted Grade value, calculation value, weighted contribution, upstream
freshness state, and reason codes. Later explanation work can therefore consume
persisted calculation facts instead of reconstructing them from mutable source
state.

## Deterministic calculation fingerprint

The fingerprint binds material academic state: algorithm version, exact
class/student/period/calendar scope, activation and policy references, exact
standards configuration and target scale, state treatment, rounding policy, and
the exact per-standard selected proficiency basis and resolved state.

Wall-clock calculation time, filesystem paths, mtimes, enumeration order, and
Python object identity do not participate. Canonical ordering makes equivalent
academic input deterministic.

## Immutable result history

`StandardsGradeResultSnapshot` schema version 1 uses record type
`meridian_standards_grade_result`. It embeds the exact calculation inputs and
input SHA-256, exact activation/policy/scale provenance, exact reproducible
outcome, algorithm/fingerprint metadata, contiguous result revision and
supersession metadata, and UTC calculation time.

Canonical persistence follows the established v0.3 Grade-result model under a
class-local `standards_grades` collection. Student-bearing result paths use a
deterministic SHA-256 subject key rather than exposing the raw student ID in the
new path segment. Immutable revision JSON is paired with an exact SHA-256
sidecar. Reads are bounded and reject malformed, unexpected, escaping, or
symlinked canonical state.

Writing a result does not select it. Selection is an explicit SHA-bound
compare-and-swap operation and may deliberately select a valid historical
result revision. Historical selection verifies the exact immutable activation,
Grade policy, proficiency scale, and Academic Period proficiency-result
revisions/digests on which that result depended. Historical validity is not the
same as currentness.

Before a new result revision is committed, Meridian reassembles the exact
current standards Grade basis and requires it to reproduce the candidate inputs
and outcome. This check is repeated under the result-family write lock so a
changed source selection or policy cannot silently commit a result assembled
from an obsolete observation.

## Result freshness

A persisted result is either `current` or `stale`. Independent deterministic
staleness reasons are:

1. `calendar_scope_changed`
2. `activation_changed`
3. `policy_changed`
4. `proficiency_results_changed`
5. `algorithm_changed`

Freshness comparison is pure. It does not recalculate, mutate, or select a
result. A historical result remains immutable even after current source state
changes.

## Producer neutrality and source immutability

The standards Grade runtime imports no ScoreForm, Quillan, or Concord grading
semantics. Cross-producer acceptance begins from the accepted issue #44 chain,
where released producer evidence is mapped into Meridian Grade Item proficiency
and then Academic Period proficiency. Issue #51 persists and explicitly selects
that exact Academic Period result before Grade assembly.

The representative scenario therefore includes ScoreForm native points,
Quillan scaled ratings, and Concord student-level scaled evidence upstream, but
#51 sees only the selected Meridian Academic Period proficiency result. Producer
owned source bytes are compared before and after the standards Grade work and
must remain unchanged.

## Deliberate non-goals

Issue #51 does not implement hybrid Grade calculation, teacher overrides,
teacher-facing Grade previews, ReportingSnapshots, CSV/report exports, official
Grade writes, automatic Academic Period proficiency recalculation, a generic
formula language, or producer-specific Grade shortcuts. Those remain separate
v0.3 responsibilities.

## Installed acceptance

Issue #51 has two complementary interoperability boundaries. Source-level
acceptance exercises released ScoreForm v0.11.0, Quillan v0.10.0, and Concord
v0.3.0 evidence through the existing v0.2 proficiency pipeline before #51
consumes the selected Academic Period result. The dedicated installed acceptance
uses exact Core v0.6.3 plus released ScoreForm v0.11.0 and Quillan v0.10.0 with
the candidate Meridian wheel; Concord is deliberately absent and remains an
optional reader rather than a standards-Grade runtime dependency.

The installed smoke establishes real persisted Grade Item proficiency and
Academic Period proficiency histories with exact ScoreForm/Quillan work
provenance, explicitly selects the upstream scale/policies/results, activates one
exact standards-based Grade policy, calculates the Grade, proves that writing a
result does not select it, explicitly selects/reloads it, verifies deterministic
fingerprint/result reproduction, and launches a fresh-process reload. Both
processes verify imports originate from installed `site-packages`, `pip check`
passes, and producer-owned plus v0.2 proficiency source bytes remain unchanged by
the Grade layer.

This installed boundary does not create Grade preview presentation, teacher
override, hybrid Grade calculation, ReportingSnapshot, or official school-system
Grade state.
