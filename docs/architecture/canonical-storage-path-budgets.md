# Canonical storage path budgets

Issue #102 establishes Meridian's first-use canonical filesystem contract before
any real teacher workspace depends on the development-era layout.

The central rule is:

```text
logical identifier != filesystem component
```

and the workspace-ownership rule is:

```text
Core-owned workspace identity != Meridian-owned storage key
```

Core continues to own the workspace root, `classes/<class_id>`, registered work,
Academic Period calendars, standards, rosters, publications, and other Core
state. Once a path enters `classes/<class_id>/modules/meridian`, Meridian owns
the serialization of its variable descendants and must keep them explicitly
bounded.

## Canonical opaque keys

`meridian.storage_path_keys.storage_path_key()` derives deterministic,
namespace-separated SHA-256 keys from canonical semantic identity parts.

The current key shape is:

```text
mk_<64 lowercase hexadecimal characters>
```

The exact opaque-key maximum is therefore **67 characters**.

The canonical helper also defines explicit leaf budgets:

```text
<key>.json         <= 72 characters
<key>.json.sha256  <= 79 characters
```

Revision-number leaves such as `1.json`, `1.json.sha256`, `current.json`, and
`.write.lock` are smaller fixed forms.

Semantic input length does not change the opaque-key length. Two identities with
a shared long prefix remain distinct because the complete structured identity is
hashed; Meridian does not truncate the semantic prefix.

## Identity remains authoritative in records

The opaque key is infrastructure identity only. Full logical values remain in
canonical structured records, including Grade Item IDs, work references, student
IDs, policy IDs, scale/profile IDs, ReportingDefinition IDs, ReportingSnapshot
IDs, and Export Profile IDs.

A loader derives the same key directly from semantic identity and opens the exact
canonical location. Normal lookup therefore does not require scanning every
stored record to recover an object's identity.

Collection-listing operations may enumerate their collection, but exact lookup
remains deterministic:

```text
semantic identity -> bounded path key -> exact canonical path
```

## Bounded canonical families

Issue #102 applies the contract across Meridian-owned Grade Item, membership,
attempt/reassessment, evidence, proficiency, Grade-policy, Grade-result,
reporting, export, and related policy/result storage.

Representative first-use forms include compact namespace literals plus bounded
keys, for example:

```text
.../modules/meridian/gi/<key>/<revision>.json
.../modules/meridian/gm/<key>/<revision>.json
.../modules/meridian/gp/<key>/<revision>.json
.../modules/meridian/prof/s/<key>/<revision>.json
.../modules/meridian/prof/p/<key>/<revision>.json
.../modules/meridian/ap/r/<key>/<revision>.json
.../modules/meridian/rs/<key>/current.json
```

Already-bounded digest identities remain bounded rather than being re-keyed
without a defect.

## Integrity and authority are unchanged

Path shortening does not weaken storage authority. Existing contracts remain:

- immutable revisions are create-only where required;
- current selection is explicit rather than inferred from history;
- SHA-256 sidecars authenticate exact canonical bytes;
- `relative_path` must equal the canonical path reconstructed from identity;
- path/model identity mismatches fail closed;
- containment and symlink protections remain in force;
- temporary publication never turns a semantic identifier back into an
  unbounded filename.

Teacher-selected external export destinations remain a separate boundary and are
not rewritten into opaque internal paths.

## Windows and deep-path qualification

Windows long-path support is defense in depth, not Meridian's storage contract.
Correctness does not depend on changing:

```text
HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled
```

The Issue #102 installed acceptance runs the candidate Meridian wheel with exact
released **Core 0.6.4** in the existing prepared Core-only qualification matrix.
It creates a controlled deep workspace, persists deliberately long semantic
identities, reloads them, exercises current selectors, checks all observed
Meridian-owned components against the documented bounds, verifies fresh-process
key determinism, and confirms that the observed Windows path-policy value is
unchanged.

ScoreForm, Quillan, and Concord are intentionally absent from this dedicated
storage qualification. Existing installed matrices continue to cover their
adapter combinations separately.

## Core dependency relationship

Issue #102 changes Meridian's exact development/installed qualification baseline
to authenticated Core 0.6.4. It does **not** use a Core 0.6.4-only runtime API,
so the compatible package dependency remains:

```text
pds-core>=0.6.3,<0.7
```

The exact qualification target and the declared compatible runtime floor serve
different purposes.

## Pre-deployment correction

This change is deliberately **pre-deployment**. Meridian had not yet created a
real teacher workspace, so Issue #102 establishes one correct first-use layout.

There is **no migration** layer, no dual old/new reader, no automatic rename
tooling, and no compatibility promise for development-only path strings that
preceded this contract. Development fixtures were updated directly to the new
canonical layout before it became user data.
