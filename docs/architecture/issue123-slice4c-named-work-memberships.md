# Meridian #123 Slice 4C — Current Registered Work and Grade Item Relationships

**Reviewed base:** `b1516471e3da84b8bf694ce607547e4e429985a5`

## Scope

Introduce a read-only teacher-first route in Grade Items (option 7) that follows:

1. A Core-verified active class (reuse current session where possible).
2. A currently projected Grade Item selected by its teacher-facing title.
3. Existing current Core work registrations, shown by title, kind, producer and lifecycle.
4. Exactly one matching recorded Grade Item membership, or an explicit **no recorded relationship** state.

Registrations are retrieved through `query_academic_work_registration_catalog` with an exact class/year filter, `current_only=True`, and a hard upper bound. The disposable catalog is verified, never rebuilt by a menu read. Noncurrent, cross-class and cross-year registrations are rejected. Archived registrations are excluded from this routine selection; direct CLI/Advanced review remains possible. No registration is created implicitly.

The Grade Item and membership come exclusively from `project_grade_items_review` (or the menu's injected read provider). Matching uses the complete exact `ModuleWorkRef`, not a title or input substring. Registration revision, selected membership revision/digest, and Grade Item revision are internal currentness witnesses. Selection refreshes the exact catalog and rechecks the Grade Item before display. If any source is ambiguous or stale, the route fails without changing an academic record.

A current marking-period assignment is shown by Core's verified label when possible. Old, incompatible, or unavailable calendar associations remain explicit historical/review-needed information; they are not retargeted. Missing membership or no selected membership decision never implies `included` or low proficiency. The route has no authorization grant, academic calculation, or commit operation.

## Compatibility and historical baseline

The old six-entry direct-call Grade Items menu retains its original commands. The new seventh entry is available only to a composed teacher-first navigation context. Existing option numbers, the exact-record Advanced author/select routes, and their preview/commit boundaries are preserved. The 49-operation Slice 1 inventory is a **historical baseline**, so this intentional added routine entry is documented here rather than rewriting or silently recapturing the frozen 49 routes.

## Qualification

- Choices contain exact `(module_id, work_id)` and read-only state witnesses but never show those opaque tokens in ordinary screen labels.
- Duplicate identities, duplicate indistinguishable descriptions, wrong class/year, stale Grade Item, and oversized registration sets fail closed.
- An unlinked registration, an unselected membership, and an included membership are distinct.
- Changing the current registration or selected membership state changes the exact witness and invalidates old selection.
- B/M/Q propagation, read-only execution, #110 raw-ID quarantine, original menu behavior, and #121/#122 existing boundaries remain covered by regression tests.

**Not in 4C:** guided membership authoring/selection, grade item authoring, publication-specific authorization, or migration of the remaining manual proficiency-write workflows. These remain explicit, separate work for subsequent sub-slices.
