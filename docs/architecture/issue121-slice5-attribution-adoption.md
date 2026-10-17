# Issue #121 Slice 5 — saved attribution throughout the interactive teacher application

- Parent: #120; implementation issue: #121.
- Branch: `121-persistent-teacher-identity-preferences-classroom-context`.
- Starting commit: `6149d4f17922653309fb7018288c1807695d9ce7`.

## Purpose

A teacher profile configured in Slice 4 now supplies the **same stable actor ID** to
routine authoring operations from the normal Meridian main menu. The display
name is shown as `Recorded by: ...`. Changing the display name does not change
the canonical actor ID. An explicit identity replacement applies to future
attribution only. Historical academic records are not modified.

## Transitional UI integration

The 20 known interactive identity prompts (five guided and fifteen legacy)
currently use either `Teacher name for attribution: ` or `Teacher actor ID: `.
Slice 5 installs one `TeacherAttributionInput` adapter **only in the default
interactive teacher-menu composition**, rather than editing all canonical
authoring services or inventing a mutable global actor. The adapter supplies
`TeacherIdentityProvider.resolve().actor_id` at the existing prompt boundary.
Every other input, including confirmation, rationale, student selection, and
explicit academic judgment, passes through unchanged.

Prompt-based interception is deliberately transitional until the later #120
teacher-first menu overhaul replaces legacy screens with explicit injected
actor dependencies. The source inventory test freezes the known 20 sites; a
new or renamed site requires deliberate review.

## Fail-closed and authority behavior

- No saved identity, corrupt or unreadable profile: **abort the current teacher
  authoring path** with `ReturnToMainMenu`, after displaying a Settings recovery
  instruction and allowing the teacher to read it. Nothing is passed to the
  downstream service; there is no reliance on blank-string validation.
- The profile is reloaded each time an attribution is requested; it cannot
  authenticate the person at the keyboard or grant protected evidence access.
- All academic decision previews, separate write/current-selection steps, and
  confirmations remain as previously implemented. No Grade, attempt, policy,
  eligibility, or standard is selected on the teacher's behalf.
- `run_menu(dependencies=...)` retains fully injected test behavior. Exact CLI
  commands and explicit programmatic APIs do not pass through this input
  adapter and retain their existing actor requirements.
- Evidence authorization recomposition retains the same provider. Settings
  remains a normal input route (its prompts are not substituted).

## Qualification

Run the new attribution tests and existing main-menu composition/foundation,
plus the affected guided menu tests, once. Run Ruff and strict mypy on the new
module and modified `menu.py`. The wrapper is backed by Slice 2's validated
storage and does not modify persisted student/evidence records itself.

## Follow-up (#121 Slice 6)

Qualify installed-wheel sessions, actor changes and profile failures during
realistic authoring journeys; confirm that every legacy service fails closed
without a profile, handle a deliberate one-action override in the advanced
workflow if required, and document the migration to explicit provider injection
as the teacher-facing legacy screens are replaced under #120.
