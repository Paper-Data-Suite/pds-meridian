# Meridian #121 — Slice 3: persistent navigation preferences

- Parent: [#120](https://github.com/Paper-Data-Suite/pds-meridian/issues/120)
- Issue: [#121](https://github.com/Paper-Data-Suite/pds-meridian/issues/121)
- Branch: `121-persistent-teacher-identity-preferences-classroom-context`
- Baseline: Slice 2 at `5fae69036e60966b532de1a5168dc27c9f137e2b`

## Purpose and architecture

Implement a separate durable **teacher-local navigation hint**, without persisting academic authority or protected evidence. The stored file is `teacher-preferences-v1.json` beneath the same Meridian-specific user-configuration directory as Slice 2's `teacher-profile-v1.json`. It never modifies Core `config.json` or the academic workspace. This is a Meridian-local compatibility adapter, not a claimed Core-wide profile API.

Only the following fields are saved: schema version, revision, SHA-256 fingerprint of the resolved workspace location, selected school year, class ID, and optionally an exact Core `ModuleWorkRef` (module/class/work IDs). No student IDs/names, grades, publication IDs, evidence, authorizer, grant, path, token, or other protected state is stored.

The saved workspace fingerprint prevents a preference from one workspace being used in another. A changed workspace requires a **deliberate** replacement using the exact previous preference fingerprint; never silently migrate the old choice. Preference writes are explicitly requested by their caller after a user choice, not performed on launch or every menu keypress.

## Service interface

`TeacherNavigationPreferencesStore` offers:

- `load()`: read-only, no directory or file creation;
- `for_workspace(root)`: return the stored hint only for the same resolved workspace;
- `save_selection(root, school_year, class_id, work, expected)`: explicit save with optimistic compare-and-swap. A first save expects absence; subsequent saves require the complete previous stored reference. Clear the selected class/work by passing `None` explicitly. Switching work/class in the preference value requires coherent parent identity.

The implementation reuses Slice 2's guarded user-local directory, shared interprocess lock, bounded verified reads, file/link checks, and durable atomic-replacement pattern. Storage is strict schema v1 with duplicate-key rejection and Core identifier/year validation. Configuration files on POSIX retain restrictive permissions. Broken or incompatible files are not silently reset.

`validate_resume_hint(root, stored)` performs only Core-backed, read-only validation: workspace fingerprint, active school year, matching class metadata school year, exact current roster, and optional current Academic Work Registration. Stale work falls back to the validated class; a stale/missing class does not become a session selection. A missing active school year prevents automatic resumption; the teacher can choose a class normally.

`apply_verified_navigation(session, candidate)` makes a **deliberately invoked** navigation-only update to an empty process-local `TeacherSessionContext`. It never restores publication, Grade Item, student, eligibility, attempt, proficiency, reporting, or authorization context and never overwrites an existing active selection. Core must be rechecked by downstream operations regardless of this hint.

## Scope boundary

Slice 3 provides the persistence and safe-resume service. It does **not** yet add settings screens, startup UI, or automatic capture of ordinary menu selections; those are integrated in Slice 4 together with teacher identity setup/settings. Slice 5 removes repeated actor prompts, while Slice 6 qualifies real Windows/installed usage. This isolation lets storage and canonical-state checks be reviewed before teacher interactions change.

Neither this slice nor a saved preference supplies permission to open a protected ScoreForm, Quillan, or Concord publication. Existing authorization, work/roster currentness, academic period, and CAS rules remain mandatory.

## Focused acceptance

The dedicated tests cover read-only absence, explicit persistence, storage content, workspace separation, CAS conflicts, valid and invalid years/classes/work, bad schema/JSON, oversized files and symlink refusal, stale school years, class metadata year mismatches, missing rosters, inactive/missing work, good registered work, no implicit teacher-profile creation, no publication/student/authorization fields, and navigation-only opt-in resumption.

The Windows branch must still run the actual installed Core/Meridian focused tests, Ruff and strict mypy. The isolated local tests used simplified Core stand-ins; they are not a replacement for installed qualification.
