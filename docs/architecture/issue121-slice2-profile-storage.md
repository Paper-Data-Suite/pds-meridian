# Meridian #121 — Slice 2: durable teacher profile and attribution provider

**Umbrella:** [#120](https://github.com/Paper-Data-Suite/pds-meridian/issues/120)
**Issue:** [#121](https://github.com/Paper-Data-Suite/pds-meridian/issues/121)
**Branch:** `121-persistent-teacher-identity-preferences-classroom-context`
**Depends on:** Slice 1 (`e882ede915f7361022d3ae43128e6cd4999aebe5`)

## Scope

Add `meridian.teacher_profile` without modifying existing academic workflows. This is a **teacher self-declared attribution profile**, not login, identity proof, publication-read permission, an academic decision, or a global canonical teacher ID service. Existing Core does not yet expose a released shared teacher-profile contract. Until Core provides one, this module is a Meridian-local, explicitly labeled compatibility adapter. Other PDS apps must not read its private schema as a promised universal contract.

### Public service surface

- `TeacherProfileStore.load()` reads the local profile without creating files.
- `create(display_name, actor_id=None)` is explicit first-use setup. If no actor ID is supplied, the action creates a stable opaque `teacher-<uuid4>` ID; it does not derive identity from OS, Git, path, or account metadata.
- `update_display_name(expected, name)` preserves actor ID and increments revision.
- `replace_identity(expected, display_name=..., actor_id=..., confirmed=True)` changes the actor ID for **future** records only. A new ID can also be generated at this explicitly confirmed action.
- `reset(expected, confirmed=True)` removes only the local profile, never academic records.
- `TeacherIdentityProvider.resolve()` returns both `actor_id` and `display_name`, or gives an actionable not-configured error. `temporary_override(...)` returns a validated identity for **one intended action** and does not modify local configuration.
- Mutations require an exact `StoredTeacherProfile` fingerprint/revision for concurrent-update protection. `create()` rejects existing profiles. The provider is injectable; no global singleton is introduced.

### File and privacy contract

The profile is stored beneath `pds_core.workspace.get_workspace_config_path().parent / 'meridian'`, outside the canonical academic workspace, in `teacher-profile-v1.json`. It does **not** edit Core's `config.json`, so it cannot discard the currently configured `workspace_root`.

Only `schema_version`, `revision`, `actor_id`, `display_name`, `created_at`, and `updated_at` are persisted. There are **no** class, student, protected-evidence, publication, grant, grade, or workspace-path fields. The schema is strict, versioned, bounded to 4 KiB, rejects duplicate keys, and requires normalized safe names and Core-valid actor identifiers. Profile directory/file permissions are owner-only on POSIX. Windows uses a per-user application configuration directory and refuses recognized reparse points; installed Windows security qualification remains part of Slice 6.

Writes use an exclusive interprocess lock, a same-directory temporary file, flush/fsync, atomic replacement, and optimistic compare-and-swap. Reads refuse symlinks/reparse points, nonregular files, unsafe POSIX permissions, corrupt JSON, unrecognized schemas, and oversized files. Unsafe existing content is never silently overwritten, reset, or migrated. The lock file may remain after normal process exit; it is not a stale lock because operating-system byte-range/flock locks are released when the process closes. Profile reset does not delete the lock file.

### Actor provenance and downstream contract

The stored actor ID and display name are deliberately **different** fields. Later guided and legacy menus should consume them through dependency-injected provider code, preserving the exact actor representation required by each canonical service and showing a human-readable teacher label. No historical academic record is altered by editing/resetting the profile. The selected actor profile is not an authorization grant; existing `review_evidence` and `teacher_reporting` checks remain authoritative.

### Scope boundary / next slices

- **Slice 3:** separately persist preferred class/year and optional work hints with workspace-scoped, Core-validated, non-authoritative resumption. Never serialize `TeacherSessionContext` or a selected student.
- **Slice 4:** add first-use setup, active teacher label, Settings/Advanced edit/reset and one-action temporary override to Meridian's teacher menu.
- **Slice 5:** inject the provider into all known guided and legacy actor-prompt sites; reduce the 20-prompt baseline to zero and update the raw-ID quarantine only for real removals. Do not change write-versus-current-selection semantics (owned by #122).
- **Slice 6:** full installed-wheel, Windows user-config/reparse, rollback, launch→setup→quit→restart→author and direct-CLI compatibility acceptance.

## Focused acceptance

`tests/test_issue121_slice2_teacher_profile.py` verifies read-only absence; durable create/relaunch; display-only edit; explicit actor change and reset; fingerprint conflicts; competing writers; corrupt, unsupported, oversized and duplicate-key JSON; Unicode/ID validation; symlink/reparse guard where supported; FIFO guard on POSIX; POSIX private permissions; clock correctness; override non-persistence; and no academic/authorization content in the file.

This is a storage/provider slice, **not** a claim that routine teacher prompts have been removed. Slice 4/5 integration is required before the classroom usability target is met.
