# Meridian #124 E2F2 — Original selection-only restart port

Pinned base: `9e12116f0218615e9d677702fca1997da13ddbdf` (E2F1).

The adapter requires literal `RESUME`; cancellation performs zero reads or writes. It obtains the original action preview from E2F1, reloads the original #122 journal, and uses the existing `teacher_action_restart_grade_item` or `teacher_action_restart_membership` canonical restart port. Both explicitly refuse `persist_exact()`. The #122 restart inspection must report exact selection eligibility. The receipt and E2F1 witness are rechecked immediately before handing the action to E2E. E2E revalidates E2D and #122 recovery, performs only the exact CAS selection, and verifies the composite canonical state afterwards.

A fresh UUID, new preparation, immutable write, auto-resume, arbitrary selector, and teacher menu command are not introduced. Unknown outcomes remain review-only. This is not a cross-process transaction, and concurrent changes must still be rejected by the underlying canonical #122 CAS. Full-suite and installed-wheel qualification remain pending.
