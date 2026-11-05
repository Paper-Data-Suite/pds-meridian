# Meridian #124 — E2G3O11 Grade Items one-confirmation entry

Base: `6c0e721374c7302878df9632f0ec04aa9f72fef8`.

## Purpose

The native ScoreForm, Quillan, and scored Concord journeys and five-wheel installation were qualified in E2G3O8–E2G3O10. The qualified one-APPLY teacher journey was reachable from the Meridian main menu via `D`, but Manage Grade Items still presented the older separate author/select and membership workflows. This slice adds an explicit secondary route into the *same* trusted discovery/setup controller.

## Change

- Under **Manage Grade Items**, with a teacher navigation context and an injected trusted discovery callback, display `D. Discover Registered Assessments / Set Up Grade Item`.
- Delegate to that callback; on normal return display **Manage Grade Items** again. The same teacher session and process-local class/work/publication scope survive.
- The main-menu `D` and Grade Items `D` share one composed handler and one `GuidedGradeItemBridgeDependencies` instance, preserving the current #122 action/correlation and attribution boundaries.
- Preserve options 1–9 and their existing Advanced exact-record behavior. In the legacy no-navigation entry and when no trusted callback is supplied, `D` is absent/inert.
- No new canonical write pathway, evidence read, authorization grant, producer mutation, Grade calculation, or currentness inference.

## Acceptance and scope limitations

The four tests establish callback visibility, safe absence in legacy/untrusted contexts, return to the same menu and identical default application handler composition. E2G3O4–E2G3O10 cover the actual canonical one-confirmation setup. E2G3O11 does **not** establish direct setup from an already selected Evidence Inbox item, which remains an explicit #124 release-readiness gap requiring separate reviewed routing/authorization design. It must not be silently marked complete in the final acceptance ledger.

Final candidate still requires the complete repo Ruff/mypy/pytest/package validator and the full Windows/Ubuntu Python matrix at the actual PR candidate SHA. No merge or issue closure is authorized by this slice alone.
