# Attempt-selection policy and decisions

## Purpose

Issue #30 adds Meridian's canonical v0.2 attempt-selection layer after explicit
Grade Item membership (#28) and canonical evidence eligibility (#29).

It answers one bounded question:

```text
For this Grade Item/work/student and one exact immutable projection snapshot,
which explicit producer-native attempt observation(s), if any, were selected
from the exact currently eligible candidate set?
```

The boundary is:

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
proficiency calculation
```

Attempt selection preserves all producer evidence. It does not edit, delete,
renumber, rank, replace, average, or otherwise reinterpret producer attempts.

## Applicability is explicit

Attempt selection is not a mandatory wrapper around every producer.

A publication is attempt-selectable only when its exact Core Publication Record
advertises `multiple_attempts` and the authorized Meridian projection exposes a
safe explicit attempt boundary. Current released behavior is therefore:

```text
ScoreForm v0.10.0 -> applicable when projected attempt identity is valid
Quillan v0.9.0   -> not_applicable
Concord v0.2.0   -> not_applicable
```

Quillan submissions/reviews and Concord Scores are not renamed `attempt 1`.
Multiple numbers, timestamps, standards, score records, or publication revisions
never create attempt identity by inference.

`derive_attempt_candidates(...)` distinguishes:

```text
applicable
not_applicable
unsupported_attempt_shape
membership_stale
source_unverifiable
```

A producer that advertises `multiple_attempts` but cannot provide a safe generic
attempt identity fails closed as `unsupported_attempt_shape`; it is not silently
reclassified as a single-attempt producer.

## Exact attempt identity

`AttemptProjectionReference` binds one exact immutable projection snapshot:

```text
work: Core ModuleWorkRef
publication_id
cache_key
snapshot_digest
```

`AttemptObservationReference` adds:

```text
student_id
AttemptTargetReference
AttemptNativeIdentity
```

The target must be the explicit producer target kind `attempt`, either on an
attempt-level evidence item or as a child item's exact `parent_target`.

The native identity preserves the exact producer-native
`NativeReference(kind="attempt", ...)`. At least one of `identifier` or
`sequence` is required. Meridian does not assign semantic meaning to an opaque
identifier. ScoreForm v0.10.0 uses its native positive `attempt_number` as the
reference sequence.

The same producer-native attempt in a different Publication Record, cache key, or
snapshot digest is a different exact `AttemptObservationReference`.

## Grouping projected evidence into attempts

Candidate derivation receives an already authorized immutable projection
snapshot. For one exact student it:

1. checks the publication's explicit `multiple_attempts` capability;
2. inspects only the generic Meridian evidence projection;
3. resolves the currently selected #29 eligibility decision for each exact item;
4. admits only sources whose #29 current resolution has
   `operative_included == true`;
5. locates the explicit attempt target/parent target;
6. locates exactly one native `attempt` reference;
7. rejects contradictory target/native attempt relationships; and
8. groups exact eligible evidence under the resulting attempt observation.

The helper never opens producer-native files and never imports ScoreForm,
Quillan, or Concord.

Candidate ordering is deterministic presentation/provenance order. A native
sequence may be used to make ScoreForm candidates stable in ascending order, but
order is not academic preference.

```text
candidate order -X-> selected attempt
higher sequence -X-> preferred attempt
later timestamp -X-> preferred attempt
higher score -X-> preferred attempt
```

## Exact #29 eligibility basis

Each `AttemptCandidate` contains an `AttemptObservationReference` plus one or more
`AttemptEligibilityBasis` values.

Each basis records:

```text
EvidenceSourceReference
eligibility_revision
eligibility_decision_sha256
```

This is intentionally exact. A later eligibility decision does not mutate an old
attempt-selection decision. If eligibility changes, current-use resolution
re-derives the candidate basis and reports the old decision as stale.

Only #29 states with `operative_included == true` can form candidates. Current
#29 semantics therefore allow an explicitly included superseded source while
blocking withdrawn, pending, unsupported, excluded, stale-membership, and
unverifiable sources.

Issue #30 does not reimplement Core source-lifecycle rules.

## Evidence values are not selection inputs

Candidate records do not copy:

- points or percentages;
- correctness;
- answer choices;
- rubric/rating values;
- feedback text;
- standards evidence bodies; or
- producer artifacts.

Candidate derivation does not inspect evidence value magnitude. Typed producer
states such as `NativeStateValue("blank")` or `NativeStateValue("ambiguous")`
remain untouched in the immutable projection snapshot.

In particular:

```text
blank != 0
ambiguous != 0
missing != 0
unsupported != 0
```

Attempt selection performs no scoring.

## Explicit versioned policy

`AttemptSelectionPolicy` is a stable policy family with immutable revisions.
The logical identity is:

```text
class_id
grade_item_id
work
policy_id
```

Version 1 intentionally supports only:

```text
selection_basis = "explicit"
```

There is no built-in `latest`, `highest_score`, `first`, `most_recent`, or
percentage-ranking policy.

Each revision records:

```text
policy_revision
supersedes_revision
minimum_selected
maximum_selected
actor
rationale
revised_at
```

`minimum_selected` and `maximum_selected` constrain explicit cardinality. This
can represent:

```text
0..0      select none
0..1      zero or one
1..1      exactly one
1..3      one through three
0..null   any finite explicit subset
```

Cardinality constrains a teacher-controlled choice; it does not rank candidates.

Policy revision 1 uses `supersedes_revision = null`. Later revisions are
contiguous. The pure transition validator performs no I/O.

## Explicit policy selection

Writing a newer policy revision never activates it.

Each policy family has a separate `current.json` pointer bound to exact revision
bytes by SHA-256. Selection uses compare-and-swap against the caller's expected
current revision. Historical policy revisions may be explicitly reselected.

Never infer active policy from:

```text
highest revision
latest revised_at
mtime
directory order
```

## Student attempt-selection decisions

`AttemptSelectionDecision` is one immutable student-scoped decision. Its logical
history is:

```text
class_id
grade_item_id
work
student_id
```

Each decision revision binds:

```text
exact #28 membership revision + SHA-256
exact selected policy revision + SHA-256
exact AttemptProjectionReference
complete AttemptCandidate snapshot
selected_attempts
actor
rationale
decided_at
```

`selected_attempts` is an ordered duplicate-free tuple of exact candidate attempt
identities. Every selected attempt must exist in `candidates`.

An empty selection is explicit state:

```text
selected_attempts = ()
```

It is not the same as no attempt-selection decision, no evidence, missing work,
or zero.

A single selection does not mean newest, best, official, or replacement.
A multiple selection does not mean average, combine, weight, or reassess.

## Decision history and current selection

Decision revision 1 uses `supersedes_revision = null`; later revisions are
contiguous and preserve the same class/Grade Item/work/student logical identity.
A later revision may bind a changed candidate snapshot, policy, membership basis,
selection, actor, or rationale while retaining complete earlier history.

Writing a new decision revision does not make it current.

Each student history has an independent `current.json` pointer. Explicit current
selection is compare-and-swap protected and may deliberately reselect an older
revision only when its dependencies are still valid.

```text
highest decision revision -X-> current decision
latest decided_at -X-> current decision
```

## Canonical storage

Issue #30 stores state beneath the existing #28 Grade Item/work membership
relationship:

```text
classes/<class_id>/modules/meridian/grade_items/<grade_item_id>/
  memberships/<producer_module_id>/<work_id>/
    current.json
    revisions/
    evidence_eligibility/
    attempt_selection/
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

`subject_key` is a deterministic lowercase SHA-256 of the canonical
class/Grade Item/work/student scope. It is a path key, not a replacement student
identity. The immutable decision itself retains exact `student_id`.

Policy/decision revision bytes are canonical UTF-8 JSON with one LF, immutable
SHA-256 sidecars, bounded reads, contiguous history, exact replay, collision
rejection, and per-history write locks.

The #28 membership root permits only the new real `attempt_selection/`
directory; #28 does not interpret its contents.

## Current-use resolution and stale decisions

`resolve_current_attempt_selection(...)` combines the explicit selected decision
with current authoritative dependencies without mutating state.

It distinguishes at least:

```text
not_applicable
no_decision
selected_none
selected
policy_stale
membership_stale
eligibility_stale
candidate_set_stale
source_unverifiable
unsupported_attempt_shape
```

A selected decision is operative only when:

- its exact membership revision/digest is still the explicit current included
  membership;
- its exact policy revision/digest is still explicitly current;
- the authorized projection snapshot still matches the decision source;
- candidate attempt identities still match; and
- each candidate's exact #29 eligibility revision/digest still matches.

If the attempt identities are unchanged but an eligibility basis changes, the
resolver returns `eligibility_stale`. If attempts are added/removed or the exact
snapshot changes, it returns `candidate_set_stale`.

No stale decision is rewritten. No replacement decision is created implicitly.

## Reassessment boundary

Issue #30 deliberately stops before #31.

It does not encode:

```text
replaces
replaced_by
combine
average
recency
highest
retained_prior
```

A ScoreForm correction is a later producer-native attempt and may appear as
another candidate. #30 does not assume that the later number replaces the older
attempt. Core publication supersession likewise remains source lifecycle rather
than attempt preference.

Issue #31 owns reassessment/replacement/combination/retained-history semantics.

## Authorization and privacy

Candidate derivation and current-use resolution require an
`AuthorizedProjectionSnapshot`. Knowing a publication ID, cache key, digest,
student ID, or attempt identity is not authorization to open evidence.

Attempt-selection storage contains identity/provenance metadata only. It does not
become a second student evidence store.

The runtime model/storage modules import no producer package and create no global
registry, background task, or filesystem state on import.

## Compatibility

Issue #30 retains:

```text
Python >=3.11
pds-core>=0.6,<0.7
```

The later grouping-signal adoption issue remains responsible for raising the Core
minimum to 0.6.1.

## Explicit non-goals

Issue #30 does not implement:

- automatic highest/latest/first attempt selection;
- score ranking or percentage normalization;
- automatic eligibility;
- reassessment/replacement/combination/recency policy (#31);
- native-value mapping;
- proficiency scales;
- standards evidence aggregation;
- proficiency calculation;
- conventional/hybrid Grade calculation;
- grouping-signal derivation/export;
- reports or SIS synchronization;
- mutation of producer attempts;
- mutation of projection snapshots; or
- mutation of #29 eligibility history.

The resulting explicit sequence is:

```text
membership != evidence eligibility
eligibility != attempt selection
attempt selection != reassessment
```
