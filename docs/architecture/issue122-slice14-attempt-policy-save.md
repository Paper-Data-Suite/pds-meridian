# Meridian #122 — Slice 14: ordinary attempt-policy Save/Apply

Baseline: `a7622f7f164365c6265abf5c7bfe4c744be8a7dd` on `Paper-Data-Suite/pds-meridian`.

## Why this slice exists

The default guided attempt-policy route still called `apply_guided_attempt_policy`,
which writes and selects using two independent services without the #122 durable
teacher-action receipt, even though the teacher was asked once to continue.

## Ordinary route

- An already-current `ready` policy is an explicit no-write branch. It is not
  journaled as a new Save and is not used as permission to select a different policy.
- `create` and `revise` bind one canonical immutable policy candidate, actor,
  Grade Item membership, academic calendar, work registration, policy history,
  revision digest, and original current-pointer baseline before presenting **one**
  Save and make current confirmation.
- `select_existing` binds an exact verified historical revision and carries
  the existing-content digest into the same receipt/orchestration lifecycle; it
  does **not** reauthor the immutable policy.
- `PreparedGuidedAction` invokes the #122 receipt-first orchestrator, checks the
  target digest after persistence, verifies exact CAS selection, and reloads
  canonical current state before reporting Applied.
- On partial progress, the teacher sees a truthful result and may explicitly
  resume the exact action in the still-open session. Restart-specific recovery
  for this policy family is part of the subsequent #122 qualification slice.
- Preflight blocks changed work registration, Grade Item relationship,
  academic calendar, profile attribution, policy history, or target digest.

Existing `guided_attempts.apply_guided_attempt_policy` and policy author/select
functions are deliberately unchanged for legacy/advanced callers.

## Verification scope

`tests/test_issue122_slice14_attempt_policy_action.py` exercises ordinary
single-action create/revise/select-existing, cancellation, idempotent replay,
academic dependency changes, and the menu adoption boundary. Tests use synthetic
`tmp_path` workspaces only. The Windows runner tests the changed production
modules with Ruff, strict mypy and focused pytest; it commits/pushes only on green.

Remaining before closing #122: durable post-restart policy-only selection
recovery; installed and multi-process synthetic acceptance; teacher-interaction
counting; final full suite once; Windows/Linux CI.
