# Meridian #126 — E3B production #31 adapter and installed Core dependency matrix

**Baseline:** E3A accepted at `7098f6eccc05d7ab49a4f120eeab9d5b7d632ca5` on branch `126-verified-correction-attempt-reassessment-management`.

## Scope

E3A proved the native #30/#31 immutable file, pointer and #122 receipt primitives with a purpose-built native domain port. **E3B invokes the real `prepare_reviewed_reassessment_action` adapter and its `PreparedGuidedAction.apply/resume` path**, rather than using E3A's purpose-built port. The existing real #30/#31 storage functions, immutable digest validation, pointer CAS and class-scoped #122 receipt store are used in temporary workspaces.

Unconnected live authorization sources remain synthetic: ScoreForm publication/eligibility, membership/roster/academic period, and the local teacher profile. They are substituted explicitly by the E3A shared fixture and E3B adapter seam; no Core or #31 storage mutation is monkeypatched to claim a production outcome. Thus, E3B does **not** prove installed native ScoreForm contract D4, live teacher identity, production record authorization, final A1–A18, or complete wheel reproducibility. The runner verifies that `pds-core` is installed as a noneditable distribution satisfying Meridian's declared dependency bound `>=0.6.5,<0.7`. It reports optional module distribution versions without assuming they are installed.

## Failure matrix and expected truth

- Success requires #122 `applied`, real current #31 immutable revision, the independent reassessment resolver, and a finalized journal; #30 history remains exactly unchanged.
- Cancel never creates #31 revision or journal.
- Missing or changed #30 current selection, wrong actor, a forged reviewed digest, stale #31 policy, withdrawn publication, changed included-membership source or academic calendar must fail before any new #31 write.
- If the real writer saves the immutable #31 record and then throws, the outcome must **not** claim success; the immutable revision remains discoverable for exact-action recovery.
- If CAS selection is interrupted before the pointer update, reusing the exact original action with `resume` must select the existing revision without reauthoring it.
- If CAS selection succeeds but the operation throws before acknowledgement, the first outcome must not claim success; a subsequent read-only reconciliation must establish exact current state and original-action resume must not rewrite.
- A failure updating the write-stage receipt must not transform a persisted record into claimed success.
- Repeating the same exact action must not write another revision; source withdrawal must prevent unsafe restart.

## Native authority retained

No new academic storage, policy, Grades, Standards, SIS, Note or journal schema is introduced. #31's `write_reassessment_decision_revision`, `select_reassessment_decision_revision`, and `resolve_current_reassessment` remain authoritative. The #122 journal is recovery evidence and cannot override canonical truth. All tests use synthetic IDs and temporary workspaces; no teacher or student production records are touched.

## Acceptance and next work

Runner qualification: exact branch and pristine worktree; package hashes; installed noneditable Core version; Ruff import sort/format/check; strict mypy on existing production adapter; focused E3B/E3A/#126/#30/#31/#122 pytest; documentation checker and Git scope checks. Only full success leads to commit/push. E3B does not automatically close Slice E: evaluate any remaining authorization/installed ScoreForm gaps before moving to the teacher-facing Slice F. Final A1–A18 acceptance remains pending.
