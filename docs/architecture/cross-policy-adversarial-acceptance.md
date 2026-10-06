# Cross-policy adversarial acceptance

Issue #60 is Meridian v0.3's final cross-policy acceptance layer before the
release audit in Issue #61. It tests the interaction of already-implemented
authorities; it does not add a new Grade policy, selection rule, snapshot rule,
or Suite contract.

The governing rule is:

```text
adversarial acceptance != new policy authority
```

The accepted authority chain remains:

```text
producer publication state
-> Meridian evidence / interpretation
-> conventional Grade
-> standards Grade
   - weighted_mean
   - profile_constrained_mean
-> hybrid Grade
-> teacher Grade override
-> Grade/report preview + explanation
-> immutable ReportingSnapshot
-> local export boundary
-> Suite operations integration
```

Issue #60 exercises difficult states across that chain while keeping each
authority distinct.

## Distinctions permanently guarded

The source-level adversarial suite preserves these separations:

```text
source state != policy consequence

empty != zero
missing != zero
incomplete != zero
unknown proficiency != low proficiency

publication supersession != reassessment replacement
publication withdrawal != override withdrawal

attempt selection != reassessment treatment
written Grade result != selected Grade result
selected Grade result != fresh Grade result

teacher override != mutation of base Grade
selected override != automatically applicable override

ReportingSnapshot predecessor/supersession != current-use selection
historical snapshot != current live Grade

profile eligibility != weighted mean
intermediate rounding != final rounding

group evidence != student evidence
numeric producer value != conventional points

readiness != academic success
ready=True != no attention needed
```

Integrity failure also remains separate from a valid academic nonnumeric state.
A digest mismatch, wrong exact scale, malformed canonical record, unsafe path,
or corrupt selector is not converted to academic `missing`. Conversely,
`missing`, `incomplete`, `blocked`, `insufficient`, `unavailable`,
`unresolved`, or profile `indeterminate` is not treated as corruption merely
because it prevents a numeric Grade.

## Empty, incomplete, and nonnumeric state

A valid empty Academic Period never fabricates a denominator or numeric zero.
Conventional calculation remains insufficient when there is no contributing
denominator. Standards calculation remains insufficient when its minimum
calculated-result requirement is not satisfied. A profile-constrained policy
keeps unknown proficiency unknown, and a higher indeterminate profile band
cannot be skipped merely to force a lower-band Grade.

The same underlying `incomplete` source state is tested under explicit
`blocking`, `exclude`, and `zero` policy consequences. The source state remains
`incomplete`; only the policy consequence changes. Numeric zero therefore
appears only under explicit policy authority.

Hybrid calculation preserves the same boundary. If no component validly
contributes and no component explicitly calculates zero, the hybrid result
remains insufficient rather than becoming zero.

## Attempts, reassessment, and producer lifecycle

Real ScoreForm repeated-attempt evidence demonstrates that explicit Meridian
attempt/reassessment authority controls contribution. Higher score, later
timestamp, larger attempt number, filesystem order, and revision order are not
selection rules. Multiple operative point observations without an authorized
combination rule remain unresolved rather than being silently averaged, summed,
or ranked.

Core publication lifecycle remains independent authority. Supersession does not
create a Meridian reassessment relationship and does not auto-author or
auto-select a replacement Grade. Withdrawal changes current source eligibility;
it does not mean numeric zero.

Historical Grade-result bytes remain immutable. Writing a new result revision
does not select it, and the highest result revision is never inferred current.

## Exact proficiency-scale and profile authority

Both `weighted_mean` and `profile_constrained_mean` require the exact selected
proficiency-scale authority. Scale ID, revision, digest, and canonical ordered
definition matter; same-looking labels are not sufficient equivalence.

Profile-constrained acceptance retains Issue #99 semantics:

```text
exact weighted mean
-> three-valued profile evaluation
-> selected Grade band
-> floor / cap / no adjustment
-> one final rounding step
```

A higher `indeterminate` band prevents silent downgrade. Numeric zero is not
reinterpreted as low proficiency. Hybrid consumes the standards component's
final unrounded Grade and does not reevaluate profile predicates itself.

See [Profile-constrained standards Grade policy](profile-constrained-standards-grade.md)
and [Standards-based Grade calculation](standards-grade-calculation.md).

## Final-only Decimal rounding

Conventional, standards, profile-constrained, and hybrid calculations retain
exact Decimal arithmetic through intermediate steps. Acceptance includes cases
where rounding components before composition would produce a different answer.

Supported rounding modes remain policy-owned. `half_up` and `half_even` are
explicitly exercised. No Python float/default rounding becomes academic
authority, and there is no universal 0-100 clamp.

## Teacher override lifecycle

Teacher overrides remain downstream of one exact selected base Grade result.
An applicable override is bound to that exact source result; it does not float
to a newly selected base revision.

Withdrawal is another immutable override decision:

```text
write withdrawal != select withdrawal
select withdrawal -> base regains precedence
```

The prior override remains historical and unchanged. Override withdrawal is not
Core publication withdrawal, and neither lifecycle is represented as a numeric
Grade state.

## ReportingSnapshot authority

ReportingSnapshots remain immutable observations of exact reviewed Grade/report
state. Freezing a successor or correction does not make it current. Current-use
selection remains separate digest-bound compare-and-swap authority.

Historical profile snapshots replay the exact frozen profile policy, predicate
evaluation, selected band/bounds, adjustment, Grade basis, and provenance.
Later policy or scale movement does not rewrite historical meaning.

See [Immutable ReportingSnapshots](reporting-snapshots.md).

## Group and nonstudent evidence

Real Concord group evidence remains `concord_group` evidence with no individual
student subject. It is never cloned or individualized to make a Grade
calculable. In standards aggregation it is explicitly excluded as
`nonstudent_target`; including it cannot fabricate student proficiency.

The installed scenario also verifies the projection-cache privacy boundary.
The first process proves that Concord produced the group item. When the cache is
authorized for one requested student, Meridian intentionally stores only
matching student-subject items; the known group item is absent from that
student-scoped cache while the producer manifest remains unchanged.

See [Concord adapter](concord-adapter.md) and
[Exact projection snapshots and cache](exact-projection-snapshots-and-cache.md).

## Suite operations regression

Issue #59 remains authoritative for Suite integration. Issue #60 proves that a
structurally valid class can remain readiness-ready while its selected Grade is
blocked, insufficient, or stale. Readiness is structural rather than academic.

A ready class may simultaneously produce Meridian attention. Issue #60 does not
move Grade semantics into readiness, redesign attention, add a Suite runtime
dependency, or make owner actions executable commands.

See [Suite operations integration](suite-operations-integration.md).

## Source-level adversarial modules

The permanent source-level acceptance layer is divided by authority boundary:

```text
test_issue60_empty_incomplete_adversarial.py
test_issue60_attempt_scale_adversarial.py
test_issue60_group_lifecycle_adversarial.py
test_issue60_override_selection_adversarial.py
test_issue60_rounding_profile_adversarial.py
test_issue60_reporting_snapshot_adversarial.py
test_issue60_multi_adversity_operations.py
```

These tests compose existing production APIs. Issue #60 adds no production
runtime module and no test-specific production authority.

## Authenticated installed baseline

Issue #60 installed qualification uses these exact released sibling versions:

```text
pds-core      0.6.4
scoreform     0.11.0
quillan       0.10.3
pds-concord   0.3.0
pds-meridian  0.2.0 candidate wheel
```

The compatible runtime dependency remains:

```text
pds-core>=0.6.3,<0.7
```

ScoreForm, Quillan, and Concord remain optional producer integrations; none
becomes an unconditional Meridian runtime dependency. `paper-data-suite` is not
a Meridian runtime dependency.

## Six-matrix installed qualification

Issue #60 preserves the six prepared dependency matrices introduced by Issue
#96:

```text
core
scoreform
quillan
concord
scoreform-quillan
all-adapters
```

No seventh environment is created. The broad Issue #60 smoke runs in the
existing `all-adapters` matrix through
`scripts/installed_qualification_runner.py`.

The installed scenario persists/selects representative conventional,
weighted-mean standards, profile-constrained standards, and hybrid Grades;
exercises explicit override withdrawal; freezes a ReportingSnapshot; and
projects real Concord group evidence. A second fresh process reloads the
canonical state, reproduces the embedded calculations, verifies selected
override history and effective precedence, checks exact ReportingSnapshot
bytes/digests, verifies the student-scoped Concord cache boundary, and performs
no workspace mutation.

The prepared environment owns dependency installation, one `pip check`, source
isolation, exact installed origins, and package-set fingerprinting. The package
set must remain unchanged after the Issue #60 smoke.

## Packaging and repository validation

Every Issue #60 adversarial test, installed smoke/reload/wrapper, architecture
document, and closeout acceptance test is required by source-distribution
validation. The runtime wheel remains production-only; no acceptance helper is
added as a runtime module.

There is no second top-level validator. Normal final qualification remains:

```text
pytest
Ruff
strict mypy
documentation validation
wheel + sdist build
Twine checks
wheel/sdist guards
authenticated dependency verification
six-matrix prepared installed qualification
git diff --check
```

`scripts/validate_repository.py` reaches Issue #60 through the existing central
installed runner.

## Relationship to Issue #61

Issue #60 establishes permanent adversarial evidence so Issue #61 can perform
the final v0.3 calculation, explanation, export, and release audit without first
discovering basic cross-policy authority failures.

Issue #61 remains responsible for the release-wide audit, including no silent
zeroes, no source mutation, no official-system authority claims, deterministic
snapshots, safe exports, and exact release artifacts.

Issue #60 cross-policy adversarial and installed acceptance — implemented and
qualified.
