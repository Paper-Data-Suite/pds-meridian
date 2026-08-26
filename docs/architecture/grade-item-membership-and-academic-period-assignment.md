# Grade Item membership and Academic Period assignment

## Status

Implemented for Meridian v0.2 development by issue #28.

This document extends the Grade Item foundation from issue #27 and specializes
ADR 0004's rule that Grade Item membership and Academic Period assignment are
explicit Meridian academic-interpretation decisions.

## Purpose

A Grade Item definition answers what the teacher's logical academic item is.
Membership answers a different question:

```text
Which exact Core-registered work participates in this Grade Item,
and to which exact Core Academic Period is that participation assigned?
```

The runtime boundary remains:

```text
Grade Item definition
!=
Grade Item membership
!=
evidence eligibility
!=
attempt selection
!=
proficiency calculation
```

A producer publication can exist without membership. A membership can exist
before any publication is available. Publication discovery is therefore never a
membership mutation trigger.

## Runtime modules

The implementation is split between:

```text
meridian.grade_item_memberships
meridian.grade_item_membership_storage
```

`meridian.grade_item_memberships` owns immutable models, pure transition
validation, and canonical JSON conversion.

`meridian.grade_item_membership_storage` owns exact Core-backed dependency
validation, immutable canonical persistence, explicit current selection, and
bounded deterministic queries.

Neither module imports ScoreForm, Quillan, Concord, or another producer package.
The producer-neutral boundary is Core `ModuleWorkRef` plus the exact Academic
Work Registration revision prepared by issue #27's `GradeItemWorkReference`.

## Logical membership identity

One logical relationship is identified by:

```text
class_id
grade_item_id
work.module_id
work.work_id
```

The following are revision context, not logical relationship identity:

```text
grade_item_revision
registration_revision
calendar_revision
membership_revision
```

This permits one relationship to preserve history while the teacher reviews a
new Grade Item revision, a new Core Academic Work Registration revision, or a
new Academic Period Calendar revision.

A Core work may be an explicit member of more than one Grade Item. Meridian does
not impose a universal one-work-to-one-Grade-Item rule.

## Academic Period assignment

`GradeItemAcademicPeriodAssignment` stores exactly:

```text
period: Core AcademicPeriodRef
calendar_revision: positive integer
```

The Core reference contributes:

```text
school_year
period_id
```

Historical period meaning is therefore bound by:

```text
school_year + calendar_revision + period_id
```

Meridian does not copy Core's period label, type, dates, hierarchy, sequence, or
lifecycle into a second mutable registry. When descriptive period state is
needed, the exact historical Core calendar revision is reloaded.

An assignment names one period only. It does not automatically imply membership
in a parent, child, sibling, or every period containing a date.

The following are not period-assignment rules:

```text
publication timestamp
registration timestamp
completion date
due date
current date
currently active period
```

A future date-based policy would need to be explicit and versioned rather than
being hidden in #28 storage behavior.

## Membership decision contract

`GradeItemMembershipDecision` records one immutable membership decision.

Version 1 uses:

```text
schema_version = "1"
record_type = "meridian_grade_item_membership"
```

The exact decision fields are:

```text
schema_version
record_type
class_id
grade_item_id
grade_item_revision
grade_item_revision_sha256
work_reference
membership_revision
supersedes_revision
decision
academic_period
actor_id
rationale
decided_at
```

### Grade Item basis

`grade_item_revision` and `grade_item_revision_sha256` bind the exact immutable
Grade Item revision reviewed by the decision. The SHA-256 is the digest already
verified by issue #27 storage.

A later Grade Item current-selection change does not rewrite this basis.

### Work basis

`work_reference` reuses `GradeItemWorkReference` from issue #27:

```text
work: Core ModuleWorkRef
registration_revision: positive integer
```

The registration revision is exact provenance. The current Core registration is
not substituted during reload or selection.

### Decision state

The closed version-1 values are:

```text
included
excluded
```

`included` requires one exact Academic Period assignment.

`excluded` requires:

```text
academic_period = null
```

Absence of persisted membership state remains a third, distinct condition:

```text
no decision != excluded
```

This distinction matters to later attention and evidence-policy workflows. A
missing decision cannot silently become either inclusion or exclusion.

### Actor and rationale

`actor_id` is a required bounded opaque deployment-provided identifier. It is
historical attribution, not an identity registry or authorization mechanism.
Meridian does not derive it from an operating-system username or environment
variable.

`rationale` is optional bounded text. It is part of the immutable decision when
provided. The schema does not require a rationale for every routine inclusion or
exclusion.

`decided_at` is timezone-aware and canonicalized to UTC. It records when the
decision was authored; it never determines Academic Period membership.

## Membership revision history

Membership revisions are positive integers beginning at 1.

Revision 1 uses:

```text
supersedes_revision = null
```

Every later revision `N` uses:

```text
supersedes_revision = N - 1
```

Pure transition validation requires the same class, Grade Item, and logical
`ModuleWorkRef`, contiguous membership revisions, explicit supersession, and
nondecreasing decision time.

A later revision may change:

- the exact Grade Item revision/digest;
- the exact Academic Work Registration revision;
- included/excluded state;
- the exact Academic Period assignment;
- actor attribution;
- rationale.

Those changes never edit an earlier decision in place.

## Core-backed dependency validation

Before new membership state is persisted and again before it becomes the
explicit selected decision, Meridian validates the exact authoritative
dependencies.

### Core class

Core class metadata must exist and match `class_id`. Its canonical school year is
the authority used for Academic Period compatibility.

### Grade Item

The exact Grade Item revision must load successfully through issue #27 storage,
and its verified SHA-256 must equal `grade_item_revision_sha256`.

A new `included` decision cannot target an `archived` Grade Item revision.
Historical membership records are not modified if a different Grade Item
revision is archived later.

### Academic Work Registration

The exact `ModuleWorkRef` and `registration_revision` are loaded through Core's
public Academic Work Registration storage API.

A new `included` decision cannot target a registration revision whose lifecycle
is `cancelled`.

A newer Core registration revision or a changed Core current pointer does not
rewrite an existing Meridian decision.

### Academic Period Calendar

For an included decision, Meridian reloads exactly:

```text
assignment.period.school_year
assignment.calendar_revision
assignment.period.period_id
```

The class school year, period reference school year, and calendar school year
must agree. The exact period must exist in that exact calendar revision.

`planned`, `active`, and `closed` periods are valid explicit targets.
A new included decision cannot target a `cancelled` period.

A later Core calendar revision does not reinterpret historical membership.

## Canonical storage

Membership is canonical Meridian state beneath the Grade Item that owns the
relationship:

```text
classes/
  <class_id>/
    modules/
      meridian/
        grade_items/
          <grade_item_id>/
            current.json
            revisions/
              ...
            memberships/
              <producer_module_id>/
                <work_id>/
                  current.json
                  revisions/
                    1.json
                    1.json.sha256
                    2.json
                    2.json.sha256
```

Issue #28 extends issue #27's Grade Item root validator only enough to permit a
real `memberships/` directory. Membership storage validates everything below
that directory independently and fail-closed.

Core registration storage, Core Academic Period storage, producer work
directories, Publication Records, and projection caches are never modified.

## Immutable persistence and integrity

Each membership revision is canonical UTF-8 JSON with:

- sorted keys;
- two-space indentation;
- exact closed schemas;
- duplicate-key rejection;
- missing/unknown-key rejection;
- no nonfinite JSON constants;
- one trailing LF;
- deterministic Core reference conversion;
- canonical UTC timestamps.

Each revision has a lowercase SHA-256 sidecar over the exact JSON bytes:

```text
<revision>.json.sha256
```

Load validates bounded file size, regular-file status, safe directory chains,
sidecar syntax, SHA-256, canonical JSON, path/model identity, logical work
identity, and revision identity.

Exact retries of an existing revision with the same canonical bytes return an
`existing` disposition. The same revision identity with different bytes is a
conflict and is never overwritten.

## Explicit current selection

Each Grade Item/work relationship has a separate `current.json` selector with:

```text
schema_version
record_type
class_id
grade_item_id
work
membership_revision
decision_sha256
```

The pointer contains identity and digest only; it does not duplicate decision,
period, actor, or rationale fields.

Creating a higher membership revision does not select it. Selection uses
compare-and-swap semantics through `expected_current_membership_revision`.

An older historical revision may be explicitly reselected.

The following never select current membership:

```text
highest membership revision
newest decided_at
filesystem mtime
directory enumeration order
```

Thus:

```text
highest membership revision -X-> current membership
```

## Deterministic queries

The storage layer can deterministically:

- list logical work relationships for a Grade Item;
- list one relationship's contiguous revision history;
- load an exact historical revision;
- load the explicit current selection;
- distinguish no current decision from selected `excluded`;
- return selected `included` relationships in module/work order.

Queries use persisted membership state only. They do not discover publications,
producer manifests, score-like evidence, or adapter capability.

## No publication-driven membership

The forbidden transition is explicit:

```text
publication appears -X-> Grade Item membership
```

Similarly, publication compatibility, numeric evidence, rubric evidence, an
active producer work, or a newly discovered result does not create or select a
membership decision.

Issue #29 now implements the separate canonical evidence-eligibility decision
family over exact authorized projection sources after work membership exists.

## Filesystem safety

All canonical path identities are validated. Storage rejects traversal,
absolute-path injection, Windows drive/root injection, unsafe identifiers,
symlinked canonical components, symlinked files, nonregular files, unexpected
visible entries, malformed sidecars, malformed pointers, and path/model identity
mismatches.

Membership reads are bounded. Membership records are configuration, not a place
to store evidence payloads or arbitrary notes.

## Privacy boundary

Membership decisions contain class/work configuration and teacher attribution.
They must not contain:

- student IDs or names;
- student evidence;
- proficiency values;
- Grades;
- attempt selections;
- grouping bands;
- GroupMembership state;
- reports.

The optional rationale is not intended for student-specific notes.
Student-bearing academic interpretation remains in later record families with
separate authorization and privacy boundaries.

## Dependency and producer boundary

Issue #28 remains compatible with:

```text
pds-core>=0.6,<0.7
```

It uses only public Core APIs present in the Core v0.6.0 baseline. The later
neutral grouping-signal issue owns the minimum-Core change to 0.6.1.

No producer package is required to import or use membership support.

## Explicit issue boundary

Issue #28 implements registered-work membership and exact Academic Period
assignment only. It does not implement:

- publication-driven membership discovery;
- evidence eligibility (implemented by #29);
- attempt selection;
- reassessment/replacement;
- proficiency scales or native-value mapping;
- standards evidence aggregation;
- proficiency calculation;
- Academic Period proficiency aggregation;
- conventional/hybrid Grade calculation;
- weighting execution;
- grouping-signal derivation/export;
- public teacher workflow/CLI commands;
- reports or SIS synchronization.

The resulting sequence remains:

```text
publication ingestion != Grade Item creation
Grade Item creation != membership
membership != evidence eligibility
```


## Next interpretation boundary

Issue #29 adds canonical eligibility records without changing this membership
contract. Exact eligibility history binds one included membership revision and
one exact projection snapshot/item source. Membership remains work-level state;
it does not become student evidence state.

See [Evidence eligibility decisions](evidence-eligibility-decisions.md).
