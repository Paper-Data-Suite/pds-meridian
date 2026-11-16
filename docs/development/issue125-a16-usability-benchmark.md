# Issue #125 A16 usability benchmark

Status: **A16 satisfied.** The assessment-level batch workflow materially
reduces observed teacher interaction for the exact synthetic 29-student,
six-question ScoreForm case while producing the same selected-current
eligibility outcomes as the existing individual workflow.

This is an automated scripted-menu benchmark, not an observation of a human
teacher's reading, thinking, or typing time. No human completion-time or
classroom speedup ratio is claimed.

## Qualified baseline

The required baseline was
`dd7f1f3e90da658ae7c984faee39a273b7d2a08d`. GitHub Actions run
`43770225476` completed successfully with all eight Ubuntu/Windows jobs for
Python 3.11, 3.12, 3.13, and 3.14. Draft PR #144 pointed to that exact commit
when this benchmark began. Work occurred in a separate Git worktree.

## Fixture and equivalent intended outcomes

Both workflows used independently initialized synthetic workspaces produced by
the released ScoreForm publication APIs and the existing native acceptance
fixture. Each workspace contained:

- 29 Core roster students;
- one six-question ScoreForm attempt per student;
- 406 native evidence items in the authorized Meridian projection;
- one current included Grade Item relationship and Academic Period;
- the same saved synthetic teacher identity and eligibility policy; and
- no eligibility decisions when timing began.

Each student contributes 14 source items: two attempt-level items
(`attempt_points` and `result_origin`), six selected-response items, and six
question-correctness items. Across 29 students this is 406 items. The benchmark
intentionally selects only the 174 question-correctness items. The other 232
items are authoritative source evidence but are not the routine eligibility
scope and remain without eligibility decisions.

The equivalent intended outcomes were:

- 167 question-correctness items Included;
- all six correctness items for synthetic `student001` Excluded as one student
  exception in the batch workflow;
- question 1 for synthetic `student002` Pending as one exact-item exception;
  and
- no rationale, with `eligibility.manual` on every non-Include decision.

The stored disposition, reason codes, rationale, policy, actor, and revision
were compared by synthetic student and question target across the two
independent workspaces. They matched exactly. Each workflow created 174 new
action receipts, all decisions were selected-current revision 1, and all 232
non-target source items remained untouched.

## Measured production-menu routes

The individual measurement entered the real evidence inbox and used the real
individual eligibility continuation for every correctness item. It selected
class, assessment, represented students, each displayed evidence row, Grade
Item, disposition, policy, teacher attribution, Save, verified result, and the
required Back navigation. It did not call the storage API directly.

The batch measurement entered the same real inbox in a fresh workspace and
opened the assessment-level eligibility route. It selected the Grade Item once,
filtered the now-disambiguated display labels by `question correctness`,
selected all 174 filtered rows over nine pages, chose common Include, reviewed
one student exception and one exact-item exception, entered attribution once,
and confirmed the exact plan with one `APPLY`.

Screen transitions are calls to the production menu's `clear_fn`. Inputs are
all values returned to production `read_choice` calls, including navigation and
read-result pauses. Substantive confirmations are the 174 individual
`Save and make current` choices versus the one batch `APPLY`.

## Actual comparison

| Metric | Individual workflow | Batch workflow |
| --- | ---: | ---: |
| Native source items visible to projection | 406 | 406 |
| Target items | 174 observed correctness items | 174 observed correctness items |
| Other source items left untouched | 232 verified | 232 verified |
| Teacher inputs | 1,805 | 40 |
| Screens/transitions | 1,631 | 38 |
| Substantive confirmations | 174 | 1 |
| Repeated Grade Item selections | 174 | 1 |
| Repeated policy interactions | 174 | 1 |
| Repeated teacher-attribution/actor interactions | 174 | 1 |
| Canonical evidence or Grade Item IDs entered manually | 0 | 0 |
| Automated full menu/action elapsed time | 1,345.371 s | 44.507 s |
| Separately instrumented canonical execution | 37.229 s, sum of 174 individual `PreparedGuidedAction.apply` calls | 42.473 s, one sealed batch executor including per-item progress and verification |
| New action receipts | 174 | 174 |
| Final canonical state | 167 Included, 6 Excluded, 1 Pending; verified selected-current | Same exact outcomes; verified selected-current |
| Collateral workspace changes | 0 outside allowed Meridian eligibility/receipt paths | 0 outside allowed Meridian eligibility/receipt/progress paths |

The observed reduction is 1,765 fewer scripted teacher inputs, 1,593 fewer
screen transitions, 173 fewer substantive confirmations, and 173 fewer repeated
Grade Item, policy, and attribution interactions. These direct count
differences establish the intended interaction benefit without converting the
automated timings into a human speedup ratio.

The batch's separately instrumented canonical duration is not expected to be
less than the sum of individual `apply` calls: the batch timing also includes
sealed progress records, batch preflight, and per-item verification. The
like-for-like full production-menu elapsed measurement includes navigation,
preview preparation, source/current-state checks, rendering to an in-memory
stream, canonical execution, post-write reloads, and final verification for
both paths.

## A16 defect found and corrected

Before the benchmark, the assessment selector displayed ScoreForm's
selected-response and correctness rows with the same student/question label.
The teacher could not choose exactly the 174 correctness targets without
depending on hidden ordering or canonical IDs. A failing regression captured
that ambiguity.

The minimal correction adds the teacher-readable result kind only when two
selectable rows for the same student otherwise share the same evidence label.
For example, the rows become `Question 1 · Selected response` and
`Question 1 · Question correctness`. Unique labels are unchanged. Candidate,
replaceable, and batch-exception selection use the same disambiguation. No raw
identifier, automatic selection, authorization, source, CAS, eligibility, or
recovery behavior changed.

## Measurement environment

The two workflows ran sequentially in one pytest process with no competing
benchmark workload:

| Component | Observed value |
| --- | --- |
| Workstation | Micro-Star International Claw 8 AI+ A2VM |
| CPU | Intel Core Ultra 7 258V, 8 cores / 8 logical processors, reported 2,200 MHz maximum |
| Memory | 33,866,657,792 bytes installed (approximately 31.5 GiB) |
| OS | Microsoft Windows 11 Home, 64-bit, version 10.0.26200, build 26200 |
| Python | 3.14.1 |
| pytest | 9.2.0 |
| Ruff | 0.16.1 |
| Core | 0.6.6 |
| ScoreForm | 0.13.0 |
| Quillan | 0.10.6 |
| Concord | 0.3.2 |
| Meridian candidate | 0.4.2 |

Fixture creation, producer publication, Grade Item setup, and initial
projection preparation occurred before each workflow timer. The workspaces were
independent so the first workflow's decisions could not accelerate, block, or
otherwise change the second workflow's initial state.

## Reproduction and qualification

Installed native benchmark, executed from a source-free harness with Meridian
loaded from the candidate wheel in `site-packages`:

```text
PDS_ISSUE125_A16_NATIVE_TEST=1
python -m pytest -q -s tests/test_issue125_a16_usability_benchmark.py
2 passed in 1400.74s (0:23:20)
```

The emitted measurement record was:

```text
A16_BENCHMARK python=3.14.1 platform=Windows-11-10.0.26200-SP0
evidence=406 targets=174 other=232
outcomes={'excluded': 6, 'included': 167, 'pending': 1}
individual_inputs=1805 individual_screens=1631 individual_confirmations=174
individual_grade_selections=174 individual_actor_policy_interactions=174
individual_elapsed_seconds=1345.371 individual_canonical_seconds=37.229
batch_inputs=40 batch_screens=38 batch_confirmations=1
batch_grade_selections=1 batch_actor_policy_interactions=1
batch_elapsed_seconds=44.507 batch_canonical_seconds=42.473
manual_canonical_ids=0 receipts_each=174 collateral_paths=0
```

Focused source regression and affected selection/navigation tests:

```text
python -m pytest -q \
  tests/test_issue125_a16_usability_benchmark.py \
  tests/test_issue125_slicef1_assessment_menu.py \
  tests/test_issue125_slicef2_teacher_hardening.py \
  tests/test_issue125_h3a1_status_navigation.py \
  tests/test_issue125_h3a2_resolution_navigation.py \
  tests/test_issue125_h3d10a_authorized_filter.py \
  tests/test_issue125_h3d5_status_route_terminal_matrix.py
148 passed, 1 explicit native-gated skip in 1.56s
```

Static and formatting checks used:

```text
ruff check meridian/menu_teacher_assessment_eligibility.py \
  tests/test_issue125_a16_usability_benchmark.py
ruff format --check meridian/menu_teacher_assessment_eligibility.py \
  tests/test_issue125_a16_usability_benchmark.py
python -m mypy meridian/menu_teacher_assessment_eligibility.py
python scripts/check_documentation.py
```

## Artifact identities

| Distribution | Version | SHA-256 |
| --- | --- | --- |
| `pds-core` | 0.6.6 | `d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301` |
| `scoreform` | 0.13.0 | `4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7` |
| `quillan` | 0.10.6 | `7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb` |
| `pds-concord` | 0.3.2 | `825b27bc6142cc8bce8c3b9381a3337c4a55e983f6f3f2e7e4b1a10f980e83ce` |
| `pds-meridian` candidate | 0.4.2 | `e4c998be6fbdb357d4b1c59104daaf3d356051b1a83ad11d8b43d06fc0fc2f5c` |

## Limitations

1. Scripted input removes human reading, thinking, motor, and classroom
   interruption time. Automated elapsed values must not be presented as human
   completion times.
2. The expensive full comparison was run once after the verifier correction.
   Interaction counts are deterministic production-menu observations, but the
   wall-clock values are single-run workstation measurements rather than a
   statistical performance study.
3. The individual canonical timing is the sum of 174 action `apply` calls; the
   batch canonical timing is the complete sealed batch executor. Their scopes
   are intentionally labeled and are not used to claim a storage-layer ratio.
4. The benchmark covers the required 29-by-6 native ScoreForm fixture and its
   stated exception pattern. It does not generalize timing to every producer,
   roster size, device power state, or storage medium.
5. The full repository validator was not repeated. It remains the later A18
   gate; A18 was not begun here.

