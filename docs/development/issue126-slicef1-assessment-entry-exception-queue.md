# #126 Slice F1 — Assessment Entry and Read-Only Attempt Exception Queue

## Authority and bounded Slice E closure review

Starting from accepted E3B `a751a3a9a8a1ca6832fdf8221636a10e07c2d397`, Slice E's focused implementation and test exit gate is **satisfied within its documented synthetic/native boundaries**:

- E1: read-only durable #30/#31 and #122 receipt reconciliation.
- E2A: explicit restart of a persisted immutable #31 selection using its original journal; no reauthor.
- E2B: newly reviewed #31-only continuation when a prior #30 action is current and no competing #31 journal or immutable revision exists.
- E3A: native temporary-workspace immutable files, current pointers, CAS and receipts under interruption.
- E3B: production `prepare_reviewed_reassessment_action` under installed Core 0.6.6 and synthetic authorized producer/roster/calendar/profile inputs. Acceptance: 285 passed, 2 Windows symlink-permission skips.

**Not claimed by E closure:** genuine ScoreForm producer publication/roster authorization, installed D3/D4 menu journey, Report 9, packaged full-suite CI, or A1–A18 final acceptance. No merge or release is authorized here. Issue #126 remains open. E closure is a *focused slice* judgment, not a release qualification.

## F1 implementation

`meridian/menu_teacher_corrections.py` supplies a read-only teacher screen entered from the **already authorized Evidence Review assessment**. The `menu_teacher_evidence.py` change adds `Review Corrections & Attempts` to the assessment summary and wires the default handler; injection-based callers can omit the handler. The existing #110 row-level attempt menu remains available unchanged.

1. Retain and verify current session work, class and publication identity. Reuse #124 selected/current included Grade Item choices, with no silent setup. If the session or source is invalid, show an explicit blocked message rather than opening native history.
2. Call the existing #126-B `project_assessment_attempt_inventory` for this exact prepared authorized projection. It already composes #125 eligibility, source-native attempt references, #30 current selection and necessary #31 state. The menu additionally compares work/class/publication/cache/digest/Grade Item and rejects duplicate student IDs and stale source presented as current.
3. Display an **exception-first authorized roster**. A toggles all authorized students; E returns to exceptions; N/P page through windows of 20; R reloads the exact projection. Paging and returning from a student screen do not silently reread an entire class.
4. Student detail shows source-reported points/origin, scan-review references, operative eligibility, #30 state, #31 state and attention. The correction cause remains **unverified by this display**; scores, attempt sequence, and revision order never imply correction or retake.
5. H displays source attempt history; T displays explicit technical source and student IDs within the already authorized scope. Ordinary queue and detail screens omit raw IDs, hashes and URLs. B returns, M/Q propagate the existing Core navigation exceptions.
6. No implementation path in F1 accepts a `TeacherActionActor`, prepares a #122 action, changes policy, writes or selects #29/#30/#31, or creates receipts. It does **not** mark a decision applied/current or open Notes.

Inputs `:notes`, arbitrary rationale, search strings and direct CLI arguments are **not** parsed as shared commands; F1's keyboard shortcuts are only for the controlled menu-choice prompt. ANSI/control characters from roster/source display labels are sanitized, not interpreted. No dependency on unpublished Core header/UI capabilities was added; `print_menu_header` is a plain accessible fallback.

## Intentional limits and next slices

F1 is deliberately read-only. It does not yet implement **F2: per-student correction/reassessment choice and guarded confirmed Save and Use**, nor **F3: student-scoped recovery, full canonical decision History and finish/Standards route**. The label *Source Attempt History* intentionally does not claim to be a complete #30/#31 revision journal.

A missing included Grade Item returns to Published Assessment Setup (#124); missing/uncertain eligibility returns to the existing #125 review, not implicit Include. Existing publication reauthorization is not invented or broadened. An assessment's native attempt capability and its exact authorized projection remain the only source of candidate identity.

## Focused qualification and acceptance ledger

The F1 runner enforces the accepted E3B HEAD, clean workspace, branch/remote equality, installed noneditable Core 0.6.6 compatibility, ZIP file checksums and narrowly bounded source paths before modifying Git. It applies one fail-closed guarded patch to `menu_teacher_evidence.py`, copies the new menu/tests/doc, runs focused Ruff, strict mypy, new F1 menu tests and existing evidence/attempt/regression tests, documentation and whitespace checks. It commits/pushes only when all gates pass.

- **A1:** D1 source entry plus new F1 menu tests; installed D3/D4 pending.
- **A2/A6/A7:** historical/native facts shown without causal certification; cross-producer installed validation pending.
- **A3/A4/A5:** F1 shows authorized candidates but performs no interpretation/save; F2 required.
- **A8/A9/A10:** read-only immutable inventory and current eligibility labels; real producer qualification pending.
- **A11:** source/snapshot/work/Grade Item/session mismatches blocked; concurrent action precommit is F2.
- **A12:** one assessment-level entry, exception-first roster, no technical IDs/name reentry; teacher usability study pending.
- **A13:** no academic mutation possible in F1; F2 cancellation requires separate qualification.
- **A14/A15:** E1–E3B focused recovery suites accepted; D4 installed journey pending.
- **A16:** keyboard/plain fallback and B/M/Q/`:notes` tests in F1; Core capability matrix and installed D3/D4 remain Slice G.
- **A17:** downstream consumer audit deferred to H, #133/#134 remain independently owned.
- **A18:** final wheel/CI/full validation deferred to J.

**No A-row should be marked finally complete from this F1 acceptance alone.** All fixtures synthetic, no classroom data.
