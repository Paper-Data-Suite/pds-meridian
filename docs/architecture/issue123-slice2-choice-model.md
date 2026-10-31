# Meridian #123 — Slice 2: Read-only Choice Model and Renderer

**Base:** Slice 1 commit `81c7579f079da003e7fd917406582ac974a3383f` on `123-teacher-first-navigation-existing-menus`.

**Status:** Common navigation foundation only. This slice does **not** activate new teacher menu workflows, create academic data, or alter Reports 1–9.

## Files

- `meridian/teacher_navigation_choices.py` — typed transient `TeacherChoice`, `TeacherChoiceCatalog` protocol, bounded scope catalog validation, Unicode-safe display-only search, pagination, and a narrow `ReportOption` adapter.
- `meridian/teacher_navigation_terminal.py` — injected, keyboard-first terminal selector with Back/Main/Quit, search/clear, paging, manual refresh, and opt-in single-row Advanced technical details.
- `tests/test_issue123_slice2_teacher_choices.py` — synthetic read-only, identity, freshness, accessibility and adversarial contract tests.

## Exact identity, not display authority

Each candidate has an opaque, nonempty tuple of canonical identity parts. Labels, details, source and status are teacher-readable presentation. A separate optional `witness` carries an exact read-only revision/digest from a domain source. Identity and witness do not appear in normal output and are **never accepted from text labels**. They can be inspected for one selected visible row under `T. Advanced / exact record details`.

The common model is not a new canonical academic record, authorization grant, or `TeacherSessionContext` extension. `TeacherChoiceCatalog.options(scope=..., selected=...)` is an injected read-only discovery contract. Domain adapters (implemented in subsequent slices) will provide verified, class/year-scoped candidates using Core and Meridian's existing authoritative read APIs. The shared service does **not** read arbitrary producer private files or inspect protected student answers.

A catalog with duplicate identities, identical normalized displays, invalid controls, unsupported types, or more than 500 results is unusable by design. The teacher needs a meaningful disambiguator from the owner, rather than an unreliable first-match or a guessed suffix. Names containing ordinary path punctuation render as inert text, never filenames. Display filtering never searches private exact identity tokens.

`load_teacher_choices` makes a bounded read, and `page_teacher_choices` searches/slices that read in memory. An explicit `R` refresh or row selection triggers a fresh read. Choosing a numbered row checks the entire candidate (including witness and display) against a fresh result. A mismatch forces another deliberate choice. An only-available row is **not** selected automatically.

**Important:** The selector's fresh-read check does not replace execution-time authorization, source currentness, exact compare-and-swap, or a #122 Save/Apply receipt. Domain workflows must *reload* the chosen canonical record, its current pointer/dependencies, and permission at the consequential action boundary. If no witness can be provided by a supported public source, a domain adapter must not infer one. No automatic academic author/select or export action is reachable from these new modules.

## Terminal contract

| Input | Behavior |
| --- | --- |
| `1`–`25` | Choose an actually visible row (a second catalog read must match exactly) |
| `N` / `P` | Next / previous bounded page, where present |
| `S` | Search visible descriptions, case-insensitive with Unicode NFKC/casefold |
| `C` | Clear the search and return to the first page |
| `R` | Explicitly refresh the bounded catalog |
| `T` | Advanced diagnostics for **one** numbered visible row |
| `B` or blank | Cancel without a selection or write |
| `M` / `Q` | Propagate existing Core main-menu/quit navigation exceptions |

Maximum page size is 25, default is 10. Search length is bounded to 120 visible characters. Terminal control, bidi/invisible format, and multiline characters are rejected in display inputs and searches. An empty result still presents search, refresh, and navigation; it never silently chooses a replacement. Errors from domain readers are not printed to the teacher-facing terminal.

This surface is deliberately keyboard-first and screen-reader-friendly: contiguous numbering per page, text labels, page counts, explicit shortcut help, no ANSI decoration or cursor positioning. It supports a simple injected `input_fn`, `output` stream and `clear_fn` for tests and all terminal implementations.

## Relationship to existing components

- **#111 Reports:** `choices_from_report_options` is a one-way adapter from existing `ReportOption` identities/labels; `collect_guided_report_selection` and `LiveReportChoiceCatalog` are unchanged. Domain wiring can reuse this model without replacing working report logic.
- **#110 prompt quarantine:** neither new file is a legacy `menu*.py` controller or introduces an `input_fn` prompt asking for an ID, revision, digest, or cache key. Slice 1's frozen raw-prompt count and 49-operation inventory remain unchanged.
- **#121 teacher profile/preferences:** no persistent context or student metadata is stored. Session integration remains Slice 3.
- **#122 actions and recovery:** the new layer offers **no** Save/Apply implementation, academic mutation, receipt, or authorization bypass.

## Qualification boundaries

Slice 2 adds behavior-level tests for Unicode equivalent duplicate labels, duplicate exact IDs, first-only choice no auto-selection, witness/label/identity staleness, exact row selection on paged lists, filter isolation, empty and oversized catalogs, B/M/Q, opt-in technical details, error sanitization, and read-only cancellations. The committed source and issue #123 Slice 1 audit are preserved; the runner does not modify any legacy controller or #111 source.

The final #123 acceptance criteria (real authoritative domain catalogs, per-menu migration, retained class/period context, before/after keyboard counts, installed-wheel acceptance and full CI) remain future slices. The standalone Slice 2 selector cannot truthfully claim these have been completed.

## Domain adapter example (future slice)

```python
# A caller injects a Core/Meridian-backed read-only catalog;
# the selector neither creates nor verifies that catalog's authority.
choice = select_teacher_choice(
    catalog=domain_catalog,
    scope="student",
    selected={"class": verified_class_id},
    title="Select student",
    question="Which student?",
    input_fn=input_fn,
    output=output,
    clear_fn=clear_fn,
)
if choice is not None:
    # Domain service: reload the canonical record, check its exact identity,
    # state and authorization, then perform a separately reviewed action.
    ...
```
