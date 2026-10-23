# Meridian #123 — Slice 6B1: Select the latest authored Grade override decision

**Baseline:** `32143958c17492cbeb35cc8dfb67aaa95e270683` · Branch `123-teacher-first-navigation-existing-menus`

## Scope

Adds option **6. Use the latest authored override decision by student** to the teacher-context Overrides menu. This intentionally preserves existing menu choice numbers 1–5 and the no-context exact-record paths. A teacher selects a verified class, marking period, roster student, and explicit calculation family, then reviews the **latest authored** `override` or `withdraw` decision and types `USE` to select it.

Selection is a **single consequential operation**: `OverrideMenuDependencies.selection_previewer` performs Meridian's existing canonical latest-revision and current-pointer read; `selection_committer` calls `commit_teacher_grade_override_selection_preview`, with its history/digest/currentness CAS checks. The controller checks scope and preview coherence, and re-reads both before committing. No new revision is authored, no Grade computed, and no work evidence is accessed here.

A selected `withdraw` decision **does not apply a replacement Grade**. An already-current exact target is a no-op. A declined confirmation does not invoke commit. Failed or indeterminate commits instruct the teacher to inspect canonical selected state; they do not claim rollback. No raw record identities or hashes appear in routine output. Existing direct CLI and Advanced authoring/withdrawal services retain their separate semantics and teacher attribution.

## Safety and acceptance

- Core classes, rosters, and current marking-period catalog are reverified; UI choices are transient hints, never authority.
- Only the **latest** authored override decision is eligible; historical reselection is prohibited by the existing lifecycle service.
- Correctly represent `override`, `withdraw`, `none`, and a true numeric zero; never infer a replacement from absence.
- Exit/confirmation behavior remains owned by existing Meridian/Core navigation. No Core #237 shared header or Notes command is implemented.
- Focused tests cover use/cancel/no-op/withdrawal, plan and scope mismatch, currentness changes, errors after an attempted commit, Advanced compatibility, and M/Q propagation.
- Ruff, strict mypy, frozen #123 menu audit, historical regression suites and exact staged-change verification must all qualify on the user workstation before commit and push.

### Deferred

Guided **authoring** of new override revisions and guided **withdrawal** create immutable revisions with potentially partial success and teacher-attribution controls. Those remain separate future slices, not implicit side effects of selection. Integration with Core's shared teacher header/command facilities begins only after #237 is released and installed-qualified.
