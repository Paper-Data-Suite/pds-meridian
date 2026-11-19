# Meridian #126 — Slice F2A: teacher-reviewed correction Save and Use

**Baseline:** `cbfe34a887624b535c3d5b0f6803bb2397c31023` (accepted F1, branch `126-verified-correction-attempt-reassessment-management`). This slice is Meridian-owned, not a ScoreForm/Quillan/Concord or Core change.

## User journey

F1 assessment-level queue → selected authorized student → **C. Review teacher-verified correction** → explicitly identify original native observation → explicitly identify distinct *operative-eligible* result intended for current academic use → required teacher explanation → review exact proposed #30/#122 action → **Save and Use This Decision** or Cancel. Successful qualified save reports exact independently verified current selection and returns to a refreshed F1 queue. Previously recorded source attempts remain in history.

The original observation may be inoperative/excluded; the current-use result may not be. Source point values, sequence numbers, timestamps and scan review references are displayed as public facts, **never used to choose a result**. The menu never certifies that ScoreForm itself published a causal correction. Instead it encodes an attributable *teacher-reviewed correction treatment* into the exact immutable #30 rationale using Slice C. No unreviewed independent correction authority is created.

F2A is the **one-selected-attempt correction path**; genuine multiple-current-attempt reassessment and policy/relationship navigation are separately planned for F2B. F2A never writes #31, never creates a selection policy, and refuses a missing/unqualified exact-one #30 policy. Policy creation or selection is a distinct explicit action, through existing #110/#122. It uses #121 saved actor identity only once, without a repeated name prompt.

## Authority and failure model

- Entry requires the same current authorized F1 inventory, a unique authorized roster identity, an included Grade Item membership, a supported current #30 status, at least two source-reported native observations, and a distinct eligible replacement.
- The selected policy preset is the single qualified `minimum_selected=maximum_selected=1` preset; it must already be **ready** in canonical state. Nothing is implicitly created or selected.
- `preview_attempt_interpretation` captures the exact original/selected attempts and teacher explanation; `prepare_reviewed_attempt_resolution` from D1 rereads current roster, source and eligibility, binds teacher attribution, verifies policy and prepares the one #122 academic action.
- Only the teacher choosing the exact **1. Save and Use This Decision** triggers the D1 action. Enter, B or 2 cancels without writing. M/Q propagate through Core shared navigation. Free-text rationale is never interpreted as a menu command, including `:notes`.
- D1's #122 action is the *only* immutable decision writer/CAS selector. Its independent canonical #30 readback must report exact operative current before this menu says **Current Verified** or proposes Standards review.
- Exceptions once a write might have started are **uncertain**, not rolled back. The menu forbids blind reapply and points to existing #122 recovery. A single menu invocation never retries a write.
- Source/roster/policy/profile mismatch before action preparation blocks without an academic write. A successful or interrupted decision always invalidates the F1 in-memory roster view, forcing a new authorized projection before the next student task.

## Non-goals and pending release evidence

Not a writer for producer scans, Core publication, #29 eligibility, #31 reassessment, Standards, proficiency, Grades, SIS or Reports. This does not demonstrate final 29x6 **installed ScoreForm** human UX acceptance, merged CI, or A1–A18 completion. F2B will add the genuine reassessment path; F3 will add explicit History, recovery and continuation actions. Repeated equivalent teacher requests and D4 installed composition need dedicated final integration/recovery qualification.

## Qualification

Synthetic F2A regression cases cover explicit original/replacement identity, existing exact-one policy requirement, cancellation before writing, saved actor failure, stale authority and invalid student scope, no implicit eligibility writes, one guarded confirmation, literal `:notes` rationale, uncertain #122 outcomes, M/Q navigation and refresh of the assessment queue. Regressions also include F1 Evidence Inbox, #126 #30/#31/#122 and native storage interruption tests. The guarded acceptance runner requires the exact F1 accepted commit, a clean branch, installed noneditable Core 0.6.6-compatible distribution, package hash verification, Ruff, targeted strict mypy, pytest, docs and Git whitespace checks before conditional commit/push. No merge.
