# Meridian #121 — Slice 6: Advanced one-action attribution and qualification

**Parent:** #120. **Branch:** `121-persistent-teacher-identity-preferences-classroom-context`.

## Boundaries

Meridian persists the self-declared teacher profile in an isolated per-user
settings file, not in the academic workspace. The saved actor ID is used for
normal guided and legacy attribution requests; the human name is displayed.
Neither the saved profile nor a temporary override is evidence authorization,
a role, an academic decision, or a grant to a district system.

The optional **Teacher Settings → 8. Override next attribution (Advanced)**
action asks for the alternate actor ID and name and requires the explicit
`OVERRIDE` confirmation. The next existing attribution prompt receives that
actor ID and shows `Recorded by (one-action override)`. The override is then
consumed; it is not a session-wide impersonation setting. It is consumed at
*attribution-request time*, even if the teacher later cancels the academic
write. Teacher Settings → 9 cancels an unused override. Main Menu and Settings
warn whenever one is queued, preventing an invisible lingering change.

An override requires an existing readable saved profile. The exact profile
SHA-256 fingerprint is captured when arming and rechecked before consumption.
A display-name change, identity replacement, reset, or profile corruption
causes the override to fail closed and return to Main Menu; the override is
**not** applied and is disarmed. Quit/EOF/Ctrl+C also discard any pending
actor. Missing profiles cannot be bypassed by typing a temporary actor.

The actor state lives in an injected `OneActionAttributionOverride` object
shared by all nine interactive teacher controllers and Teacher Settings. The
same object survives evidence-authorization reader recomposition without
persisting it. Direct CLI commands and Core's authorization layer are unchanged.

## Review and acceptance

- Existing nine numbered main-menu actions and navigation remain unchanged.
- First-use setup, profile editing, saved classroom preferences, and guarded
  Core resume behavior from Slices 2–4 remain intact.
- Every existing guided and legacy actor prompt uses the saved actor without
  routine identity retyping. The last-five guided prompts and remaining legacy
  sites are protected by the Slice 5 inventory test.
- Unit and integrated-menu tests cover normal identity, one-shot override,
  cancel, missing profile, corrupt profile, actor changes, and exact prompt
  behavior. Focused checks should include Slices 2–6 and prior menu-contract
  tests. Run strict mypy, Ruff, and staged whitespace on changed files.
- Installed-wheel acceptance and a final cross-repository compatibility / CI
  review are required before merging or closing #121; a passing source-tree
  gate alone is not a release qualification. Do not automatically create a
  public release or rewrite another repository under this issue.

## Scope left to #120 sub-issues

This change does not merge separate immutable write/current-selection steps,
fix raw classroom IDs in legacy menus, automatically authorize evidence,
select attempts, choose proficiency, or convert evidence-only work into Grades.
Those changes belong to the other numbered child issues under #120.
