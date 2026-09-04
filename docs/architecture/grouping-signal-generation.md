# Deterministic grouping-signal generation

Issue #38 implements Meridian's deterministic internal derivation boundary for
temporary contextual grouping bands. It consumes one exact Core roster, one
explicitly selected #37 grouping-signal derivation policy, and the exact
selected/current #35 Academic Period proficiency interpretation for each roster
student. It produces one immutable, content-addressed Meridian derivation
snapshot.

The governing separation remains:

```text
Academic Period proficiency
!=
grouping-signal policy
!=
grouping-signal derivation
!=
Core grouping_signal_set_v1 export
!=
GroupPlan
```

Issue #38 therefore **does assign contextual bands inside Meridian**, but it does
not preview or approve those bands, create a Core grouping signal, export CSV,
launch Concord, choose a grouping strategy, choose target group size/count, or
create Group/GroupMembership state.

## Runtime modules

Issue #38 adds four runtime modules:

```text
meridian.grouping_signal_derivation
meridian.grouping_signal_derivation_storage
meridian.grouping_signal_generation
meridian.grouping_signal_generation_basis
```

`meridian.grouping_signal_derivation` owns the pure immutable domain contract,
canonical JSON, privacy-minimal roster membership basis, deterministic
student-level derivation, calculation fingerprint, content-addressed derivation
identity, and exact derivation reference.

`meridian.grouping_signal_derivation_storage` owns immutable class-local
persistence, SHA-256 sidecars, exact replay, collision detection, bounded reads,
locking/atomic writes, deterministic listing, and path/symlink/integrity
hardening.

`meridian.grouping_signal_generation_basis` reconstructs the **current** #35
aggregation-input basis from explicit current Grade Item, membership, and #34
selection state. It does not recalculate proficiency.

`meridian.grouping_signal_generation` orchestrates selected #37 policy
resolution, Core roster loading, selected #35 result resolution, exact #35
freshness assessment, structured blockers, pure derivation, and successful
persistence.

None of these modules imports ScoreForm, Quillan, Concord, Portia, or Vitrine.
The production #38 runtime also does not import Core grouping-signal
model/storage/CSV/diagnostic APIs.

## Exact generation request

The workspace-level entry point is:

```python
generate_grouping_signal_derivation(
    workspace_root,
    class_id,
    policy_id,
)
```

A generation request resolves exactly:

```text
class_id
+ explicitly selected #37 policy revision/digest
+ exact current Core roster membership
+ current #35 aggregation-input basis
+ explicitly selected #35 result per roster student, when present
```

No `latest`, newest-file, highest-revision, newest-timestamp, filesystem-mtime,
or first-match heuristic is used.

If the requested #37 policy has no explicit current selection, generation returns
the structured class-level blocker:

```text
no_selected_policy
```

It does not silently select a policy revision.

## Exact Core roster membership basis

Core's current roster is the membership authority for one new derivation.
Meridian stores that basis as `GroupingSignalRosterBasis`, containing only:

```text
class_id
student_ids
membership_sha256
```

`student_ids` are canonicalized into lexical order. `membership_sha256` binds the
class ID plus that exact ordered membership set.

The derivation does **not** copy roster names, email addresses, guardian data,
period display text, arbitrary extra columns, or the roster source path.

A membership change changes the roster basis and therefore the calculation
fingerprint. A display-name-only change does not.

Every successful derivation contains exactly one
`GroupingSignalStudentDerivation` for every student in this exact roster basis.
There are no duplicates, omissions, or out-of-roster student records.

## Current #35 basis reconstruction

A persisted #35 result embeds the exact inputs that were current when that result
was calculated. Those historical embedded inputs cannot be treated as the
current basis for a new #38 request.

`meridian.grouping_signal_generation_basis` therefore rebuilds current #35
inputs from current explicit Meridian interpretation state:

```text
current Grade Item selection
    + active standards-proficiency-capable Grade Item purpose
    + current selected included membership decisions
    + exact current Grade Item revision/digest match
    + exact selected Core Academic Period/calendar revision
    + current selected #34 result, when one is compatible
```

Grade Items are discovered deterministically and candidates are ordered by stable
`grade_item_id`.

A Grade Item that no longer has any selected included membership relevant to the
target Academic Period scope is absent from the rebuilt current candidate set.
That changes the #35 input digest and can make an older selected #35 result stale.

If one Grade Item retains mixed in-scope and out-of-scope selected memberships,
the whole exact basis remains visible so #35 can preserve its existing
`period_scope_mismatch` semantics. Issue #38 does not invent a new period-scope
rule.

A selected #34 result that cannot form a valid current #35 candidate under the
exact current Grade Item/membership/standard/scale basis is treated as unavailable
for the rebuilt #35 input candidate. #38 does not rewrite or reinterpret that
historical #34 result.

## Exact selected #35 result eligibility

For each roster student, issue #38 loads only the explicitly selected #35 result
for the exact class, Academic Period, student, and standard family selected by
the #37 policy.

A selected result must match the #37 academic basis exactly:

```text
class
Academic Period + calendar revision
standard
#35 aggregation-policy reference + digest
proficiency-scale reference + digest
```

A valid selected result that does not match this basis produces:

```text
selected_result_mismatch
```

Meridian does not scan #35 history for a more convenient substitute.

Absence of an explicitly selected result remains:

```text
missing_result
```

It is never interpreted as zero, Band 1, lowest proficiency, failure, or absence
from the roster.

## Freshness reuses #35 semantics

Issue #38 defines no second freshness model. It calls the existing pure #35
freshness diagnostic with:

```text
selected persisted #35 result
+ rebuilt current #35 inputs
+ exact selected #35 policy
+ exact target proficiency scale
+ exact Academic Period Calendar revision
+ current #35 algorithm version
```

The existing #35 reasons remain authoritative:

```text
inputs_changed
policy_changed
scale_changed
calendar_changed
algorithm_changed
```

A stale selected result produces:

```text
stale_result
```

with the exact ordered #35 staleness reasons and exact selected result reference.

Stale is not missing, insufficient, or low. A stale result cannot be admitted
through the selected #37 policy's `missing_result_handling`, and #38 does not
silently recalculate #35.

The lower-level orchestration entry point requires an explicit current #35 input
basis. If a selected result is supplied without that basis, it produces:

```text
current_basis_unavailable
```

rather than pretending historical embedded inputs are current.

## Missing and insufficient policy

The selected #37 policy independently defines:

```text
missing_result_handling
insufficient_result_handling
```

with the v1 values:

```text
noncontributing
blocking
```

For `noncontributing`, the roster student remains represented in the rich
derivation but receives no scale position or contextual band.

For `blocking`, generation does not persist a successful derivation snapshot and
returns a structured blocker.

Missing and insufficient remain different:

```text
missing
!=
insufficient_evidence
!=
calculated low proficiency
```

An insufficient selected #35 result preserves its exact result reference.
A missing result has no fabricated source-result reference.

## Pure deterministic band mapping

For a calculated eligible/current #35 result, the transformation is exactly:

```text
proficiency_level_id
    -> exact position on exact #37-bound proficiency scale
    -> explicit #37 band definition containing that position
    -> contextual ordinal band
```

No raw points, percentages, native scores, evidence counts, dates, student
identity, or class distribution participate in the band decision.

The #37 rule:

```text
same_level_same_band
```

is absolute. Two students with the same exact source proficiency level map to the
same contextual band.

Student ID is used only for canonical ordering and identity. It is never a
tie-breaker for academic band assignment.

## No class-relative derivation

Schema v1 does not implement percentile bands, quantiles, tertiles, quartiles,
equal-population partitioning, rank, median split, curved thresholds, or another
class-relative transformation.

Adding or removing a classmate can change the exact roster membership basis and
therefore the derivation identity, but it cannot change another student's band
when that student's own exact result and the selected policy remain unchanged.

## Rich per-student provenance

`GroupingSignalStudentDerivation` stores only the bounded provenance necessary to
explain one student's place in the internal derivation:

```text
student_id
source_state
disposition
source_result
proficiency_level_id
scale_position
band
```

Calculated contributors preserve the exact #35 result reference, exact level,
scale position, and band. Missing noncontributors have no fabricated result
reference, level, position, or band. Insufficient noncontributors preserve their
exact #35 result reference but have no level, position, or band.

## Immutable derivation snapshot

`GroupingSignalDerivationSnapshot` binds:

```text
schema_version
record_type
derivation_id
class_id
algorithm_version
policy_reference
roster_basis
dimension_id
band_count
student_derivations
calculation_fingerprint
```

The v1 constants are:

```text
GROUPING_SIGNAL_DERIVATION_SCHEMA_VERSION = "1"
GROUPING_SIGNAL_DERIVATION_RECORD_TYPE = "meridian_grouping_signal_derivation"
GROUPING_SIGNAL_DERIVATION_ALGORITHM_VERSION =
    "academic_period_proficiency_band_v1"
```

The exact #37 policy is represented by a digest-bound
`GroupingSignalDerivationPolicyReference`, not a bare policy ID.

The snapshot contains no Core `signal_set_id`, no Concord strategy, no target
group size/count, and no GroupPlan/Group/GroupMembership state.

## Deterministic calculation fingerprint

`grouping_signal_derivation_calculation_fingerprint(...)` SHA-256 binds the
canonical semantic generation state:

```text
algorithm version
exact #37 policy reference/digest
exact Core roster membership basis
exact ordered per-student source resolution and derived state
```

The fingerprint is independent of wall-clock time, PID, filesystem mtime,
directory enumeration order, Python hash randomization, UUID/randomness, display
names, and platform path style.

## Content-addressed identity

Derivation identity is:

```text
derivation_id = "gsd_" + calculation_fingerprint
```

using the full lowercase SHA-256 fingerprint.

This is intentionally different from #37 policy history. A derivation is a
deterministic calculation output, not teacher-selected mutable current state.
Therefore #38 has no derivation revision family and no `current`, `latest`, or
`active` pointer or alias.

Same semantic inputs produce the same derivation identity. Material policy,
roster membership, selected-result, source-state, proficiency-level, or band
changes produce a different identity.

## No wall-clock field in canonical derivation

The canonical #38 derivation deliberately contains no `generated_at` field.
Wall-clock time would make identical semantic inputs serialize differently and
weaken content-addressed replay.

Later #39 review/acceptance or #40 export workflow records may carry their own
timestamps. Core `GroupingSignalSet.created_at` belongs to #40 export, not #38.

## Canonical serialization

Derivation JSON uses canonical UTF-8, sorted object keys, two-space indentation,
non-ASCII preservation, nonfinite-number rejection, and a terminal newline.
Unknown, missing, duplicate, noncanonical, or invalid fields fail closed.

Roster student IDs and student derivations use lexical student-ID ordering.

`GroupingSignalDerivationReference` binds:

```text
class_id
derivation_id
derivation_sha256
```

`derivation_sha256` is the SHA-256 of exact canonical derivation bytes and is
distinct from the semantic `calculation_fingerprint`.

## Immutable content-addressed storage

Storage is class-local Meridian state:

```text
classes/<class_id>/modules/meridian/grouping_signal_derivations/
  <derivation_id>.json
  <derivation_id>.json.sha256
```

There is no revision subtree and no `current.json`.

Write semantics are:

```text
new identity + exact bytes -> created
same identity + same exact bytes -> existing
same identity + different bytes -> conflict/integrity failure
```

Loads verify canonical path, model identity, canonical bytes, SHA-256 sidecar,
and requested reference digest. Listing is deterministic and fully validates
visible collection entries.

Storage rejects unsafe/traversal identities, symlinks, unexpected entries,
incomplete JSON/SHA pairs, malformed sidecars, noncanonical JSON, CRLF-altered
bytes, tampering, oversized files, lock conflicts, and path/model disagreement.

Historical derivations remain exactly loadable after later roster, policy, or
proficiency changes. Historical existence does not imply current applicability.

## Structured generation blockers

Normal teacher/workflow-resolvable inability to generate is returned as a
deterministic `GroupingSignalGenerationResult(status="blocked", ...)`.

The v1 blocker vocabulary is:

```text
no_selected_policy
missing_result
insufficient_evidence
stale_result
selected_result_mismatch
current_basis_unavailable
```

Blockers are ordered deterministically. Storage corruption, malformed canonical
state, unsafe paths, and other integrity failures remain exceptions rather than
ordinary academic blockers.

## Zero-contributor derivations

A selected #37 policy can legitimately make every roster student
`noncontributing`.

If every source state is valid under the policy and none is blocking, #38 may
persist a valid Meridian derivation with zero contributing bands. It does not
invent Band 0 or Band 1 merely to satisfy a later interchange contract.

Core `grouping_signal_set_v1` requires a declared dimension to have at least one
student-band entry. Therefore an all-noncontributing #38 derivation is not
Core-exportable. Issue #39 must expose that condition, and issue #40 must refuse
Core export rather than mutating the derivation.

## Privacy boundary

The rich internal #38 state may contain exact student ID, exact #35 result
reference/digest, source state, proficiency level ID, ordinal scale position,
contextual band, exact #37 policy reference, and exact roster membership
identity.

It must not copy student names, email/guardian/contact data, raw evidence, raw
points or percentages, essay text, question responses, rubric prose/details,
attempt narratives, behavior/support records, protected-trait data, Concord
strategy, or group membership.

## Fairness and semantic boundary

A #38 band is temporary, contextual, ordinal, policy-specific,
dimension-specific, and Academic-Period-specific. It is not ability,
intelligence, potential, readiness, disability/support category, behavior
classification, Grade, percentage, universal proficiency label, permanent
learner trait, or group placement.

Meridian does not define canonical labels such as low/medium/high. The numeric
band is meaningful only with the exact selected policy and dimension context.

## No academic feedback loop

Grouping derivation remains downstream planning data. Neither the band nor later
group membership may be fed back as evidence used to calculate the same
proficiency judgment.

```text
Meridian proficiency
    -> #38 grouping derivation
    -> later grouping workflow
    -X-> evidence used to recalculate the same proficiency
```

## No Core signal construction in #38

Production #38 runtime intentionally does not import or call:

```text
pds_core.grouping_signals
pds_core.grouping_signal_storage
pds_core.grouping_signal_csv
pds_core.grouping_signal_diagnostics
```

Tests may use Core signal storage read APIs only to prove that no signal was
written.

Future #40 export can project only class/dimension/band-count, contributing
student-ID/band pairs, and minimal module-generated source provenance. The future
Core source can bind the exact #38 `derivation_id` and exact canonical-byte
`derivation_sha256`.

Three identities remain distinct:

```text
#38 calculation_fingerprint
#38 derivation_sha256
future Core signal-record digest
```

## No Concord planning in #38

Issue #38 does not import Concord and does not define `similar_signal`,
`mixed_signal`, target group size/count, missing-signal placement, manual group
changes, plan approval, Group, GroupMembership, or GroupPlan.

A contextual band is not a group assignment.

## Read-only imports

Importing any of:

```text
meridian.grouping_signal_derivation
meridian.grouping_signal_derivation_storage
meridian.grouping_signal_generation
meridian.grouping_signal_generation_basis
```

must not create files/directories, inspect a workspace, change environment
variables, configure logging, discover producer packages, or write a derivation.

## Acceptance coverage

Focused and integration coverage proves pure deterministic mapping, exact
`same_level_same_band`, no class-relative mapping, canonical roster membership
identity, missing/insufficient policy, content-addressed replay, immutable
storage, hardening, explicit #37 selection, exact Core roster use, current #35
input-basis reconstruction, exact selected #35 result resolution, mismatch and
freshness blockers, real persisted Grade Item -> membership -> #34 -> #35 ->
#37 -> #38 flow, deterministic replay, and no Core grouping signal creation.

An isolated installed-wheel smoke additionally proves this calculated path
using only exact Core v0.6.3 plus the candidate Meridian wheel, with
ScoreForm, Quillan, and Concord absent from the environment.

## Issue handoff

At the completion of issue #38:

```text
#35 Academic Period proficiency aggregation — implemented
#36 Core neutral grouping-signal contract — implemented
#37 teacher-controlled grouping-signal derivation policy — implemented
#38 deterministic grouping-signal generation — implemented
#39 grouping-signal preview and diagnostics — implemented
#40 Core/CSV grouping-signal export — implemented
#41 teacher eligibility, proficiency, and planning-export workflows — implemented
#42 proficiency and planning-export explanation/trace views — next
```

Issue #39 now consumes one exact `GroupingSignalDerivationReference` and
implements immutable preview/diagnostics, read-only currentness, deliberate
teacher review, explicit review selection, live acceptance revalidation, and a
teacher-facing projection. See
[Grouping-signal preview, diagnostics, and teacher review](grouping-signal-preview-diagnostics.md).

Issue #40 consumes an explicitly selected, still-applicable
`accepted_for_export` review and owns the conversion into Core
`grouping_signal_set_v1`, optional `grouping_signal_csv_v1`, immutable Core
exchange persistence, and any explicit handoff to Concord.

No automatic preview, acceptance, export, `latest` alias, or downstream planning
is introduced by issue #38 or #39.
