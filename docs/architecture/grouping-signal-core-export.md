# Immutable Core/CSV grouping-signal export

Issue #40 implements the deliberate boundary from one explicitly selected,
still-applicable #39 `accepted_for_export` review into Core's released
`grouping_signal_set_v1`, with an optional Core-native
`grouping_signal_csv_v1` file.

```text
#38 immutable derivation
    -> #39 preview/diagnostics
    -> explicitly selected accepted review
    -> #40 final revalidation
    -> Core grouping_signal_set_v1
        -> immutable Meridian export receipt
        -> optional grouping_signal_csv_v1
```

## Eligibility and final revalidation

`meridian.grouping_signal_export_eligibility` requires an explicitly selected
review whose decision is `accepted_for_export`. The exact review, preview, and
derivation dependencies must verify and the #38 derivation must still be current.

Stable blockers include `no_selected_review`, `review_not_accepted`,
`review_stale`, `derivation_not_current`, and `review_selection_changed`.

Immediately before persistence, #40 reloads the selected review and requires the
same digest-bound revision, then reassesses live #38 currentness. A changed
selection or stale/blocked derivation prevents the Core write.

## Pure Core projection

`meridian.grouping_signal_export` constructs Core's actual `GroupingSignalSet`.
The caller supplies explicit `signal_set_id` and timezone-aware `created_at`.

Core provenance is:

```text
source.kind = module_generated
source.module_id = meridian
source.snapshot_id = derivation.derivation_id
source.snapshot_digest_algorithm = sha256
source.snapshot_digest = derivation.derivation_sha256
```

`source.snapshot_digest = derivation.derivation_sha256` is distinct from the
#38 calculation fingerprint, #39 preview/review digests, Core signal digest, and
CSV digest.

Exactly one #38 dimension is exported. Only contributors become Core
`student_id`/`dimension_id`/`band` entries. Missing and insufficient
noncontributors remain absent; no sentinel band is invented. Zero contributors
cannot satisfy Core v1 and therefore block export.

## Core diagnostics and persistence

Before persistence, #40 uses Core `diagnose_grouping_signal(...)` and requires
Core roster coverage and band counts to agree exactly with the accepted #39
preview. `class_mismatch`, `wrong_class_student`, and `unknown_student` are
blocking invariant failures. Core missing-student warnings must identify exactly
the reviewed noncontributors.

Persistence delegates to Core `write_grouping_signal(...)`:

```text
new identity + exact bytes -> created
same identity + exact bytes -> existing
same identity + different bytes -> conflict
```

No `current`, `latest`, or `active` alias is created.

## Immutable Meridian export receipt

`GroupingSignalExportReceipt` stores only:

```text
class_id
signal_set_id
created_at
exact #38 derivation reference
exact #39 preview reference
exact #39 review reference
core_contract = grouping_signal_set_v1
core_digest_algorithm = sha256
core_signal_digest
```

It does not copy student bands, names, proficiency values, raw evidence, or
diagnostic prose.

Storage is:

```text
classes/<class_id>/modules/meridian/grouping_signal_exports/
    <signal_set_id>.json
    <signal_set_id>.json.sha256
```

Receipt loads verify exact #38/#39 dependencies plus Core identity, source
binding, created_at, and digest.

Recovery semantics are:

```text
Core absent + receipt absent -> create both
Core exact + receipt absent -> create missing receipt
Core exact + receipt exact -> both existing
Core conflict -> fail closed
receipt exists + Core missing/different -> integrity failure
```

If Core succeeds but receipt persistence fails, #40 raises
`partial_core_write_success` with the exact Core identity/digest so an exact retry
can reconcile the receipt without changing Core state.

## Optional CSV

CSV is generated only from the exact stored Core signal whose receipt verifies.
Meridian calls Core's serializer/parser and requires
`representation_scope = complete_signal`, then requires exact runtime and
canonical JSON equality after round-trip.

File semantics are explicit and non-overwriting:

```text
destination absent -> created
destination exists with exact bytes -> existing
destination exists with different bytes -> conflict
```

CSV includes Core metadata plus `student_id,band`; it does not add display names
or richer academic details. CSV failure never removes or mutates Core/receipt
state.

## Privacy, fairness, and downstream boundary

Bands remain temporary contextual ordinal planning signals, not ability,
intelligence, potential, readiness, disability, behavior, Grade, percentage, or
permanent learner labels.

### No Concord dependency

Production #40 code does not import ScoreForm, Quillan, Concord, Portia, or
Vitrine. It does not launch Concord, select a grouping strategy, create or
approve a GroupPlan, or create Group/GroupMembership state.

The prohibited feedback path remains:

```text
proficiency -> #38 -> #39 -> #40 Core signal -> downstream planning
                                           -X-> proficiency evidence
```

## Installed acceptance

An isolated installed-wheel smoke uses released Core 0.6.3 plus the candidate
Meridian wheel only. It exercises #38 generation, #39 preview/review/selection,
#40 Core export, exact Core digest reload, immutable receipt, Core-native CSV
round-trip, and exact replay. Sibling PDS packages are absent.

## Issue handoff

```text
#38 deterministic grouping-signal generation — implemented
#39 grouping-signal preview and diagnostics — implemented
#40 Core/CSV grouping-signal export — implemented
#41 teacher eligibility, proficiency, and planning-export workflows — next
```
