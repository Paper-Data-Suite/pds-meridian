# Issue #124 E2G2 — Bound composite recovery navigation

The existing class-local interrupted-save menu accepts an optional, trusted
`assessment_context_loader(root, session, entry)` callback. By default it is
`None`, so existing #122 recovery behavior remains unchanged.

If a caller supplies a composite `AssessmentSetupPreview` and exact
`TeacherActionActor`, the menu requires matching class, Grade Item, session
context and original journal action. It checks E2F1 original receipt witness
before forwarding to the E2G1 teacher confirmation prompt. This adds no new
authoring or generic resume authority and does not infer composite context
from the receipt. Any invalid supplied context fails closed without offering
a second selection path in that menu step. B/M/Q remain owned by the existing
menu and input helpers.

**Boundary:** This increment wires an opt-in, typed navigation handoff. The
application still requires a trusted caller to supply the reviewed context;
there is no automatic context reconstruction or persistent review serialization.
