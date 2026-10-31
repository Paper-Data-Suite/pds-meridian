# Meridian #123 — Slice 4D1: Guided adoption of an existing Grade Item version

**Base:** `b12e8892b3b32d8c39062103e054cc37684fcf0e` on `123-teacher-first-navigation-existing-menus`.

## Scope

Add one teacher-first **Use existing Grade Item version** option, available only when
Meridian is entered through its shared verified navigation context. A teacher
chooses class (or reuses a verified class), Grade Item by current title, and an
existing immutable version labeled with title, status and date. They review
which version is currently selected and explicitly type `USE` to adopt the
chosen version. A canceled choice, an already-current version or a failed
recheck does not issue the selection commit.

The existing `preview_grade_item_selection` / `commit_grade_item_selection_preview`
remains the sole write interface. CAS checks for the target, full immutable
history and current pointer remain in the domain layer. This slice does not
author Grade Item revisions, select work memberships, create registrations,
select missing Grade Items automatically, change policy/evidence, or alter the
independent CLI and Advanced exact-record routes.

## Boundaries

- Discovery is read-only: `project_grade_items_review`,
  `list_grade_item_revisions`, `load_grade_item_revision`, and
  `get_current_grade_item_revision`.
- Navigation retains only process-local hints after a successful use action;
  display labels and currentness witnesses are not authorization tokens.
- Candidate history is bounded to 100 versions and the existing verified
  class/Grade Item scope. A change in class, current version, exact revision
  digest, or history causes refresh rather than substitution.
- The teacher confirms one meaningful use action. The existing immutable
  authoring and selection paths remain Advanced. No second adoption prompt.
- The existing terminal header, B/M/Q and selector conventions remain intact.
  Core #236 has frozen `pds_core.teacher_experience/1`; Core #237 still owns
  implementation of the shared green renderer and `:notes` parser. This
  slice introduces neither a duplicate shared renderer nor command dispatch.
- `Grade Item` is not an inferred Score, Grade, evidence authorization or
  membership decision. The action does not change work relationships.

## Qualification

Focused tests cover visible named revision lists, exact identity, current and
historical status, bounded history, missing/cross-class/stale state, initial
and post-confirmation currentness checks, one deliberate commit, cancel/no-op,
CAS conflict, and M/Q propagation. Existing #110 prompt quarantine and
#121/#122/report/Grade Item regression checks remain mandatory. The packaged
runner guards the exact baseline and approved staged inventory, then runs
Ruff, strict mypy, frozen audit, regression tests, commit and non-force push.

## Follow-on

The next Grade Items sub-slice will evaluate guided **membership revision
selection** using the existing membership preview/commit service. It must
retain Core registered-work identity, Grade Item version basis and period
revision checks, and cannot silently select an only-available decision.
Shared headers/Notes adoption waits for released Core #237 capability tokens,
not on a Meridian-specific replacement.
