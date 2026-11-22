# Meridian #126 — Slice G1: Core capability-aware teacher header

## Accepted predecessor and authority

Source baseline: accepted F3B2 `79c0654c1fbafc41afbee5d6e4e84d60281ecb73`.
Exactly one existing Meridian file is changed: `meridian/menu_ui.py`. New tests and this note are synthetic. No academic records, Core source, Suite source, producer storage or dependency floors are changed.

Normative design: Core `docs/teacher_experience_contract_v1.md`, Suite `docs/integration/teacher-experience-contract-matrix.md`, Meridian #126 §7. Source design does not establish installed D2/D3/D4 readiness.

## Behavior and compatibility boundary

- Installed Core **0.6.6** is pre-contract: `pds_core.teacher_experience` is absent. Meridian prints its historical readable `Meridian`, task-title, blank-line header, with no ANSI emission. Core B/M/Q navigation remains canonical.
- If a **future installed** Core module exposes contract version `1` and an immutable capability set containing `terminal.header.v1`, Meridian calls **only public** `TeacherScreenHeader` and `print_teacher_header` with `color="auto"` and the actual output stream. Core owns the ANSI/VT, `NO_COLOR`, `TERM=dumb`, captured-stream and redirected fallback decision.
- If the contract module is truly absent, fallback is supported. If it claims v1 but is malformed, broken internally, or advertises header support without its public implementation, raise an explicit bounded `TeacherHeaderCompatibilityError`, not a silent downgrade.
- If an installed valid v1 Core **does not advertise** `terminal.header.v1`, fallback continues. This does not disable other healthy module operations.
- In either path, caller-owned screen titles are validated to reject blank or control-character strings. There is no Core source checkout import or unpublished private Core UI call.
- The module does **not** activate a shared `:notes` interpreter. `terminal.notes_command.v1` is not a Notes service; even an advertised parser cannot grant storage/menu authority. Text/confirmation/pause inputs remain literal; existing B/M/Q and local N/P/H/R/X/Z keys are unchanged.
- `print_menu_header(output)` (no task title) retains its legacy plain `Meridian` output because the new Core API requires a nonblank title. Existing spacing is retained for all callers.

## D0–D4 release-evidence ledger

| Level | Exact G1 evidence | Qualification limit |
| --- | --- | --- |
| D0 | Core v1 and Suite v0.2 contracts read | Design only; no runtime guarantee |
| D1 | New source, simulated v1/pre-contract tests, installed Core 0.6.6 regression run | Source and tested installed dependency behavior only |
| D2 | `probe_installed_core.py` checks installed noneditable `pds-core` 0.6.6; `probe_g1_runtime.py` records available header token | No publisher-verified *future* Core header release or wheel hash claim |
| D3 | F3B2–F1 menu tests and synthetic Core capability/collision cases, then qualified Windows runner | Not a real installed complete Meridian wheel/teacher-completion session |
| D4 | Not completed | Official mixed wheels, physical classroom, Core/Suite launch and ARM64/Ubuntu not yet qualified |

## Acceptance matrix scope and handoff

A16 **conditional G1 source coverage**: missing header fallback, explicit incompatibility, captured output, pure title validation, B/M/Q and literal `:notes` behavior. Continued G2 acceptance must verify exact installed consumer entry point, `NO_COLOR` / dumb / Windows terminal output and real current-session navigation; Suite-owned launch remains Suite #52/#15. New Notes/menu/context services are independently gated and remain unqualified. A1–A15 are unchanged by this slice. A17 and A18 remain H and J respectively.

## Focused qualification

`tests/test_issue126_sliceg1_shared_header.py` and the existing F1–F3B2/Issue #110 and #126 native regression set; `ruff check`/`ruff format --check` on changed Python paths, strict mypy on the changed helper, documentation validator, Git clean baseline and approved-path checks. A passing matrix is **not** a publisher wheel provenance claim. Any skipped Windows symlink tests remain explicit.
