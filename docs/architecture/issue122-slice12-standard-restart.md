# Issue #122 — Slice 12: Standards association restart recovery

## Scope

Teacher-facing **R. Review Interrupted Saves** can present `RESUME` only for a uniquely identifiable, previously persisted Standards association whose receipt, immutable revision, source authority, current Grade Item, included membership, current work registration, exact calendar, teacher attribution and CAS baseline remain valid. The action **does not** create immutable association revisions or silently replace another selected decision.

## Canonical identity discovery

`list_standard_evidence_association_identities` enumerates a bounded class-local association collection. It refuses unknown entries, directory links, invalid histories, excessive counts, digest mismatches and revision-1 key/identity mismatches. It decodes a verified canonical first revision; a receipt fingerprint alone cannot be used as a storage path or evidence authorization. Ambiguous or missing matches fail closed.

## Authority and recovery

`_RestartStandardPort` validates the exact opaque receipt fields, saved identity, unique canonical source + Standard pair, actor/profile currentness, an unextended immutable history, exact digest, included current membership, Grade Item revision, registration revision, calendar digest, and authoritative Standards resolution. Recovery conservatively blocks a Standard that is no longer active. It **reopens the existing snapshot with fresh publication authorization**. The selector also rechecks current authorization and Standards dependencies **under the association selection lock**, using an additive optional `authorized_snapshot` argument; existing manual selection callers are unchanged.

`inspect_restart_standard` only observes; after a separate exact `RESUME` confirmation, `resume_restart_standard` delegates to the shared selection-only orchestration kernel. In doubt, including no current evidence authority, a changed receipt, missing source, invalid scope, stale dependencies, or pointer divergence, the menu offers manual review without selecting anything. There is no rollback or duplicate write.

## Qualification

The distribution wheel allowlist includes the new runtime adapter. Focused tests cover no-write inspection, CAS selection, cancel, receipt changes, actor and source drift, standard invalidity, and menu safety. Windows Ruff, strict mypy and repo pytest gates are enforced by the Slice 12 runner before any commit/push. Final full-suite, wheel, Core compatibility and CI checks remain #122 closeout gates.
