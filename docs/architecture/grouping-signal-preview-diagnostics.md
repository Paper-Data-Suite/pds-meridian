# Grouping-signal preview, diagnostics, and teacher review

## Status

Meridian issue #39 implements the review boundary between deterministic private
grouping-signal derivation (#38) and explicit Core/CSV export (#40).

The implemented flow is:

```text
#38 immutable Meridian derivation
        |
        | exact GroupingSignalDerivationReference
        v
#39 deterministic immutable preview + diagnostics
        |
        | deliberate teacher review
        v
#39 explicitly selected review revision
        |
        | #40 only, after fresh revalidation
        v
Core grouping_signal_set_v1 / optional grouping_signal_csv_v1
```

The separation is deliberate:

```text
Academic Period proficiency
!= grouping-signal policy
!= grouping-signal derivation
!= Meridian derivation review
!= Core signal export
!= Concord GroupPlan approval
!= canonical Concord Group membership
```

Previewing does not export. Accepting does not export. Export happens only in #40.

## Exact preview input

One preview request consumes one explicit
`GroupingSignalDerivationReference`. Meridian does not infer a latest, newest,
only, or active derivation.

The exact #38 JSON/SHA-256 pair is loaded and verified before preview
construction. A preview request does not auto-generate or persist a replacement
#38 derivation.

The exact derivation binds the exact #37 policy revision. Preview generation
loads that revision and verifies its exact academic dependencies, including the
exact #35 policy and target proficiency-scale revision.

## Read-only currentness

`meridian.grouping_signal_currentness` reuses #38 generation semantics without
persisting a candidate derivation.

Conceptually:

```text
exact stored #38 derivation
        |
        +-- current #37 selection
        +-- current Core roster membership
        +-- current #35 basis/results
        |
        v
derive candidate #38 in memory only
        |
        v
compare candidate to stored derivation
```

Currentness states are:

```text
current
stale
blocked
```

A derivation is `current` only when the current in-memory #38 candidate resolves
to the same exact derivation reference.

Stable stale reasons include:

```text
algorithm_changed
policy_selection_changed
roster_membership_changed
source_result_reference_changed
source_proficiency_changed
source_resolution_changed
```

Blocked currentness preserves #38 generation blocker codes:

```text
no_selected_policy
missing_result
insufficient_evidence
stale_result
selected_result_mismatch
current_basis_unavailable
```

Display-name-only roster edits do not stale a derivation because #38 roster
identity is membership-based. Student membership changes do stale it.

Historical stale previews remain viewable. They cannot be accepted for export.

## Immutable preview snapshot

`meridian.grouping_signal_preview` defines:

```text
GroupingSignalPreviewSnapshot
GroupingSignalPreviewReference
GroupingSignalPreviewCurrentness
GroupingSignalPreviewCoverage
GroupingSignalPreviewStudentRow
GroupingSignalPreviewBandSummary
GroupingSignalPreviewTieGroup
GroupingSignalPreviewDiagnostic
```

A preview binds:

- exact #38 derivation reference, algorithm, and calculation fingerprint;
- exact #37 policy reference and title;
- exact Academic Period / school-year / calendar revision;
- exact standard ID;
- exact #35 policy reference;
- exact proficiency-scale reference;
- exact #38 roster basis;
- dimension and configured band definitions;
- tie, missing-result, and insufficient-result rules;
- deterministic student rows;
- coverage and distribution summaries;
- deterministic tie groups;
- currentness;
- ordered structured diagnostics; and
- a semantic preview fingerprint.

Preview identity is content-addressed:

```text
preview_id = "gsp_" + preview_fingerprint
```

The preview contains no wall clock, PID, random UUID, path, or display name.
Teacher-facing names therefore cannot affect preview identity.

Preview SHA-256 is the digest of exact canonical preview bytes and is separate
from both #38 calculation identity and future Core signal identity.

## Student rows

Calculated students preserve:

```text
student_id
source_state = calculated
disposition = contributing
exact #35 result reference
proficiency_level_id
scale_position
band
```

Missing-result students preserve:

```text
student_id
source_state = missing
disposition = noncontributing
no source-result reference
no proficiency level
no scale position
no band
```

Insufficient-evidence students preserve:

```text
student_id
source_state = insufficient_evidence
disposition = noncontributing
exact #35 result reference
no proficiency level
no scale position
no band
```

Rows are ordered lexically by `student_id`.

## Distribution

Preview coverage records:

```text
roster_student_count
contributing_student_count
noncontributing_student_count
missing_noncontributor_count
insufficient_noncontributor_count
occupied_band_count
empty_band_count
```

Each configured band has a deterministic student-ID list and count.

Meridian does not invent a statistical imbalance heuristic. Structural
conditions are diagnosed directly.

## Tie preservation

A tie group means multiple students have the same:

```text
proficiency_level_id
scale_position
resulting band
```

`same_level_same_band` remains exact. Student ID, roster order, randomization,
or target group count never split same-level ties.

## Diagnostics

Diagnostics have stable severities:

```text
informational
warning
blocking
```

Stable issue #39 diagnostic codes include:

```text
derivation_not_current
current_generation_blocked
zero_contributors
missing_noncontributors
insufficient_noncontributors
partial_coverage
empty_bands
single_occupied_band
```

`zero_contributors` is blocking for acceptance because Core
`grouping_signal_set_v1` requires at least one represented student band in a
declared dimension.

Missing and insufficient results remain valid noncontributors when #37 permits
them; they are warnings rather than fabricated bands.

Empty bands and single occupied band are structural warnings. Ties are explicit
structured preview data rather than a fairness defect.

Integrity corruption is an exception, not a diagnostic that a teacher can
acknowledge away.

Diagnostic identity is content-addressed over structured semantics:

```text
diagnostic_id = "gpd_" + sha256(structured diagnostic subject)
```

Diagnostic wording is not the acknowledgment key.

## Immutable preview storage

Preview storage is Meridian-owned class-local state:

```text
classes/<class_id>/modules/meridian/grouping_signal_previews/
    <preview_id>.json
    <preview_id>.json.sha256
```

There is no `current.json`, `latest.json`, or active preview selector.

Write semantics are:

```text
new identity + exact bytes -> created
same identity + same exact bytes -> existing
same identity + different bytes -> conflict/integrity failure
```

Storage verifies canonical bytes, exact digest sidecars, path containment,
bounded reads, canonical identity, symlink safety, complete pairs, and visible
collection shape.

## Teacher review model

`meridian.grouping_signal_review` defines immutable human workflow state:

```text
GroupingSignalReviewDecision
GroupingSignalReviewReference
GroupingSignalReviewActor
GroupingSignalReviewApplicability
```

Review decisions are:

```text
accepted_for_export
rejected
```

A review binds:

- class ID;
- exact #38 derivation reference;
- exact #39 preview reference;
- immutable review revision;
- explicit predecessor revision;
- decision;
- exact acknowledged warning diagnostic IDs;
- teacher actor ID; and
- timezone-aware `reviewed_at`.

The review does not copy student names, preview rows, scores, percentages,
evidence, or diagnostic prose.

## Acceptance rules

`accepted_for_export` is available only when:

1. the exact preview is valid;
2. the previewed derivation was current;
3. the exact derivation is re-assessed and remains current at review time;
4. the preview has no blocking diagnostics; and
5. every warning diagnostic ID is acknowledged exactly.

There is no wildcard acknowledgment and no future-warning acknowledgment.

A warning-free preview still requires a deliberate `accepted_for_export`
decision.

Blocking diagnostics cannot be acknowledged away.

A rejected review can be recorded even for a stale or blocked preview and does
not carry warning acknowledgments.

Acceptance is not export.

## Review revisions and explicit selection

Review storage is:

```text
classes/<class_id>/modules/meridian/grouping_signal_reviews/
    <derivation_id>/
        revisions/
            000001.json
            000001.json.sha256
            000002.json
            000002.json.sha256
            ...
        current.json
```

Review revisions are immutable and contiguous.

Writing a newer review does not select it and does not silently supersede the
selected review.

`current.json` is an explicit compare-and-swap selection pointer. Historical
reviews remain loadable.

Selected review applicability is read-only:

```text
current
stale
not_accepted
```

An immutable accepted review may later become stale because policy, roster,
source resolution, source proficiency, or algorithm state changes. Meridian does
not rewrite the old acceptance.

Issue #40 must revalidate the selected accepted review and live derivation state
again immediately before export.

## Teacher-facing projection

`meridian.grouping_signal_preview_projection` builds a noncanonical read-only
teacher view with sections for:

```text
Class
Academic Basis
Derivation Identity
Policy
Band Definitions
Coverage
Band Distribution
Student Assignments
Ties
Noncontributing Students
Diagnostics / Limitations
Review Status
Export Boundary
```

Current Core roster display names may be joined transiently through `student_id` for
teacher display. Names do not enter persisted #38/#39 canonical records and do
not alter any fingerprint or digest.

If a current roster name changes, the same persisted preview can display the new
name while preserving exact preview and derivation identity.

Neutral labels are used:

```text
Band 1
Band 2
...
```

Meridian does not define canonical `low`, `medium`, `high`, ability, intelligence,
potential, readiness, disability, behavior, Grade, percentage, permanent learner
category, or final group-assignment labels.

## Privacy boundary

Persisted #39 state uses only identifiers and provenance required to explain and
review the exact grouping derivation.

It does not persist:

- student names;
- email or guardian contact data;
- raw scores or percentages;
- responses, essays, rubric prose, or raw evidence;
- behavior/support records;
- protected traits;
- Concord strategy;
- Concord GroupPlan;
- Group or GroupMembership; or
- target group size/count.

## No academic feedback loop

Grouping preview and review remain downstream planning workflow state:

```text
proficiency
    -> #38 derivation
    -> #39 preview/review
    -> #40 export
    -X-> evidence used to recalculate the same proficiency
```

Neither review status nor downstream group membership becomes academic evidence.

## No Core or Concord write in #39

Issue #39 does not create a Core `GroupingSignalSet`, select a Core
`signal_set_id`, set Core `created_at`, write Core exchange storage, write CSV,
launch Concord, create a GroupPlan, approve a GroupPlan, or create canonical
Group/GroupMembership state.

The production #39 runtime has no ScoreForm, Quillan, Concord, Portia, or Vitrine
runtime dependency.

## Installed acceptance

Repository qualification includes an isolated installed-wheel smoke using:

```text
released pds-core 0.6.3
candidate pds-meridian wheel
```

The smoke deliberately leaves ScoreForm, Quillan, Concord, Portia, and Vitrine
absent. It exercises the real current #38 derivation path, immutable #39 preview,
exact warning acknowledgment, review revision, explicit review selection, and
teacher-facing projection while proving Core grouping-signal storage remains
empty.

## Issue handoff

At completion of #39:

```text
#35 Academic Period proficiency aggregation — implemented
#36 Core neutral grouping-signal contract — implemented
#37 teacher-controlled grouping-signal derivation policy — implemented
#38 deterministic grouping-signal generation — implemented
#39 grouping-signal preview and diagnostics — implemented
#40 Core/CSV export — next
```

Issue #40 alone owns projection into Core `grouping_signal_set_v1`, optional
`grouping_signal_csv_v1`, immutable Core exchange persistence, Core export-time
identity/timestamp fields, and any explicit downstream Concord handoff.
