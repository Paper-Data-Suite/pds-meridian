# Reassessment and replacement relationships

## Purpose

Issue #31 adds Meridian's canonical v0.2 reassessment and replacement layer after
explicit attempt selection (#30).

It answers one bounded question:

```text
For this Grade Item/work/student and this exact operative #30 decision,
how are the explicitly selected attempts related for later academic interpretation?
```

The boundary remains:

```text
publication validity
!=
Grade Item membership
!=
evidence eligibility
!=
attempt selection
!=
reassessment/replacement
!=
native-value mapping
!=
standards aggregation
!=
proficiency calculation
```

In short:

```text
attempt selection != reassessment
reassessment != native-value mapping
```

Issue #31 stores relationships and provenance. It does not inspect scores or
calculate a result.

## Exact #30 basis

Every persisted `ReassessmentDecision` binds an exact immutable #30 decision with
`AttemptSelectionDecisionReference`:

```text
decision_revision
decision_sha256
```

The surrounding reassessment record also carries the exact:

```text
class_id
grade_item_id
work
student_id
```

Before a new #31 decision is written or selected, Meridian reloads that exact #30
revision and requires the current #30 resolver to return an operative `selected`
state for the same revision and SHA-256.

A later #30 decision never rewrites an earlier #31 record. The old #31 decision
remains immutable and current-use resolution reports `attempt_selection_stale`.

## Applicability

#31 follows #30 rather than inventing a second producer-applicability mechanism.

The current resolver distinguishes:

```text
not_applicable
attempt_selection_unresolved
selected_none
single_selected
no_decision
resolved
attempt_selection_stale
policy_stale
```

### Not applicable

When #30 reports `not_applicable`, #31 also reports `not_applicable`. No
reassessment record is fabricated.

### Selected none

When #30 has an operative explicit empty selection, #31 reports:

```text
selected_none
contributing_attempts = ()
```

This is explicit absence of selected attempts. It is not zero, failure, missing
work, or an inferred lowest performance state.

### One selected attempt

When #30 has exactly one operative selected attempt, #31 reports:

```text
single_selected
```

and passes that exact attempt forward as the sole contributor. No ceremonial
reassessment record is required because there is no inter-attempt relationship
to establish.

### Multiple selected attempts

Two or more operative selected attempts require an explicit #31 relationship
decision. Without one, the resolver returns:

```text
no_decision
```

Later proficiency work must not guess `retain all`, `latest`, `highest`, or
`average`.

## Explicit policy

`ReassessmentPolicy` is a stable policy family with immutable revisions. Its
logical identity is:

```text
class_id
grade_item_id
work
policy_id
```

Version 1 uses exactly:

```text
relationship_basis = "explicit"
```

The policy authorizes a deterministic duplicate-free subset of:

```text
retain
replace
combine
recency
```

One student decision uses exactly one authorized mode. A future schema can add
richer mixed relationships when a concrete classroom requirement justifies the
added complexity.

Policy revision 1 uses `supersedes_revision = null`. Later revisions are
contiguous and preserve the same logical identity. A new revision never becomes
current automatically.

Each policy family has its own SHA-256-bound `current.json` selector. Selection
uses compare-and-swap and permits deliberate historical reselection.

Never infer current policy from:

```text
highest revision
latest revised_at
mtime
directory order
```

## Retain mode

`retain` means every exact #30 selected attempt remains independently
contributing.

For example:

```text
#30 selected:
  attempt 1
  attempt 3

#31 retain:
  contributing:
    attempt 1
    attempt 3
```

Retain does not mean average, equal weighting, numeric merge, or identical
standards interpretation. Those consequences belong downstream.

## Replacement mode

`ReplacementRelationship` records an explicit directed academic relationship:

```text
replacement_attempt
replaced_attempts
```

For example:

```text
attempt 3
  replaces:
    attempt 1
    attempt 2
```

Validation requires:

- every relationship member to be in the exact #30 selected set;
- no self-replacement;
- no duplicate replaced target;
- no competing replacement for the same attempt;
- no replacement chain or cycle in v1; and
- replacement attempts to remain contributing.

The exact contributing set is the #30 selected order minus explicitly replaced
attempts.

A replaced attempt becomes historical/noncontributing only for this exact #31
decision. It is not deleted, invalidated, withdrawn, or rewritten.

## Combination mode

`ReassessmentCombination` groups two or more exact selected attempts:

```text
combination_id
members
```

Combination groups are deterministic, duplicate-free, and disjoint in v1.
Every member remains contributing.

`combine` means only:

```text
these exact attempts are intended to be considered together later
```

It does not define:

```text
sum
average
weighted average
maximum
minimum
percentage
rubric merge
```

No numeric reducer exists in #31.

## Recency mode

`recency` stores an explicit ordered tuple of every exact selected attempt:

```text
least recent / lowest recency preference
    ->
most recent / highest recency preference
```

The order is authored policy/teacher state. Meridian does not reconstruct it from
producer metadata.

A recency decision also stores an exact nonempty `contributing_attempts` suffix.
The suffix must narrow the full recency order. If every selected attempt should
remain contributing, use `retain`.

The following never create recency automatically:

```text
attempt number
recorded_at
publication revision
manifest generated_at
filesystem timestamp
```

## No hidden ranking

Issue #31 contains no general academic behavior equivalent to:

```text
higher score -> preferred
higher attempt number -> preferred
later timestamp -> preferred
newer publication -> preferred
```

An earlier/lower-sequence attempt may explicitly replace a later/higher-sequence
attempt. This is intentional proof that replacement is relationship-driven rather
than chronologically inferred.

## Contributing attempts

Every persisted `ReassessmentDecision` exposes exact:

```text
contributing_attempts
```

Mode validation defines them as:

```text
retain
  -> all exact #30 selected attempts

replace
  -> all exact #30 selected attempts minus explicitly replaced attempts

combine
  -> all exact #30 selected attempts

recency
  -> explicit most-recent suffix of the explicit recency order
```

Downstream #32+ code consumes this explicit set rather than reconstructing it from
scores or timestamps.

## Retained history

All producer evidence and all #29/#30 history remain intact.

The relationship is:

```text
producer attempt
    -> #29 eligibility history
    -> #30 attempt-selection history
    -> #31 contributing or historical/noncontributing interpretation
```

#31 never modifies:

- producer records;
- Core Publication Records;
- projection snapshots;
- #29 eligibility decisions;
- #30 candidates;
- #30 decisions.

## Producer correction is not reassessment

### ScoreForm

ScoreForm v0.10.0 is the first-class v1 reassessment producer because its public
contract exposes real `multiple_attempts` identity. A correction may create a new
native attempt, but the new attempt does not automatically replace an older one.
It can participate in #31 only after #30 explicitly selects it.

```text
ScoreForm correction attempt
!=
Meridian academic replacement
```

### Quillan

At the #31 baseline, Quillan v0.9.0 review/rating correction produces new
immutable producer publication history rather than ScoreForm-style attempt
identity.

Therefore the #31 Quillan behavior remains:

```text
#30 not_applicable
#31 not_applicable
```

A newer Quillan manifest revision is not fabricated into `attempt 2`.

### Concord

Concord v0.2.0 owns native correction, Score supersession, moderation revision,
and evidence-link supersession. Meridian's adapter preserves that native
provenance, including concepts such as:

```text
score_supersedes
moderation_supersedes
score_link_supersedes
```

Those producer-native relationships do not become #31 reassessment records.
Current Concord behavior remains:

```text
#30 not_applicable
#31 not_applicable
```

## Source lifecycle is not academic replacement

Core publication supersession and withdrawal remain source lifecycle. #29/#30
already incorporate those states into current-use resolution.

Issue #31 does not infer academic replacement from:

```text
Core publication superseded
Meridian included_source_superseded
producer-native corrected record
```

These remain different concepts from Meridian `replace`.

## Non-score states remain typed

#31 never reads or rewrites evidence values. An attempt may contain native typed
states such as blank or ambiguous evidence. Relationship storage does not convert
those states to:

```text
0
False
lowest level
missing-score sentinel
```

In particular:

```text
blank != 0
ambiguous != 0
missing != 0
unsupported != 0
```

Native-value mapping belongs to #32.

## Decision history

`ReassessmentDecision` is one immutable student-scoped decision. Its logical
history is:

```text
class_id
grade_item_id
work
student_id
```

Each revision binds:

```text
exact #30 decision revision + SHA-256
exact #31 policy revision + SHA-256
mode
contributing_attempts
replacement_relationships
combinations
recency_order
actor
rationale
decided_at
```

Revision 1 uses `supersedes_revision = null`. Later revisions are contiguous and
use nondecreasing decision timestamps.

Writing a new decision does not make it current. Each student history has a
separate CAS-protected current pointer. Historical decisions may be reselected
only while their exact dependencies remain valid.

Never infer current from:

```text
highest decision revision
latest decided_at
mtime
directory order
highest attempt number
```

## Current-use resolution and staleness

`resolve_current_reassessment(...)` first delegates to
`resolve_current_attempt_selection(...)`.

A selected #31 decision is operative only when:

- #30 remains operative;
- the exact #30 revision/digest still matches;
- the exact selected-attempt set still matches;
- the exact #31 policy revision/digest remains explicitly current; and
- the stored relationship remains valid against that selected set.

A changed #29 eligibility decision, #30 candidate set, membership, source state,
or #30 policy reaches #31 through #30's nonoperative/stale resolution. #31 does
not rebuild #29 eligibility independently.

Stale state is reported, not repaired:

```text
old decision remains immutable
current pointer is not rewritten
no replacement decision is created automatically
```

## Canonical storage

Issue #31 stores state beneath the existing #30 attempt-selection relationship:

```text
classes/<class_id>/modules/meridian/grade_items/<grade_item_id>/
  memberships/<producer_module_id>/<work_id>/
    attempt_selection/
      policies/
      students/
      reassessment/
        policies/
          <policy_id>/
            current.json
            revisions/
              1.json
              1.json.sha256
        students/
          <subject_key>/
            current.json
            revisions/
              1.json
              1.json.sha256
```

`subject_key` reuses #30's deterministic SHA-256 scope key. It is a path key, not
student identity. The immutable record retains `student_id`.

Policy and decision bytes use canonical UTF-8 JSON with one LF and immutable
SHA-256 sidecars. Reads are bounded. Paths are containment checked. Symlinked
canonical directories/files are rejected. Histories use narrow per-policy or
per-student write locks.

The #30 collection validator permits only the real `reassessment/` child and
does not interpret its contents.

## Authorization and privacy

#31 uses #30's authorized current-use resolver rather than opening projection
bytes itself. Possession of a student ID, attempt identity, policy ID, decision
revision, or digest is not evidence authorization.

Reassessment storage contains relationship/provenance metadata only. It does not
copy:

- answers;
- scores;
- points;
- percentages;
- correctness;
- rubric values;
- standards evidence bodies;
- feedback;
- producer artifacts.

## Producer neutrality

`meridian.reassessment` and `meridian.reassessment_storage` import no producer
package. They operate on generic `AttemptObservationReference`, public #30
resolution/state, `ModuleWorkRef`, and Meridian-owned records.

No ScoreForm, Quillan, Concord, Portia, or Vitrine runtime dependency is added.

## Compatibility

Issue #31 retains:

```text
Python >=3.11
pds-core>=0.6,<0.7
```

The later grouping-signal adoption issue remains responsible for raising the Core
minimum.

## Native-value mapping boundary

Issue #31 deliberately does not interpret producer-native values. Issue #32 now
implements that separate policy layer in `meridian.proficiency_mapping` and
`meridian.proficiency_mapping_storage`.

It can answer:

```text
which exact selected attempts still contribute?
which were explicitly replaced?
which are explicitly grouped for later combination?
what explicit recency order applies?
```

It does not answer:

```text
what does a producer-native value mean on a Meridian proficiency scale?
how should a combination be calculated?
what is the student's proficiency?
```

Issue #32 maps one exact producer-native value through one exact teacher-defined
profile/scale revision while preserving unmapped, unsupported, and native-state
outcomes. It still does not associate that mapped value with a standard or
calculate student proficiency; issue #34 owns the next calculation boundary.

```text
reassessment != native-value mapping
native-value mapping != standards evidence association
```
