# #124 E2G3D: explicit fresh-review caller

An opt-in `make_fresh_assessment_context_loader` translates fresh, explicit
teacher choices into the `(reviewed, actor, load_fresh_review)` contract of
E2G3C. Every `load_fresh_review()` call re-reads canonical assessment and
Grade Item data using C1. It never decodes intent choices from receipts,
reconstructs an old preview from a digest, writes academic state or resumes.

The caller must provide a trusted teacher-choice UI and verified actor.
A missing UI is **not** automatically registered. The E2G3B and E2G3C gates
remain authoritative for correlation, original receipt, and exact selection.
