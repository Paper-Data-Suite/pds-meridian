# Meridian #123 Slice 9A — Teacher-Named Current Grade Explanation

**Base:** `c27e8619afac598e2e4bc92105a8dc63a3ceec21`
**Branch:** `123-teacher-first-navigation-existing-menus`

## Teacher task

The teacher-context **Explain** menu adds **9. Explain a current Grade by name**. The original exact-ID routes 1–8 remain numbered, with clear **Advanced:** labels in teacher context. The legacy no-context menu is unchanged.

The teacher chooses or reuses a Core-verified class and current marking period, selects an enrolled student by roster name, and chooses the supported calculation family (standards-based, conventional or hybrid). The **existing** `ExplainMenuDependencies.current_grade` service alone evaluates the explanation; it retains policy, evidence-access and freshness semantics. This slice neither caches explanations nor creates a Grade, override, snapshot, export, or evidence-read permission.

## Trust and currentness

- Choices come from the existing authoritative `TeacherAcademicChoiceCatalog`, `PeriodProficiencyChoiceCatalog`, and common terminal selector. They carry canonical IDs internally; display names are never authority.
- The verified class, marking period, student choice and period choice are rechecked before and after the explanation read, and again while its screen remains active. The provided explanation is required to contain the exact class, student, calendar revision, school year, marking period and calculation family it was asked to explain. Mismatched or changed data fails closed without displaying academic results.
- The normal screen replaces the explanation's technical student and period lines with teacher-readable names and shows policy/result/freshness detail from the canonical explanation. Missing numeric Grades are **not** displayed as zero.
- `T` deliberately opens the existing explanation's technical provenance, including IDs/digests. No ordinary path asks teachers to transcribe them.
- Core `B/M/Q` navigation propagates correctly. Internal errors and private paths are not printed; the teacher receives a safe blocker.

## Explicit boundaries

- No new academic record authoring, comparison baseline, student assessment inference, SIS update, local export, or producer evidence read in the navigation layer.
- A calculation needing protected evidence continues to fail through the established explanation authority when permission is absent.
- Class/year/period currentness is revalidated; display labels do not authorize access.
- Retains option 1's manual expert explanation without altering its direct-call or CLI contracts.
- Does not affect the existing Planning Signal menu; other Explain operations will receive independent named routes.

## Qualification

- One additive controller, one focused-test module (21 isolated tests), this architecture note, one precise `meridian/menu_explain.py` patch.
- Guarded baseline/remote/worktree, exact source blob, four unique patch anchors and manifest checks before any edits.
- Ruff import/format/full lint, strict mypy, frozen #123 Slice 1 route inventory, #110 raw-ID quarantine, historical Explain/Grade/Export regressions and focus tests before any commit/normal push.
- `B/M/Q` behavior and the eight original Explain operations remain available; no producer/Core contract changes.
