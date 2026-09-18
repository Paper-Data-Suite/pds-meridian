# Teacher Grade overrides and effective Academic Period Grade

Issue #53 implements Meridian v0.3's teacher-controlled override layer over one
exact final Academic Period Grade result. It is downstream of conventional,
standards-based, and hybrid Grade calculation and upstream of issue #54 Grade
preview/explanation and issue #55 `ReportingSnapshot` construction.

This architecture specializes [ADR 0005](../decisions/0005-v03-grade-preview-and-reporting-snapshot-architecture.md)
and the v0.3 umbrella issue #47. The governing separation remains:

```text
producer evidence
    != Meridian interpretation
    != proficiency
    != immutable base Grade calculation
    != teacher Grade override
    != effective Grade
    != Grade preview
    != ReportingSnapshot
    != export artifact
    != official school-system record
```

## Version-1 boundary

Version 1 overrides only final Academic Period Grade results. The supported base
families are exactly:

```text
conventional
standards_based
hybrid
```

The override layer does not alter Grade Items, evidence, attempt/reassessment
state, proficiency, Grade policy, Grade-policy activation, producer state, or
Core state. It does not provide lower-level overrides for any of those objects.

One override decision belongs to one exact logical scope:

```text
class
student
AcademicPeriodRef
calendar revision
calculation family
```

Within that scope it binds one exact immutable source Grade-result reference,
including the source result revision and SHA-256 digest.

## Exact source binding

`GradeOverrideSourceResultReference` is a closed tagged abstraction over the
existing family-specific result references:

```text
ConventionalGradeResultReference
StandardsGradeResultReference
HybridGradeResultReference
```

The family tag is explicit. Meridian never infers a source family because two
JSON objects look structurally similar.

The source reference preserves:

```text
class_id
student_id
school_year
period_id
calendar_revision
result_revision
result_sha256
```

Normal active-override authoring resolves the exact explicitly selected source
Grade result for the requested family. It does not choose the greatest revision,
newest timestamp, latest file, highest Grade, or a result with a matching numeric
value. Before a new immutable override revision is committed, the workflow
revalidates that exact source authority; the storage writer repeats the supplied
precommit guard while holding the override-family write lock.

A selected source result is not assumed fresh merely because it is selected.
The authoring/effective-Grade boundary reuses each existing source family's
freshness contract. Selection and freshness are separate facts.

## Numeric replacement semantics

An active `override` decision supplies one exact finite nonnegative `Decimal`
replacement Grade.

There is no universal 0-100 clamp. A replacement such as `105.25` is valid when
that is the teacher's explicit final-Grade decision. The override layer does not
reround the value through the source Grade policy and does not reinterpret it as
points, a percentage input, a proficiency level, or evidence.

Version 1 does not invent teacher-authored nonnumeric final Grade values.
However, a numeric override may replace a valid current base outcome whose
source status is:

```text
calculated
blocked
insufficient
```

The original base result remains byte-identical and retains its original status.

## Actor, rationale, and decision time

Every teacher override decision records exact teacher actor provenance and a
required bounded nonblank rationale. Non-teacher actor kinds are invalid for the
version-1 teacher override contract.

`decided_at` is timezone-aware UTC audit metadata. It never establishes
precedence. A later timestamp does not make a revision current.

## Immutable revision history

Teacher override history is append-only and contiguous:

```text
revision 1
-> revision 2 supersedes 1
-> revision 3 supersedes 2
-> ...
```

A correction creates another immutable `override` decision. A withdrawal creates
an immutable `withdraw` decision. Reactivation after withdrawal creates another
new immutable `override` decision. Historical records are not rewritten,
deleted, or silently restored.

An `override` decision contains:

```text
exact source Grade-result reference
exact replacement Grade
teacher actor
rationale
UTC decision time
```

A `withdraw` decision contains:

```text
exact source Grade-result reference inherited from the withdrawn override
exact withdrawn override reference
teacher actor
rationale
UTC decision time
```

Withdrawal is lifecycle state, not a final Grade value.

## Canonical persistence and privacy

The canonical family is stored under a privacy-minimal deterministic subject key:

```text
classes/<class_id>/modules/meridian/grade_overrides/
  periods/<school_year>/<period_id>/students/<subject_key>/<family>/
    current.json
    revisions/
      1.json
      1.json.sha256
      2.json
      2.json.sha256
```

The raw student ID remains inside the validated immutable record because it is
part of exact academic identity, but it is not exposed as the student-bearing
path segment.

Revision JSON is canonical and SHA-bound. Reads are bounded and reject malformed
or noncanonical JSON, incomplete JSON/digest pairs, SHA disagreement, symlinks,
path escapes, unexpected canonical entries, and scope/path disagreement. Exact
retry of identical immutable bytes is idempotent; different bytes at an existing
revision conflict.

## Writing is not selection

Persistence deliberately separates immutable history from current authority:

```text
write revision != select revision
newest revision != current revision
highest revision != current revision
```

`current.json` is an explicit SHA-bound selector. Selection uses compare-and-swap
against the caller's expected current reference.

The low-level storage selector can identify an exact historical revision for
repair/composition needs. The teacher lifecycle workflow intentionally does not
expose historical reselection as an audit-free undo mechanism. Normal teacher
selection may select only the latest authored immutable decision. A correction,
restore, or reactivation is represented by a new immutable decision.

## Withdrawal lifecycle

Normal withdrawal begins from the exact explicitly selected active `override`.
The workflow:

1. loads and verifies that exact selected active override;
2. loads its historical source Grade result by exact revision and digest;
3. appends one immutable `withdraw` decision;
4. leaves the active override selected after the write; and
5. requires a separate explicit CAS selection of the withdrawal.

This preserves the same `write != select` invariant used by active override
authoring.

Withdrawal remains possible if the withdrawn override's source result is no
longer the currently selected source Grade result. Withdrawal terminates an exact
teacher decision; it is not a new claim that the historical source is current.
The historical source must nevertheless remain present and digest-valid.

## Non-floating behavior after recalculation

An active override applies only when its exact source reference equals the exact
currently selected base result reference.

Suppose the selected conventional result is revision 1 and an active override is
bound to revision 1:

```text
source r1 selected
+ override bound to source r1
-> override may apply
```

Writing source result revision 2 alone changes nothing because writing does not
select. If source revision 2 is explicitly selected later:

```text
source r2 selected
+ old override bound to source r1
-> old override is non-applicable
-> valid current base r2 governs
```

No Grade value, family similarity, student/period match, timestamp, or revision
ordering can make the revision-1 override float onto revision 2. Applying a new
replacement to revision 2 requires a deliberately authored new immutable override
bound to revision 2 and an explicit override selection.

## Source freshness versus override applicability

An exact source-reference match is necessary but not sufficient for active
override authority. The selected source result must also be current under its
existing family-specific freshness contract.

A matching override over a stale selected source does not make that source
current. Effective resolution reports `source_result_stale` and produces no
current effective authority.

Expected non-applicability is represented structurally rather than as an
integrity exception. The effective Grade contract distinguishes states equivalent
to:

```text
no_override
applicable
withdrawn
source_result_changed
source_result_stale
```

These are ordinary lifecycle/currentness observations.

By contrast, corrupt canonical state fails closed. Examples include:

```text
corrupt current override pointer
selected override digest mismatch
missing selected override revision
malformed selected override record
scope disagreement in selected canonical state
corrupt historical source result referenced by the selected override
```

Integrity failure is never silently reclassified as `no_override` merely so the
base Grade can be returned.

## Deterministic effective-Grade precedence

`meridian.effective_grade` is read-only. It does not write, select, recalculate,
repair, or rebind anything.

The behavior matrix is:

```text
BASE                         SELECTED OVERRIDE        EFFECTIVE RESULT
------------------------------------------------------------------------
current + calculated         none                     base Grade
current + calculated         applicable override      replacement Grade
current + calculated         selected withdrawal      base Grade
current + calculated         override for old source  base Grade + diagnostic
current + blocked            none                     no numeric Grade
current + blocked            applicable override      replacement Grade
current + insufficient       none                     no numeric Grade
current + insufficient       applicable override      replacement Grade
stale base                   matching override        no current authority
```

`EffectiveGradeResolution` preserves the complete downstream handoff rather than
returning a naked number. It exposes:

```text
base_result_family
exact base_result_reference
base_result_status
base_grade
base_freshness_status
base_freshness_reasons
exact selected_override_reference, if any
full immutable override_decision, if any
override_applicability
override_reasons
effective_grade
effective_source = base | override | none
```

This is the public structured provenance surface consumed by later v0.3 work.

## #54 Grade preview handoff

Issue #54 may explain the effective Grade without reconstructing teacher intent
from filesystem history. It can state, from one resolution object:

- what exact base Grade result is selected;
- whether that result is current or stale;
- what the original base outcome/value was;
- whether an override decision is selected;
- whether that decision is applicable, withdrawn, old-source, or stale-source;
- the exact replacement Grade when applicable; and
- whether the displayed effective value comes from `base`, `override`, or no
  current authority.

Issue #54 must remain a preview/explanation layer. Reading a preview must not
select an override, create a snapshot, or write an official Grade.

## #55 ReportingSnapshot handoff

Issue #55 can bind its immutable reporting observation directly to:

```text
exact selected source Grade-result reference
the source's currentness observation
exact selected override reference/decision, if present
override applicability
effective Grade
effective source
```

When an override is applicable, a later snapshot can therefore preserve both the
original calculated result and the teacher replacement without treating either as
an inferred latest record. When no override is applicable, the snapshot can
preserve the diagnostic reason rather than discarding it.

No downstream consumer needs to infer provenance from a filesystem path.

## Installed acceptance

Issue #53's installed smoke uses exact released Core v0.6.3, ScoreForm v0.11.0,
and the candidate Meridian wheel in an isolated venv outside the source checkout.
Quillan and Concord are deliberately absent from that representative installed
scenario; source-level tests cover all three Grade-result families.

The installed scenario creates a real released ScoreForm publication and uses the
already-qualified conventional Grade path to create/select a canonical base Grade
result. It then proves:

```text
author active override
-> write does not select
-> base remains effective
-> explicitly select active override
-> replacement becomes effective
-> fresh-process reload reproduces active authority
-> write immutable withdrawal
-> active override remains selected/effective
-> explicitly select withdrawal
-> fresh-process reload reproduces withdrawal
-> base Grade regains precedence
```

It also runs `pip check`, requires Meridian imports to resolve from installed
`site-packages`, prevents user-site/PYTHONPATH sibling leakage, keeps Quillan and
Concord absent, and verifies the original source Grade-result bytes and producer
source/publication bytes remain unchanged throughout the lifecycle.

## Non-goals

Issue #53 does not implement:

- proficiency, Grade Item, evidence, or attempt overrides;
- arbitrary text/letter/non-numeric final Grade replacements;
- policy or activation changes;
- automatic Grade recalculation;
- automatic override rebinding;
- automatic latest/newest override selection;
- timestamp-based precedence;
- Grade preview UI or explanation presentation;
- `ReportingSnapshot` construction;
- snapshot comparison;
- report/CSV export;
- direct SIS/LMS/gradebook writes;
- official school-system Grade authority;
- menu/suite-attention integration; or
- producer-specific override behavior.

## Completion invariant

The complete version-1 chain is:

```text
exact immutable Grade-result history
        |
        v
explicit selected source Grade result
        |
        v
existing source-result currentness contract
        |
        v
exact immutable teacher override history
        |
        v
explicit selected override decision
        |
        v
exact source-reference applicability
        |
        v
deterministic effective Meridian Grade
```

The answer to "what Grade is effective now?" never depends on guessing from
timestamps, choosing the highest revision, mutating historical calculation state,
or silently carrying an old override onto a later recalculation.
