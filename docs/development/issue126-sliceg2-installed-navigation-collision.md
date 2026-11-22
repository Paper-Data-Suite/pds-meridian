# Meridian #126 — G2 installed navigation and command-collision qualification

## Baseline and purpose

- Branch: `126-verified-correction-attempt-reassessment-management`.
- Accepted parent: G1 `a77974b9654a634a4a2c19aced84e91dac19b638`.
- G1 remains the production header adaptation. **G2 modifies no production code.**
- G2 tests the actual `run_assessment_corrections_menu` and student-detail routes
  using the accepted **synthetic** 29-student, six-question fixture and installed
  Core navigation. Inert injected callbacks record routing without academic writes.
- The check verifies installed Core 0.6.6 B/M/Q, readable plain text and
  non-interception of unrelated text. It is **not** a claim that the source
  checkout constitutes an official published Meridian wheel.

## Qualified UI contract — this slice

| Screen boundary | Navigation and collision evidence |
| --- | --- |
| Assessment queue | `A/E`, `N/P`, `R`, `I`, numbered roster selection, B/M/Q |
| Student detail | Exactly one owner for `C`, `S`, `D`, `I`, `V`, `X`, `Z` |
| Local read-only views | `H` source history; `T` Technical Details; no implicit save |
| Action return | Refresh authoritative assessment inventory before new use |
| Core navigation | B returns; M/Q raise the published Core unwind exceptions |
| Context drift | Changed publication/session prevents returning to stale student use |
| `:notes` | Not intercepted on menus; literal in rationale, confirmation, pause |
| Header | Core v0.6.6 plain fallback, captured stream has no ANSI bytes |

The local `H` command means **History** on this screen; it must not be
reinterpreted as a global Help shortcut. The menu uses `S` for genuine
reassessment and `Z` for exact #31 recovery; `X` remains read-only.

The shared Notes command is not enabled on any #126 prompt: no installed Core
Notes menu or private Notes record capability has been qualified. An installed
future parser token alone would not authorize launching or writing Notes. Core
`parse_navigation_choice` continues to own B/M/Q; Meridian does not wrap,
monkeypatch or reinterpret these signals.

## Exact release-evidence boundary

- **D0:** Suite v0.2/Core teacher-experience v1 design contract applies.
- **D1:** G1 production code and G2 source-level menu tests are qualified on
  accepted branch SHA only after guarded Windows checks.
- **D2:** Installed Core 0.6.6 fallback may be observed; **first published Core
  wheel with `terminal.header.v1` or `terminal.notes_command.v1` not attested**.
- **D3:** This slice probes the actual installed Core navigation against a
  Meridian **working checkout**; installation of a released Meridian wheel and
  Suite handoff/cross-process return remain unqualified.
- **D4:** Exact mixed-wheel and realistic human 29-student journey remain
  pending Slice I/J and separate Suite acceptance.

## Runner and acceptance

The guarded runner checks archive member hashes, the clean exact G1 baseline,
remote branch equality, installed `pds-core` compatibility and two accepted
source Git blobs. It introduces only this test file and documentation. It
runs Ruff, strict mypy on the unchanged menu modules, the installed runtime
probe, G2/G1/F1–F3B2 native focused tests, documentation and Git checks.
Commit/push are conditional; no merge, producer mutation or release occurs.

## Ownership and residual risks

- Core #237 and Suite #52/#54 own future published header, command and Notes
  interfaces; G2 must not import unreleased Core symbols unconditionally.
- Core #235 and Suite #15/#51 own cross-module teacher-UX composition, not a
  Meridian-only navigation test.
- Meridian #126 Slice H owns current-attempt consumer audit; #133/#134 remain
  separately owned Report 9 work.
- The final A1–A18 ledger must preserve these D0–D4 distinctions and the
  exact two symlink-permission skips observed on native Windows storage tests.
