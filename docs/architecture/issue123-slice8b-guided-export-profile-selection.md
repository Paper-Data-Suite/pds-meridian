# Meridian #123 Slice 8B — Guided Export Profile Selection

**Base:** `1e07328` on `123-teacher-first-navigation-existing-menus`

## Teacher workflow

The teacher-context Export menu adds **8. Use latest Export Profile version by name**. A teacher chooses a verified class and an existing Export Profile through the scoped, refreshed choice catalog. The catalog distinguishes the latest authored revision from the version currently selected for export, including when the selected revision is older. An already-current latest revision causes no write. No technical profile identity is requested, and teacher attribution uses the existing saved-identity adapter.

The teacher reviews the name, prior selected version, and exact latest target, then confirms **USE**. Blank or any other answer cancels without changing the selected version. The workflow does not construct an Export Profile, preview a payload, create a file, issue a receipt, or call an external system.

## Exact authority and failure modes

The existing `_preview_profile_selection` loads the latest canonical immutable revision/digest and current selector reference. The controller checks the preview's class/profile/title/revision against the refreshed catalog. The actual selected version is separately reloaded before review and before commit; this avoids confusing selector revision with authored profile revision. Immediately after confirmation, the preview is recomputed and compared exactly with the reviewed plan. The existing `select_export_profile` service owns the digest-bound compare-and-swap, teacher attribution and immutable selected reference.

The controller invokes that service only after deliberate confirmation. The post-commit loader must return the exact selected revision and digest, and the class inventory must show that version as current. A failed write/readback is reported as **uncertain**, with instructions to inspect the selection, rather than asserting a rollback. Errors before calling the committer clearly state no selection was attempted. Detailed failures are not exposed in teacher terminal output.

## Compatibility and qualification

The six original Export operations remain at their original numbers in an explicitly marked Advanced section. The earlier option 7 retains its number. The legacy no-context menu retains options 1–6. One former Slice 8A static assertion is changed to accept later append-only options while still requiring option 7. No new Core or Export Profile storage API, UI database, raw-ID literal prompt site, or producer-evidence read is introduced.

Focused adversarial tests cover CAS/currentness drift, older revisions, cancellation, valid and invalid previews, already-selected short circuit, post-write digest and selected-state readback, redacted errors and Core M/Q propagation. The guarded Windows qualification runner checks exact Git baseline, branch, source blobs, payload manifest and scope; Ruff, strict mypy, Issue #123 frozen audit, existing Export tests, and three regression groups must pass before an exact-scope commit and normal push.
