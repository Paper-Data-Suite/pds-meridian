# Grade Items and canonical storage

## Status

Implemented for Meridian v0.2 development by issue #27.

This document describes Meridian's first executable academic-interpretation
record family. It specializes ADR 0004 without changing Core or producer
contracts.

## Purpose

A Grade Item is Meridian-owned academic configuration. It gives the teacher a
stable logical item that later evidence-membership, proficiency, and Grade-policy
records can reference.

A Grade Item is not a Core Academic Work Registration, producer assignment,
Publication Record, evidence decision, proficiency result, conventional Grade,
report, or official school-system record.

The core identity boundary is:

```text
stable grade_item_id
        |
        +-- immutable revision 1
        +-- immutable revision 2
        +-- ...
        |
        v
explicit current.json selection
```

`latest` is never inferred from timestamps, directory order, filesystem mtime,
or the highest revision number.

## Runtime modules

The implementation is split between:

```text
meridian.grade_items
meridian.grade_item_storage
```

`meridian.grade_items` is pure model/serialization code.
`meridian.grade_item_storage` owns canonical local persistence and explicit
revision selection.

Neither module imports ScoreForm, Quillan, Concord, or another producer package.

## Grade Item revision contract

The version-1 record uses:

```text
schema_version = "1"
record_type = "meridian_grade_item"
```

Its exact fields are:

```text
schema_version
record_type
class_id
grade_item_id
grade_item_revision
supersedes_revision
title
purpose
status
weighting
created_at
revised_at
```

### Stable identity

`class_id` is a Core class identity. `grade_item_id` is a Meridian logical
identity validated with Core's path-safe identifier rules. Neither title nor a
producer work ID is Grade Item identity.

A title change therefore creates a new immutable revision without changing
`grade_item_id`.

### Revision lineage

Revision numbers are positive integers beginning at 1. Revision 1 has:

```text
supersedes_revision = null
```

Every later revision `N` has:

```text
supersedes_revision = N - 1
```

Canonical persisted history is contiguous. Creating revision 3 before revision 2
is a conflict rather than an implicit repair.

`created_at` is constant across the logical item. `revised_at` records creation
of one exact revision. Both are timezone-aware and canonicalized to UTC. Revision
1 uses `created_at == revised_at`; later revisions cannot move backward in time.

### Purpose

The closed version-1 purpose values are:

```text
standards_proficiency
conventional_grade
standards_and_conventional
reporting_only
```

Purpose describes intended academic participation only. It does not create work
membership, evidence eligibility, Academic Period membership, or a calculated
Grade.

### Lifecycle

The closed version-1 status values are:

```text
active
archived
```

Archiving is historical lifecycle state. There is no destructive deleted state.
Changing status creates another immutable revision.

## Reserved weighting metadata

A Grade Item may optionally preserve future conventional/hybrid Grade-policy
metadata:

```text
category_id: str | null
relative_weight: Decimal | null
```

At least one field must be present when a weighting object exists.

`category_id` is a Meridian-local future policy reference. Issue #27 does not
create a category registry.

`relative_weight` is an exact positive finite `Decimal`. It serializes as
canonical decimal text, not binary floating point. For example:

```text
Decimal("1.5000") -> "1.5"
```

This metadata is stored but never executed in v0.2 Grade Item storage. No weight
normalization, percentage conversion, category calculation, missing-work rule,
or conventional Grade calculation occurs here.

## Exact registered-work revision reference

`GradeItemWorkReference` is a reusable value for later membership records:

```text
work: Core ModuleWorkRef
registration_revision: positive integer
```

It deliberately does not live as an authoritative collection inside
`GradeItemRevision`.

The boundary is:

```text
GradeItemRevision
        |
        | referenced by later state
        v
GradeItemMembershipDecision   # issue #28
        |
        +--> ModuleWorkRef
        +--> exact registration_revision
        +--> Academic Period decision
```

This preserves ADR 0004's distinction between a Grade Item definition and the
teacher decision about which registered work participates in it.

Creating a Grade Item never discovers or includes Core registrations or
publications automatically.

## Canonical JSON

Grade Item revisions use closed-schema deterministic JSON:

- UTF-8;
- sorted keys;
- two-space indentation;
- one trailing newline;
- no duplicate object keys;
- no unknown or missing fields;
- no nonfinite JSON numbers;
- exact canonical decimal text;
- canonical UTC timestamps.

A persisted file that decodes to semantically valid data but is not in canonical
encoding is an integrity failure. Readers do not rewrite it automatically.

## Canonical workspace layout

Grade Items are canonical Meridian state, not disposable cache state.

For class `english10_p2` and item `unit1_assessment`:

```text
classes/
  english10_p2/
    modules/
      meridian/
        grade_items/
          unit1_assessment/
            current.json
            revisions/
              1.json
              1.json.sha256
              2.json
              2.json.sha256
```

The Core class directory must already exist before the first Grade Item revision
is written. Meridian may create its own descendants beneath that class, but it
does not create a synthetic Core class.

Producer work directories are never modified.

## Revision integrity

Each persisted revision has a lowercase SHA-256 sidecar over the exact canonical
JSON bytes:

```text
<revision>.json.sha256
```

A verified stored revision binds:

```text
class_id
grade_item_id
grade_item_revision
revision_sha256
exact canonical bytes
```

Load verifies the directory chain, regular-file status, byte bound, sidecar
format, digest, canonical JSON, and path/model identity.

Tampered JSON, a changed sidecar, a path/model disagreement, a symlink, a missing
pair member, a gap in revision history, or an unexpected canonical-storage entry
fails closed.

## Immutable writes and retries

Revision persistence never overwrites a historical revision.

An exact retry of the same revision identity with the same canonical bytes may
return `existing`. The same revision identity with different bytes is a
conflict.

Revision creation and current selection are separate operations. Persisting a
new highest revision does not select it.

## Explicit current selection

`current.json` is an operational selector, not another mutable copy of Grade Item
fields.

Its exact fields are:

```text
schema_version
record_type
class_id
grade_item_id
grade_item_revision
revision_sha256
```

The current record points to one already-persisted and integrity-verified
revision. Loading current state reopens that exact revision and verifies that the
pointer digest still matches.

Selection uses compare-and-swap behavior through an expected current revision.
A stale expectation fails rather than silently winning a race.

A teacher/application may explicitly select an older historical revision. That
changes only operational selection; it does not mutate revision history or any
historical calculation that previously referenced another revision.

If revisions exist but `current.json` does not, the result is no current
selection. The storage layer never chooses the highest revision automatically.

## Locking and durability

One `.write.lock` is scoped to the logical Grade Item. Revision creation and
pointer publication use that lock to prevent concurrent split state.

Immutable revision and digest files use exclusive creation. The mutable current
pointer is written through a temporary file and atomically replaced. Files are
flushed and `fsync` is attempted where the platform supports it.

Unexpected residual files fail closed rather than becoming invisible state.

## Path and read safety

Storage validates Core-compatible path-safe identifiers and keeps all paths
lexically beneath the supplied workspace root. Existing directory chains and
canonical files must not be symlinks.

Revision, pointer, and digest reads are finite. Grade Item configuration is not a
container for evidence, student lists, reports, or arbitrary binary data.

## Privacy boundary

A Grade Item revision contains class/item configuration only. It must not contain:

- student IDs or names;
- student evidence;
- proficiency values;
- Grades;
- attempt selections;
- grouping bands;
- GroupMembership state;
- report content.

Student-bearing decisions and calculations are later record families with their
own authorization boundaries.

## Core and producer authority

Core remains authoritative for class identity, `ModuleWorkRef`, Academic Work
Registration revisions, publications, standards, and Academic Periods.

Producer modules remain authoritative for their own work and native academic
records.

Meridian owns Grade Item identity, revisions, selection, and integrity metadata.
A persisted reference to Core or producer state is provenance/reference data, not
a copied source of truth.

## Explicit issue boundaries

Issue #27 does not implement:

- Grade Item membership or Academic Period assignment (#28);
- evidence eligibility;
- attempt selection;
- reassessment/replacement policy;
- proficiency scales or native mappings;
- standards evidence aggregation;
- proficiency calculation;
- conventional/hybrid Grade calculation;
- weighting execution;
- grouping-signal derivation or export;
- Grade Item teacher menus/CLI workflows;
- reporting or SIS synchronization.

The implemented boundary remains:

```text
publication ingestion != Grade Item creation
Grade Item creation != membership
membership != evidence eligibility
```
