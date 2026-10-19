# Issue #122 — final installed qualification checks

The `scripts/smoke_program_issue122_multi_process.py` program is executed by the
existing prepared **Core-only installed-wheel matrix**, from outside the
source checkout. Separate Python interpreters share an isolated temporary
workspace. It validates that a write interrupted before current selection
survives restart; repeated ordinary APPLY never reauthors; explicit RESUME
selects the exact saved revision once; subsequent recovery observes already
applied; changed CAS pointers and corrupted receipts block without selection;
and cancel has no academic mutation. The synthetic canonical domain port is
purpose-built for testing the orchestration/receipt boundary. It does **not**
replace the domain-specific guided authoring tests or claim real student data.

`tests/test_issue122_slice16_teacher_confirmation.py` measures confirmation
input count at the **already-prepared ordinary Save/Apply** interaction: one
for an affirmative save and one for cancellation, with no second selection
confirmation. The historical baseline was two separate confirmations per
prepared decision. This does not claim the whole teacher assessment journey
needs one interaction or fix per-student/per-question batching.

Authoritative final checks remain `scripts/validate_repository.py` using exact
released Core 0.6.6 and qualified producer wheels. This includes one full
pytest run, mypy, package/sdist validation, built-wheel installed smokes, and
source-isolation checks; the CI matrix runs Python 3.11–3.14 on Windows and
Linux. Test only in temporary synthetic workspaces, never district OneDrive.

Log the exact candidate commit, wheel inputs, completed matrices, test counts,
CI results, and actual operating system/Python architecture before closing.

**Known scope:** installed orchestration restart is validated here with a
synthetic canonical port. Earlier #122 slice tests exercise specific academic
domain adapters, permissions and menu routes, while existing issue #110
installed tests exercise representative ScoreForm/Quillan evidence routes.
Do not conflate those individual checks into one physical end-to-end test of
all seven academic families.
