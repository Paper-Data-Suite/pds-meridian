# Evidence eligibility decisions

## Purpose

Issue #29 adds Meridian's canonical v0.2 evidence-eligibility decision layer.
It answers one narrow question:

```text
For this exact projected evidence item,
in this exact Grade Item/work context,
what is its eligibility state for later academic interpretation?
```

The layer preserves the architecture adopted in ADR 0004:

```text
publication validity
!=
Grade Item membership
!=
evidence eligibility
!=
attempt selection
!=
reassessment
!=
proficiency calculation
```

Eligibility is explicit historical state. A valid publication, supported
projection, number, rubric level, standard reference, or included Grade Item
membership does not silently make evidence eligible.

## v0.1 annotation versus canonical v0.2 state

`meridian.evidence.EvidenceItem` already carries an immutable
`EvidenceEligibility` value with `unevaluated`, `eligible`, and `ineligible`
states. That value is part of an immutable projection snapshot and remains
projection-time annotation/compatibility state.

Issue #29 does not mutate that field and does not rewrite projection snapshots.
The canonical v0.2 state is separate:

```text
immutable ProjectionSnapshot
        |
        +--> exact EvidenceItem
        |
        v
immutable EvidenceEligibilityDecision revisions
        |
        v
explicit current.json selection
```

An old projection annotation is not automatically migrated. No canonical #29
record means no canonical eligibility decision.

## Exact source identity

`EvidenceSourceReference` binds one evidence item to one exact immutable
projection snapshot:

```text
work: Core ModuleWorkRef
publication_id
cache_key
snapshot_digest
item_id
```

`item_id` alone is not immutable source identity. Adapters may intentionally
preserve one logical item ID across later publication/projection snapshots. The
exact source is therefore:

```text
Publication Record
+
projection cache identity
+
exact snapshot digest
+
item_id within that snapshot
```

The storage `source_key` is the lowercase SHA-256 of the canonical serialized
`EvidenceSourceReference`. It is a deterministic path key, not a second logical
identity.

Decision records do not duplicate student answers, points, rubric values,
standard lists, native provenance, or complete `EvidenceItem` payloads.

## Authorization boundary

Student-bearing evidence remains protected by the existing projection-cache
read authorization boundary.

Before an exact source may be used to ground or select a canonical eligibility
decision, callers provide an `AuthorizedProjectionSnapshot`. Meridian verifies:

- exact `cache_key`;
- exact `snapshot_digest`;
- exact Core `publication_id`;
- exact Core `ModuleWorkRef`;
- exactly one matching `item_id`;
- exact evidence provenance/projection identity.

Possession of a cache key, digest, path, or item ID is not authorization.
Canonical eligibility storage is not a bypass around evidence-read policy.

## Grade Item and membership scope

Eligibility is contextual. The same exact projected evidence source may be
handled differently in two Grade Items.

One logical eligibility history is scoped by:

```text
class_id
grade_item_id
EvidenceSourceReference
```

Each decision also binds the exact #28 membership revision and SHA-256 used for
review:

```text
membership_revision
membership_revision_sha256
```

The referenced membership must exist, verify, be `included`, and identify the
same exact work as the evidence source. Before an eligibility revision becomes
current, that exact membership revision must still be the explicitly selected
membership. A stale membership selection fails with a conflict rather than
silently substituting a newer revision.

A later membership revision never rewrites historical eligibility decisions.

## Decision record

`EvidenceEligibilityDecision` is immutable and revisioned. Version 1 persists:

```text
schema_version
record_type
class_id
grade_item_id
source
membership_revision
membership_revision_sha256
eligibility_revision
supersedes_revision
disposition
actor
policy
reason_codes
rationale
source_state
decided_at
```

The canonical record type is:

```text
meridian_evidence_eligibility_decision
```

Revision 1 uses `supersedes_revision = null`. Later revisions are contiguous and
explicitly supersede the preceding eligibility revision. Supersession is
history, not deletion.

The pure transition validator requires the same class, Grade Item, and exact
`EvidenceSourceReference`, plus contiguous revision numbers and nondecreasing
decision time. Membership revision, policy, actor, rationale, disposition, and
observed source lifecycle may change through a new immutable decision revision.

## Six semantic dispositions

ADR 0004 requires at least these distinctions:

```text
included
excluded
pending
unsupported
superseded
withdrawn
```

They are deliberately not collapsed to a boolean or to the older projection
annotation's `eligible` / `ineligible` vocabulary.

### `included`

The exact evidence source may proceed to later Meridian interpretation stages in
this Grade Item context.

It does not mean an attempt was selected, a reassessment replaced earlier work,
a native value was mapped, proficiency was calculated, or a Grade was produced.

`included` requires an exact policy reference and teacher/policy authority. It
carries no exclusion reason codes. A decision cannot be authored as `included`
when the observed Core source is already withdrawn.

A superseded-but-not-withdrawn source can still be explicitly included under
policy; source lifecycle does not silently become academic preference.

### `excluded`

The exact source was explicitly reviewed and is not eligible for downstream
academic interpretation in this Grade Item.

`excluded` requires an exact policy, teacher/policy authority, and at least one
reason code. Exclusion does not mutate producer evidence, withdraw a Core
publication, select a replacement, assign zero, or delete history.

### `pending`

Eligibility is unresolved and requires later review/policy resolution.

`pending` is not exclusion. It requires policy context and at least one reason
code. Time passing does not automatically convert pending evidence to included
or excluded.

### `unsupported`

The exact projected evidence item is valid, but the current eligibility
policy/support layer cannot responsibly classify/use its semantics.

`unsupported` is not adapter unavailability, an invalid publication, a blank
response, a numeric zero, or a future proficiency-mapping failure. A #29
unsupported decision exists only after a valid exact `EvidenceItem` exists.

It requires an exact policy/support reference and at least one reason code.

### `superseded`

This is a system/source-lifecycle disposition, not a teacher exclusion.

It is valid only when canonical Core publication-series state proves the source
Publication Record is historical/superseded. It requires system authority, no
policy-causation claim, an observed successor/head identity, and reason code(s).

Attempt number, score, timestamp, standard identity, and filesystem ordering do
not establish source supersession.

### `withdrawn`

This is a system/source-lifecycle disposition grounded in an exact Core
`PublicationWithdrawal`.

A teacher cannot fabricate withdrawal, and an eligibility policy cannot
reactivate withdrawn source evidence.

The hard current-use rule is:

```text
Core source withdrawn
    -> selected included decision remains historical
    -> operative inclusion is blocked
```

The old decision/pointer is not rewritten automatically. Current source state is
resolved separately so audit history remains intact.

## Actor and policy provenance

`EvidenceDecisionActor` distinguishes:

```text
teacher
policy
system
```

and carries one opaque deployment-provided `actor_id`. It records authorship; it
does not prove authorization or create an institutional identity registry.
Meridian never derives the actor from the OS username, filesystem owner,
environment variables, Git identity, or student identity.

Academic dispositions use an exact `EvidenceEligibilityPolicyReference`:

```text
policy_id
policy_version
```

Source-lifecycle `superseded` and `withdrawn` records use system authority and
must not claim that a teacher policy caused Core lifecycle state.

Issue #29 records policy provenance only. It does not implement a universal
eligibility rule language or engine.

## Reasons and rationale

Non-`included` dispositions require ordered, duplicate-free, contract-safe
`reason_codes`. `included` intentionally has no exclusion reason codes.

An optional bounded `rationale` may capture concise teacher-facing context.
Rationale is not a place to duplicate student work, scores, medical information,
accommodations, or other unnecessary sensitive data.

## Source-state observation

Each decision preserves the Core publication lifecycle observed when the
revision was authored:

```text
current
superseded
withdrawn
withdrawn_superseded
```

The observation also records exact head/successor identity where applicable and
`withdrawn_at` when Core withdrawal exists.

This is decision-time provenance. Current authoritative lifecycle is reloaded
separately when a revision is selected or resolved for use.

Thus:

```text
historical source observation
!=
current Core source lifecycle
```

A later Core change never mutates the stored decision.

## Canonical storage

Eligibility histories live beneath the #28 membership relationship:

```text
classes/
  <class_id>/
    modules/
      meridian/
        grade_items/
          <grade_item_id>/
            memberships/
              <producer_module_id>/
                <work_id>/
                  current.json                 # #28 membership selector
                  revisions/                   # #28 membership history
                  evidence_eligibility/
                    <source_key>/
                      current.json
                      revisions/
                        1.json
                        1.json.sha256
                        2.json
                        2.json.sha256
```

`source_key` is deterministic SHA-256 over the canonical exact source reference.
It is never derived from a title, timestamp, random UUID, score, or directory
order.

The narrow #28 compatibility change permits only a real
`evidence_eligibility/` child directory. #28 does not interpret its contents;
#29 validates that subtree independently.

## Immutable revisions and digest binding

Eligibility revision JSON is canonical UTF-8 with sorted object keys,
deterministic formatting, one trailing LF, closed schemas, duplicate-key
rejection, no nonfinite constants, and canonical UTC timestamps.

Every immutable revision has an exact lowercase SHA-256 sidecar. Load validates:

- bounded regular-file reads;
- canonical directory chain;
- sidecar syntax (including CRLF rejection);
- exact digest;
- canonical JSON;
- path/model identity;
- exact source key and revision identity.

Exact retry semantics are:

```text
same identity + same exact bytes -> existing
same identity + different bytes -> conflict
```

## Explicit current selection

Each Grade Item/evidence-source relationship has a separate `current.json`
pointer containing identity and digest only:

```text
schema_version
record_type
class_id
grade_item_id
source_key
eligibility_revision
decision_sha256
```

The pointer does not duplicate disposition, actor, policy, reasons, rationale,
membership data, or source evidence.

Creating a higher eligibility revision never selects it. Selection uses explicit
compare-and-swap via `expected_current_eligibility_revision`.

The following never select current eligibility:

```text
highest revision
latest decided_at
filesystem mtime
directory order
newest publication
```

Historical revisions may be explicitly reselected when current dependencies
permit it.

## Current-use resolution

`resolve_current_evidence_eligibility` is read-only. It combines:

```text
explicitly selected eligibility revision
+
explicitly selected #28 membership
+
authorized exact evidence source
+
current Core publication lifecycle
```

without mutating any state.

It distinguishes at least:

```text
no_decision
included
included_source_superseded
included_source_withdrawn
excluded
pending
unsupported
superseded
withdrawn
membership_stale
source_unverifiable
```

A selected decision is therefore not automatically usable evidence.
`operative_included` is true only when the selected decision is `included`, the
exact membership remains selected/included, and Core source state is not
withdrawn.

## Attempt and reassessment boundary

Issue #29 never applies:

```text
latest wins
highest wins
first wins
best score wins
```

An evidence source may be `included` and still not be selected later.
Issue #30 owns explicit attempt selection.

Likewise, eligibility does not represent replacement, reassessment, combination,
recency weighting, or retained-history policy. Issue #31 owns those
relationships.

Producer/Core publication supersession remains a lifecycle fact and does not
silently become academic replacement.

## Native-value and proficiency boundary

Eligibility preserves producer-native meaning. It does not:

- normalize points to percentages;
- map rubric numbers;
- convert booleans to mastery;
- interpret same-looking producer numbers as Meridian proficiency levels;
- convert non-score states to zero;
- calculate standards proficiency.

Later mapping/scale/calculation issues own those semantics.

## Non-student evidence

An exact source may reference a valid `EvidenceItem` with `subject = null`.
Issue #29 does not synthesize a student identity or copy Group evidence to Group
members.

This specifically prevents a circular path such as:

```text
Group result
    -> inferred individual evidence
    -> individual proficiency
    -> grouping signal
```

## Filesystem and concurrency safety

Storage validates identifiers and containment, rejects path traversal and
Windows absolute/drive injection, rejects symlinked canonical components and
nonregular files, bounds reads, rejects unexpected visible entries, and uses one
write lock per exact eligibility relationship.

Current-pointer publication uses a temporary file plus atomic `os.replace` and
filesystem synchronization where supported.

## Producer neutrality and compatibility

The eligibility model/storage layer imports no ScoreForm, Quillan, Concord,
Portia, or Vitrine runtime package. Exact source semantics are reached through
Core identities and Meridian's producer-neutral immutable projection contracts.

Issue #29 retains:

```text
Python >=3.11
pds-core>=0.6,<0.7
```

The later grouping-signal issue remains responsible for raising the Core minimum
to 0.6.1.

## Explicit non-goals

Issue #29 does not implement:

- automatic eligibility from publication availability;
- a universal eligibility policy engine;
- mutation/migration of v0.1 `EvidenceEligibility` annotations;
- attempt selection (#30);
- reassessment/replacement (#31);
- native-value mapping;
- Meridian proficiency scales;
- standards-evidence aggregation;
- proficiency calculation;
- Academic Period proficiency aggregation;
- conventional/hybrid Grade calculation;
- grouping-signal derivation/export;
- reports or SIS synchronization;
- producer or Core record mutation.

The resulting sequence remains explicit:

```text
projection != canonical eligibility decision
membership != evidence eligibility
eligibility != attempt selection
```
