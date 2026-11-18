# Issue #126 — Slice A: correction and attempt contract baseline

**Branch:** `126-verified-correction-attempt-reassessment-management`
**Source base:** merged Meridian `main` at `cb960283d20db13fd7498f7f357d9a1d2d28ef5f` (initial branch state; recheck future HEAD).
**Status:** Baseline contract and synthetic regression completed; **no correction-aware teacher workflow has yet been implemented**.
**Scope:** Read-only audit, synthetic canonical-model tests and the precise Slice B entry contract. No new persisted schema, producer writes, policy change or shared Core dependency.

## Decision A1 — Existing Meridian authority is sufficient for explicit selection

- `meridian/attempt_selection.py` and `attempt_selection_storage.py` own immutable per-student policy/decision revisions, producer-native attempt identity, exact authorized projection/eligibility bases, current pointers and canonical current-state resolution. An attempt number is a native identity component **not** an educational precedence or correction cause.
- `meridian/reassessment.py` and `reassessment_storage.py` own explicit `retain`, `replace`, `combine` and `recency` interpretations, bound to the exact upstream attempt-decision revision/digest. A single current selected attempt needs no ceremonial inter-attempt relation.
- `meridian/teacher_action_orchestration.py`, `teacher_action_restart_attempt.py`, and #122 adapters supply reviewed write/select, CAS, receipts and fresh-authorized recovery. Receipts are not academic authority.
- `meridian/menu_teacher_assessment_eligibility.py` and #125's review/progress/recovery modules own student-grouped operative eligibility. A correction/attempt review must consume that state, not create a second eligibility selector.
- The new teacher workflow may project **read-only interpretation hints** and explicitly record teacher reasoning via authorized existing decisions. Do **not** create another attempt-selection current pointer or policy automatically. A new correction-interpretation schema remains **unapproved** until a genuine gap in #30/#31 actor/rationale/provenance is demonstrated.

## Decision A2 — Producer correction fact is not teacher's academic interpretation

| Observed case | Public source fact | Permitted Meridian behavior | What cannot be inferred |
| --- | --- | --- | --- |
| ScoreForm scan first recorded 0/6; teacher corrects to 6/6, later numbered Attempt 2 | Both native attempt observations and their source provenance; correction cause **only if declared by the qualified public reader** | Teacher can select exact corrected result and record attributable correction rationale. Keep Attempt 1 in history | Two scores, new number, or later publication alone do not certify the same original paper |
| Student performs real second sitting | Two native attempts; the reason for second sitting may require teacher input | Explicit attempt selection and #31 relationship when multiple contribute | Latest, first, highest or best result is not a default academic rule |
| Later ScoreForm manifest revision republishes history | New exact producer/Core publication state, possibly the same native attempts | Revalidate current source and existing selected bases; preserve historical revisions | Record-set revision is not attempt number |
| Quillan revised review/publication | Quillan-native review correction and publication history | Respect current native evidence; attempt selection remains not applicable absent an explicit capability | Manifest revision 2 is not “Attempt 2” |
| Concord moderation/Score correction | Concord-native correction, supersession and scoring semantics | Preserve native score/moderation provenance; don't assign group observations to students | Score revision or moderation does not imply reassessment |
| Unknown, withdrawn, stale, denied or contradictory source | Insufficient current verified authorization/identity | Show separate `unresolved`/`stale`/`unsupported`/`denied` outcome and safe next action; do not save a guessed selection | Absence of source evidence is not zero or permission |

The classroom trigger uses 29 students, six questions, and a teacher-verified OMR error, but repository fixtures must remain synthetic and must **not** include the real student's identity, answer sheet or responses.

### Exact ScoreForm release/reader boundary

ScoreForm [#162](https://github.com/Paper-Data-Suite/pds-scoreform/issues/162) defines separate attempt numbers, producer record-set revisions, explicit Core publication-series supersession and preserved history. Existing Meridian #30 uses an explicit projected `attempt` target/native reference, and requires all selected candidates to come from **one** authorized immutable projection snapshot. **Do not inspect ScoreForm private files for a correction signal.** Before implementing a “producer-verified correction” label, verify the actual official released ScoreForm reader provides the necessary cause/provenance; otherwise label teacher-reviewed correction honestly and log a producer-owned follow-up if needed.

## Decision A3 — Main current usability defect is a missing correction-aware assessment view

The current `guided_attempts.py` has policy presets and per-student candidate labels of the form “Attempt N”, without causal correction classification. `menu_teacher_attempts.py` enters a single student's review, selects a Grade Item and policy, explicitly prompts for “Teacher name for attribution”, and then prompts for attempt choice and rationale. It correctly executes existing canonical write/select but is not the #126 target assessment-level exception-first workflow. It neither proves a correction from producer data nor gives the teacher an explicit correction-vs-retake decision view.

**Next Slice B must implement a read-only, bounded, authorized roster-grouped correction/attempt review** over existing #124/#125 context. It should separate:
1. current student/Grade Item/work and qualified producer/native attempts;
2. current selected #30 policy/decision and whether #31 is needed/resolved;
3. exact producer-publication lifecycle/source status;
4. producer-verified cause, teacher-reviewable cause or genuinely unresolved cause **without conflating them**;
5. source, membership, eligibility, authorization and candidate-set attention; and
6. a validated continuation target to #125 or the existing #30 menu.

All row labels must disambiguate identical names and preserve exact internal references. Review/preview must be zero-write. Do not produce a new decision from a score comparison.

## Decision A4 — Shared Core/Suite experience is a separate qualified seam

The normative [Suite Teacher Experience Design v0.2](https://github.com/Paper-Data-Suite/pds-paper-data-suite/blob/main/docs/design/teacher-experience-design-specification.md), [Core contract v1](https://github.com/Paper-Data-Suite/pds-core/blob/main/docs/teacher_experience_contract_v1.md) and [Suite dependency matrix](https://github.com/Paper-Data-Suite/pds-paper-data-suite/blob/main/docs/integration/teacher-experience-contract-matrix.md) require:
- `Meridian` green application name (when qualified and terminal-capable), current screen title and optional validated context; legible plain fallback for `NO_COLOR`, non-TTY, `TERM=dumb` and unsupported ANSI/Windows terminals;
- `B/M/Q` existing navigation and scoped `H`, keyboard paging, no command collision;
- `:notes` recognition **only at an explicitly enabled interactive menu-choice prompt**, never in search/rationale/free text, confirmations or unattended CLI;
- one meaningful reviewed action, independently verified current state and truthful no-write/partial/uncertain receipt;
- Core-owned roster/Standards authority and Suite-owned launch/home, without introducing producer-owned substitutes.

**Release distinction:** Core source `main` contains the #237 header/command parser with `terminal.header.v1` and `terminal.notes_command.v1`; official Core **0.6.6** predates both public capabilities. The Suite matrix does not establish D2 released-Core qualification. Consequently Slice B uses a readable existing Meridian header and does **not** import future Core UI interfaces unconditionally. When a real release qualifies them, adopt with per-capability probing and D3 installed Meridian collision/navigation tests. A parser capability alone does not supply Notes storage/menu; no fake `:notes` operation or structured student Notes context.

## Decision A5 — Report 9 is not a #126 shortcut

`report_menu_execution.py` and `benchmark_current_analysis.py` remain downstream clients whose exact attempt authority must be audited before reporting corrected item statistics. [#133](https://github.com/Paper-Data-Suite/pds-meridian/issues/133) owns the live Report 9 generation failure, and [#134](https://github.com/Paper-Data-Suite/pds-meridian/issues/134) owns multi-attempt item-statistics reconciliation. #126 owns the canonical selection and a clear consumer handoff, not an unverified claim that either report defect is repaired.

## Executable synthetic baseline and status

`tests/test_issue126_slicea_contract_baseline.py` constructs two exact native attempts under the same synthetic ScoreForm publication/projection and proves the existing immutable #30 model permits **different explicitly selected subsets with unchanged source facts**. It also checks that #31 relationship is separate and explicitly bound, different source digests cannot be conflated, and canonical resolution vocabularies preserve stale/unverifiable/unresolved states. Its test-only point totals cannot authorize academic selection.

These are **contract baseline** tests. They do not execute a corrected-scan UI or installed producer reader, and cannot close the A2/A3/A12/A16 gates. Full CI and native end-to-end qualification remain future obligations.

## Slice B entry gate

1. Verify exact branch SHA, clean worktree, official dependency-wheel identities and current public Core/Suite capabilities.
2. Construct a read-only assessment-level view of authorized **current** roster-attributed attempts and exception state from existing projections.
3. Demonstrate 29 × 6 synthetic ScoreForm inventory with one correction-like pair, one true retake pair, unknown/withdrawn/unauthorized states and unique student IDs; no sensitive records.
4. Distinguish verified source fact from teacher assertion; don't invent correction relation.
5. Preserve canonical #29 eligibility, #30 selection, #31 reassessment and #122 recovery as independent authorities.
6. Prove identical canonical storage bytes before/after read-only review; use focused tests, not repeated full-repo validators.

**Slice A acceptance:** contract audit and test fixtures only, 0 academic writes, no new schema, no sibling repository changes. No overall #126 A1–A18 acceptance criterion is closed by this baseline alone.
