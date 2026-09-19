# Grade and report preview explanations

Issue #54 adds Meridian v0.3's read-only Grade/report explanation layer over the
exact Grade calculation, policy, and teacher-override authority established by
issues #49-#53. It is governed by ADR 0001, ADR 0002, and ADR 0005 and remains
inside v0.3 umbrella issue #47.

The boundary is deliberately narrow:

```text
producer evidence
    != Meridian interpretation
    != proficiency
    != Grade calculation
    != teacher override
    != Grade preview/explanation
    != ReportingSnapshot
    != export artifact
    != official school-system record
```

A Grade preview is advisory. It explains existing selected Meridian state; it
does not create, select, repair, or recalculate academic authority.

## Current preview authority

The public current-preview target is explicit about:

```text
class_id
student_id
AcademicPeriodRef
calendar_revision
calculation_family
```

The supported families are exactly `conventional`, `standards_based`, and
`hybrid`. Family is never inferred from filenames, timestamps, revision order,
or whatever store happens to load first.

`explain_current_grade_preview()` composes the selected Grade result, the exact
current family basis, selected teacher override, and issue #53 effective-Grade
precedence. Conventional and hybrid currentness require the caller's explicit
`ConventionalGradeWorkEvidenceSpec` tuple; standards-based preview rejects that
irrelevant input.

A selected Grade may be stale and still be explainable. Selection and freshness
are distinct. A stale selected result does not become current authority merely
because it remains selected or because a teacher override exists.

## One coherent observation

Current preview uses optimistic reread/revalidation rather than a global lock.
It captures an initial witness containing the exact selected Grade-result
reference, the canonical digest of the assembled current input basis, current
activation/policy references, selected override reference, and resolved
effective Grade. It then loads the persisted result's exact historical policy
and activation, builds the explanation, and captures the witness again.

If any material selector or current basis moves, the operation fails with
`grade_preview.currentness_conflict`. This also catches changes that would
collapse to the same human-facing stale reason, because the exact assembled
input digest is part of the witness.

The error taxonomy includes:

```text
grade_preview.error
grade_preview.target_invalid
grade_preview.target_not_found
grade_preview.source_unavailable
grade_preview.integrity_failed
grade_preview.currentness_conflict
grade_preview.comparison_invalid
```

Expected academic states and stale selected results become structured
explanations. Corruption never degrades to `no Grade`, `no override`, or
`unchanged`.

## Exact policy, state treatment, and rounding

The explanation loads the exact Grade-policy activation and policy revision
referenced by the persisted Grade result. A newer current policy is never
substituted for the policy that actually produced the historical result.

The common projection exposes policy title/family, exact activation and policy
references, actor/rationale provenance, state treatment, reassessment handling,
and rounding. Missing and non-Grade states remain semantically distinct from
numeric zero unless the exact policy assigned the `zero` consequence.

Numeric explanation preserves exact `Decimal` values for the unrounded Grade,
rounded base Grade, rounding quantum, mode, and application stage. A teacher
override replacement is not rerounded through the base policy, so these remain
separate concepts:

```text
base unrounded Grade
base rounded Grade
override replacement Grade
effective Grade
```

## Conventional breakdown

Conventional explanation supports `total_points`, `weighted_items`, and
`weighted_categories`. It projects exact Grade Item revision/digest identity,
title/purpose/status, category and policy weights, possible points, persisted
source state, policy action, earned/possible values, percentage, contribution,
reason codes, and recorded provenance.

Provenance preserves the existing typed kinds (`source`, `membership`,
`eligibility`, `attempt_selection`, and `reassessment`). Opaque reference keys remain opaque. The preview layer does not reverse-parse
them into stronger authority.

Weighted-category explanation also preserves configured category title/weight,
included/excluded item identities, earned/possible values, fraction,
contribution, and reasons. The formula projection describes the actual policy
mode rather than labeling every calculation as a generic average.

## Standards-based breakdown

Standards explanation exposes the target proficiency-scale reference,
aggregation strategy, minimum calculated-result requirement, actual count,
active weight, weighted numerator, unrounded Grade, and rounded Grade.

Each configured standard preserves its weight, source state/action, exact
Academic Period proficiency-result reference, algorithm/fingerprint, target
scale, proficiency level, converted Grade, calculation value, contribution,
upstream freshness, and reasons.

When a standard carries an exact Academic Period proficiency result, issue #54
uses the existing historical explanation machinery with `selection="revision"`.
The nested path remains:

```text
standards Grade result
-> exact AcademicPeriodProficiencyResultReference
-> exact historical Academic Period proficiency explanation
-> exact historical Grade Item proficiency references
```

The nested revision, digest, algorithm, fingerprint, scale, and proficiency
outcome must agree with the values embedded in the Grade calculation. Current
proficiency is never substituted for historical provenance. Protected producer
evidence remains behind the existing authorization boundary.

## Hybrid breakdown

Hybrid explanation does not invent a fourth grading model. It explains the
bounded combination of the exact conventional and standards components embedded
inside `HybridGradeResultSnapshot.inputs` and `outcome`.

It exposes configured component weights, component source status/action,
algorithm versions and fingerprints, exact unrounded component Grades, weighted
contributions, active hybrid weight, weighted numerator, hybrid unrounded and
rounded Grades, and reasons. The component breakdown helpers consume the
embedded calculation inputs/outcomes.
The hybrid explanation never substitutes independently selected conventional or standards Grade results.

## Teacher override and effective Grade

Issue #54 consumes issue #53's `EffectiveGradeResolution`; it does not implement
parallel precedence. The explanation preserves selected override identity,
decision kind, exact source result, teacher actor, required rationale, decision
time, replacement Grade or withdrawal reference, applicability/reasons, and the
effective `base` / `override` / `none` source.

The applicability states remain `no_override`, `applicable`, `withdrawn`,
`source_result_changed`, and `source_result_stale`. An old override never floats
to a later Grade result, and a stale source cannot be made current by override.

## GradePreviewObservation and ReportingSnapshot boundary

`GradePreviewObservation` is a compact, deterministic, versioned,
privacy-minimized handoff for later reporting. It preserves exact scope, base
result, freshness, algorithm/fingerprint/input digest, activation/policy,
rounding and family semantic basis, selected override/applicability, and
effective Grade/source. Decimal serialization is lossless and basis entries use
a canonical order.

`GradePreviewObservation` is **not** a `ReportingSnapshot`. Issue #54 defines no
snapshot storage, snapshot revision/current selection, issuance semantics,
report-definition persistence, or export artifact. Those remain issue #55.

`PriorReportingSnapshotGradeBasis` is intentionally snapshot-neutral: #55 can
later extract/freeze a real observation and pass it to the #54 comparison
engine without #54 knowing the future snapshot schema.

The comparison engine has deterministic `new`, `removed`, and `comparable`
relationships and a closed reason taxonomy covering calculation family, base
result/status/Grade, policy/formula, membership/participation, evidence or
proficiency basis, weighting, state handling, rounding, algorithm, override,
override applicability, freshness, effective Grade, and effective source.
Numeric deltas use exact Decimal arithmetic. A material input/fingerprint change
that cannot be explained by the structured dimensions fails closed.

## Report preview

Report preview accepts only explicit `GradeReportPreviewRequest` values.
It does not infer a roster from storage.
Rows are canonically ordered by explicit target.
A truly absent selected Grade becomes an `unavailable` row with
`no_selected_grade`; corruption, broken provenance, or currentness conflict still
raises an error instead of masquerading as absence.

The deterministic summary counts requested/available/unavailable rows, base
calculated/blocked/insufficient states, current/stale states, numeric/nonnumeric
effective Grades, and effective `base`/`override`/`none` sources.

## Read-only guarantee

Explanation, observation, comparison, and report-preview APIs perform no
academic mutation. They do not write or select Grade results; write or activate
policies; author/select/withdraw overrides; create ReportingSnapshots; export
CSV or other transfer artifacts; modify Core; modify producer state; or write an
SIS/LMS/district gradebook.

Qualification compares whole-workspace file digests before and after preview,
including real producer, Core, policy, Grade-result, proficiency, and override
state. No ReportingSnapshot or export is created.

## Installed acceptance and compatibility audit

The issue #54 candidate-wheel smoke runs outside the source checkout, disables
user/site source leakage, runs `pip check`, verifies every new Meridian module
comes from installed `site-packages`, and installs the exact supported released
contracts together:

```text
pds-core      0.6.3
scoreform     0.11.0
quillan       0.10.0
pds-concord   0.3.0
```

It creates real canonical conventional, standards-based, and hybrid Grade state,
including a conventional teacher override to `105.25`; explains all three
families; freezes deterministic observations; builds report/comparison output;
proves workspace immutability; and repeats the explanation in a fresh process.
The fresh process reopens conventional/hybrid projection evidence through the
existing authorization-gated projection-cache reader rather than republishing or
rewriting evidence.

The stable-release audit immediately before Slice 7 found Core v0.6.3,
ScoreForm v0.11.0, Quillan v0.10.0, Concord v0.3.0, Meridian v0.2.0, and Paper
Data Suite v0.1.0 unchanged. Vitrine advanced to v0.3.0 on 2026-09-19 but
remains interoperability context only and is not a Meridian dependency. Portia
still has no GitHub Release and remains a nondependency.

See also [ADR 0001](../decisions/0001-policy-driven-standards-proficiency-and-grade-calculation.md),
[ADR 0002](../decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md),
and [ADR 0005](../decisions/0005-v03-grade-preview-and-reporting-snapshot-architecture.md).
