# Meridian #117 — Slice 14: benchmark reassessment and immutable revision acceptance

Slice 14 extends **the existing installed ScoreForm, Quillan, and Concord Report 9 journeys**. It does not add a matrix, install wheels, or alter Core/producer contracts.

After the first confirmed teacher plan is saved, the same installed teacher menu is entered again. The teacher chooses **Edit latest plan**, keeps all existing planning sections, records an Exit Ticket reassessment, selects the individual still needing attention, and types `SAVE PLAN`.

Acceptance requires:

- two immutable revisions `(1, 2)`, with the original revision SHA-256 unchanged;
- exact restoration of revision 1 annotations, including the empty original reassessment;
- revision 2 preserves interpretation, standard judgments, groups, and instructional responses;
- revision 2 contains a typed reassessment tool, date, explicit remaining student, teacher observation, and no fabricated source ID;
- source references match the original current authorized assessment, and the four-section Markdown report contains the follow-up;
- publication IDs remain hidden from the ordinary teacher-facing menu.

Two focused regressions cover save and cancellation using the existing synthetic planning fixtures. They are separate from installed-wheel execution, which occurs **once in the final six-matrix qualification** against the exact released Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6, and Concord 0.3.2 wheels.

No real student data or external SIS writes. Existing authority and source-currentness gates remain unchanged.
