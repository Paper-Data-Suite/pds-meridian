# Meridian #123 — Slice 11D: Installed-wheel navigation harness

**Base:** `1d5af8a` (qualified Slice 11C).  **Scope:** One additive prepared-wheel smoke command, seven local harness tests, and no changes to the existing central #96 runner. The teacher application's menu behavior and academic services remain unchanged.

## Qualification boundary

The existing `scripts/installed_qualification_runner.py` manages temporary, source-isolated environments with exact candidate/released wheels for Core, Meridian, ScoreForm, Quillan, and Concord. Slice 11D adds a standalone entrypoint `python -m scripts.smoke_test_issue123_navigation_wheel <meridian.whl> <core.whl> <scoreform.whl> <quillan.whl> <concord.whl>`. This invokes the exact existing **all-adapters** prepared-wheel harness. The central #96 matrix runner, whose smoke order is frozen by its existing tests, remains unchanged. No custom environment engine, dependency-version override, or producer-compatibility inference is added.

The new smoke checks installed-module origins inside the prepared virtual environment, navigates the eight teacher domains and nested Planning Signal through actual CLI processes launched outside the source checkout, verifies named and Advanced menu texts and `B`/`M`/`Q` transitions, rejects raw canonical field prompts on those non-action navigation routes, and confirms no files are created in the smoke's outside directory. It does not author or select any academic record, open protected student publications, export a signal, or create a workspace.

The smoke runs inside a newly prepared exact all-adapters wheel environment. Its local unit tests use a fake subprocess boundary, and **do not count as a successful installed-wheel smoke**. The Slice 11D source runner qualifies this registration and existing tests; the actual five-wheel matrix requires exact wheel artifacts and a later explicit execution record before #123 closure.

## Follow-on acceptance

- Execute the prepared all-adapters matrix using explicit local wheel artifacts whose metadata and supported versions match the repository requirements.
- Inspect installed module origins, pip dependency check, and immutable distribution fingerprint before/after the navigation smoke.
- Retain cross-domain synthetic journeys and 29-student, duplicate-name tests from Slices 11B/11C; they are source-tree behavioral evidence, not a substitute for full installed domain-data acceptance.
- Run the Windows/Linux CI matrix, packaging/sdist allowlist, source prompt baseline, and final full test suite. Record before/after teacher input measurements and publish the teacher navigation/Advanced guide.

**Status before wheel-matrix execution:** Harness registration qualified by source tests only; installed-wheel acceptance remains pending.
