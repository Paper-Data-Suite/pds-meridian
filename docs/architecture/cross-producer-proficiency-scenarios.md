# Cross-producer proficiency scenarios

## Status and scope

Issue #44 qualifies Meridian's source-level proficiency interpretation across the
released academic-result contracts for:

```text
pds-core     0.6.3
scoreform    0.11.0
quillan      0.10.0
pds-concord  0.3.0
```

The scenarios extend issue #13's cross-producer synthetic ingestion foundation
through the teacher-controlled interpretation layers implemented in issues
#27-#43. They do not introduce a parallel cross-producer model.

The qualified path is:

```text
Core publication
    -> exact producer adapter projection
    -> Grade Item membership
    -> evidence eligibility
    -> attempt selection
    -> reassessment
    -> Standard association
    -> native-value mapping
    -> bounded Standard aggregation inputs
    -> Grade Item standards proficiency
    -> Academic Period standards proficiency
    -> read-only explanation trace
```

Every arrow is a separate boundary. A successful earlier stage never authorizes
or infers a later one.

## Frozen distinctions

Issue #44 makes these distinctions executable acceptance requirements:

```text
publication validity
    != Grade Item membership

Grade Item membership
    != evidence eligibility

evidence eligibility
    != attempt selection

attempt selection
    != reassessment

producer-declared Standard alignment
    != Meridian Standard association

producer-native value
    != Meridian proficiency

same numeric value
    != same native scale

mapped native value
    != calculated proficiency

Grade Item proficiency
    != Academic Period proficiency

student academic evidence
    != grouping instruction

proficiency
    != grouping band

grouping signal
    != GroupPlan

calculation
    != export
```

Producer contracts remain authoritative for producer-native meaning. Meridian
interprets them only through explicit, versioned Meridian records and policies.

## ScoreForm: repeated attempts and response states

The synthetic ScoreForm work contains two distinct attempts for the same student.
The released adapter preserves both and does not designate either as official,
best, latest, or current.

The scenarios prove:

- projection order and attempt number do not choose an operative attempt;
- no current attempt decision remains unresolved and contributes nothing;
- `selected_none` is an explicit no-contribution decision, not zero;
- selecting one attempt binds that exact attempt;
- selecting multiple attempts requires the existing reassessment contract;
- explicit replacement determines contribution rather than chronology or score;
- changing teacher attempt/reassessment decisions changes the canonical
  aggregation basis and calculation fingerprint without rewriting history; and
- a Core publication correction requires a fresh interpretation bound to the
  exact canonical successor publication.

Response semantics remain separate. A blank or ambiguous
`selected_response_state` stays `NativeStateValue`. A separate
`question_correctness=False` observation is a different result kind and cannot
rewrite blank or ambiguous response state as numeric zero. Attempt points remain
`NativePointValue`.

## Quillan: ratings, applicability, and missingness

The scenarios exercise the released Quillan `0 / 2 / 4` native rating scale and
preserve distinctions among:

```text
real lowest rating
middle rating
unrated
not applicable
applicable with evidence absent
returned_without_full_review
overall Standard rating
review-unit Standard observation rating
```

A real native rating of `0` remains a real rating. It is not equivalent to
`unrated`, evidence absence, non-applicability, or a returned-without-full-review
state. Absence of an overall rating does not manufacture one.

Overall Standard ratings and review-unit Standard observation ratings remain
different source-signature families. A mapping profile for one cannot silently
map the other, and a rating profile cannot map applicability, evidence-presence,
review, or minimum-requirement states. Exact Quillan native-scale provenance is
retained.

## Concord: student targets, group targets, and moderation

A current `core_student` + `standard_backed` + `scored` result may contribute to
student proficiency only after the ordinary Meridian chain of membership,
eligibility, Standard association, attempt/reassessment applicability, exact
mapping, aggregation, and calculation succeeds.

A standard-backed `core_student` non-score disposition such as `absent` remains
a native state rather than numeric zero.

A `concord_group` result remains nonstudent evidence even when the scenario
deliberately gives it Grade Item membership, included eligibility, explicit
Standard association, and an otherwise compatible mapping profile. At the
student aggregation boundary it is still:

```text
excluded: nonstudent_target
```

Student references in Concord evidence or moderation provenance do not rewrite
the actual target or subject identity. Moderation remains traceable provenance
and does not silently choose eligibility, Standard association, mapping, or
proficiency.

Concord's producer-native current/superseded score history also remains distinct
from Core publication lifecycle. A superseded Concord score stays historical
producer provenance while the explicitly current Concord score remains current.

## Similar-looking values are not equivalent

The collision scenario deliberately includes values that all contain the scalar
`2`:

```text
ScoreForm: 2 earned points
Quillan:   native rating 2
Concord:   native score 2
```

They remain different values:

```text
ScoreForm -> NativePointValue
Quillan   -> NativeScaledValue on the exact Quillan scale
Concord   -> NativeScaledValue on the exact Concord scale
```

The Quillan and Concord native scales are not equal. Mapping profiles are bound
to the complete source signature and cannot cross-apply merely because labels or
numeric levels look similar. Raw-point mappings also bind the exact
`points_possible`; a denominator mismatch is explicit `unsupported`, not an
inferred percentage conversion.

## One mixed Grade Item

The representative Grade Item explicitly includes ScoreForm, Quillan, and
Concord work. For one synthetic student and Standard, its finite candidate set
contains mapped ScoreForm evidence, mapped Quillan performance, mapped Concord
student performance, a producer-native state, and an excluded Concord
group-target result.

The canonical aggregation input preserves every exact source identity and a
deterministic ordering. Native states and exclusions remain visible in the
explanation basis but are not silently converted into performance. Repeated
execution from the same exact persisted workspace produces the same canonical
inputs, digest, calculation fingerprint, and outcome.

## Mixed proficiency-policy behavior

With nonblocking native-state handling, sufficient mapped performance remains
and the mixed result is `calculated`.

With blocking native-state handling, the result is:

```text
status = insufficient_evidence
reason = blocking_native_state
```

The blocking path never converts missing/native state into the lowest
proficiency level.

## Academic Period carry-forward

A representative persisted Grade Item proficiency result is carried into the
existing Academic Period aggregation path using exact Grade Item references,
explicit current calendar state, and existing direct/descendant period scope.

Producer identity does not alter the Academic Period algorithm. Missing or
insufficient Grade Item results remain nonnumeric states rather than low
proficiency. Reversing caller-provided membership order within the same persisted
workspace does not alter the canonical basis or result.

Issue #44 performs calculation only. It does not export a Core grouping signal.

## Core correction, withdrawal, and immutable history

Core publication lifecycle remains canonical.

### ScoreForm correction

The scenario creates a real ScoreForm record-set revision 2 through Core
supersession. Current discovery returns the exact canonical successor rather than
a filename, timestamp, revision-number, or directory-order heuristic.

A fresh authorized projection is created for that successor. Fresh source-bound
eligibility and Standard associations are authored, attempt/reassessment
decisions are revised against the exact corrected projection, and a new Grade
Item proficiency result is persisted.

The historical result and trace continue to identify only the exact old
ScoreForm publication. The new current result and trace identify only the exact
Core successor.

### Quillan withdrawal

A real Core withdrawal makes the old Quillan source nonoperative for a fresh
calculation. The source becomes an explicit eligibility exclusion rather than a
low score or generic missing value.

The prior proficiency result remains immutable history. Its historical
explanation still names the exact withdrawn publication that originally
contributed.

## Explanation and trace

Issue #44 reuses the issue #42 explanation model. It does not create another
trace representation or recalculate while explaining.

The calculated mixed Grade Item trace retains exact ScoreForm, Quillan,
Concord-student, and Concord-group source identities; native-state and exclusion
outcomes; mapping-profile and Standard-association provenance;
attempt-selection/reassessment provenance; calculation policy; and target scale.

Historical trace selection never substitutes a newer current producer
publication, teacher decision, or proficiency result.

## No grouping circularity

Concord academic-result evidence and Concord grouping state are separate domains.

The explicit anti-circularity path is:

```text
Concord group academic result
    -> Meridian student Standard aggregation
    -> excluded: nonstudent_target
```

That conclusion requires no inspection of Concord `GroupPlan`, `Group`, or
`GroupMembership`. Group membership is not an academic-evidence selector, and a
group-target score is not promoted into individual student proficiency.

The issue #44 calculation scenarios also do not treat a Core
`grouping_signal_set_v1` as academic evidence and do not invoke Meridian
grouping-signal generation or export to complete proficiency calculation.

## Producer-neutral runtime and dependency direction

Executable guards verify that the generic Grade Item / Academic Period
proficiency modules do not import ScoreForm, Quillan, Concord, or `pds-concord`,
and do not import Meridian grouping/planning-signal generation or export modules.

The base runtime dependency remains:

```text
pds-core>=0.6.3,<0.7
```

Released producer readers remain exact optional extras:

```text
scoreform==0.11.0
quillan==0.10.0
pds-concord==0.3.0
```

Producer-specific parsing remains confined to explicit adapter composition.

## Synthetic-data boundary

All issue #44 scenario identities remain bounded synthetic identifiers, including:

```text
synthetic_class_2026
student_synthetic_001
student_synthetic_002
standard_ela_1
synthetic_quiz_alpha
synthetic_essay_alpha
activity_1
```

No real student record, roster, Grade, submission, scan, credential, private
URL, or workstation path belongs in the scenario family.

## Acceptance surfaces

Issue #44 extends the existing issue #13 support rather than replacing it:

```text
tests/cross_producer_proficiency_support.py
tests/cross_producer_attempts_support.py
tests/cross_producer_aggregation_support.py
tests/cross_producer_native_states_support.py
tests/cross_producer_academic_period_support.py
tests/cross_producer_correction_support.py
tests/cross_producer_decision_history_support.py

tests/test_cross_producer_proficiency_issue44.py
tests/test_cross_producer_attempts_issue44.py
tests/test_cross_producer_aggregation_issue44.py
tests/test_cross_producer_policy_issue44.py
tests/test_cross_producer_native_states_issue44.py
tests/test_cross_producer_academic_period_issue44.py
tests/test_cross_producer_lifecycle_issue44.py
tests/test_cross_producer_correction_issue44.py
tests/test_cross_producer_decision_history_issue44.py
tests/test_cross_producer_boundaries_issue44.py
```

Documentation and source-distribution acceptance are guarded separately.

## Boundary with issue #45

Issue #44 proves the semantic correctness of the source-level cross-producer
proficiency pipeline.

Issue #45 owns the installed end-to-end qualification from exact installed
Core/producer/Meridian artifacts through teacher decisions, proficiency,
grouping-signal generation/export, Core JSON/CSV round trip, and history reload.

Critically, issue #45 performs that installed proficiency and signal-export
acceptance without Concord installed. Issue #44 does not pull that installed
requirement backward and does not add a duplicate installed cross-producer smoke.

## Handoff

```text
#42 explanation/trace views — implemented
#43 Meridian proficiency attention summaries — implemented
#44 cross-producer proficiency scenarios — implemented
#45 installed proficiency and signal-export acceptance without Concord — implemented
#46 final v0.2.0 audit — implemented; release preparation qualified
```
