# Meridian #123 — Slice 4A: Named Grade Item and selected proficiency review

**Parent:** #123, Slice 4 of the implementation plan
**Reviewed branch base:** `f9653f6b27dce4fb684b3efa5d404a986bcd072d`

## Boundaries

This is an **incremental, read-only sub-slice** of the larger Grade Items / Proficiency migration. It does **not** claim to complete all 16 menu operations in those two controllers. No Grade Item, membership, proficiency, scale, policy, authorization, receipt, Grade, or planning decision is created or selected by this slice.

With the normal nine-task teacher entry point, Meridian now offers:

- **Manage Grade Items 1 and 2:** named Grade Item selection, with search and paging, followed by a read-only relationships review. The selected class is reused when Core verifies it. No class or Grade Item ID is transcribed. Currentness is checked again after selection.
- **Review Proficiency 1:** name-based class → existing Grade Item → roster student → Standard for which Meridian has an **already selected** result. It invokes the existing explanation loader, not a new permission or calculation path. The source pointer is rechecked after explanation. Absence of a current result is not represented as zero.
- **Other exact-record operations:** shown with an explicit **Advanced** prefix in the normal composed menus. The existing routes and explicit direct/CLI services remain unchanged.

Injected/direct callers with `navigation_context=None` still receive the exact original menu labels and dispatch routes.

## Authoritative read contracts

- Core `list_class_folders`, class metadata and roster; `TeacherNavigationContext.verify_class` checks workspace, active school year, exact class, and roster before the class is carried between menus.
- Meridian `project_grade_items_review` projects persisted Grade Item and membership state. Opaque Grade Item IDs and SHA digests remain in transient `TeacherChoice` identity/witness, never in normal row labels.
- Core `student_display_name`, using roster position and class period to disambiguate identical display names. If the verified roster changes after selection, the choice must be made again.
- Meridian `list_standard_proficiency_result_identities(maximum_families=500)` plus `load_current_standard_proficiency_result`; identities are validated by the storage reader. Historical/unselected results are not offered as currently selected proficiency. Neither producer files nor protected student responses are opened during enumeration.
- The existing proficiency explanation loader remains the only way to show a current result, subject to its existing source/readiness checks. A revoked or unexplainable result is a blocker, never an invented grade.

## Intentional limits and next Slice 4 work

- The current Grade Item relationship review shows producer ownership and relationship status. A human-facing **registered work title** and Core calendar label require their own exact registration / period join, not a guessed filename or work ID.
- A Grade Item with no selected revision may lack a title. Indistinguishable option labels block selection rather than dumping canonical IDs or picking a record automatically.
- The Proficiency named list presents existing **selected** Grade Item results only. Direct calculation, result author/select, period proficiency and planning readiness still use explicitly labeled Advanced routes pending guided equivalents and #128 policy configuration.
- The Advanced route labels do not remove historical exact inputs. The independent #110 188-prompt quarantine and immutable Slice 1 source snapshot remain unchanged.
- A class name distinct from its canonical Core class ID is not available in the public class metadata model. The fallback `Class <class_id>` is explicit; a future owner contract may improve it.
- Freshness checks are read-only navigation checks, not a write-side CAS witness, domain permission grant, or a replacement for the #122 Save/Apply receipts and conflict gates.

## Qualification

Runner gates: exact branch/base and remote; clean tree; hashes for every package payload and exact original menu blobs; patch anchor preflight; Ruff import sorting/format/lint; strict mypy; new Slice 4A tests; Slice 1–3 and #110 contract tests; reports/profile/receipt regression tests; frozen Slice 1 inventory verification; whitespace and staged-scope checks. Commit/push only after success.
