# Issue #124 — E2G3O2: durable composite review binding

## Qualification objective

Connect the E2G3N one-confirmation review controller to the **existing** E2C correlated live binder. Avoid a second receipt engine. Academic source, current-selection compare-and-swap, original #122 action IDs and the monotone E2B correlation remain owned by their existing modules.

## Scope

- One additive entry point in `menu_teacher_assessment_setup_review.py`: `review_correlated_assessment_setup_once`.
- Guard the selected class, work, Grade Item and optional publication against the process-local teacher session before constructing an action.
- Require a saved, exact teacher actor for write-bearing plans; allow `already_ready` read-only verification with no actor and no `APPLY` prompt.
- Read existing per-class E2B correlation records before presenting `APPLY`; a prior matching Grade Item or work identity directs the teacher to interrupted-save recovery rather than rebuilding action IDs.
- Bind the reviewed setup **only** through `bind_correlated_live_assessment_setup`, which performs its independent under-lock correlation claim and pre-action binding.
- Delegate confirmation and readiness/session continuation to E2G3N; maintain the same no-retry rule for partial and unknown outcomes.
- No change to normal menu routing or academic storage. E2G3O3 is required to activate the reviewed write path from D discovery.

## Failure boundaries

A missing workspace, wrong session, invalid or temporary actor, corrupt correlation inventory, preexisting correlation claim, or live binder exception refuses entry before showing the confirmation prompt. The handler cannot transform a journal, catalog status, title, or previously created correlation into fresh write authority. The existing E2C closure independently checks collisions just before invoking #122 APPLY, so the read-only preflight is not relied on for concurrency safety.

The facade is a **composition boundary** and is not by itself an end-to-end production menu test. The E2G3O2 focused tests inject actions for prompt/session contracts; existing E2C, E2G3K, E2G3L, and E2G3N tests cover storage and restart behaviors.

## Qualification

Strict mypy and Ruff on the changed module, focused E2G3O2 + adjacent #124 suites, full exact file-scope and remote-HEAD guards. No unqualified commit, reset, clean, or force-push.
