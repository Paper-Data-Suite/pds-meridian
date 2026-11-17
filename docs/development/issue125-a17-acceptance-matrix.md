# Issue #125 A17 navigation acceptance matrix

Status: **A17 satisfied within documented supported boundaries.** The released
Core 0.6.6 contract supplies shared B/M/Q navigation, but does not publish a
module-facing app-header or Notes capability. Meridian therefore preserves its
plain, readable local header and treats `:notes` as inert input in prompts that
do not advertise Notes. No private Core CLI helper, new Notes provider, Suite
dependency, or academic action was added.

This closure is limited to A17 navigation and shared contracts. It does not
qualify A18, the final PR SHA, the full repository validator, or merge
readiness.

## Baseline and installed environment

The required baseline was
`dd466ff5ca961103ead1770921dfd2032e899ab5`. GitHub Actions run
`43984803358` completed successfully for that exact SHA with all eight
Ubuntu/Windows jobs for Python 3.11, 3.12, 3.13, and 3.14. Draft PR #144
pointed to the same SHA when A17 work began. Work and qualification occurred
in a separate Git worktree.

The source-free installed acceptance loaded Meridian from the candidate wheel
in `site-packages`, not from the repository. The exact installed versions were:

| Distribution | Version | SHA-256 |
| --- | --- | --- |
| `pds-core` | 0.6.6 | `d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301` |
| `scoreform` | 0.13.0 | `4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7` |
| `quillan` | 0.10.6 | `7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb` |
| `pds-concord` | 0.3.2 | `825b27bc6142cc8bce8c3b9381a3337c4a55e983f6f3f2e7e4b1a10f980e83ce` |
| `pds-meridian` candidate | 0.4.2 | `1f36d398d97e79052f198b7a72300bea701932b1b4544e1bb666bf5828cb26e4` |

## Acceptance matrix

| Scenario | Installed contract exercised | Observed result | Precise boundary | Verdict |
| --- | --- | --- | --- | --- |
| B/M/Q from assessment and Grade Item selection | Core 0.6.6 `NavigationChoice`, `parse_navigation_choice`, `ReturnToMainMenu`, and `QuitPDS` | B returns locally; M and Q propagate to their shared unwind boundary. Empty input remains a local cancel only where the menu documents it. | Meridian does not reinterpret Core exceptions or add a fourth global command. | Qualified. |
| Exception queue navigation | Real assessment exception queue plus Core navigation | N/P preserve the read-only page, B cancels assessment review, and M/Q unwind. `V` reopens the complete queue and `D` returns only to exact selection, never Apply. | The queue reports projected conditions; it does not manufacture producer failures that never became publications. | Qualified. |
| Authorized search/filter | Real exact-scope filter and authorized display labels | Student and evidence-label casefold matching works. Queries are limited to 80 printable characters. Blank, control, overlong, private-ID, and no-match queries select nothing. A failed search never becomes select-all. | Search is intentionally not a canonical-ID lookup and never widens the already-authorized candidate set. | Qualified. |
| Pagination and stable identity | Real 406-candidate ScoreForm selector and focused 174-item cases | Global displayed ordinals remain attached to the same exact candidates across N/P. Only visible page numbers toggle. B discards selections made on multiple pages. | Paging changes presentation only; it is not authority and does not persist a draft selection. | Qualified. |
| Terminal fallback | Meridian `StringIO`/noninteractive output, `NO_COLOR=1`, and Core navigation labels | Headers, navigation, paging, and exception text remain readable with zero ANSI escape sequences. | Meridian's released teacher menus do not claim terminal styling beyond readable plain text. | Qualified. |
| Core app-header capability | Public installed `pds_core.menu_navigation` surface | Core 0.6.6 exposes navigation labels, parsing, hinting, and printing. It exposes no public `app_header` or `print_app_header` contract there. Meridian uses its existing plain `Meridian` header. | Core contains an implementation header under `pds_core.cli_support`, whose package identifies itself as internal CLI support. A17 does not bind Meridian to that private module. | Supported fallback; no API invented. |
| Core Notes capability | Public installed Core 0.6.6 navigation surface and real Meridian prompts | No documented Notes-capability-present path is published to modules. `:notes` is inert in unsupported prompts, produces no plan or confirmation, and changes no academic or journal state. | A future public Core capability would require a separate integration. A17 does not introduce a provider or Suite dependency. | Supported fallback; no API invented. |
| Individual re-entry after batch cancel | Real installed ScoreForm inbox and evidence-detail menus | After filtering, paging, and canceling batch review, the teacher re-enters Review Students, opens the original student's evidence detail, and returns normally. The same class/work/publication/Grade Item authorization context remains selected. | Re-entry uses existing individual menus; batch state is not substituted as authority. | Qualified. |
| Advanced recovery re-entry | Existing `R` route to the real interrupted-save receipt inbox | Recovery opens from exact batch scope, reports the two finalized setup receipts read-only, and B returns to the same batch scope. It neither replays nor creates an action. | Recovery remains exact receipt-based review. It is not a general batch undo or retry command. | Qualified. |
| Cancellation and collateral effects | Fresh native ScoreForm workspace, full byte inventory, and receipt inventory | Two batch entries, matched and failed filters, cross-page toggles, queue viewing, recovery viewing, `:notes`, individual viewing, and cancellation leave the workspace byte-for-byte identical and receipt IDs unchanged. No evidence or Grade Item ID is entered or rendered. | The inventory covers the synthetic workspace, not unrelated OS state. | Qualified. |

## Representative installed walkthrough

The executable A17 walkthrough uses the released ScoreForm APIs and existing
native setup fixture to create one synthetic 29-student, six-question
assessment. The authorized projection contains 406 source items. It then
drives the real production inbox and menus in this order:

1. Select the synthetic class and assessment.
2. Enter assessment eligibility and choose the current Grade Item.
3. Open the complete read-only exception/coverage queue and return with `D`.
4. Match one student by display label, toggle one item, and cancel the filter
   selection.
5. Run a failed display-label search and verify that it selects nothing.
6. Toggle exact items on pages 1 and 2, return to page 1, and cancel the whole
   selection.
7. Enter the existing Advanced interrupted-save recovery route and return.
8. Enter `:notes` at a prompt with no Notes capability and continue without an
   action.
9. Cancel batch review, re-enter the existing individual workflow, open one
   evidence detail, and return through each local Back boundary.
10. Enter batch review a second time and cancel again.
11. Leave the assessment, assignment, class, and inbox screens through their
    real local Back routes.

The emitted installed evidence record was:

```text
A17_INSTALLED_NAVIGATION source_items=406 students=29 batch_entries=2
failed_filter_selects=0 paged_selection_cancelled=true
advanced_reentry=true individual_reentry=true manual_canonical_ids=0
ansi_sequences=0 academic_changes=0
```

The test additionally verifies exact retained session context, unchanged
receipt identifiers, a byte-identical workspace, absence of candidate and
Grade Item canonical IDs from both input and output, and absence of the batch
attribution and Apply-review screens.

## Executable qualification

Focused source command, with the installed-native test deliberately gated:

```text
python -m pytest -q \
  tests/test_issue125_a17_navigation_acceptance.py \
  tests/test_issue125_h3d5_status_route_terminal_matrix.py \
  tests/test_issue125_h3d10a_authorized_filter.py \
  tests/test_issue125_slicef1_assessment_menu.py \
  tests/test_issue125_slicef2_teacher_hardening.py \
  tests/test_issue125_slicef1_inbox_hook.py \
  tests/test_issue125_h3d3_exception_queue_navigation.py
115 passed, 1 explicit installed-native skip
```

Source-free installed command with the official dependencies and A17 gate:

```text
PDS_ISSUE125_A17_NATIVE_TEST=1
python -m pytest -q -s <the seven focused modules above>
116 passed in 13.65s
```

Static and documentation qualification:

```text
ruff check tests/test_issue125_a17_navigation_acceptance.py
ruff format --check tests/test_issue125_a17_navigation_acceptance.py
python scripts/check_documentation.py
```

No production file changed, so a new production mypy target was not
applicable. Existing production behavior is exercised from the built wheel.
The 23-minute A16 benchmark and the full repository validator were not
repeated.

## Remaining limitations

1. Core 0.6.6 has no public module-facing header or Notes capability. The
   qualified behavior is Meridian's supported plain-header/inert-command
   fallback, not a capability-present branch that cannot be invoked.
2. The representative native walkthrough uses ScoreForm. The shared B/M/Q,
   filter, pagination, terminal, and recovery code is producer-independent;
   A17 does not repeat the already-qualified producer-semantics matrices.
3. Byte identity covers the complete synthetic workspace. It is not a claim
   about unrelated host state or terminal emulator behavior.
4. A17 does not qualify A18, the eventual final PR commit, the full validator,
   or merge readiness.
