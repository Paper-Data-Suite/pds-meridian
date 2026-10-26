# Meridian #123 Slice 9C — Named Grade Item Proficiency Explanation

## Teacher route

Add **11. Explain Grade Item proficiency by name** only when the verified teacher navigation context exists. Keep legacy **3. Advanced: Grade Item proficiency** and all other Explain choices for exact-ID diagnostic work. Non-context interactive menu remains options 1–8.

The flow uses existing bounded, authoritative #123 catalogs in this order: verified class → selected Grade Item (title/status) → roster student (name) → Standard with an **existing selected proficiency result**. A missing result is never interpreted as zero or fabricated. It reuses the verified session class and displays the chosen Grade Item, student, Standard, selected calculation result, policy and evidence counts in teacher-facing language. Technical identities and digests appear only after `T`.

## Canonical contracts and safeguards

- `TeacherAcademicChoiceCatalog` provides exact `identity` plus title/name/status and an opaque read witness. It is not permission to compute or modify evidence.
- For `standard`, the catalog's current selected-result witness is `<revision>:<sha256>` from the canonical `load_current_standard_proficiency_result`. Parse it only to verify the read-only explanation's exact result revision and digest; never accept a label as academic authority.
- Existing `ExplainMenuDependencies.grade_item_proficiency` delegates to `explain_grade_item_proficiency()` with `GradeItemProficiencyTraceTarget(selection="current")`. This verifies the stored #34 result and its #42 dependencies, without recomputation or evidence opening beyond its current contracts.
- Before reading, after reading, before displaying, and before showing technical details, reload selected Grade Item, roster student, Standard-result witness and class scope. A missing or changed current pointer fails closed and asks the teacher to refresh.
- Bind result presentation back to class ID, Grade Item ID, selected Standard-result revision and digest. Require the exact selected student/Standard in the presentation's source lines; replace student ID with roster display name on the ordinary screen.
- Preserve shared `B/M/Q` and normal continuation behavior. Catch unexpected domain failures with redacted teacher-facing guidance; propagate Core navigation exceptions.
- No state writes, new policies, evidence authorization, snapshot creation, recalc, aliasing historical revisions, or persistence changes.

## Qualification

A guarded exact-baseline runner checks the expected `8641c4a` branch head and remote, clean worktree, reviewed patch anchors, SHA-256 manifest and additive paths. It runs Ruff, strict mypy, the frozen #123 navigation audit, focused named-flow tests, and full preexisting bounded regression groups before committing/pushing the exact four-file scope. Full workstation gates remain required.
