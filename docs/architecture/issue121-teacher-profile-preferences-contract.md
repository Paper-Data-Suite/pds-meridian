# Issue #121 — Teacher profile, preferences, and classroom context contract

**Parent:** [#120](https://github.com/Paper-Data-Suite/pds-meridian/issues/120)
**Work item:** [#121](https://github.com/Paper-Data-Suite/pds-meridian/issues/121)
**Branch:** `121-persistent-teacher-identity-preferences-classroom-context`
**Contract baseline:** Meridian `main` at `acd703442a9f09cf1da3c89051ec193a5b610714`; Core `main` at `bf3e6c08dd3f51e47cdbe56b11a3873a9d4491b3` (October 17, 2026).
**Slice 1:** Design and characterization only; no changed teacher-facing behavior.

## 1. Classroom problem and measurable outcome

A single-teacher installation must not ask the teacher to type their name or actor ID for each Grade Item, eligibility, attempt, Standard-association, proficiency, override, snapshot, export, or planning operation. The verified live ScoreForm walkthrough required repeated identity entry while processing only one question for one student in a six-question, 29-student assessment. The observed interaction count does not scale to ordinary teaching.

**Required outcome of #121:** After a single explicit setup, routine actor prompts are **zero** across all Meridian teacher workflows and after relaunch. Teacher attribution remains explicit in each durable academic record. Identity is *not* authentication or access authorization. Other #120 tickets own bulk grading and combining write/current-selection operations.

## 2. Existing architecture and inventory

`meridian/teacher_session.py` defines `TeacherSessionContext`, a process-local navigation object. It carries active class, `ModuleWorkRef`, publication ID, Grade Item ID, and student ID. Changing parent scope clears dependent selections. `menu.py` clears it on Q/EOF/Ctrl+C; `M. Main Menu` retains it while the process runs. Do not turn this object into a second academic authority or serialize student scope.

Current teacher identity prompts as of the baseline:

| Menu controller | `Teacher name for attribution:` | `Teacher actor ID:` |
| --- | ---: | ---: |
| `menu_teacher_eligibility.py` | 1 | 0 |
| `menu_teacher_attempts.py` | 1 | 0 |
| `menu_teacher_grade_items.py` | 1 | 0 |
| `menu_teacher_standards.py` | 1 | 0 |
| `menu_teacher_proficiency.py` | 1 | 0 |
| `menu_evidence.py` (legacy) | 0 | 3 |
| `menu_grade_items.py` (legacy) | 0 | 2 |
| `menu_proficiency.py` (legacy) | 0 | 2 |
| `menu_overrides.py` | 0 | 2 |
| `menu_snapshots.py` | 0 | 2 |
| `menu_export.py` | 0 | 3 |
| `menu_planning_signal.py` | 0 | 1 |
| **Total** | **5** | **15** |

This is a *baseline*, not permission to preserve legacy prompts. Slice 1 acceptance checks prevent new occurrences at unreviewed sites while allowing the known prompts to disappear in later slices. Any newly named actor prompt or use of direct `input()` for actor identity must be identified in the adoption audit before finishing #121.

Relevant existing tests include `test_teacher_session_context_issue110.py`, `test_teacher_menu_composition_issue57.py`, and `test_issue110_teacher_interface_contract.py`. The last test preserves an existing legacy raw-ID prompt inventory; #121 should not alter that fixture unless a removal truly changes its sites, and those removals must be documented.

## 3. Ownership decision and compatibility boundary

**Confirmed:** Core `pds_core.workspace` supplies `get_workspace_config_path()`, platform-specific per-user configuration locations, workspace-root resolution, and an atomic JSON write pattern. Core's public `WorkspaceConfig` currently contains only `workspace_root`. No public Core teacher-profile contract was identified in this audit.

**Decision:** A PDS-wide teacher identity is a candidate **Core-owned shared convention**, not an independently invented canonical Meridian actor identity for all other apps. #121 may ship an initial **Meridian-owned compatibility adapter/provider** for local self-declared identity while Core does not supply a released contract. Keep it behind a documented interface, separate from academic records, and explicitly plan shared-contract adoption before telling other modules to read it. A Core-owned API requires a separate Core issue, release qualification, and an explicitly upgraded dependency; #121 must not import unreleased Core functions or rewrite Core's `config.json` schema.

**Provisional storage boundary for slices 2–3:** Store Meridian-local settings under a restricted application-owned child of `get_workspace_config_path().parent`; do not modify Core's existing `config.json`. Keep settings **outside the academic workspace** (including OneDrive), while using the Core-resolved workspace as an ephemeral key for workspace-scoped navigation hints. Avoid storing raw workspace paths in settings, or use only documented privacy-bounded tokens. Resolve exact paths and applicable link/reparse checks at the eventual storage implementation; this document does not create a storage path or file.

Future migration must preserve existing actor values in historical records, map the explicit profile forward without changing actor identity silently, and handle older local profiles before replacing them. If Core shared support is not part of the #121 release, document its limitations and leave a stable provider seam for subsequent cross-PDS adoption.

## 4. Planned contracts for later slices

### Explicit attribution profile

- First-use teacher-controlled **display name** and stable **actor ID**; never infer either from OS username, Git identity, file owner, or student data.
- Validated, versioned and bounded profile with controlled Unicode name handling, unambiguous actor identity, and deliberate change/reset.
- A provider resolves the *concrete* actor value and display name for an operation; downstream canonical services continue receiving exact actor strings.
- Actor ID remains stable when a teacher edits only the display name. An identity change affects future records only, with no rewrite of immutable audit history.
- Routine review screens may display `Recorded by: ...`; authoring that needs identity blocks with an actionable setup route if no valid profile exists. Non-mutating views remain available where safe.
- A temporary per-operation override does not modify the saved profile.
- Stored teacher identity is not authentication. It does not grant `review_evidence` or `teacher_reporting` access and cannot replace the existing protected-read authorizer.

### Durable preferences and safe resume

- Persist only the explicitly selected preferred school year and class, and optionally a *resolvable* work/assessment hint; other preferences only when they have a real UI consumer.
- Do **not** persist selected student, protected evidence, eligibility, attempt, Standard judgment, Grade result, cache entry, publication authorizer, or a whole `TeacherSessionContext`.
- A remembered selection is a **hint**, never a verified/current record. At the next launch, validate workspace identity, year, class, and any chosen work against Core before offering resume. A publication/Grade Item/student is *not* silently reselected from disk.
- Switching workspace/year/class/work/publication invalidates dependent context through the existing scope-clearing rules. Q/EOF/Ctrl+C continues clearing in-memory `TeacherSessionContext`; preferences remain durable.
- Profile changes and preference writes must not generate academic decisions, touch protected publication bytes, or create workspace records on launch.

### Persistence and concurrency

- Strict version/schema validation, bounded reads, atomic flush/replace, safe permissions, and explicit treatment of corrupt, too-large, incompatible, unreadable, or symlink/reparse-point files.
- Prevent path traversal and write-through links; scope profile configuration to the local user without credentials/tokens or student data.
- Save/update/reset deliberately; protect concurrent writers via expected-version/fingerprint preconditions or an equivalent verified method. Never quietly overwrite a more recent profile or salvage unsafe malformed content.
- No background process, cloud account, district-specific path, or new secret store is required.

### Existing interface and migration

- Preserve direct noninteractive CLI explicit-actor semantics unless an intentional backward-compatible opt-in is separately specified.
- Inject the actor provider through menu dependencies and session composition, not a global singleton; injected tests must remain deterministic.
- Apply the provider to **both** the five guided prompt sites and the fifteen legacy prompt sites. Any other actor-reading route found during implementation is also in scope.
- Show current identity and offer edit/reset/temporary override via Settings/Advanced; do not add a required extra identity confirmation to academic workflow screens.
- #122 owns combined academic write+current-selection; #121 must not change those transaction semantics.

## 5. Slice sequence and handoff gates

1. **Slice 1 — contract baseline:** This document and focused guard tests, with no runtime behavior change.
2. **Slice 2 — profile/provider/storage:** Durable identity, versioned schema, safe local storage, explicit setup/edit/reset and adversarial tests.
3. **Slice 3 — preferences/resume:** Workspace-scoped class/year hints and validation without protected reads or phantom selection.
4. **Slice 4 — menu/settings composition:** First-use screen, quiet identity display, Advanced changes, provider wiring.
5. **Slice 5 — prompt adoption:** Remove twenty baseline identity prompts via shared provider; update legacy prompt quarantine evidence only for actual changes.
6. **Slice 6 — qualification:** Focused tests plus clean installed wheel, Windows path assessment, and explicit end-to-end setup → quit → restart → author → edit → restart acceptance.

**Slice 1 gate:** Existing guided/session and legacy contracts still run; the documented prompt baseline agrees with source; the design does not conflate identity, navigation, protected access, and academic authority.

**Final #121 gate:** One-time explicit setup; **zero routine actor re-entry** across all relevant menu paths; no backward-incompatible direct CLI change; safe restarts, workspace scope changes, attribution history, and installed acceptance. Test-only success without a real teacher journey is insufficient.
