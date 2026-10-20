# Issue #123 — Slice 1: frozen teacher-navigation audit and contract

**Status:** Slice 1, audit only. No teacher-facing behavior or academic writes change here.
**Reviewed branch:** `123-teacher-first-navigation-existing-menus`
**Audited base / `main` SHA:** `0e9afa0eeb879de1741c57bff3cd9b94f79f772f`
**Issue:** <https://github.com/Paper-Data-Suite/pds-meridian/issues/123>
**Parent:** #120; dependency constraints: #110, #111, #121, #122.

## Deliverables and invariants

- `scripts/issue123_navigation_audit.py`: deterministic, source-only AST inventory. It has no workspace, producer, PDS Core, grading, network, or authorization imports. It can produce/check a frozen UTF-8 JSON snapshot. It refuses unreviewed source drift using the original Git blob SHAs.
- `issue123-slice1-inventory.json`: **all 49 individual operations** across the eight existing menus, target route dispositions and scheduled migration slices; nine already-guided report kinds; **all call sites** of `read_choice` or direct `input_fn` in the enumerated menu/guide files, with source file, top-level/nested function, line, call style, literal vs dynamic prompt and raw-ID marker. This is an exhaustive *static call-site* inventory, **not** a trace of the runtime path or an assertion about authorization.
- `tests/test_issue123_slice1_navigation_audit.py`: exact source identity, all eight operation lists, nested Planning Signal reachability, report preservation, baseline determinism, safe parsing of dynamic/nested prompts and #110 compatibility.
- Existing #110 test keeps its independently frozen **188** legacy raw-ID sites / digest `2639c4ee…d2dfa5ae55`; no prompt wording is changed or exempted in Slice 1.

Snapshot generation: `python scripts/issue123_navigation_audit.py --write-snapshot` (once, from exact reviewed sources). Future regression: `python scripts/issue123_navigation_audit.py --check`. **Never overwrite** a snapshot merely because a prompt changed. Later slices must explicitly record why, replace baseline SHA locks with behavioral selectors/Advanced-only reachability tests, and deliberately update #110's count/digest when appropriate.

## Adoption inventory: operation-by-operation classifications

The JSON snapshot is the canonical **49-row, individual operation-by-operation** inventory (option, visible label, exact existing handler, target classification and proposed slice). Summary of target dispositions:

| Menu | Options | Named routine path goal | Existing exact/manual route to segregate into Advanced |
|---|---:|---|---|
| Grade Items | 1–6 | 1 review all; 2 inspect relationships; new guided current Grade Item/work choice and deliberate authoring | 3 author exact Grade Item revision, 4 select revision, 5 author exact membership, 6 select membership |
| Proficiency | 1–10 | 1 current Grade Item; 2 period; 3 planning readiness; newly guided calculation and existing-result selection | 4–9 are *currently* exact preview/write/select paths; retain as Advanced until full guided equivalents exist; 10 routes to Planning Signal |
| Grades | 1–2 | 1 individual Grade; 2 bounded class report with named roster selection | None needed for the two currently offered read-only operations |
| Overrides | 1–4 | 1 inspect; 2 review+author; 3 deliberate select; 4 review+withdraw | Keep lower-level exact revision operations discoverable without presenting raw prompts as routine |
| Snapshots | 1–6 | 1 list, 2 inspect, 3 current selection, 4 deliberate select | 5 exact Reporting Definition author; 6 build-request JSON freeze is Advanced until supported structured builder is available |
| Export | 1–6 | 1 list profiles, 2 inspect, 5 preview+local export, 6 receipts | 3 exact profile author, 4 exact latest-revision select require Advanced placement or bounded guided equivalents |
| Explain | 1–8 | 1 Grade, 2 comparison, 3 Grade Item, 4 academic period, 5 derivation, 6 preview/review, 7 planning export, 8 receipt | Exact IDs must be retained only behind diagnostic/Advanced entry after guided equivalents |
| Planning Signal | 1–7 | 1 readiness, 4 preview/diagnostics, 5 teacher review, 6 select review, 7 explicit Core export | 2 exact derivation author and 3 exact preview author need deliberate Advanced segregation |

**Dispositions describe the desired future interface**, not current capability. In Slice 1 all legacy prompts are still reachable and unchanged. Later migrations may promote a currently Advanced-only implementation to a named route when its existing canonical request can be preserved without guessing. Do not remove a supported operation from the API or imply that its functionality has already been migrated.

### Reachability and composition

The teacher main menu in `meridian/menu.py` exposes **nine** tasks (Review New Evidence, Grade Items, Proficiency, Grades, Overrides, Snapshots, Export, Explain, Reports). `run_proficiency_menu` option **10** invokes `run_planning_signal_menu`; Planning Signal has no independent main task. Existing `Review New Evidence` passes a shared `TeacherSessionContext` into its class-first inbox; the other legacy menu handlers are currently composed without that context. Reports use `ReportGuide`, `ReportOption`, `LiveReportChoiceCatalog`, `collect_guided_report_selection` and the report execution boundary; **preserve** their 1–9 behavior and add class-context handoff tests in Slice 3.

## Input-friction baseline (static, conservative)

The first column below counts *scope/technical fields requested* on typical pre-existing paths, not navigation keystrokes, confirmation, pause, retries or branch-dependent loops. These are the **minimum field entries identifiable in source**, not instrumented elapsed time or a real 29-student test. The full AST call-site counts, including direct `input_fn` and dynamic prompts, are preserved in the JSON and can be compared later.

| Representative operation | Fields currently typed | Teacher-facing replacement target |
|---|---:|---|
| Grade Items > Review one | 2: class ID, Grade Item ID | Current named class + titled Grade Item |
| Proficiency > Review Grade Item result | 4: class, Grade Item, student, Standard IDs | Named assessment → roster student → Standard |
| Grades > Preview one current Grade | 6: class, year, period, calendar revision, family, student | Retain verified class/period; select student + family |
| Overrides > Review current | 6: class, student, year, period, calendar revision, family | Retain scope; named student/current Grade |
| Snapshots > Inspect | 2: class ID, snapshot ID | Title + period + dated state |
| Export > Preview/export | 4: class, profile, snapshot, SHA-256 **before preview** | Titled profile + exact snapshot; internal digest |
| Explain > Grade Item result | 4: class, Grade Item, student, Standard IDs | Current titled item + named student + Standard |
| Planning Signal > Review readiness | 2: class ID, grouping policy ID | Current named class + configured policy |

**Follow-up measurement gate:** Slice 8 must run scripted synthetic input streams through composed menus; log only **counts/latency and non-sensitive route identifiers**, not student names or answers; compare redundant scope prompts, catalog reads and timing before/after. Static counts above are not a claim to have executed those teacher journeys.

## Sources, ownership and authority boundaries checked

These are observed public modules/functions to consider when implementing **bounded read-only** catalogs; their existence is **not** a blanket compatibility/authorization claim. API/version compatibility must be checked against installed Core before Slice 2/3 use.

| Owner | Authoritative candidate discovery | Important constraint |
|---|---|---|
| Core `pds_core.classes` / `class_metadata` | `list_class_folders`, `load_class_metadata_for_class` | Verify workspace/year and current class identity; no inferred class title |
| Core `pds_core.rosters` | `load_class_roster`, `student_display_name`, `student_sort_name` | Only for selected class; duplicate display names must retain distinct canonical roster identity |
| Core academic periods | `academic_period_storage` / `academic_periods` and catalog `query_academic_period_catalog` | Verify year, lifecycle, hierarchy, calendar revision; never substitute a different period |
| Core registered work | `list_academic_work_registration_refs`, `load_current_academic_work_registration`, `query_academic_work_registration_catalog` | Verify current registration and source status; catalog is discovery, not publication-read permission |
| Core publication catalog | `query_publication_catalog` | Publication listing is not permission to inspect protected evidence or generate a projection |
| ScoreForm | `scoreform/academic_work_registration.py` | Producer-owned assignment title and registration verified through Core; no scraping assignments |
| Quillan | `quillan/academic_work_registration.py` | Same registration boundary; no inference from file names |
| Concord | `concord/academic_work_registration.py` | Respect `evidence_only`, local criterion vs Standard judgment, and shared/group work ownership |
| Meridian #111 Reports | `report_live_catalog`, `report_guided_selection` | Catalog display identity distinct from exact value; revalidate at execution |
| Meridian #121 / #122 | `teacher_session`, `teacher_preferences`, `teacher_action_*` | Hints carry no authority; existing Save/Apply CAS/receipts/attribution remain the only write path |

**No cross-repository change** is introduced in this slice. Missing public readable metadata is a truthful limitation requiring a separate owner issue/version gate, not permission to parse producer-private stores.

## Non-negotiable next-slice acceptance

Slice 2 must define a typed, UI-neutral exact-identity choice with duplicate-label disambiguation, bounded search/pagination and explicit cancellation, with dependency-injected authoritative read catalogs and no permissions expansion. Choices must be reloaded at action time, not treated as authority. Slice 3 passes compatible verified process-local context to legacy handlers without breaking direct callers. Slices 4–7 replace or deliberately sequester the **whole** ordinary routes and track the #110 raw prompt delta. No new main-menu Planning Signal task.

Slice 1 intentionally does **not** hide the existing raw-ID prompts, add a selector engine, cache live records, read student files, grant source access, or publish/modify any canonical record.
