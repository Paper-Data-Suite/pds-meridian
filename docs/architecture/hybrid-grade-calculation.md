# Bounded hybrid Grade calculation

Issue #52 adds Meridian's bounded v0.3 hybrid Grade calculation over the exact
conventional and standards-based calculation semantics established by issues
#50 and #51. The result is advisory Meridian calculation history. It is not a
teacher override, Grade preview presentation, ReportingSnapshot, export
artifact, SIS write, or official school-system Grade.

## One exact hybrid authority

The exact calculation scope is one class, one student, one exact
`AcademicPeriodRef`, one exact Academic Period calendar revision, and one exact
explicitly selected Grade-policy activation. The activation must identify one
exact digest-bound `GradePolicyRevision` with `calculation_family = "hybrid"`.

Grade-policy family `current` is not activation. A newer policy revision is not
substituted for the exact activated revision, and policy authority does not
inherit across Academic Periods.

Version 1 consumes the existing bounded `HybridGradeConfiguration`:

```text
HybridGradeConfiguration
  conventional: ConventionalGradeConfiguration
  standards_based: StandardsBasedGradeConfiguration
  conventional_weight: positive Decimal
  standards_weight: positive Decimal
```

The two configured component weights sum exactly to 1. Issue #52 does not add an
expression language, recursive component graph, plugin-defined formula, hidden
component, or inferred weighting.

## Hybrid components are calculated under the hybrid policy

A hybrid Grade is not constructed from separately selected conventional and
standards Grade results.

```text
selected standalone conventional Grade result
+ selected standalone standards Grade result
  != hybrid Grade authority
```

Standalone #50 and #51 result histories may have been calculated under different
policies, activations, state treatment, rounding, or participation. Reusing
those selected result histories would therefore splice together authorities
that do not necessarily belong to the activated hybrid policy.

Instead, one exact hybrid policy embeds both component configurations:

```text
one exact selected hybrid activation
  -> exact hybrid GradePolicyRevision
       -> embedded conventional configuration
       -> embedded standards-based configuration
```

The hybrid assembler resolves that activation and policy once, then uses the
accepted #50 and #51 component-assembly semantics directly under those embedded
configurations.

The standalone family-gated #50/#51 calculation constructors remain intact.

## Conventional component authority

The conventional component preserves issue #50 semantics. It consumes the exact
policy-participating Grade Items, exact Academic Period membership, authorized
projection snapshots, evidence eligibility, attempt-selection authority, and
reassessment authority. `NativePointValue` remains the conventional point-value
boundary. Generic producer numerics are not coerced into points.

The hybrid layer does not create another conventional interpretation path.
The hybrid layer does not consume a selected standalone conventional Grade
result.

## Standards component authority

The standards component preserves issue #51 semantics. It consumes explicitly
selected Academic Period proficiency results for the exact participating
standards, proves those selected results are currently usable, requires the
exact target proficiency-scale revision and SHA-256 digest, and applies only the
hybrid policy's exact proficiency-level-to-Grade conversions.

The hybrid layer does not reopen producer evidence, rebuild Grade Item
proficiency, or recalculate Academic Period proficiency.
The hybrid layer does not consume a selected standalone standards Grade result.

The standards authority chain remains:

```text
producer evidence
  -> Meridian v0.2 interpretation and selection
  -> Grade Item proficiency
  -> Academic Period proficiency
  -> selected current proficiency result
  -> hybrid policy standards component
```

## Component status and hybrid action

The two component calculation statuses remain explicit:

* `calculated`
* `blocked`
* `insufficient`

A calculated component contributes its exact unrounded Grade. A blocked
component remains blocking. An insufficient component enters the hybrid boundary
as `insufficient_evidence` and follows the exact activated policy's existing
state treatment, which can be `exclude` or `blocking` for that state.

The hybrid layer does not silently reinterpret a blocked component as excluded,
zero, or missing.

## Explicit exclusion and active-weight renormalization

If `insufficient_evidence` is explicitly treated as `exclude`, the insufficient
component contributes neither value nor weight. The remaining active component
is renormalized only through the active-weight denominator:

```text
weighted_numerator
  = sum(active component unrounded Grade * configured component weight)

active_weight
  = sum(configured weight for active components)

unrounded hybrid Grade
  = weighted_numerator / active_weight
```

This behavior exists because the exact policy says `exclude`. It is not an
automatic "use whatever is available" fallback.

If no component blocks but no numeric component remains active, the result is
`insufficient`, never numeric zero.

## Calculated zero is still calculated

A component may legitimately calculate zero through its own exact lower-level
policy semantics. That is a calculated component, not a missing or insufficient
component. It retains its configured hybrid weight and contributes exactly
`0 * weight`.

Missing, unresolved, stale, unavailable, or insufficient state is not silently
converted to zero.

## Unrounded component composition

Hybrid arithmetic consumes each calculated component's `unrounded_grade`, not
its `rounded_grade`.

```text
round(component A), round(component B), then combine
  !=
combine exact component Grades, then round final hybrid Grade
```

Component-level rounded values remain diagnostic output only. The hybrid
weighted products, numerator, active weight, and division use exact `Decimal`
arithmetic. Version 1 applies the activated policy's rounding quantum and mode
once, at the final hybrid stage.

## No hidden clamp

Issue #52 introduces no universal 0-100 clamp. A valid component Grade may
exceed 100 when its exact policy permits it, and the resulting hybrid Grade may
also exceed 100.

## Deterministic calculation fingerprint

The hybrid fingerprint binds the material academic calculation basis:

* hybrid algorithm version;
* exact class/student/period/calendar scope;
* exact activation and policy references;
* exact `HybridGradeConfiguration` and component weights;
* exact state treatment and final rounding policy;
* exact canonical conventional component input;
* conventional component algorithm version and fingerprint;
* exact canonical standards component input; and
* standards component algorithm version and fingerprint.

Wall-clock calculation time, filesystem paths, mtimes, enumeration order, and
Python object identity do not participate.

## Immutable result history

`HybridGradeResultSnapshot` schema version 1 uses record type
`meridian_hybrid_grade_result`. It embeds the exact hybrid calculation input and
input SHA-256, exact activation/policy provenance, exact reproducible hybrid
outcome, algorithm/fingerprint metadata, contiguous result revision and
supersession metadata, and UTC calculation time.

Canonical persistence uses a class-local `hybrid_grades` collection. Student
result paths use a deterministic SHA-256 subject key rather than exposing the
raw student ID in the new path segment. Immutable revision JSON is paired with
an exact SHA-256 sidecar. Reads are bounded and reject malformed, unexpected,
escaping, or symlinked canonical state.

Writing a result does not select it. Selection is an explicit SHA-bound
compare-and-swap operation. A valid historical revision may be explicitly
reselected when its immutable dependencies remain verifiable.

## Historical dependency integrity is not currentness

Historical hybrid selection verifies the exact immutable dependencies that
formed the stored observation:

* exact activation revision and digest;
* exact hybrid Grade-policy revision and digest;
* every conventional Grade Item revision and digest;
* exact proficiency-scale revision and digest; and
* every non-null Academic Period proficiency-result revision and digest.

Historical selection does not require those dependencies to remain the current
live selections. Freshness and immutable historical validity are separate
concepts.

## Commit-time current-basis protection

A new hybrid result write carries the same caller-bounded conventional
`work_evidence` used during assembly. Meridian reassembles the full hybrid basis
before commit and again under the hybrid result-family write lock. Both the
refreshed exact inputs and outcome must match the candidate snapshot.

This prevents a changed activation, policy, conventional evidence/decision
basis, proficiency result, or other material authority from committing a result
assembled from an obsolete observation.

## Result freshness

A persisted hybrid result is either `current` or `stale`. Version 1 uses these
canonical staleness reasons in this order:

1. `calendar_scope_changed`
2. `activation_changed`
3. `policy_changed`
4. `conventional_inputs_changed`
5. `proficiency_results_changed`
6. `algorithm_changed`

Authority changes are reported as authority changes. Under the same activation
and policy, conventional source/decision drift is distinguished from standards
proficiency-result drift. A hybrid or component algorithm-version change is
reported through `algorithm_changed`.

Freshness diagnosis is pure and read-only. It does not recalculate, persist, or
select a replacement result.

## Producer neutrality and source immutability

The representative source-level acceptance uses one coherent cross-producer
workspace. ScoreForm native point evidence flows through the accepted #50
membership, eligibility, attempt, and reassessment authority into the
conventional component. ScoreForm, Quillan, and Concord standards evidence flows
through the accepted v0.2 proficiency chain into an explicitly persisted and
selected Academic Period proficiency result for the standards component.

One exact hybrid policy then governs both component configurations and their
weights. The acceptance deliberately leaves standalone conventional and
standards Grade result selectors empty, proving #52 does not depend on those
histories. Producer-owned ScoreForm, Quillan, and Concord bytes must remain
unchanged across hybrid calculation, persistence, selection, reload, and
freshness evaluation.

## Deliberate non-goals

Issue #52 does not implement arbitrary Grade formulas, recursive hybrid graphs,
more than the bounded conventional-plus-standards pair, cumulative-course Grade
semantics, Academic Period roll-up, new attempt/reassessment authority,
proficiency recalculation, generic producer numeric normalization, teacher
Grade/proficiency overrides, override precedence, teacher-facing Grade preview
workflows, ReportingSnapshots, report/export workflows, direct SIS/LMS writes,
or official Grade authority.

Teacher override records and precedence remain the next architectural layer in
issue #53.

## Installed acceptance

Issue #52 has complementary source-level and installed interoperability
boundaries. Source-level acceptance exercises released ScoreForm v0.11.0,
Quillan v0.10.0, and Concord v0.3.0 through one coherent workspace. The dedicated
installed smoke uses exact Core v0.6.3 plus released ScoreForm v0.11.0 and
Quillan v0.10.0 with the candidate Meridian wheel; Concord is deliberately absent
and remains an optional reader rather than a hybrid-Grade runtime dependency.

The installed smoke reuses the already-qualified #50 and #51 harness setup while
requiring every Core, producer, and Meridian runtime import to originate from the
fresh environment's installed `site-packages`. Real ScoreForm native points flow
through membership, eligibility, attempt selection, and reassessment for the
conventional component. Exact ScoreForm/Quillan work provenance flows through
persisted Grade Item and Academic Period proficiency for the standards component.
The historical conventional activation is superseded by one exact hybrid
activation before calculation, and no standalone conventional or standards Grade
result is written or selected.

The smoke calculates, persists, explicitly selects, reloads, canonically
round-trips, and freshness-checks the hybrid result, proves deterministic
reassembly, runs `pip check`, and launches a fresh-process reload. Both processes
verify the selected hybrid result reproduces exactly and producer plus v0.2/
Grade-policy source state remains byte/digest stable. The installed environment
is created outside the source checkout with `PYTHONPATH`, `PYTHONHOME`, and user
site influence removed.

This installed boundary does not create teacher overrides, Grade preview
presentation, ReportingSnapshots, exports, direct SIS/LMS writes, or official
school-system Grade state. Teacher override records and precedence remain issue
#53 work.
