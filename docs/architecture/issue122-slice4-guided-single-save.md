# #122 Slice 4 — Guided Grade Item and eligibility single Save/Apply

## Status and implementation boundary

This slice wires the existing #122 action contract, receipt store, and
orchestration kernel into the **guided** Grade Item creation, Grade Item/work
membership, and evidence eligibility menus. It does not replace legacy
advanced/manual author and select operations. It does not alter producer-owned
work, Core publications, grades, student submissions, or authorization grants.

Each reviewed **record-family action** has **one** normal confirmation:

- Create a Grade Item: author the exact revision, CAS-select it, independently
  reload and verify it is current.
- Include a work in a Grade Item for a selected academic period: author the
  exact membership revision, CAS-select it, independently reload the selected
  membership and verify its Core work, current Grade Item, and calendar basis.
- Choose evidence eligibility: author the exact teacher-selected disposition
  under an authorized source, CAS-select it, independently reload selected
  eligibility and verify the unchanged publication, source lifecycle,
  membership, calendar, and policy context.

Creating a Grade Item and linking work to it are **two academic record-family
operations**. The teacher reviews each meaningful academic choice; this slice
does not claim a single atomic transaction across both stores. If the new
Grade Item is current but subsequent membership setup is canceled or blocked,
the Grade Item continues to exist and must not be silently undone.

## Security and exactness

- The action scope includes a hash of the workspace path, class/Grade Item,
  and, where applicable, Core school year, academic period ID, a digest of the
  loaded and validated current calendar, and the work identity fingerprint.
- The immutable candidate digest comes from the existing canonical model
  serializer. The prior selector's revision **and** record digest are bound.
- Grade Item authoring continues through the existing authoritative authoring
  service. Membership and eligibility use their existing dependency validation
  and CAS selection services. No new policy makes academic choices for teachers.
- The saved profile SHA-256 binds actor attribution, and the existing #121
  one-request override is consumed through the menu's explicit actor request.
  A direct controller call cannot invent a temporary attribution token.
- Journal records are privacy-minimal, scoped to the class, and are **not**
  the source of grading truth. Each successful response follows an independent
  canonical read. Any interrupted write or selection preserves immutable
  history and refuses to assert success without verified current state.
- No receipt is created merely by displaying a review. Cancellation before
  Save returns without invoking an academic mutation.

## Teacher-facing recovery

The normal menu presents `Save and make current` **once**. If a canonical read
proves that the exact immutable decision was saved but has not become current,
the screen offers a separately reviewed `Resume selecting this exact saved
decision` choice. That explicit `RESUME` never invokes an immutable writer,
and a changed current selector requires a new review. Unknown/current-
unverified status must **not** be shown as applied.

A general post-restart listing of unfinished receipts is not yet wired into
navigation. The foundation and read-only reconciliation were delivered in
Slices 2–3; follow-on integration must expose durable discovery/recovery
without reauthoring an interrupted Grade Item under a new derived ID. Do not
claim the entire #122 recovery acceptance complete until this is verified.

## Validation

Run Ruff auto-fix, formatter, lint and formatting checks, strict mypy on
changed production modules, focused synthetic kernel/menu tests, and the
existing #121 attribution override regressions. The final #122 qualification
will run the full suite **once** at the final qualified commit, plus wheel,
installed synthetic grade flows, and Windows/Linux CI. Do not use the district
OneDrive workspace for development acceptance.

## Teacher interaction baseline

Prior guided flow per operation: `Write this decision` confirmation, followed
by `Make ... Current` confirmation. After Slice 4: one `Save and make current`
confirmation on the ordinary success path. Additional recovery confirmation
is presented only after a verified partial outcome. This does **not** change
per-student/per-question batching; that is beyond #122.
