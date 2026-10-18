# Issue #121 — Slice 4: teacher Settings integration

**Parent:** [#120](https://github.com/Paper-Data-Suite/pds-meridian/issues/120)

**Branch:** `121-persistent-teacher-identity-preferences-classroom-context`

## Scope

Add `S. Teacher Settings / First-Time Setup` to the existing Meridian main menu,
without renumbering the nine tasks or changing the evidence-access action.
Teacher Settings is an opt-in, on-demand surface for the durable attribution
profile introduced in Slice 2 and classroom navigation hints from Slice 3.
Opening Meridian or Settings does not create local settings files.

Settings supports:

1. **One-time profile setup:** Ask for a human name and `SAVE` confirmation.
   Generate a stable, Core-safe actor ID through the profile store. No OS user,
   Git identity, school/district string, or arbitrary default is substituted.
2. **View/rename:** Show the exact stored identity in Advanced; change its
   display name with explicit `SAVE`, preserving actor ID and prior audit records.
3. **Replace identity:** Require explicit `CHANGE`. The new actor applies only
   to future decisions and never migrates or rewrites historical records.
4. **Reset identity:** Require explicit `RESET`. Remove only the local profile.
5. **Save current class:** Require a current, Core-validated active school year,
   class metadata/roster, and current work registration if an assessment is
   selected. Save only after `SAVE`. Replacing hints for a different workspace
   requires `REPLACE`; compare-and-swap prevents lost updates.
6. **Resume saved class:** Revalidate a matching workspace, active school year,
   class metadata/roster, and optional work registration before showing the
   proposal and again after the teacher confirms `RESUME`. Never overwrite a
   class selected in the current session.
7. **Clear saved navigation:** Require `CLEAR`. Preserve the current process-
   local selection, teacher identity, academic records, and authorizations.

## Authority boundary

Settings are convenience and attribution data, not credentials. Resumption
never restores a student, publication authorization, evidence decision, Grade
Item, attempt, proficiency, or Grade. Canonical currentness and access checks
remain mandatory in downstream workflows. No automatic SIS or LMS writes.

A missing profile does not prevent browsing. Consequential flows will consume
`TeacherIdentityProvider` from the next #121 slice; Slice 4 does **not** yet
remove the existing per-operation actor prompts.

## Implementation boundary

The existing main menu continues to own the process-local
`TeacherSessionContext`. The new Settings controller accepts injected stores,
workspace resolver, input/output functions, and clear function for deterministic
qualification. Preferences remain outside the academic workspace under Core's
per-user configuration directory convention.

## Focused acceptance

- [ ] First setup, cancel, persisted reload, name update, identity replacement,
      and profile reset.
- [ ] No user identity inferred from shell/environment or profile absence.
- [ ] Correct source attribution and no mutation of historical records.
- [ ] Existing `1–9`, `A`, `H`, and Core navigation remain intact.
- [ ] Class/work preferences only saved after Core validation and teacher consent.
- [ ] Resumption does not make stale/withdrawn work current or grant access.
- [ ] Workspace mismatch, changed hint, malformed storage, and concurrent edits
      produce an actionable failure rather than silent repair.
- [ ] Focused pytest, Ruff, strict mypy, and staged whitespace gates pass.

The feature is not complete until the later #121 slices wire the common identity
provider through every routine teacher decision surface.
